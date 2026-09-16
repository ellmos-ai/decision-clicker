# Security Policy / Sicherheitsrichtlinie

[English](#english) · [Deutsch](#deutsch)

---

<a name="english"></a>
## English

### Supported Versions

| Version | Supported          | Security SLA                                            |
|---------|--------------------|---------------------------------------------------------|
| 1.1.x   | :white_check_mark: | 48h Acknowledgment / 5-Day Triage / 30-Day Remediation  |
| < 1.1.0 | :x:                | Best effort / Update recommended                        |

Security fixes are prioritized for the latest minor release line on the default `master` branch.

### Reporting a Vulnerability

If you discover a security vulnerability, please do **NOT** open a public issue. Instead, report it privately via GitHub:

- **GitHub Private Advisory:** [Report a Vulnerability](https://github.com/ellmos-ai/decision-clicker/security/advisories/new)
- **Primary Security Contact:** `security@open-bricks.org`
- **Organizational Security:** `security@ellmos.ai`
- **Maintainer Escalation:** `lukas@open-bricks.org` / `support@lukasgeiger.com`

We commit to an initial response acknowledging receipt within **48 hours**, a formal triage assessment within **5 business days**, and a targeted remediation plan or patch release within **30 calendar days**.

### Deployment Boundary & Threat Model

Decision Clicker is a local-first administrative UI and CLI tool:
1. **Loopback-Only Binding:** The integrated HTTP mini-server strictly binds to `127.0.0.1` or `localhost`. It enforces no remote authentication because it is designed strictly for local operator use. Never expose port `8096` to public networks, LANs, containers, or unsecured reverse proxies.
2. **Host & Origin Validation:** All mutating HTTP requests (`POST /api/decide`, `POST /api/undo/...`) enforce exact matching of the local `Host` header and browser `Origin`. Cross-site Fetch Metadata is rejected.
3. **Human-UI Boundary (least authority):** `/api/new` is the only JSON write path and may only submit *open proposals*; it requires the custom header `X-Decision-Clicker: 1`. `/api/decide`, `/api/intake` and `/api/undo/*` reject JSON even with that header and require an explicit action in the HTML UI, carrying a five-minute, single-use confirmation bound to server instance, action and record. Changing a request's content type therefore does not cross the boundary. The Python facade split (`ProposalSubmitter` vs `DecisionClicker`) is a least-authority integration contract, not a sandbox for code that already has unrestricted imports and filesystem access.
4. **Non-Elevation / RunAsInvoker:** Decision Clicker executes entirely in user space without requiring root or administrative privileges.

### Core Security & Data Integrity Invariants

- **Fail-Closed Foreign Locks:** Every write operation checks for existing `LOCK*.txt` or active agent locks before modifying files. Any lock immediately halts execution.
- **Single Data Canon:** The file-based decision chain (`TO-DECIDE-USER.txt`) remains the sole authority. Rebuilt Markdown or JSON indexes are disposable caches.
- **No Overwriting:** Existing decisions are never overwritten; only placeholder fields can be updated.
- **Byte-Preserving Backups:** A byte-for-byte pre-write backup is created before any mutation.
- **Provenance-Guarded Reversible Undo:** Undo operations verify Decision Clicker provenance markers and log reset events to an append-only audit trail.
- **Zero-Egress Privacy:** No external network requests, analytics, or telemetry are ever performed.

---

<a name="deutsch"></a>
## Deutsch

### Unterstützte Versionen

| Version | Unterstützt        | Sicherheits-SLA                                           |
|---------|--------------------|-----------------------------------------------------------|
| 1.1.x   | :white_check_mark: | 48h Eingangsbestätigung / 5 Tage Triage / 30 Tage Fix-Plan |
| < 1.1.0 | :x:                | Nach Verfügbarkeit / Update empfohlen                     |

Sicherheitskorrekturen werden für die neueste Version auf dem Standard-Branch `master` bereitgestellt.

### Sicherheitslücke melden

Bitte melden Sie Sicherheitslücken **niemals** über öffentliche GitHub Issues. Nutzen Sie stattdessen:

- **GitHub Private Vulnerability Advisory:** [Sicherheitslücke privat melden](https://github.com/ellmos-ai/decision-clicker/security/advisories/new)
- **Zentrale Sicherheit:** `security@open-bricks.org`
- **Organisationskontakt:** `security@ellmos.ai`
- **Maintainer:** `lukas@open-bricks.org` / `support@lukasgeiger.com`

Wir garantieren eine Eingangsbestätigung innerhalb von **48 Stunden**, eine fundierte Triage-Rückmeldung innerhalb von **5 Werktagen** sowie einen verbindlichen Behebungsplan bzw. Patch-Release innerhalb von **30 Kalendertagen**.

### Schutzgrenzen & Sicherheitsmodell

Decision Clicker ist ein lokales Administrationswerkzeug:
1. **Strikte Loopback-Bindung:** Der integrierte HTTP-Miniserver bindet ausschließlich an `127.0.0.1` oder `localhost`. Der Port darf niemals im LAN, WAN, Container-Netzwerk oder über ungeschützte Reverse-Proxys exponiert werden.
2. **Host- & Origin-Validierung:** Alle mutierenden HTTP-Endpunkte prüfen strikt übereinstimmende lokale `Host`- und `Origin`-Header. Cross-Origin Fetch-Metadaten werden abgewiesen.
3. **Grenze zur menschlichen Oberfläche (geringste Autorität):** `/api/new` ist der einzige JSON-Schreibweg und darf nur *offene Vorschläge* einstellen; er verlangt den Header `X-Decision-Clicker: 1`. `/api/decide`, `/api/intake` und `/api/undo/*` weisen JSON auch mit diesem Header ab und verlangen eine ausdrückliche Aktion in der HTML-Oberfläche mit einer fünf Minuten gültigen, einmal verwendbaren Bestätigung, die an Serverinstanz, Aktion und Eintrag gebunden ist. Ein Wechsel des Content-Type überschreitet die Grenze daher nicht. Die Trennung der Python-Fassaden (`ProposalSubmitter` gegenüber `DecisionClicker`) ist ein Integrationsvertrag geringster Autorität, keine Sandbox für Code, der ohnehin uneingeschränkt importieren und auf das Dateisystem zugreifen kann.
4. **Unprivilegierter Betrieb (RunAsInvoker):** Das Tool erfordert keinerlei Administrator- oder Root-Rechte.

### Sicherheits- und Datenintegritäts-Invarianten

- **Fail-Closed bei externen Sperren:** Vor jedem Schreibzugriff wird auf `LOCK*.txt` und aktive Sperren geprüft. Bei Fund bricht das Tool ab.
- **Einziger Datenkanon:** Die Textdatei `TO-DECIDE-USER.txt` bleibt der alleinige Kanon. Generierte Index-Dateien sind weggreifbare Caches.
- **Kein Überschreiben:** Bereits getroffene Entscheidungen werden niemals überschrieben.
- **Byte-getreue Vorab-Sicherung:** Vor jeder Kettendatei-Mutation wird ein byte-identisches Backup angelegt.
- **Reversibles Undo mit Herkunftsnachweis:** Undo erfordert einen Nachweis, dass der Block durch Decision Clicker erzeugt wurde; die Rücksetzung wird im unveränderlichen Audit-Trail protokolliert.
- **Zero-Egress Datenschutz:** Keinerlei Telemetrie, Analytics oder ausgehende Netzwerkverbindungen.
