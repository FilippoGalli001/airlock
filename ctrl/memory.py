"""Memory of a person's reviews, on Pinecone (integrated embedding) through the Sprites gateway.

Only decisions reviewed by a person are stored. Automatic decisions never are.
"""
import json

from . import config
from .http import HTTPError, request

HEADERS = {"X-Pinecone-API-Version": "2025-04"}


class Memory:
    def __init__(self, base=None):
        self.base = (base or config.PINECONE).rstrip("/")
        self.ns = f"{self.base}/indexes/{config.PINECONE_INDEX}/records/namespaces/{config.PINECONE_NAMESPACE}"

    def ensure_index(self):
        try:
            request("GET", f"{self.base}/indexes/{config.PINECONE_INDEX}", headers=HEADERS)
        except HTTPError as e:
            if e.status != 404:
                raise
            request("POST", f"{self.base}/indexes/create-for-model", {
                "name": config.PINECONE_INDEX, "cloud": "aws", "region": "us-east-1",
                "embed": {"model": "multilingual-e5-large", "field_map": {"text": "text"}}}, HEADERS)

    def remember(self, record_id, text, **meta):
        rec = {"_id": record_id, "text": text[:2000], **{k: str(v)[:500] for k, v in meta.items()}}
        request("POST", f"{self.ns}/upsert", json.dumps(rec).encode(),
                {**HEADERS, "Content-Type": "application/x-ndjson"})

    def clear(self):
        """Forget every review (used before a demo)."""
        try:
            request("POST", f"{self.base}/indexes/{config.PINECONE_INDEX}/vectors/delete",
                    {"deleteAll": True, "namespace": config.PINECONE_NAMESPACE}, HEADERS)
        except HTTPError as e:
            if e.status != 404:  # namespace already empty
                raise

    # multilingual-e5-large scores unrelated documents around 0.78–0.81; real matches were ≥ 0.86
    def search(self, query, top_k=3, min_score=0.84):
        if not query.strip():
            return []
        r = request("POST", f"{self.ns}/search", {"query": {"inputs": {"text": query}, "top_k": top_k},
                                                  "fields": ["text", "action", "doc_type", "when"]}, HEADERS)
        hits = r.get("result", {}).get("hits", [])
        return [{"id": h["_id"], "score": round(h["_score"], 3), **h.get("fields", {})}
                for h in hits if h["_score"] >= min_score]
