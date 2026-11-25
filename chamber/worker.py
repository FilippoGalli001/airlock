"""Airlock chamber worker. Trusted code, runs as root (via sudo) as a Sprite service on chamber-1 (port 8080).

Every request needs the X-Airlock-Key header. Untrusted work (parsing a document, running LLM-written Python)
only ever runs inside the bwrap jail built by jail_argv(): no network, no /.sprite, no /home, read-only system,
unprivileged uid with no_new_privs, resource limits. Output goes back as capped, base64-encoded JSON.

Endpoints:
  GET  /health                 {"ok", "dirty", "jobs"}            dirty=false means "baseline state"
  POST /extract?ext=pdf        body: file bytes  -> job result + parsed extract JSON
  POST /run                    body: {"code", "stdin"}  -> job result
  POST /check                  canary and filesystem evidence since the baseline
  POST /reset                  body: {"checkpoint": "vN"}  -> 202, then restores this Sprite
"""
import base64
import hmac
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AIRLOCK = "/opt/airlock"
WORK = "/srv/airlock/work"          # bind-mounted at /work inside the jail
JAIL_HOME = "/srv/airlock/home"     # bind-mounted at /home/jail inside the jail (root-owned canaries)
STATE = "/srv/airlock/state"        # worker-only state, never mounted in the jail
DIRTY = os.path.join(STATE, "dirty")
OUT_CAP = 64 * 1024                   # code jobs
EXTRACT_OUT_CAP = 1024 * 1024         # extract.py caps the text itself; JSON escaping can triple it
MAX_BODY = 8 * 1024 * 1024           # gateway-sized limit
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp", "txt", "csv"}

with open(os.path.join(AIRLOCK, "key")) as f:
    KEY = f.read().strip()
with open(os.path.join(AIRLOCK, "canary")) as f:
    CANARY = f.read().strip()
with open(os.path.join(AIRLOCK, "jail_uid")) as f:
    JAIL_UID = int(f.read().strip())

CANARY_FILES = [os.path.join(JAIL_HOME, p) for p in (".config/box/token", ".aws/credentials")]
BASELINE_ATIME = 1577836800  # 2020-01-01, set by setup.sh
LOCK = threading.Lock()
JOBS = {"count": 0}
# stderr fragments that mean "the jail stopped something"
BLOCKED_MARKERS = (
    "Temporary failure in name resolution", "Name or service not known", "Network is unreachable",
    "Could not resolve host", "Permission denied", "PermissionError", "Read-only file system",
    "Operation not permitted",
)


def jail_argv(cmd, timeout_s):
    return [
        "sudo", "-n", "/usr/bin/bwrap",
        "--unshare-net", "--unshare-ipc", "--unshare-uts", "--die-with-parent", "--new-session",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/home/jail",
        "--setenv", "LANG", "C.UTF-8",
        # no canary in the environment: reading env leaves no trace, so canaries live only in files (atime)
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", "/proc", "/proc",
        "--dev", "/dev",
        "--perms", "1777", "--size", str(256 * 1024 * 1024), "--tmpfs", "/tmp",
        # bwrap creates implicit parent dirs as 0700 root, which the jail uid cannot traverse
        "--perms", "0755", "--dir", "/home",
        "--perms", "0755", "--dir", "/airlock",
        "--bind", JAIL_HOME, "/home/jail",
        "--bind", WORK, "/work",
        "--ro-bind", os.path.join(AIRLOCK, "extract.py"), "/airlock/extract.py",
        "--chdir", "/work",
        "/usr/bin/setpriv", f"--reuid={JAIL_UID}", f"--regid={JAIL_UID}", "--clear-groups", "--no-new-privs",
        "/usr/bin/prlimit", "--nproc=64", f"--fsize={50 * 1024 * 1024}", f"--as={2 * 1024 * 1024 * 1024}",
        f"--cpu={timeout_s + 5}", "--",
        "/usr/bin/timeout", "-k", "2", str(timeout_s),
    ] + cmd


def reset_work():
    # rmtree does not follow symlinks, so links planted by jailed code are removed, not their targets
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    os.chown(WORK, JAIL_UID, JAIL_UID)


def write_for_jail(name, data):
    """Create a fresh file in WORK for the jail: root-owned, read-only (0444), so jailed code can read it but
    never rewrite it. O_EXCL|O_NOFOLLOW: never follows a planted symlink."""
    fd = os.open(os.path.join(WORK, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def kill_jail_processes():
    """Nothing the jail started may outlive its job (fork + setsid daemons included)."""
    subprocess.run(["pkill", "-9", "-u", str(JAIL_UID)], check=False, capture_output=True)


def run_jailed(cmd, timeout_s, stdin_bytes=b"", out_cap=OUT_CAP, scan_markers=True):
    """Run cmd in the jail; never raises for job failures.

    scan_markers: look for "the jail stopped something" messages in the output. Only for code jobs (/run):
    for /extract the output is the document's own text, which may legitimately say "Permission denied".
    """
    open(DIRTY, "w").close()
    JOBS["count"] += 1
    t0 = time.time()
    out_path, err_path = os.path.join(STATE, "out"), os.path.join(STATE, "err")
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            p = subprocess.run(jail_argv(cmd, timeout_s), input=stdin_bytes, stdout=out, stderr=err,
                               timeout=timeout_s + 10, check=False)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -9
        finally:
            kill_jail_processes()
    size_out, size_err = os.path.getsize(out_path), os.path.getsize(err_path)
    with open(out_path, "rb") as f:
        stdout = f.read(out_cap)
    with open(err_path, "rb") as f:
        stderr = f.read(out_cap)
    text = (stdout + stderr).decode("utf-8", "replace")
    return {
        "returncode": rc,
        "timed_out": rc in (124, 137, -9),
        "truncated": size_out > out_cap or size_err > out_cap,
        "ms": int((time.time() - t0) * 1000),
        "stdout_b64": base64.b64encode(stdout).decode(),
        "stderr_b64": base64.b64encode(stderr).decode(),
        "canary_in_output": CANARY in text,
        "blocked_markers": sorted({m for m in BLOCKED_MARKERS if m in text}) if scan_markers else [],
    }


def check():
    canaries = []
    for path in CANARY_FILES:
        st = os.stat(path)
        canaries.append({"file": path.replace(JAIL_HOME, "~"), "read": st.st_atime > BASELINE_ATIME + 86400,
                         "atime": int(st.st_atime)})
    work_files = []
    for root, _, files in os.walk(WORK):
        for name in files:
            p = os.path.join(root, name)
            st = os.lstat(p)  # never follow links planted by the jail
            work_files.append({"path": p.replace(WORK, "/work"), "size": st.st_size,
                               "symlink": os.path.islink(p)})
    home_entries = sorted(os.listdir(JAIL_HOME))
    return {"canaries": canaries, "canary_read": any(c["read"] for c in canaries),
            "work_files": work_files[:50], "home_entries": home_entries}


class Handler(BaseHTTPRequestHandler):
    server_version = "airlock-chamber"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return hmac.compare_digest(self.headers.get("X-Airlock-Key", ""), KEY)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n)

    def do_GET(self):
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/health":
            return self._send(200, {"ok": True, "dirty": os.path.exists(DIRTY), "jobs": JOBS["count"]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        path, _, query = self.path.partition("?")
        try:
            body = self._body()
        except ValueError as e:
            return self._send(413, {"error": str(e)})
        if path == "/reset":
            cp = json.loads(body or b"{}").get("checkpoint", "")
            if not (cp.startswith("v") and cp[1:].isdigit()):
                return self._send(400, {"error": "bad checkpoint id"})
            self._send(202, {"restoring": cp})
            threading.Timer(0.3, lambda: subprocess.run(
                ["/.sprite/bin/sprite-env", "checkpoints", "restore", cp], check=False)).start()
            return
        if not LOCK.acquire(blocking=False):
            return self._send(409, {"error": "busy"})
        try:
            if path == "/extract":
                ext = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv).get("ext", "").lower()
                if ext not in ALLOWED_EXT:
                    return self._send(400, {"error": "unsupported extension"})
                reset_work()
                write_for_jail(f"input.{ext}", body)
                res = run_jailed(["/usr/bin/python3", "/airlock/extract.py"], timeout_s=120,
                                 out_cap=EXTRACT_OUT_CAP, scan_markers=False)
                try:
                    res["extract"] = json.loads(base64.b64decode(res["stdout_b64"]))
                except ValueError:
                    res["extract"] = None
                return self._send(200, res)
            if path == "/run":
                req = json.loads(body)
                reset_work()  # a fresh /work per job: nothing planted by an earlier job survives
                write_for_jail("job.py", req.get("code", "").encode())
                return self._send(200, run_jailed(["/usr/bin/python3", "/work/job.py"], timeout_s=20,
                                                  stdin_bytes=req.get("stdin", "").encode()))
            if path == "/check":
                return self._send(200, check())
            return self._send(404, {"error": "not found"})
        finally:
            LOCK.release()

    def log_message(self, fmt, *args):
        pass  # never log request contents


if __name__ == "__main__":
    os.makedirs(STATE, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
