# Privacy

Decision Clicker processes decision records locally. It does not send
telemetry, analytics, crash reports, prompts, or chain content to the project
maintainers or to a third-party service.

The operator chooses the decision-chain and optional inbox paths. These files,
derived indexes, and backups can contain personal or confidential information.
Their retention and access controls remain the operator's responsibility.

Repository tests use synthetic fixtures only. Contributors must never add real
decision records, usernames, home-directory paths, access tokens, or private
system configuration to fixtures, examples, issues, or pull requests.

Source distributions explicitly include only the approved synthetic inbox and
chain fixtures. A local `tests/data/postfach_2026-08-07.txt`, if present for a
private audit, is excluded from sdist and wheel artifacts. This packaging rule
does not open the separate `PRIVATE.txt` publication gate.
