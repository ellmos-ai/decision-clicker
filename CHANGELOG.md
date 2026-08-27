# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Promote `decision-clicker` from an optional policy-registry seam to the
  fixed human writer/UI component of the decision-system bundle. The parent
  registry now requires the `decision.clicker` capability, while this package
  remains directly startable and keeps the integration data-level.
- Adopt the one-document active contract: only unanswered, decision-ready
  entries in `TO-DECIDE-USER.txt` are clickable or counted as active.
- A click now stores reversible full-block evidence and removes the answered
  block from the active template; undo restores that block and retains the
  append-only reset history.
- New entries require an explicit question and options, and ID allocation also
  reserves identifiers found in nested historical archives.

### Added

- `ellmos-module.v2.json`: originally registered decision-clicker as an
  optional structural sub-module of `policy-registry` (ticket
  T-20260824-474639761, user decision 2026-08-24, F2). The 2026-08-27 user
  decision supersedes only the optional composition status; the historical
  data-level seam remains documented.
  Both tools point at the same on-disk `_DECISIONS` chain -- the coupling is
  data-level, not a code dependency in either direction.
- `tests/test_module_manifest.py`: contract test for the manifest (JSON
  validity, private-visibility gate while `PRIVATE.txt` exists, optional-not-
  required seam, version parity with `pyproject.toml`).

## [1.0.1] - 2026-08-21

### Added

- Self-contained synthetic decision-chain and inbox fixtures.
- English and German README pair, security and privacy guidance, `llms.txt`,
  package metadata, CI, and CodeQL workflows.
- Console-script entry point `decision-clicker`.
- Regression coverage for stale indexes, structural input injection,
  cross-origin writes, DNS rebinding, and concurrent HTTP mutations.

### Changed

- Derive the OneDrive fallback from the runtime environment instead of a
  hard-coded personal path.
- Keep the first decision in a fresh Cut-and-Clue part behind its header,
  predecessor pointer, and quick index instead of inserting it before them.
- Use a neutral Decision Clicker lock name and owner.
- Replace host-dependent integration tests with deterministic portable tests.
- Bind register tests to their synthetic inbox fixtures on clean CI hosts, and
  let the private non-uploading CodeQL job read its own workflow metadata.
- Enforce loopback-only serving, local Host/Origin checks, guarded JSON writes,
  parser-safe context rendering, and process-local write serialization.
- Reject external, protocol-relative and CR/LF-bearing redirect targets, and URL-encode dynamic
  decision IDs before they reach the `Location` header.
- Run CI on Linux, macOS, and Windows for Python 3.10 through 3.13; pin workflow
  actions to immutable commits and retain CodeQL SARIF without uploading it.

### Removed

- The one-time, project-specific seed helper from the distributable tree.
- The redundant live-chain HTTP self-test; deterministic synthetic HTTP tests
  now cover the same workflow without mutating operator data.

## [1.0.0] - 2026-08-07

### Added

- Local facade, CLI, mini UI, conservative writer, inbox intake, history,
  backups, and guarded undo for file-based decision chains.
