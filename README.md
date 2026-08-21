<img src="assets/banner.png" width="100%" alt="Decision Clicker banner">

# Decision Clicker

[Deutsch](README.de.md) · English

Decision Clicker is a local-first Python library, CLI, and small web UI for
file-based decision chains. It lets people review, record, undo, and audit
decisions without moving the source of truth into a database.

The decision-chain text files remain canonical. Generated JSON and Markdown
indexes are rebuildable caches.

## Safety model

- The web server enforces a loopback bind (`127.0.0.1` or `localhost`) and has
  no remote-access authentication.
- Mutating HTTP requests validate the local Host and browser Origin. JSON
  writes additionally require `X-Decision-Clicker: 1`.
- One running process serializes its write transactions. Do not run multiple
  Decision Clicker processes against the same chain.
- Every write checks for foreign `LOCK*.txt` files and stops when one exists.
- Before changing a chain file, the writer creates a byte-for-byte backup.
- A decision field is changed only when it is still a placeholder.
- Undo is accepted only for decisions provably written by Decision Clicker.
- Decision evidence is append-only; undo adds a reset record instead of
  deleting the original record.
- Scalar entry fields reject line breaks; free-form context is rendered in a
  parser-safe quoted block.
- Tests use synthetic fixtures and never access personal decision data.

## Requirements

- Python 3.10 through 3.13.
- A decision-chain directory containing:
  - one or more `TO-DECIDE-USER*.txt` files;
  - `DECIDED-AND-DONE.md`;
  - `_tools/decisions_index.py`, implementing the `decisions.index/1`
    parser contract.

The index parser is intentionally external. Decision Clicker loads that one
parser instead of maintaining a second, subtly different parser.

## Install

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

For runtime-only use, install without the `dev` extra:

```bash
python -m pip install .
```

## Configure

`DECISION_CLICKER_CHAIN` is the recommended explicit configuration:

```powershell
$env:DECISION_CLICKER_CHAIN = "D:\data\_DECISIONS"
decision-clicker --check
```

```bash
export DECISION_CLICKER_CHAIN="$HOME/data/_DECISIONS"
decision-clicker --check
```

| Variable | Purpose | Default |
| --- | --- | --- |
| `DECISION_CLICKER_CHAIN` | Canonical decision-chain directory | Derived from the local OneDrive root |
| `DECISION_CLICKER_INBOX` | Optional legacy inbox path; multiple paths use the OS path separator | `<OneDrive>/Desktop/TO-DECIDE-USER.txt` |
| `DECISION_CLICKER_HOST` | Mini-UI bind host; loopback only | `127.0.0.1` |
| `DECISION_CLICKER_PORT` | Mini-UI port | `8096` |

Windows OneDrive environment variables are detected. The neutral fallbacks are
`~/OneDrive` and `~/Library/CloudStorage/OneDrive-Personal`. For other macOS
OneDrive layouts, set `DECISION_CLICKER_CHAIN` explicitly.

## Use

Check the chain without starting a server:

```bash
decision-clicker --check
```

Start the local mini UI:

```bash
decision-clicker --open
```

On Windows, `START.bat` performs the same local startup and avoids launching a
second instance on port 8096.

Create a decision:

```bash
decision-clicker add "Choose a rollout" \
  --frage "Which rollout should be used?" \
  --option "A — staged" \
  --option "B — immediate" \
  --empfehlung "A — easier to reverse" \
  --dry-run
```

Remove `--dry-run` after reviewing the rendered entry.

## Interfaces

| Interface | Role |
| --- | --- |
| `decision_clicker.api.DecisionClicker` | UI-independent facade for integrations |
| `decision-clicker` | CLI for checks, creation, inbox intake, and the local server |
| Mini UI on port 8096 | Lightweight fallback UI using only the Python standard library |
| Unified GUI adapter | Optional regular UI; consumes the same facade and writer |

The mini UI includes an overview, one-at-a-time review, history and undo,
creation, and a deduplicated register. JSON endpoints expose health, index,
history, creation, decisions, undo, and inbox intake to local automation.
Mutating JSON calls must send the explicit local-API guard header:

```bash
curl -H "Content-Type: application/json" \
  -H "X-Decision-Clicker: 1" \
  --data '{"title":"Choose a rollout"}' \
  http://127.0.0.1:8096/api/new
```

## Write semantics

For a decision click, the writer:

1. rejects foreign locks;
2. verifies that the indexed line still belongs to the expected decision ID;
3. creates a backup under `_decision-archive/_bak/`;
4. fills only `ENTSCHEIDUNG DES USERS:` and adds a dated tool marker;
5. appends evidence to `DECIDED-AND-DONE.md`;
6. rebuilds the derived index artifacts.

It never marks implementation as verified. A decision remains in the active
chain until the surrounding governance process verifies implementation.

## Legacy inbox intake

The optional inbox is a compatibility path, not a second source of truth.
Decision Clicker recognizes both regular headings and the legacy `ID: D-…`
form. Intake preserves IDs and original wording, adds a takeover marker to the
inbox, and is idempotent.

## Development

```bash
python -m ruff check .
python -m pytest -q
python -m build
```

The test suite covers parsing, configuration, lock behavior, byte-preserving
writes, backups, ID allocation, structural-injection protection, all creation
paths, HTTP origin/host checks, concurrent requests, intake, history, and
byte-identical decision/undo round trips. CI runs it on Linux, macOS, and
Windows with every supported Python version.

## Boundaries

- Decision Clicker records user choices; it does not choose on the user's
  behalf and does not predict answers.
- It does not verify implementation or move entries into a completed state.
- It does not own the decision-chain parser or the optional Unified GUI.
- It has no telemetry and no runtime dependency outside the Python standard
  library.

See [SECURITY.md](SECURITY.md), [PRIVACY.md](PRIVACY.md), and
[CONTRIBUTING.md](CONTRIBUTING.md) before deploying or contributing.

## License

Project-authored code, documentation, and assets are licensed under the MIT
License. See [LICENSE](LICENSE). Third-party components and their notices are
listed in [THIRD_PARTY.md](THIRD_PARTY.md).
