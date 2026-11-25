"""Deterministic rules. The LLM proposes; this module decides what happens to the proposal.

decide() never trusts the model's own labels to loosen anything: the model's `suspicious` flag and its
confidence can only make the outcome stricter.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from . import config

AUTO, APPROVAL, QUARANTINE = "AUTO", "APPROVAL", "QUARANTINE"

# tolerant of OCR confusions in the country code ("1T60…", "lT60…")
IBAN_RE = re.compile(r"(?<![0-9A-Z])[I1l]T\s?\d{2}\s?[A-Z0-9]\s?(?:[0-9O]\s?){10}(?:[0-9A-Z]\s?){12}(?![0-9A-Z])")
CODICE_FISCALE_RE = re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b")
# phrases aimed at an AI rather than at a person; deterministic, independent of the model
INJECTION_RE = re.compile(
    r"(ignore (all |the )?(previous|prior|above) (instructions|prompts?)|system (note|prompt|message)"
    r"|\bAI assistant\b|you are (now )?(an?|the) (ai|assistant|model)|pre-?approved by the user"
    r"|developer mode|jailbreak|ignora (le )?istruzioni|nota per l'?(ia|assistente))",
    re.IGNORECASE,
)


@dataclass
class Alarms:
    """Evidence from the chamber for one document (all chamber calls combined)."""
    canary_read: bool = False
    canary_in_output: bool = False
    timed_out: bool = False
    truncated: bool = False
    blocked: list = field(default_factory=list)   # stderr markers such as "Network is unreachable"


@dataclass
class Decision:
    action: str
    reasons: list

    def as_dict(self):
        return {"action": self.action, "reasons": self.reasons}


def validate(proposal):
    """Return a list of problems; empty means the proposal has the expected shape."""
    if not isinstance(proposal, dict):
        return ["proposal is not an object"]
    problems = []
    if proposal.get("doc_type") not in config.DOC_TYPES:
        problems.append(f"doc_type must be one of {', '.join(config.DOC_TYPES)}")
    conf = proposal.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        problems.append("confidence must be a number between 0 and 1")
    if not isinstance(proposal.get("suspicious"), bool):
        problems.append("suspicious must be true or false")
    issuer = proposal.get("issuer")
    if not isinstance(issuer, str) or not issuer.strip() or len(issuer) > 200:
        problems.append("issuer must be a non-empty string of at most 200 characters")
    total = proposal.get("total_eur")
    if total is not None and (isinstance(total, bool) or not isinstance(total, (int, float))
                              or not -1_000_000 < total < 1_000_000):
        problems.append("total_eur must be a number or null")
    d = proposal.get("date", "")
    if d not in ("", None):
        try:
            date.fromisoformat(d)
        except (TypeError, ValueError):
            problems.append("date must be an ISO date (YYYY-MM-DD) or empty")
    return problems


def sensitive_data(text):
    found = []
    if IBAN_RE.search(text or ""):
        found.append("IBAN")
    if CODICE_FISCALE_RE.search(text or ""):
        found.append("codice fiscale")
    return found


def injection_markers(text):
    return sorted({m.group(0).lower() for m in INJECTION_RE.finditer(text or "")})


def decide(proposal, alarms, text, canary=""):
    """Decide what happens to one document. `text` is the extracted document text."""
    problems = validate(proposal)
    if problems:
        return Decision(QUARANTINE, ["invalid proposal: " + "; ".join(problems)])

    red = []
    if alarms.canary_read:
        red.append("a canary credential was read inside the chamber")
    if alarms.canary_in_output or (canary and canary in repr(proposal)):
        red.append("the canary string reached the output")
    if red:
        return Decision(QUARANTINE, ["RED: " + r for r in red])

    yellow = []
    if alarms.timed_out:
        yellow.append("a chamber job hit its time limit")
    if alarms.truncated:
        yellow.append("chamber output was truncated")
    if alarms.blocked:
        yellow.append("the jail blocked: " + ", ".join(alarms.blocked))
    if yellow:
        return Decision(QUARANTINE, ["YELLOW: " + y for y in yellow])

    markers = injection_markers(text)
    if markers:
        return Decision(QUARANTINE, ["the document contains instructions aimed at an AI: " + ", ".join(markers)])
    if proposal["suspicious"]:
        return Decision(QUARANTINE, ["the model flagged the document as suspicious"])

    reasons = []
    sensitive = sensitive_data(text)
    if sensitive:
        reasons.append("contains sensitive data: " + ", ".join(sensitive))
    if proposal["doc_type"] not in config.AUTO_TYPES:
        reasons.append(f"'{proposal['doc_type']}' documents are always reviewed by a person")
    if proposal["confidence"] < config.MIN_CONFIDENCE:
        reasons.append(f"confidence {proposal['confidence']:.2f} is below {config.MIN_CONFIDENCE}")
    if reasons:
        return Decision(APPROVAL, reasons)
    return Decision(AUTO, [f"{proposal['doc_type']} with confidence {proposal['confidence']:.2f}, no alarms"])


def apply_review(proposal, edits, note):
    """A person's changes to a proposal awaiting approval. Returns (new_proposal, problems)."""
    edits = edits or {}
    problems = []
    unknown = sorted(set(edits) - set(config.EDITABLE_FIELDS))
    if unknown:
        problems.append("fields that cannot be changed: " + ", ".join(unknown))
    if edits and not (note or "").strip():
        problems.append("a change needs a note that says why")
    updated = {**proposal, **{k: v for k, v in edits.items() if k in config.EDITABLE_FIELDS}}
    if not problems:
        problems = validate(updated)
    return updated, problems
