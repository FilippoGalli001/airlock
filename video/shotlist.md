# Airlock demo video — shot list

Target: ~1:40, 1920x1080, 30 fps, captions only (no voice), light theme. Real footage of the live app, driven by
`video/record.mjs` (Playwright) through `sprite proxy` to airlock-ctrl; title cards, zooms and captions in Remotion
(`video/remotion`). Long waits are sped up; the real timings stay visible in the UI badges.

## State before recording
- Box `Airlock/Trusted` empty (done by hand). `reset-demo` on ctrl.
- Pre-loaded with the CLI (not shown being processed): `vendor-contract.pdf`, `service-agreement-v2.pdf`,
  `paystub-oct.pdf` (left awaiting approval).
- Live in the takes: `electric-bill-oct.pdf`, `plumber-invoice.pdf`, the approval of `paystub-oct.pdf`,
  `paystub-nov.pdf`, the red-team drill.

## Scenes

| # | Time | Scene | On screen | Caption |
|---|---|---|---|---|
| 1 | 0:00–0:08 | Hook (title card) | Dark card, "Airlock", subtitle | "Your documents can attack your AI." → "Airlock opens them in a Fly Sprite with no keys, then wipes it." |
| 2 | 0:08–0:18 | Architecture | Top bar of the app, zoomed: left card, arrow, right card | Left: "airlock-ctrl calls the connectors (Ollama · Box · Pinecone), never opens a file" · Right: "chamber: 0 connectors, egress denied, restored after every document" |
| 3 | 0:18–0:32 | Bill → AUTO (take A) | Upload `electric-bill-oct.pdf`; stage strip advances (sped up); open "Show the code the model wrote"; verdict "Filed on Box automatically"; badge back to CLEAN | "A scanned bill: OCR'd inside the jail" → "The agent checks the math with code, inside the jail" → "Clean bill → filed on Box automatically" |
| 3b | 0:32–0:34 | Box clip (user's 1 s recording) | The file in Box `Airlock/Trusted/Bills` | "Really on Box" |
| 4 | 0:34–0:46 | Invoice → overcharge (take B) | Upload `plumber-invoice.pdf`; zoom on "items 289.50 vs total 319.50: off by 30.00" and the policy reason | "A plumber's invoice. The agent's code finds a $30 overcharge" → "Policy: a person must look" |
| 5 | 0:46–1:02 | Paystub → review → memory (takes C, D) | C: open `paystub-oct.pdf`, type issuer "Acme Software (payroll)", type the note, click "Approve with my changes". D: upload `paystub-nov.pdf`, zoom on "Pinecone match 0.8x" and the issuer already corrected | "SSN + bank account → you decide" → "Your correction is remembered (Pinecone)" → "Next paystub: applied automatically" |
| 6 | 1:02–1:12 | Hostile contract (take E) | Click `vendor-contract.pdf`: "Quarantined", reasons "rule:" + "model:"; click `service-agreement-v2.pdf`: only "model:" | "A contract that tells the AI to file it as a receipt and leak a token" → "Caught by a fixed rule and by the model" → "Paraphrased: the rule misses it, the model doesn't" |
| 7 | 1:12–1:30 | Red-team drill (take F) — climax | Click "Red-team drill"; chamber badge DIRTY; table "What the jail answered"; "Red alarm: quarantined"; badge RESTORING → CLEAN | "Now assume the AI was fooled" → "Hostile code runs in the chamber" → "No keys to steal. No network. Canary tripped." → "Nothing leaves. The chamber is wiped." |
| 8 | 1:30–1:40 | Close (title card) | Dark card, motto, links | "The AI proposes. Code decides. You approve what's risky." → "Every document gets a fresh Sprite." → repo + live demo URLs |

## Rules
- Nothing personal on screen: clean Chromium profile, no Fly login page, no email, no local paths.
- One take per scene, own file; re-shoot only what fails.
- Captions ≥ 44 px, max ~8 words per line, on screen ≥ 2 s each.
