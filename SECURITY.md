# Security policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do
not include real decision-chain content, credentials, personal paths, or other
sensitive records in a public issue.

## Deployment boundary

Decision Clicker is a local administrative tool. Its mini server has no
authentication and is intended only for a trusted user on the same machine.
The server rejects non-loopback bind addresses. Do not place port 8096 behind
a LAN, VPN, container, tunnel, or public reverse proxy.

Browser writes must present a matching local Host and Origin; cross-site Fetch
Metadata is rejected. Local JSON automation must also send
`X-Decision-Clicker: 1`. These checks reduce browser-based attacks; they are
not remote-user authentication.

The configured decision-chain directory may contain sensitive governance
records. Apply operating-system permissions, storage encryption, and backups
appropriate to those records. Decision Clicker's own backup directory is not
a substitute for a system backup.

## Security invariants

- Foreign `LOCK*.txt` files stop writes.
- Indexed IDs are rechecked against the target file before writing.
- Existing decisions are never overwritten.
- Undo requires a Decision Clicker provenance marker.
- Scalar fields reject line breaks and multiline context is parser-safe.
- HTTP request bodies are size-limited.
- Mutations are serialized inside one process. Separate processes are not
  coordinated; run only one writer process per decision chain.
- No telemetry or remote API is included.
