"""Box through the Sprites gateway. The connector supports list, info, search, download, upload and folder
creation; it refuses delete, move, rename and copy — so Airlock never moves originals."""
import json
import uuid

from . import config
from .http import HTTPError, request


class Box:
    def __init__(self, base=None):
        self.base = (base or config.BOX).rstrip("/")
        self._folders = {}

    def items(self, folder_id):
        r = request("GET", f"{self.base}/2.0/folders/{folder_id}/items?fields=name,type,size,sha1&limit=1000")
        return r.get("entries", [])

    def folder(self, name, parent_id="0"):
        """Find or create a folder by name under parent. Cached."""
        key = (parent_id, name)
        if key in self._folders:
            return self._folders[key]
        for e in self.items(parent_id):
            if e["type"] == "folder" and e["name"] == name:
                self._folders[key] = e["id"]
                return e["id"]
        try:
            fid = request("POST", f"{self.base}/2.0/folders", {"name": name, "parent": {"id": parent_id}})["id"]
        except HTTPError as e:
            if e.status != 409:
                raise
            fid = json.loads(e.body)["context_info"]["conflicts"][0]["id"]
        self._folders[key] = fid
        return fid

    def layout(self):
        """Airlock/Inbox and Airlock/Trusted/<one folder per doc type>. Returns ids."""
        root = self.folder(config.BOX_ROOT_FOLDER)
        trusted = self.folder("Trusted", root)
        return {"inbox": self.folder("Inbox", root), "trusted": trusted,
                "types": {t: self.folder(n, trusted) for t, n in config.FOLDERS.items()}}

    def download(self, file_id):
        return request("GET", f"{self.base}/2.0/files/{file_id}/content", raw=True, timeout=180)

    def upload(self, folder_id, name, data):
        boundary = uuid.uuid4().hex
        attrs = json.dumps({"name": name, "parent": {"id": folder_id}})
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"attributes\"\r\n\r\n{attrs}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{uuid.uuid4().hex}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        try:
            r = request("POST", f"{self.base}/upload/files/content", body,
                        {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=180)
            return r["entries"][0]["id"]
        except HTTPError as e:
            if e.status == 409:  # same name already there: keep both, never overwrite
                stem, dot, ext = name.rpartition(".")
                return self.upload(folder_id, f"{stem or name}-{uuid.uuid4().hex[:6]}{dot}{ext if stem else ''}", data)
            raise
