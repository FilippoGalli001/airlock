"""Checks that nothing a job starts outlives it: job 1 forks a setsid daemon, job 2 lists the jail's processes.

Usage: python scripts/fork_check.py   (reads .env.chamber)
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(line.strip().split("=", 1) for line in open(os.path.join(ROOT, ".env.chamber")) if "=" in line)
HDR = {"X-Airlock-Key": ENV["AIRLOCK_KEY"], "Content-Type": "application/json"}


def call(path, body=None):
    req = urllib.request.Request(ENV["AIRLOCK_URL"] + path, json.dumps(body).encode() if body is not None else None,
                                 HDR, method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=60))


def wait_clean():
    for _ in range(120):
        try:
            if not call("/health")["dirty"]:
                return
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    raise SystemExit("chamber not clean")


def run(code):
    return base64.b64decode(call("/run", {"code": code, "stdin": ""})["stdout_b64"]).decode()


LIST = """import os
me = os.getpid()
for p in os.listdir('/proc'):
    if p.isdigit() and int(p) != me:
        try:
            if os.stat('/proc/' + p).st_uid == os.getuid():
                print(p, open('/proc/' + p + '/cmdline').read().replace(chr(0), ' ').strip())
        except OSError:
            pass
print('done')
"""

if __name__ == "__main__":
    wait_clean()
    print("job 1:", run("import os, time\nif os.fork() == 0:\n    os.setsid()\n    time.sleep(120)\n"
                        "else:\n    print('daemon started')").strip())
    print("job 2 sees these jail processes besides itself:\n" + run(LIST))
    call("/reset", {"checkpoint": ENV["AIRLOCK_BASELINE"]})
    wait_clean()
    print("chamber reset and clean")
