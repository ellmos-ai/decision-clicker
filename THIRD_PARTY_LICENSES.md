# Third-Party Licenses / Dritte-Partei-Lizenzen

> **Audit Stamp:** Stand: 2026-09-12 / As of: 2026-09-12
> **Supply-Chain Integrity:** 100% Permissive Open Source (PSFL, MIT, Apache-2.0). Zero AGPL/SSPL copyleft contamination.

## Runtime Dependencies

`decision-clicker` has **zero external runtime dependencies**. It relies exclusively on the Python standard library (Python 3.10 through 3.13).

| Component | License | Type | Notes |
|-----------|---------|------|-------|
| Python Standard Library | Python Software Foundation License (PSFL) | Runtime Standard Library | Standard Library modules (`http.server`, `urllib.parse`, `json`, `pathlib`, `subprocess`, `argparse`, `dataclasses`, `re`, `shutil`, `typing`) |

## Development & Test Dependencies

Development, static analysis, linting, packaging, and contract test suites use the following development tools (never bundled into the distribution wheel):

| Tool | License | Purpose | Source / Registry |
|------|---------|---------|-------------------|
| `pytest` | MIT License | Unit, integration, and metadata contract testing | [PyPI: pytest](https://pypi.org/project/pytest/) |
| `ruff` | MIT / Apache-2.0 | Fast linting, formatting, and AST inspection | [PyPI: ruff](https://pypi.org/project/ruff/) |
| `build` | MIT License | PEP 517 / PEP 518 distribution package builder | [PyPI: build](https://pypi.org/project/build/) |
| `setuptools` | MIT License | Standard packaging build backend | [PyPI: setuptools](https://pypi.org/project/setuptools/) |

## Assets & Media

- `assets/banner.png` / `assets/banner.svg`: Maintainer-authored project artwork, rendered directly from editable vector SVG. Contains no external fonts, models, or third-party stock assets. Distributed under the repository's MIT license.

## Governance & Supply-Chain Invariant Audit

| Invariant | Audit Determination | Verification Evidence |
|---|---|---|
| **INV-LOCAL-01** | Zero-Egress Compliance | 0 network client dependencies. Stdlib `urllib.request` is unused; `http.server` binds exclusively to loopback. |
| **INV-NOELEV-03** | RunAsInvoker Compliance | No low-level OS hook packages or elevation daemons. Operates strictly within user-space permissions. |
| **INV-LOCK-08** | Lock Concurrency Compliance | Employs native pathlib inspection for `LOCK*.txt` fail-closed barriers without external locking daemons. |
