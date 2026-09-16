# TODO — evidenzgebundene Entscheidungsvorlagen

- [ ] Das Intake-Schema optional um stabile Evidenzanker, Gegenbelege,
  fehlende Informationen, Ersteller und Kontext-Fingerprint erweitern. Der
  Clicker prüft Form und Auffindbarkeit, nicht die Wahrheit der Quelle.
- [ ] Einen Status `needs_evidence`/„Klärung nötig" vor der eigentlichen
  Entscheidung unterstützen, damit widersprüchliche Tacit-/Memory-/TOM-
  Kandidaten nicht vorschnell als entscheidungsreif erscheinen.
- [ ] Änderungen an Optionen oder Empfehlung versioniert anzeigen; ein Klick
  muss genau die betrachtete Version samt Evidenzstand referenzieren.
- [ ] Die bestehende menschliche Bestätigung und Undo-Kette beibehalten:
  Vorhersagen, Memory-Treffer und Policy-Kandidaten dürfen Entscheidungen
  einstellen, aber niemals selbst beantworten oder als umgesetzt markieren.

---

## AI Security & Dependency Audit — 2026-09-16

- **Auditor:** Gemini / Antigravity (`ai-security-and-dependency-audit` sidecar)
- **Status:** Complete / Clean (100% green)
- **Prüfumfang & Nachweise:**
  * PEP 639 Compliance: `license-files = ["LICENSE", "THIRD_PARTY_LICENSES.md"]` in `pyproject.toml`.
  * `.gitignore` Hardening: Ergänzung von Zertifikaten, Schlüsseln, Token (`*.pem`, `*.key`, `*.token`, `*.secret`, `credentials.json`, `.npmrc`), Merge-Resten (`*.orig`, `*.rej`) und Sync-Konflikt-Mustern (`*-ASUS-GEI*`, `*-WORKSTATION-LG*`, `CONFLICT_REVIEW_LOG*`).
  * Supply-Chain & Runtime-Unabhängigkeit: 0 externe Runtime-Dependencies (ausschließlich Python-Standardbibliothek); `pip check` sauber (0 defekte Requirements).
  * AST- & Secret-Scan: 0 unberechtigte Anmeldedaten, 0 private Schlüssel, 0 hardcodierte Nutzerpfade in tracked Quell- und Konfigurationsdateien.
  * Sicherheits-SLA: 30-Tage-Behebungszusage in `SECURITY.md` zweisprachig fixiert.
  * Vertragstests: 5 neue automatisierte Prüfgates in `tests/test_metadata.py` hinzugefügt; vollständige Testsuite mit 161 Tests erfolgreich (100% bestanden).

---

## TASKWRITER-Review — 2026-09-05

- Bundle: `bec6d73c-449e-4075-9b0a-46d772315cdc` · selector review
  `sha256-v1:be2df988ac317883d1de522c1779a3798ba13b30b80268fcda61316967ebd123`
- Projekt: `C:\_Local_DEV\repos\decision-clicker`
- Branch/Stand: `master` · `f03aff8` · `master...origin/master`, Arbeitsbaum vor
  TASKWRITER-Schreibzugriff sauber; zusätzlicher lokaler Read-only-Branch
  `automation/decision-clicker-readiness-20260821` bleibt unberührt.
- Gelesene Kontrollen: `README.md`, `README.de.md`, `CHANGELOG.md`, `TODO.md`,
  `CONTRIBUTING.md`, `PRIVACY.md`, `SECURITY.md`, `THIRD_PARTY.md`,
  `PRIVATE.txt`, `START.bat`, `pyproject.toml`, `ellmos-module.v2.json`,
  `docs/AI-ACT-COMPONENT-NOTE.md`, `MANIFEST.in`, `.github/workflows/ci.yml`,
  `.github/workflows/codeql.yml`, gesamter `src/decision_clicker/`- und
  `tests/`-Bestand.
- Prüfungen: `python -m ruff check .` grün; `python -m compileall -q src tests`
  grün; isolierter Cross-Origin-POST-Test grün; Wiederholung der vollständigen
  Suite `124 passed`; `python -m build --no-isolation` grün.
- Transienter Befund: Ein erster vollständiger Lauf endete mit `123 passed,
  1 failed` wegen `ConnectionAbortedError [WinError 10053]` beim erwarteten
  403-Cross-Origin-POST, obwohl der Handler 403 loggte. Der isolierte Test und
  der Wiederholungslauf waren grün; daher keine Behauptung einer Behebung,
  sondern Task 356 zur Reproduktion/Stabilisierung.
- Harter Privacy-/Release-Gate-Befund: `MANIFEST.in` nimmt per
  `recursive-include tests *.txt` die gitignorierte
  `tests/data/postfach_2026-08-07.txt` in `decision_clicker-1.1.0.tar.gz` auf.
  Die Datei wurde nicht gelesen oder veröffentlicht; Task 353 erfasst die
  Ausschluss- und Build-Verifikation. `PRIVATE.txt` bleibt offen; kein Publish,
  Upload, Release oder Registry-Eintrag.
- Eingetragene Aufgaben: #349–#356 (Intake-Evidenzanker, `needs_evidence`,
  Versionierung, menschliche Bestätigung/Undo, Sdist-Privacy, Privacy-Sweep,
  Remote-CI/CodeQL-Gate, Cross-Origin-Flake). Alle mit `effort` und `scope`,
  Projekt `decision-clicker`, Root `repos`, Quellen und vollständigem
  Ergebnis-/Abnahme-/Verifikations-/Blocker-Kontrakt registriert.
- Abgrenzung: Keine Aufgaben ausgeführt, keine Fremdsperre überschrieben, keine
  Veröffentlichung ausgelöst. Der TASKWRITER-Lock wird vor dem Review entfernt.


## Lock-Eigentum — Root-Befund 2026-09-09

- [ ] T-20260909-178020475: write_lock überschreibt einen bestehenden Fremdclaim; release_lock entfernt einen fremden Ersatz ohne Eigentumsprüfung. Beide API-Fälle sind in der isolierten T628-Lock-Gegenprobe belegt (LOCK-OWNERSHIP-FIXTURE.json, SHA2569744D23F423738D6BEB90B1CA7040F9DCCE1CFF5EEE9872BBF51496777E04449). Exklusive Übernahme und eigentumsgebundene Freigabe in allen tatsächlichen Aufrufern reparieren, gezielt testen, unabhängig reviewen und aktive Fassung nachweisen. T628 nutzt nur eine eigene sichere Ausführungshülle; Produktfix bleibt offen. Kanonische Ticketqueue: OneDrive/.TOPICS/_control-center/_TICKETS/ACTIONABLE/. Vorbestehender TASKWRITER-TODO-Stand bleibt erhalten.
