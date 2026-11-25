"""Thresholds and fixed settings. Not editable from the UI on purpose."""
import os

# Deployment values (chamber URL/key/baseline/canary, UI password) come from an env file on ctrl.
_ENV_FILE = os.environ.get("AIRLOCK_ENV_FILE", os.path.expanduser("~/airlock/airlock.env"))
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            if "=" in _line and not _line.lstrip().startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ.setdefault(_k, _v)

# --- policy ---
DOC_TYPES = ("utility_bill", "receipt", "payslip", "contract", "other")
AUTO_TYPES = ("utility_bill", "receipt")      # the only types that may be filed without a person
MIN_CONFIDENCE = 0.85
EDITABLE_FIELDS = ("doc_type", "issuer", "date", "total", "currency")

# doc_type -> folder name under Airlock/Trusted on Box (folders are created once; ids are looked up)
FOLDERS = {
    "utility_bill": "Bills",
    "receipt": "Receipts",
    "payslip": "Paystubs",
    "contract": "Contracts",
    "other": "Other",
}

# --- budgets ---
MAX_LLM_CALLS_PER_DOC = 6
MAX_RUN_PYTHON_PER_DOC = 3
DAILY_LLM_CALLS = int(os.environ.get("AIRLOCK_DAILY_LLM_CALLS", "200"))
MAX_TEXT_CHARS = 12_000                          # extracted text sent to the LLM
MAX_TOOL_OUTPUT_CHARS = 4_000                    # run_python output sent back to the LLM

# --- connectors (gateway base URLs; connection ids are not secrets) ---
GATEWAY = "https://api.sprites.dev/v1/gateway"
OLLAMA = os.environ.get("AIRLOCK_OLLAMA", f"{GATEWAY}/ollama/LVV5fvksFt-BgAkRq6QUGw")
BOX = os.environ.get("AIRLOCK_BOX", f"{GATEWAY}/box/MKmGx1iQL7QdnxpbtXhiUA")
PINECONE = os.environ.get("AIRLOCK_PINECONE", f"{GATEWAY}/pinecone/GcKFwwQUtTfpw-bjM0lfmA")
MODEL = os.environ.get("AIRLOCK_MODEL", "deepseek-v4.1-flash")
PINECONE_INDEX = "airlock-memory"
PINECONE_NAMESPACE = "decisions"
BOX_ROOT_FOLDER = os.environ.get("AIRLOCK_BOX_ROOT", "Airlock")  # the connector cannot delete: switch root for a clean demo

# --- chamber (from .env.chamber, deployed to ctrl) ---
CHAMBER_URL = os.environ.get("AIRLOCK_URL", "")
CHAMBER_KEY = os.environ.get("AIRLOCK_KEY", "")
CHAMBER_BASELINE = os.environ.get("AIRLOCK_BASELINE", "")
CANARY = os.environ.get("AIRLOCK_CANARY", "")

# --- ctrl ---
DATA_DIR = os.environ.get("AIRLOCK_DATA", os.path.expanduser("~/airlock-data"))
UI_PASSWORD = os.environ.get("AIRLOCK_PASSWORD", "")
