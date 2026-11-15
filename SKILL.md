---
name: decision-clicker
description: Operate, integrate, and verify Decision Clicker (ellmos-ai/decision-clicker) for local-first file-based decision chains (`TO-DECIDE-USER.txt`), proposal submission (`ProposalSubmitter` / `/api/new` / `decision-clicker add`), chain health checks, and human-in-the-loop governance boundaries.
---

# Decision Clicker — Product & Integration Skill

Use this skill when proposing decisions into a local `_DECISIONS` chain, checking chain contracts, launching the loopback review UI (`127.0.0.1:8096`), or embedding `decision_clicker.api`.

## Hard Safety & Governance Boundaries

1. **AI/Automation Proposal-Only Seam (`INV-HUMAN-11`):**
   - Automated agents and background pipelines MUST use `ProposalSubmitter` (Python) or `POST /api/new` (with `X-Decision-Clicker: 1`) or `decision-clicker add`.
   - Never attempt to mark an entry `DONE`, `decided`, or `implemented` via proposal paths; `/api/decide`, `/api/intake`, and `/api/undo/*` intentionally reject `Content-Type: application/json` and require an interactive human HTML-UI confirmation token.
2. **Single Data Canon (`INV-CANON-02`, `INV-ONEDOC-04`):**
   - `TO-DECIDE-USER.txt` is the sole active decision canon; `DECIDED-AND-DONE.md` is the append-only ledger. Never edit or overwrite already answered decisions (`INV-NOWRITE-06`).
3. **Fail-Closed Lock Guard (`INV-LOCK-08`):**
   - Before any chain mutation, check for foreign locks (`LOCK*.txt`, `LOCK.user.*`, `LOCK.until.*`, `LOCK.condition.*`). All writers abort immediately when a foreign lock is active.
4. **Loopback & Zero-Egress (`INV-LOCAL-01`, `INV-NOELEV-03`):**
   - Pure Python standard library (`>=3.10,<3.14`), zero external runtime dependencies, user-space execution (`RunAsInvoker`), binds strictly to loopback (`127.0.0.1` / `localhost` / `::1`).
5. **Versioned Proposals & Evidence:**
   - Proposals support `OPTIONEN-VERSION`, `EMPFEHLUNG-VERSION`, `EVIDENZSTAND`, and `KLÄRUNG NÖTIG` (`--status needs_evidence`), plus optional provenance fields (`EVIDENZANKER`, `GEGENBELEGE`, `FEHLENDE INFORMATIONEN`, `ERSTELLT VON`, `KONTEXT-FINGERPRINT`).

## CLI Workflows

```bash
# 1. Inspect chain integrity, active contract, and queue counts (read-only)
decision-clicker --check --chain /path/to/_DECISIONS

# 2. Propose a new open decision (preview with --dry-run first)
decision-clicker add "Rollout Strategy" \
  --chain /path/to/_DECISIONS \
  --frage "Which rollout pattern should be used?" \
  --option "A — Blue/Green cutover" \
  --option "B — 48h staged canary" \
  --empfehlung "B — Automated rollback safety" \
  --optionen-version 1 --empfehlung-version 1 \
  --dry-run

# 3. Preview desktop inbox intake without writing
decision-clicker intake --dry-run --chain /path/to/_DECISIONS

# 4. Launch human review mini-UI on 127.0.0.1:8096
decision-clicker --open --chain /path/to/_DECISIONS

# 5. Check or materialize chain _tools/ index scripts
decision-clicker chain-tools --check --chain /path/to/_DECISIONS
```

## HTTP Mini-Server (`http://127.0.0.1:8096`)

| Route | Method | Audience | Purpose |
|---|---|---|---|
| `/` | `GET` | Human / Agent | Overview metrics & open decisions |
| `/klick` | `GET` | Human | Single-card decision review UI |
| `/verlauf` | `GET` | Human | Reversible undo & audit history |
| `/neu` | `GET`, `POST` | Human | HTML form to submit an open entry |
| `/api/health` | `GET` | Agent / Monitor | Contract validity, counts, foreign locks |
| `/api/index` | `GET` | Agent | Full machine-readable chain index JSON |
| `/api/history` | `GET` | Agent | Clicker action history JSON |
| `/api/new` | `POST` | Agent (JSON) | Submit open proposal (`X-Decision-Clicker: 1` required) |

## Python API (`ProposalSubmitter` for Agents)

```python
from decision_clicker.api import ProposalSubmitter

submitter = ProposalSubmitter("/path/to/_DECISIONS")
receipt = submitter.submit(
    "Database Retention Window",
    frage="How long should raw audit snapshots be retained?",
    optionen=["A — 30 days", "B — 90 days"],
    empfehlung="B — Matches quarterly audit cadence",
    scope="global",
)
print(receipt["id"], receipt["line"])
```

## Verification Gates

```bash
python -m compileall -q src tests
python -m ruff check .
python -m pytest -ra -v
```
