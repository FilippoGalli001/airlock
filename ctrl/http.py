"""Tiny JSON-over-HTTP helper on the standard library."""
import json
import urllib.error
import urllib.request


class HTTPError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]!r}")
        self.status, self.body = status, body


def request(method, url, body=None, headers=None, timeout=120, raw=False):
    """body: dict (sent as JSON), bytes (sent as-is) or None. Returns parsed JSON, or bytes if raw."""
    headers = dict(headers or {})
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    else:
        data = body
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, e.read().decode("utf-8", "replace")) from None
    if raw:
        return payload
    return json.loads(payload) if payload else {}
