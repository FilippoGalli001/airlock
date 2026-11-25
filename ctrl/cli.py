"""Command line for running the pipeline on ctrl without the UI.

  python -m ctrl.cli setup                     create Box folders and the Pinecone index
  python -m ctrl.cli add FILE [FILE...]        queue local files
  python -m ctrl.cli sync                      queue new files from Box Airlock/Inbox
  python -m ctrl.cli process ID [--redteam]    run one document through the airlock
  python -m ctrl.cli list | show ID
  python -m ctrl.cli approve ID [--set k=v ...] [--note TEXT]
  python -m ctrl.cli reject ID --note TEXT
"""
import argparse
import json
import os

from . import db, pipeline
from .box import Box
from .memory import Memory


def show(doc_id):
    d = db.get(doc_id)
    print(f"#{d['id']} {d['name']}  status={d['status']}")
    print("decision:", json.dumps(d["decision"], ensure_ascii=False))
    print("proposal:", json.dumps(d["proposal"], ensure_ascii=False))
    for e in db.events(doc_id):
        e = dict(e)
        kind = e.pop("kind")
        e.pop("ts")
        for k in ("text", "code", "stdout", "stderr"):
            if isinstance(e.get(k), str) and len(e[k]) > 300:
                e[k] = e[k][:300] + "…"
        print(f"  - {kind}: {json.dumps(e, ensure_ascii=False)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--redteam", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if a.cmd == "setup":
        print(json.dumps(Box().layout(), indent=1))
        Memory().ensure_index()
        print("pinecone index ok")
    elif a.cmd == "add":
        for p in a.args:
            with open(p, "rb") as f:
                print("queued", pipeline.intake(os.path.basename(p), f.read()), p)
    elif a.cmd == "sync":
        print("queued", pipeline.sync_box())
    elif a.cmd == "process":
        pipeline.process(int(a.args[0]), redteam=a.redteam)
        show(int(a.args[0]))
    elif a.cmd == "list":
        for d in db.documents():
            print(f"#{d['id']:<3} {d['status']:<18} {d['name']}")
    elif a.cmd == "show":
        show(int(a.args[0]))
    elif a.cmd in ("approve", "reject"):
        edits = {}
        for kv in a.set:
            k, v = kv.split("=", 1)
            edits[k] = float(v) if k == "total_eur" else v
        pipeline.review(int(a.args[0]), a.cmd, edits, a.note)
        show(int(a.args[0]))
    else:
        ap.error(f"unknown command {a.cmd}")


if __name__ == "__main__":
    main()
