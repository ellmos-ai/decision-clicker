# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
