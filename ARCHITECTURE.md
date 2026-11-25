# Airlock — Architecture

> A personal quarantine agent. Untrusted documents go in; only what you approve comes out.
> **The AI proposes, the code decides, people approve what is risky** — and the untrusted part runs in a
> disposable, egress-locked VM that is reset to a clean baseline after every document.

All numbers below were measured in the spike (see `DEVLOG.md`).

## Two Sprites

```
                    ┌──────────────────────── airlock-ctrl (Sprite) ─────────────────────────┐
  you (browser) ───►│ web UI + API (FastAPI, service on :8080, password)                     │
                    │ pipeline · policy.py (deterministic, unit-tested) · SQLite (audit, queue)│
                    │ never parses or executes untrusted content                              │
                    └──┬──────────────┬──────────────┬──────────────────┬────────────────────┘
                       │ gateway      │ gateway      │ gateway          │ HTTPS to chamber URL
                       ▼              ▼              ▼                  │ X-Airlock-Key (shared key)
                    Ollama         Box            Pinecone              ▼
                 (LLM: deepseek  (Inbox in,     (memory of     ┌──────────── chamber-1 (Sprite) ──────────────┐
                  -v4.1-flash)   Trusted out)   your decisions) │ no connectors · egress deny-all              │
                                                                │ worker (trusted, service :8080):             │
                                                                │   /extract /run /check /reset                │
                                                                │   └─ untrusted work in a bwrap jail:         │
                                                                │      no network, no /.sprite, no sudo,       │
                                                                │      unprivileged uid, timeout, output cap   │
                                                                │ /reset → restores itself to the baseline     │
                                                                └──────────────────────────────────────────────┘
```

Why two Sprites (decided after the spike and Gemini's review):
- The connector gateway trusts the **whole Sprite**, not a process, and `/.sprite/api.sock` (checkpoint/restore)
  is world-writable. Any code running on ctrl could use Box, Pinecone and Ollama. So untrusted code never runs on
  ctrl — and that includes parsing hostile PDFs, not just LLM-written scripts.
- chamber-1 has no connector grants and an egress policy of `{"domain":"*","action":"deny"}` (gateway, DNS and raw
  IPs all fail). It can be wrecked freely: it is restored after every document. ctrl is never restored, so its
  SQLite audit log and approval queue are never lost.
- This is the Sprites "untrusted code" use case: hardware-isolated VM, clean baseline per request, egress-locked.

How ctrl drives the chamber (changed after testing): the gateway refuses a Custom API connector that targets
the Sprites API (`403 blocked: base URL targets the Sprites API itself`), so ctrl cannot call exec/restore on
chamber-1 through a connector, and no Sprites token goes on ctrl. Instead chamber-1 runs a small **trusted
worker** as a service on its URL. Inbound HTTP comes through the Fly proxy, so it works with egress deny-all
(measured: 2 MB in 0.23 s; wrong key → 401). The worker:
- authenticates every request with `X-Airlock-Key` (a random key in the chamber baseline and in ctrl's config:
  leaking it only lets someone run jailed, network-less code on a VM that resets — documented as a known limit);
- runs `extract` and `run_python` **inside the bwrap jail** (verified in the spike: no network namespace,
  no `/.sprite`, no `/home`, read-only system, `setpriv` to an unprivileged uid, `no_new_privs`, so no sudo),
  under `timeout` + `prlimit` (procs, CPU, file size) with a size-capped tmpfs;
- returns only JSON `{stdout_b64, stderr_b64, returncode, timed_out, truncated}`, stdout/stderr capped at 64 KB;
- `/check` runs as the worker (outside the jail): canary atimes + changed files; untrusted code cannot reach
  the checker, the marker or `/opt/airlock` (root-owned, not mounted in the jail);
- `/reset` calls `sprite-env checkpoints restore <baseline>` on its own `/.sprite/api.sock` (verified from
  inside in the spike) and answers before the restore lands; ctrl then polls `/health` until the worker reports
  the baseline id. The jail does not mount `/.sprite`, so untrusted code cannot touch checkpoints.
- The chamber URL is the only public surface of the chamber; it wakes the chamber from pause in ~0.3 s.

## Connectors (all on ctrl only, access policy name prefix `airlock-ctrl`)

| Connector | Used for | Verified |
|---|---|---|
| Ollama | LLM, OpenAI-compatible `/v1/chat/completions` with tool calling | ✅ 1.3 s, ~740 tokens per call, flags injection |
| Box | list/download `Airlock/Inbox`, upload to `Airlock/Trusted/...`, create folders | ✅ (connector refuses delete/move/rename/copy) |
| Pinecone | index `airlock-memory`, integrated embedding `multilingual-e5-large`, namespace `decisions` | ✅ |
| ~~Custom API → Sprites API~~ | ~~drive chamber-1~~ | ❌ refused by the gateway by design; replaced by the chamber worker |

The Box connector cannot delete or move files, so Airlock never "moves" the original: it records what it has
processed (by Box file id + SHA-256) in SQLite and uploads results to `Trusted`.

## Pipeline for one document

```
intake ─► chamber: extract ─► LLM agent loop ─► canary + diff check ─► policy ─► AUTO / APPROVAL / QUARANTINE
                                 │   ▲                                              │
                                 ▼   │ run_python (in chamber, ≤3)                  ▼
                              search_memory (Pinecone)                   restore chamber to baseline
```

1. **Intake.** Upload from the web UI, or "Sync" lists `Airlock/Inbox` on Box and downloads files not yet seen.
   ctrl stores bytes + SHA-256 + metadata; status `queued`. ctrl never opens the file.
2. **Extract (chamber).** ctrl POSTs the file to the worker's `/extract`. Inside the jail: `pdftotext`, and if
   that yields almost nothing, `pdftoppm` + `tesseract -l ita`. Returns `{pages, method, chars}`.
3. **Agent loop (ctrl → Ollama).** System prompt: the document is untrusted data. Tools:
   - `search_memory(query)` — read-only Pinecone search over your past decisions and notes;
   - `run_python(code)` — runs in chamber-1 under a timeout, stdin = the extracted text; for parsing tables,
     totals, dates. At most 3 calls per document;
   - `submit_extraction(...)` — the only way to answer: `doc_type` (closed enum), `issuer`, `date`,
     `total_eur`, `fields{}`, `confidence`, `suspicious`, `reason`. The LLM never names a folder or path: ctrl maps
     `doc_type` to a fixed Box folder id.
   The LLM has **no Box tools and no HTTP tool**. Budget: ≤6 LLM calls per document, daily token cap.
4. **Canary + diff check (after every chamber call).** The jail sees fake credentials
   (`~/.config/box/token`, `~/.aws/credentials`, env `BOX_TOKEN`) holding a unique string `AIRLOCK-CANARY-<id>`,
   with their atime backdated to 2020. The mount is `relatime`, so the first read sets atime to now (verified).
   - **Red**: a canary file was read (atime moved), or the canary string appears in any chamber output, tool
     argument or the final proposal. This catches "read the token, try to send it, egress fails, swallow the error".
   - **Yellow**: files changed outside `/work` since the baseline, the job hit its timeout or limits, or output
     was truncated.
   Red or yellow → document goes to `quarantine` with the evidence, no output leaves the airlock.
5. **Policy (`policy.py`, deterministic, unit-tested).**
   - `AUTO` only if: schema valid, `suspicious == false`, no canary/diff alarm, `confidence ≥ MIN_CONFIDENCE`,
     `doc_type` in `AUTO_TYPES` (utility_bill, receipt), no sensitive fields detected by regex (IBAN, codice
     fiscale) unless the type allows them.
   - `APPROVAL` for everything else that is not an alarm (payslips, contracts, low confidence, sensitive data).
   - `QUARANTINE` for alarms and invalid proposals. The model's own `suspicious` flag can only make things
     stricter, never looser.
6. **Output.** AUTO, or APPROVAL approved by you: ctrl uploads the original and a `<name>.airlock.json` to the
   fixed folder for the type (`Airlock/Trusted/Bollette|Ricevute|Buste paga|Contratti|Altro`, created once,
   ids in config). Approve with changes requires a note.
7. **Memory.** Only decisions reviewed by a person (approve, edit, reject + note) are upserted to Pinecone. The
   agent cites them next time ("last time you filed Enel bills under Casa/Bollette").
8. **Reset.** After each document ctrl calls `/reset`, in a `finally`: also after timeouts, exceptions and
   alarms. The UI timeline shows the restore as a step.

Running the pipeline: one document at a time (an `asyncio.Lock` around the whole chamber cycle, since a
restore would kill another document's job). While it runs, ctrl holds a Task (`POST /v1/tasks` on its own
socket) so it does not pause mid-pipeline; the Task is released in the same `finally`.

## State on ctrl (SQLite, `~/airlock/airlock.db`)

- `documents(id, source, box_file_id, sha256, name, status, created_at, ...)`
- `events(id, document_id, ts, kind, payload_json)` — every step: extract, llm call (model, tokens, ms),
  tool call, canary result, policy decision, approval, upload, restore.
- `budget(day, llm_calls, tokens)` — daily cap. Thresholds live in `config.py`, not in the UI.

## Web UI (served by ctrl)

Single page (server-rendered HTML + a little JS): queue, document detail with timeline (extract → agent → tools →
canary → policy → restore), approve / edit / reject with note, "Sync from Box", upload. Every request needs the
password (HttpOnly session cookie). The URL stays private while developing; it is made public for the demo only
with the password on. LLM-spending endpoints are rate-limited.

## Repository layout

```
ctrl/          FastAPI app: app.py, pipeline.py, agent.py, policy.py, chamber.py, box.py, memory.py, db.py, config.py, templates/
chamber/       baseline: setup.sh (apt, jail user, canaries, marker, key), worker.py, jail.py, extract.py
tests/         test_policy.py, test_jail_result.py
samples/       synthetic documents: scanned bill, payslip, contract, receipt, hostile PDF, red-team PDF
scripts/       deploy-ctrl.sh, build-chamber-baseline.sh

## Demo cases

1. Scanned Italian bill: OCR in the chamber → `run_python` checks the total → AUTO → Box `Bollette` → restore.
2. Payslip with IBAN: APPROVAL → you approve with a change and a note → note saved to Pinecone.
3. A second, similar payslip: `search_memory` finds your note and the proposal cites it.
4. Hostile receipt: the model flags the injection itself → QUARANTINE.
5. **Red team (assume the LLM is fooled)**: a test mode feeds the chamber a script that reads the canary token,
   tries to send it out (DNS refused), writes outside `/work` and hides the error → red + yellow → QUARANTINE →
   restore → `/check` shows the chamber clean again. This shows the layers under the model, not just the model.
```

## Threat model, in one table

| Threat | Defence |
|---|---|
| Hostile document instructs the LLM | untrusted-data framing; schema-only output; policy decides; no Box/HTTP tools for the LLM; approval for anything non-trivial |
| LLM-written code tries to steal keys | no keys exist in chamber (connectors hold them on ctrl, and chamber has no grants); canaries reveal the attempt |
| Code tries to phone home | chamber egress deny-all (DNS + raw IP blocked) |
| Code or parser exploit wrecks the chamber | restore to baseline after every document |
| Prompt injection propagates via chamber stdout to the next LLM call | stdout is size-capped, framed as untrusted data, canary-scanned; final answer still goes through policy |
| Prompt-injected ctrl agent abuses Box | Box connector cannot delete/move; the LLM has no Box tools at all |
| Jailed code tampers with the checker or the baseline | checker, marker and `/opt/airlock` are root-owned and not mounted in the jail; `/.sprite` (checkpoint API) not mounted; no sudo (`no_new_privs`) |
| Jailed code corrupts the result channel | the worker captures its output and returns capped, base64-encoded JSON |
| Fork bomb / memory / disk exhaustion | `timeout`, `prlimit` (procs, CPU, file size), size-capped tmpfs; the chamber is reset anyway |
| Two documents at once | one chamber cycle at a time (lock); reset in `finally` |
| Strangers on the public URLs | ctrl: password on every endpoint, daily LLM budget; chamber: shared key, and a jailed VM that resets |

Known limits:
- Airlock isolates the *analysis* and stops exfiltration; it uploads the original file unchanged to `Trusted`.
  It is not a CDR engine that rebuilds PDFs.
- The chamber key sits on ctrl's disk (not a provider credential; it only buys jailed, network-less compute).
- bwrap shares the chamber's kernel; a kernel exploit is out of scope, but it would still land in a VM with no
  connectors, no egress, and a reset after the document.
- Canaries catch reads and visible leaks, not every possible misbehaviour. OCR on phone photos is untested.
