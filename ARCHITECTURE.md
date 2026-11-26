# Airlock — Architecture

This file describes the code as it is. Measured numbers come from real runs on the two Sprites.

## Two Sprites

```
                 ┌──────────────────────── airlock-ctrl (Sprite) ─────────────────────────┐
 browser ───────►│ ctrl/web.py  (stdlib HTTP server, service on :8080, password cookie)  │
                 │ pipeline · policy.py (deterministic) · agent loop · SQLite (WAL)       │
                 │ never parses or executes untrusted content                             │
                 └──┬──────────────┬──────────────┬───────────────────┬───────────────────┘
                    │ gateway      │ gateway      │ gateway           │ HTTPS + X-Airlock-Key
                    ▼              ▼              ▼                   ▼
                 Ollama          Box          Pinecone      ┌──────── chamber-2 (Sprite) ─────────┐
                 deepseek-       Inbox in,    memory of     │ no connector grants, egress: deny * │
                 v4.1-flash      Trusted out  your reviews  │ chamber/worker.py (root, :8080)     │
                                                            │  /health /extract /run /check /reset│
                                                            │  └ untrusted work in a bwrap jail   │
                                                            │ restored to a checkpoint per doc    │
                                                            └─────────────────────────────────────┘
```

**Why two Sprites.** The connector gateway authenticates the *whole Sprite*, not a process, and
`/.sprite/api.sock` (checkpoint/restore) is world-writable inside a Sprite. Any code on airlock-ctrl could use
Box, Pinecone and Ollama. So untrusted content — parsing a PDF as much as running model-written code — never
touches ctrl. chamber-2 has no connector grants (connector access policies match the name prefix
`airlock-ctrl`) and an egress policy of `{"domain":"*","action":"deny"}`: DNS, the gateway and raw IPs all fail.

**Why not drive the chamber through the Sprites API.** We tried a Custom API connector pointing at
`api.sprites.dev/v1/sprites/chamber-2`; the gateway refuses it by design (`403 blocked: base URL targets the
Sprites API itself`). Instead the chamber runs a small trusted worker on its own Sprite URL, authenticated with
a shared key. Inbound requests come through the Fly proxy, so they work with egress denied, and they wake the
chamber from pause in ~0.3 s. No Sprites token lives on either VM.

## The chamber (`chamber/`)

- `setup.sh` builds the baseline: tesseract (eng+ita), poppler, bubblewrap; an unprivileged `jail` user;
  `/opt/airlock` (worker, extract.py, key, canary — root-only); the jail's home with root-owned canary files
  (`~/.config/box/token`, `~/.aws/credentials`) whose atime is set to 2020-01-01; the worker service.
- `scripts/build-chamber-baseline.sh` (run from a laptop) opens egress for apt, pushes files, runs setup,
  denies all egress, makes the chamber URL public (the worker requires the key), and checkpoints. The id goes
  to `.env.chamber` (gitignored) with the key, the canary and the URL.
- **The jail** (`worker.py: jail_argv`): `sudo bwrap --unshare-net --unshare-ipc --unshare-uts --clearenv`,
  read-only `/usr` and `/etc`, a 256 MB tmpfs `/tmp`, `/work` (fresh per job), the canary home, then
  `setpriv` to the jail uid with `no_new_privs` (so no sudo), `prlimit` (64 processes, 2 GB address space,
  50 MB files, CPU) and `timeout`. Not mounted: `/.sprite`, `/home`, `/opt/airlock`, the worker's state.
  (`--unshare-pid` is not available here, so after every job the worker runs `pkill -9 -u jail`.)
- **Files handed to the jail** are created by root with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0444: the jail can
  read them, never rewrite them, and a symlink planted by an earlier job is never followed.
- **`/extract`**: the document goes to `extract.py` in the jail: `pdftotext` (first 10 pages), falling back to
  `pdftoppm` + `tesseract` when a page has almost no text. It also reports the PDF's total page count
  (`pdfinfo`), whether pages or text were truncated, and active-content keys found in the PDF's object
  dictionaries (`/JavaScript`, `/OpenAction`, `/AA`, `/Launch`, ... — stream bodies are skipped, because image
  bytes can contain those sequences by chance).
- **`/run`**: model-written Python, document text on stdin, 20 s limit. Output is captured to files and returned
  base64-encoded, capped at 64 KB; for code jobs only, the worker notes "the jail stopped something" messages
  (`Network is unreachable`, `PermissionError`, ...).
- **`/check`**: canary atimes (a read moves atime, and the jail cannot reset it: the files are root-owned) and
  the files in `/work`.
- **`/reset`**: `sprite-env checkpoints restore <baseline>` on the chamber's own socket; the worker answers first.
  ctrl polls `/health` until `dirty: false`. Measured: files back in ~2 s, worker answering in ~4–8 s.

## ctrl (`ctrl/`)

| File | Role |
|---|---|
| `web.py` | UI + JSON API; one worker thread drains the queue; password cookie (HMAC, HttpOnly, Secure, SameSite=Strict) + `X-Airlock: 1` on POSTs; optional public read-only mode (`AIRLOCK_PUBLIC_READONLY=1`: anyone can look and start a red-team drill, which never reaches the model, Box or Pinecone, one at a time, 12 per hour, only the latest kept; every other action needs the password) |
| `pipeline.py` | one document at a time (lock); holds a Sprites Task so ctrl doesn't pause mid-document; fail-closed chamber check; reset in `finally`; reviews |
| `agent.py` | Ollama tool loop (OpenAI-compatible API) |
| `policy.py` | the rules: AUTO / APPROVAL / QUARANTINE |
| `chamber.py` | worker client; folds job results into `Alarms` |
| `box.py`, `memory.py` | Box and Pinecone through the Sprites gateway |
| `db.py` | SQLite (WAL, one connection, every query under a lock): documents, events, daily LLM budget |
| `cli.py` | the same pipeline from a terminal; `reset-demo` |

### One document

1. **Intake** — upload, or "Sync from Box" (`Airlock/Inbox`), or the red-team drill. ctrl stores the bytes.
2. **Chamber check** — `/health` must say clean; if dirty, one reset is tried; if the chamber is still dirty or
   unreachable the document goes back to the queue and the queue pauses (the UI says so). Fail closed.
3. **Extract** in the chamber.
4. **Agent** — tools: `search_memory` (read-only Pinecone search, results wrapped in `<past_reviews>`),
   `run_python` (in the chamber, at most 3 per document), `submit_extraction` (the only way to answer:
   `doc_type` from a closed enum, `issuer`, `date`, `total`, `currency`, `fields`, `arithmetic_ok`,
   `confidence`, `suspicious`, `reason`). No Box tool, no HTTP tool. At most 6 LLM calls per document and a
   daily cap. The canary string appearing in any tool call's arguments aborts the run.
5. **Alarms** — red: a canary was read (atime) or the canary string reached an output or a tool call.
   Yellow: a job timed out or was truncated, the jail blocked something during a code job, or the PDF carries
   active content.
6. **Policy** — QUARANTINE for an invalid proposal, any red or yellow alarm, an injection phrase found by a
   fixed rule, or the model's own `suspicious` flag (rule and model are reported separately). APPROVAL if the
   document is longer than what was read, the line items don't add up (`arithmetic_ok: false`), it contains
   sensitive data (SSN, bank account/routing, payment card numbers with a Luhn check, IBAN, Italian tax ID), its
   type is not bill/receipt, or confidence < 0.85. Otherwise AUTO. The model's labels can only make the result
   stricter.
7. **Output** — AUTO, or an approval by a person: the original and `<name>.airlock.json` are uploaded to the
   fixed folder for the type (`Airlock/Trusted/{Bills,Receipts,Paystubs,Contracts,Other}`). A review claims the
   document atomically (`awaiting_approval → filing`), so double clicks can't review twice; the upload runs in
   the background. Changing a field requires a note.
8. **Memory** — only reviewed decisions: the person's note plus short, flattened field values. A rejected
   document's issuer is not stored.
9. **Reset** — always, in `finally`. If it fails, the queue pauses.

## Threat model

| Threat | Defence |
|---|---|
| Hostile document instructs the LLM | untrusted-data framing; schema-only answer; fixed injection rule + model flag; policy decides; no Box/HTTP tools for the LLM; approval for anything sensitive |
| Model-written code tries to steal keys | there are none in the chamber (connectors hold them, and chamber has no grants); canary files reveal the read |
| Code tries to phone home | egress deny-all; no network namespace in the jail |
| Code tries to persist or tamper | fresh `/work` per job, root-owned read-only inputs, no-follow writes, `pkill` after each job, checkpoint restore after each document |
| Parser exploit in a hostile PDF | parsing happens in the jail, in the chamber |
| Active content in a PDF | detected and quarantined |
| Partially read document | APPROVAL |
| Abuse of Box through a fooled agent | the Box connector cannot delete, move, rename or copy; the LLM has no Box tools |
| Memory poisoning | only reviewed decisions; note + flattened fields; results framed as preferences |
| Dirty chamber reused | fail-closed health check before every document |
| Strangers on the URLs | ctrl: password on every action, daily LLM cap; chamber: shared key, jailed network-less compute that resets |

## Known limits

- Airlock isolates the *analysis* and stops exfiltration; it files the original unchanged. It is not a CDR
  engine that rebuilds PDFs.
- The injection rule is a short list of phrases; a paraphrase passes it and the model is the next layer (in our
  test the model caught a paraphrased injection on its own). The canaries cover the case where both fail.
- bwrap shares the chamber's kernel; a kernel exploit is out of scope, but it lands in a VM with no connectors,
  no egress, and a reset after the document.
- The chamber key sits on ctrl's disk (it buys jailed, network-less compute, nothing else).
- Only the first 10 pages are read; longer documents go to a person.
- `/proc` is shared read-only with the jail (no pid namespace available): don't pass secrets on command lines.
