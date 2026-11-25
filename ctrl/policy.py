"""Deterministic rules. The LLM proposes; this module decides what happens to the proposal.

decide() never trusts the model's own labels to loosen anything: the model's `suspicious` flag and its
confidence can only make the outcome stricter.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date

from . import config

AUTO, APPROVAL, QUARANTINE = "AUTO", "APPROVAL", "QUARANTINE"

# Italian IBAN, case-insensitive and tolerant of OCR confusions ("1T60…", "lT60…", O for 0)
IBAN_IT_RE = re.compile(r"(?<![0-9A-Z])[I1L]T\s?\d{2}\s?[A-Z0-9]\s?(?:[0-9O]\s?){10}(?:[0-9A-Z]\s?){12}(?![0-9A-Z])",
                        re.IGNORECASE)
# any other IBAN: upper-case country code + check digits + 11..30 alphanumerics, optionally in groups of 4
IBAN_ANY_RE = re.compile(r"(?<![0-9A-Z])[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?(?![0-9A-Z])")
# codice fiscale, case-insensitive, with optional spaces/dashes, O/0 confusions in the digit positions
_D = r"[0-9O]"
CODICE_FISCALE_RE = re.compile(
    rf"(?<![A-Z0-9])[A-Z]{{3}}[\s-]?[A-Z]{{3}}[\s-]?{_D}{{2}}[A-EHLMPR-T]{_D}{{2}}[\s-]?[A-Z]{_D}{{3}}[A-Z](?![A-Z0-9])",
    re.IGNORECASE)
MAX_FIELDS_JSON = 4000
MAX_REASON = 1000
# phrases aimed at an AI rather than at a person; deterministic, independent of the model
INJECTION_RE = re.compile(
    r"(ignore (all |the )?(previous|prior|above) (instructions|prompts?)|system (note|prompt|message)"
    r"|\bA[Il1] assistant\b|you are (now )?(an?|the) (ai|assistant|model)|pre-?approved by the user"
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
    fields = proposal.get("fields", {})
    if fields is not None and (not isinstance(fields, dict) or len(json.dumps(fields)) > MAX_FIELDS_JSON):
        problems.append(f"fields must be an object of at most {MAX_FIELDS_JSON} characters")
    reason = proposal.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        problems.append(f"reason must be a string of at most {MAX_REASON} characters")
    d = proposal.get("date", "")
    if d not in ("", None):
        try:
            date.fromisoformat(d)
        except (TypeError, ValueError):
            problems.append("date must be an ISO date (YYYY-MM-DD) or empty")
    return problems


def sensitive_data(text):
    found = []
    if IBAN_IT_RE.search(text or "") or IBAN_ANY_RE.search(text or ""):
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

    # two independent layers; report both when both fire
    quarantine = []
    markers = injection_markers(text)
    if markers:
        quarantine.append("rule: the document contains instructions aimed at an AI: " + ", ".join(markers))
    if proposal["suspicious"]:
        quarantine.append("model: flagged the document as suspicious")
    if quarantine:
        return Decision(QUARANTINE, quarantine)

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
