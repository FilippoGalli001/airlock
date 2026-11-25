# DEVLOG

## Current status
- Phase: **spike done except the LLM** (Wed Nov 25 evening). Direction: **Airlock, option B**
  (`airlock-ctrl` + `chamber-1`).
- Box, Pinecone, Ollama (deepseek-v4.1-flash, $5 credit) verified through the gateway.
- ctrl drives the chamber through a key-protected worker on the chamber URL (Custom API to the Sprites API is
  refused by the gateway).
- **Chamber done and verified** (baseline v11, red-team smoke test passes).
- **ctrl pipeline works end to end from the CLI** on airlock-ctrl: all 5 demo cases pass (see log).
- Next: web UI (FastAPI or stdlib server, password, queue, timeline, approve/edit/reject, Sync, upload,
  red-team button), service on :8080, then README + video.

## Spike checklist (decides the direction)
Sprite `airlock-spike`, org `filippo-galli`, URL `https://airlock-spike-jmgx.sprites.app` (auth: sprite = private).

| # | Check | Result |
|---|---|---|
| 1 | Sprite CLI installed on Windows | ✅ `sprite version 2026-11-03 (4eb1509)` |
| 2 | Login + create Sprite | ✅ needed a credit card on the org first ($30 trial credit). Create: 0.5 s. Ubuntu 26.04.1, 8 vCPU, 15 GiB RAM, 99 GB disk, passwordless sudo, no tokens in env |
| 3 | Connectors available to the org (`gateway/list` → `available`) | ✅ box, pinecone, ollama, apify, anthropic, openai, gemini, custom_api, … all listed. `connections: []` (none configured yet) |
| 4 | LLM call + Box list/download through the gateway | ⏳ needs connectors |
| 5 | Checkpoint / restore | ✅ create **~75 ms**, no process interruption (200 ms heartbeat, no gap). Restore from inside: files back in ~2 s, HTTP service answering in ~5 s (new pid, restarted from its on-disk definition). Reverted home files and a file created with sudo in `/etc` |
| 6 | Sleep / Tasks API | ✅ a service alone does **not** keep the Sprite awake (paused after ~15 s idle; 68 s heartbeat gap; process resumed with same pid on wake). A Task (`POST /v1/tasks`, `expire`) kept a detached 60 s job running with no pause |
| 7 | OCR | ✅ apt install tesseract-ocr tesseract-ocr-ita poppler-utils: 15 s. Synthetic noisy rotated scan as PDF: `pdftotext` → 1 char, `tesseract -l ita` → full text incl. IBAN, 0.7 s |
| 8 | Public URL | ✅ private URL answers 302 (login). Public: wake from pause in **~0.28 s**, process resumed. Reverted to private. App-level password still to write |
| 9 | Egress policy from outside | ✅ `sprite api /policy/network -- -X POST -d '{"rules":[{"domain":"api.sprites.dev","action":"allow"}]}'` → gateway 200, pypi/example.com fail at DNS (curl exit 6). Reset with `{"rules":[]}`. (`/.sprite/policy/network.json` did not appear inside.) |
| 10 | Sandbox for untrusted code | ✅ see "Security finding" below |

Decision rule: checkpoints < ~10 s and restore restarts services → **Airlock** ✅.

### Security finding (changes the architecture)
The gateway authenticates the **Sprite**, not the process. Any process in the Sprite — including an
unprivileged user — can call every connector granted to that Sprite, and `/.sprite/api.sock` is
`srw-rw-rw- root` so any process can also create/restore checkpoints. Untrusted code must therefore never run
as a plain process in a Sprite that has connector grants.
- `iptables -m owner` does not work (kernel lacks the owner match). `unshare -n` works under sudo.
- **Working sandbox**: bubblewrap + setpriv, no network namespace, no `/.sprite`, no `/home`, read-only system:
  ```
  sudo bwrap --unshare-net --unshare-ipc --unshare-uts --die-with-parent \
    --ro-bind /usr /usr --ro-bind /etc /etc --symlink usr/bin /bin --symlink usr/lib /lib \
    --symlink usr/lib64 /lib64 --ro-bind /proc /proc --dev /dev --tmpfs /tmp \
    --bind /srv/work /work --chdir /work \
    /usr/bin/setpriv --reuid=<jail uid> --regid=<jail uid> --clear-groups --no-new-privs <cmd>
  ```
  Inside: uid jail, curl exit 6, `/etc` read-only, sudo refused, `/usr/bin/python3` and tesseract work.
  (`--unshare-pid`/`--proc` fails: "Can't mount proc"; `--uid` needs a user namespace — hence setpriv.)
- Docs contradictions resolved: checkpoints do not stop processes (the "10–30 s" page is stale); services do not
  keep the Sprite awake (the in-Sprite `services.md` is wrong, the public lifecycle page is right).
- Inside the Sprite only system python (`/usr/bin/python3`) is visible to the jail; pyenv shims live under `/.sprite`.

### Option B check (two Sprites), after Gemini's review — evening Nov 25
Gemini's review: prefer **B** = `airlock-ctrl` (UI, SQLite, connectors, never runs untrusted code) +
`chamber-1` (no connectors, egress denied, restored to a clean baseline after each document). Reasons accepted:
in A the bwrap jail already confines writes, so a restore would only kill the UI and wipe local state; B is
Fly's own "untrusted code" use case. Also accepted: **connector prefix must be `airlock-ctrl`**, not `airlock`
(the old prefix would also match a chamber named `airlock-…`); `{"rules":[]}` means allow-all, not deny-all.
- `chamber-1` created (1.1 s). Deny-all egress works: `{"rules":[{"domain":"*","action":"deny"}]}` →
  gateway, pypi, example.com all fail at DNS (exit 6), raw IP 1.1.1.1 fails (exit 7).
  `sprite exec` from outside still works with egress denied.
- REST exec works as a plain POST (no WebSocket, no mini-server needed):
  `sprite api "/exec?cmd=echo&cmd=hello-from-rest&path=echo" -- -X POST` → `hello-from-rest`.
  REST checkpoints list works too.
- Open point: ctrl needs a Sprites API token to drive the chamber. Plan: a **Custom API connector** to
  `https://api.sprites.dev` holding the token, granted only to `airlock-ctrl`. The CLI has no scoped tokens
  (`sprite org` only adds/lists), so the token is org-wide (could destroy Sprites or reopen the chamber's egress).
  Mitigation to verify: the connector's endpoint allow-list (API-only) limited to the chamber's exec and
  checkpoint/restore paths.

### Connectors (user set up Ollama, Box, Pinecone with access prefix `airlock-ctrl`) — Nov 25 evening
- Created Sprite `airlock-ctrl`. `gateway/list` from it → 3 connections; from `airlock-spike` → 0. Access policy works.
  Gateway base URLs (connection IDs, not secrets):
  `box/MKmGx1iQL7QdnxpbtXhiUA`, `ollama/LVV5fvksFt-BgAkRq6QUGw`, `pinecone/GcKFwwQUtTfpw-bjM0lfmA`.
- **Ollama**: key accepted, `/api/tags` lists 25 models (incl. `deepseek-v4.1-flash`, `gpt-oss:120b`, `glm-5.3-flash`),
  but every chat call → **402 "Add usage credits or subscribe"** (native and OpenAI-compatible API, small models too).
  The account has no free inference. → LLM decision pending with the user.
- **Box** (10 GB free account, empty root): list, item info, search, download, upload, create folder ✅.
  Download: the gateway follows Box's 302 itself → 200 with content. DELETE, rename/move (PUT), copy →
  403 `endpoint is not supported by the Box connector`. So the connector cannot destroy or move files: good for
  safety; processed state must be tracked on ctrl, not by moving files. Left in Box by the test (user to delete
  by hand): file `airlock-spike-test-*.txt`, folder `Airlock-Test`.
- **Pinecone**: `POST /indexes/create-for-model` (multilingual-e5-large, integrated embedding) → index
  `airlock-memory` ready in 3 s. Data plane through the gateway by index name:
  `/indexes/airlock-memory/records/namespaces/<ns>/upsert` (NDJSON) and `/search` with `inputs.text` ✅;
  an Italian query found the right note first (0.86). No separate embedding model needed.
- **Ollama after the user loaded $5**: tool calling with `tool_choice: required` works on deepseek-v4.1-flash,
  gpt-oss:120b, glm-5.3-flash: 1.3–1.9 s, ~520–760 total tokens per call (≈ $0.0004). All three extracted the bill
  correctly and flagged the hostile receipt as `suspicious` without obeying it. Chosen: deepseek-v4.1-flash.
- **REST exec details**: `POST /v1/sprites/chamber-1/exec?cmd=...&stdin=true` with the body as stdin; 300 KB of
  random bytes arrived intact (same SHA-256). Response is `application/octet-stream`, chunks prefixed by
  `0x01` (stdout), `0x02` (stderr), `0x03 <exit code byte>`. Special characters in `cmd` query values gave 400 →
  always run fixed scripts by path. Plan: chamber prints base64 JSON only.
- Custom API connector (docs): dashboard fields base URL, token, token placement (header/query/url path);
  `allowed_endpoints`/`blocked_endpoints` via API only (`PUT /v1/oauth/connections/{id}`, full-access token).
  Tokens are created at sprites.dev/account. Plan: base URL `https://api.sprites.dev/v1/sprites/chamber-1`
  (scopes the token to one Sprite if the gateway does not allow `..`), test path traversal after creation.
- Wrote `ARCHITECTURE.md`.

### Custom API → Sprites API: refused by design; chamber worker instead — Nov 25 ~22:00
- User created a dedicated Sprites token and a Custom API connector (`custom_api/dwe0RJCkidePBolB1agc8Q`,
  base URL `https://api.sprites.dev/v1/sprites/chamber-1`, prefix `airlock-ctrl`). Every call through it →
  `403 blocked: base URL targets the Sprites API itself`. Traversal attempts (`..`, `%2e%2e`, `%2E%2E%2F`,
  `..%2f`, double-encoded) → `400 invalid path: path traversal detected`. The gateway notes: requests limited to
  8 MB, redirects not followed. → connector and token are useless: **user to delete the connector and revoke the token**.
- Replacement, tested: a worker service on chamber-1's URL with a shared key header. From ctrl: wrong key → 401,
  right key → 200 with a 2 MB body in 0.23 s, while chamber egress stays deny-all (inbound goes through the
  proxy). Test worker removed, chamber URL back to private (auth sprite).
- Gemini review #2 accepted: run `run_python` through a fixed wrapper returning capped base64 JSON; no sudo for
  jailed code, checker outside the jail; lock + reset in `finally` + Task on ctrl; closed `doc_type` enum mapped
  to fixed Box folders; CDR limit stated; red-team demo case; thresholds in config.
- atime canary verified on chamber-1: `/` is overlay `relatime`; atime backdated to 2020 → first `cat` sets it to
  now (later reads don't move it again, which is fine: compare with the baseline time).
- ARCHITECTURE.md updated accordingly (worker endpoints `/extract /run /check /reset /health`).

### Chamber built and verified — Nov 25 ~22:20
Files: `chamber/worker.py`, `chamber/extract.py`, `chamber/setup.sh`, `scripts/build-chamber-baseline.sh`,
`scripts/chamber_smoke.py`, `samples/make_samples.py` (4 synthetic scanned PDFs, fake data).
`bash scripts/build-chamber-baseline.sh` opens egress, pushes files (tar over `sprite exec --stdin`), runs setup,
denies all egress, makes the chamber URL public (worker requires the key), checkpoints → `.env.chamber`
(gitignored: key, canary, URL, baseline id). Current baseline: **v11**.
Smoke test (`python -u scripts/chamber_smoke.py`), all from the laptop over the public chamber URL:
- wrong key → 401; health 0.24 s.
- scanned bill → OCR inside the jail, full text, 2.5 s; `run_python` recomputes the total (78.40 = sum of parts).
- **red team** script: canary read → **detected via atime**; HTTPS exfil and raw IP → `Network is unreachable`;
  writes to `/home/jail`, `/etc`, `/opt/airlock` refused; `os.utime` on the canary → PermissionError
  (root-owned); sudo refused (no_new_privs); `/.sprite/api.sock` absent; env = BOX_TOKEN(canary), HOME, LANG, PATH, PWD.
- `/reset` → clean again (`dirty: false`, canary atime back to 2020, `/work` empty) in **3.8–6.1 s**.
Bugs fixed on the way: `sprite-env` not on root's PATH under sudo (use `/.sprite/bin/sprite-env`); bwrap creates
implicit parent dirs as 0700 (add `--perms 0755 --dir /home|/airlock`); jail `/tmp` tmpfs was root 0755
(`--perms 1777`). `pdftoppm` needs a writable `/tmp`.

### ctrl pipeline end to end from the CLI — Nov 25 late evening
Code (stdlib only, no pip deps yet): `ctrl/config.py policy.py http.py chamber.py agent.py box.py memory.py
db.py pipeline.py cli.py`, `tests/test_policy.py` (24 tests, `python -m unittest discover -s tests -t .`),
`scripts/deploy-ctrl.sh` (tar → `~/airlock` on airlock-ctrl, env file `~/airlock/airlock.env` = .env.chamber +
.env.ctrl with a generated UI password). `python3 -m ctrl.cli setup` created Box `Airlock/Inbox`,
`Airlock/Trusted/{Bollette,Ricevute,Buste paga,Contratti,Altro}` and checked the Pinecone index.
All five demo cases, run on airlock-ctrl:
1. scanned bill → OCR (2.6 s) → agent: search_memory + run_python (checks 52,10+12,00+7,17+7,13 = 78,40) →
   AUTO → uploaded to `Bollette` (+ `.airlock.json`) → reset 8.6 s. ~25 s total, 2 LLM calls, ~2.3k tokens.
2. payslip → APPROVAL (codice fiscale + type) → approved with an edit (issuer) and a note → `Buste paga` →
   remembered in Pinecone.
3. second payslip → memory hit 0.864 on the review → proposal uses the corrected issuer and says
   "Emittente scritto come da tua revisione precedente".
4. hostile receipt → QUARANTINE by the deterministic injection rule ("system note"); the model also set
   suspicious=true and said it ignored the hidden instructions.
5. `process --redteam` → RED (canary read), "Network is unreachable", writes and utime refused → reset 5.3 s.
Fixes: OCR read the IBAN as `1T60…` → IBAN regex now tolerates `1T`/`lT` (test added). Deleted the spike's
fake memory records d1/d2 from Pinecone.
Box now holds filed copies from these runs (bill, payslip) — fine as demo data, clean before recording.

## Log

### 2026-11-25 (Wed)
- Analysed the contest and the earlier Interop Triage project (InterSystems contest). Decided not to reuse its
  code (IRIS on a Sprite makes no sense, and the rules require code built this week); reuse only the
  "AI proposes, code decides" pattern and the prompt-injection demo.
- First plan ("Box Butler": Box organiser with Telegram approvals) was reviewed by another model. Accepted
  critiques: Sprite used like a Lambda, schedule too optimistic, Telegram token goes in the URL path (bad fit for
  the Custom API connector), Box webhook signing keys belong to Fly's Box app, OCR needed, a restore wipes an
  on-disk undo log, public URL abuse, use Ollama (partner/judge). Rejected: "checkpoint needs a Fly token inside
  the VM" (docs show `sprite-env checkpoints` over `/.sprite/api.sock`) and "Sprite sleeps mid-task" (Tasks API).
- New direction: **Airlock** (reduced scope) with canary credentials as the misbehaviour detector.
- Installed the Sprite CLI for Windows (installer checks SHA256). `git init`.
- `sprite login`: Fly OAuth OK, but creating the Sprite token failed:
  "Add a credit card to start using Sprites. $30 in free trial credit lands as soon as you do."
  (org `filippo-galli`). The "no credit card" / "free plan" claims on the marketing pages do not hold for this
  org. Blocked on the user adding a card.
