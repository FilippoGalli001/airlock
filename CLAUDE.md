# CLAUDE.md — working notes for agents on this repo

## What this is
Entry for **Fly.io Hacksgiving** (Nov 23–29, 2026; deadline Sun Nov 29 23:59 PST = Mon Nov 30 09:00 Italy).
Hard requirements: the agent **runs on a Sprite** and **uses at least one Sprites connector**. Built this week only.
One entry per person. Submission = code link + demo + 1–2 sentences + social post tagging @flydotio.

Working name: **Airlock** — a personal quarantine agent. Untrusted documents (scanned bills, contracts,
payslips, hostile PDFs) are processed by an LLM agent that writes and runs code *inside* an isolated Sprite.
No real credentials live in the VM (connectors hold them). Canary credentials detect misbehaviour, and the
Sprite is restored to a clean checkpoint. Only what the user approves leaves the airlock (Box `Trusted`, Pinecone).
Fallback direction if checkpoints turn out slow/fragile: "Uncle's Geocities" (Weird Uncle award).
Final direction is decided after the spike — see `DEVLOG.md`.

## Principle (carried over from the author's Interop Triage project, not its code)
The AI proposes, the code decides, people approve what is risky.

## Files
- `CLAUDE.md` — this file: goal, rules, current status. Keep it short.
- `DEVLOG.md` — dated log of what was done, verified, decided, and open questions. Append, don't rewrite.
- `ARCHITECTURE.md` — written once the spike settles the direction (not before).

## Rules for working here
- Never put provider keys in the Sprite or in the repo. Calls go through the gateway:
  `https://api.sprites.dev/v1/gateway/<provider>/<conn_id>/<path>` (no auth header; Sprite is identified by signature).
- Connection IDs are not secrets but keep them in config, not hard-coded.
- Anything stored on the Sprite disk is lost on restore: audit log and decisions must live outside the VM.
- **The gateway trusts the whole Sprite, not a process**, and `/.sprite/api.sock` is world-writable. Untrusted
  (agent-written) code runs only inside the bubblewrap jail documented in `DEVLOG.md` (no network, no `/.sprite`).
- CLI from Git Bash: `export MSYS_NO_PATHCONV=1` before `sprite api /policy/...`, and pass `--no-stdin` to `sprite exec`.
- Verify claims about Sprites by running them; the docs are incomplete and contradict themselves on checkpoints.
- Scope is tiny on purpose (~16 h of build time). Cut features before cutting the demo.
- The Sprite URL is public once shared: protect write actions and LLM-spending actions.

## Local environment
- Windows 11, Git Bash + PowerShell. Sprite CLI: `%LOCALAPPDATA%\Programs\Sprite\sprite.exe` (on user PATH).
- WSL2 Ubuntu available as a fallback.

## How to run
- Tests: `python -m unittest discover -s tests -t .`
- Rebuild chamber: `bash scripts/build-chamber-baseline.sh` (→ `.env.chamber`), smoke: `python -u scripts/chamber_smoke.py`
- Deploy ctrl: `bash scripts/deploy-ctrl.sh`, then on ctrl `cd ~/airlock && python3 -m ctrl.cli ...`
  (`setup | add FILE | sync | process ID [--redteam] | list | show ID | approve ID --set k=v --note .. | reject ID --note ..`)

## Status
See the top of `DEVLOG.md`.
