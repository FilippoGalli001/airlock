"""Client for the chamber worker. Everything that touches untrusted content goes through here."""
import base64
import time

from . import config
from .http import HTTPError, request
from .policy import Alarms


class Chamber:
    def __init__(self, url=None, key=None, baseline=None):
        self.url = (url or config.CHAMBER_URL).rstrip("/")
        self.key = key or config.CHAMBER_KEY
        self.baseline = baseline or config.CHAMBER_BASELINE
        if not (self.url and self.key and self.baseline):
            raise RuntimeError("chamber not configured (AIRLOCK_URL, AIRLOCK_KEY, AIRLOCK_BASELINE)")

    def _call(self, method, path, body=None, ctype=None, timeout=180):
        headers = {"X-Airlock-Key": self.key}
        if ctype:
            headers["Content-Type"] = ctype
        return request(method, self.url + path, body, headers, timeout=timeout)

    def health(self):
        return self._call("GET", "/health", timeout=30)

    def extract(self, data, ext):
        res = self._call("POST", f"/extract?ext={ext}", data, "application/octet-stream")
        return decode(res)

    def run_python(self, code, stdin=""):
        return decode(self._call("POST", "/run", {"code": code, "stdin": stdin}))

    def check(self):
        return self._call("POST", "/check", {})

    def reset(self, timeout=60):
        """Restore the chamber to the baseline and wait until it reports a clean state. Returns seconds."""
        t0 = time.time()
        self._call("POST", "/reset", {"checkpoint": self.baseline}, timeout=30)
        time.sleep(1.5)
        while time.time() - t0 < timeout:
            try:
                h = self.health()
                if h.get("ok") and not h.get("dirty"):
                    return round(time.time() - t0, 1)
            except (HTTPError, OSError):
                pass  # the worker restarts during the restore
            time.sleep(0.5)
        raise RuntimeError("chamber did not come back clean")


def decode(res):
    """Turn a worker job result into plain text fields (still untrusted)."""
    out = dict(res)
    out["stdout"] = base64.b64decode(res.get("stdout_b64", "")).decode("utf-8", "replace")
    out["stderr"] = base64.b64decode(res.get("stderr_b64", "")).decode("utf-8", "replace")
    out.pop("stdout_b64", None)
    out.pop("stderr_b64", None)
    return out


def merge_alarms(alarms, job=None, check=None):
    """Fold one job result and/or one /check result into the document's Alarms."""
    if job:
        alarms.canary_in_output |= bool(job.get("canary_in_output"))
        alarms.timed_out |= bool(job.get("timed_out"))
        alarms.truncated |= bool(job.get("truncated"))
        alarms.blocked = sorted(set(alarms.blocked) | set(job.get("blocked_markers") or []))
    if check:
        alarms.canary_read |= bool(check.get("canary_read"))
    return alarms


__all__ = ["Chamber", "Alarms", "merge_alarms", "decode"]
