# Contributing / Mitwirken

[English](#english) · [Deutsch](#deutsch)

---

<a name="english"></a>
## English

Contributions are welcome! Please review [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [PRIVACY.md](PRIVACY.md), and [SECURITY.md](SECURITY.md) before submitting a pull request.

### Local checks

```bash
python -m pip install -e ".[dev]"
python -m pip check
python -m compileall -q src tests
python -m ruff check .
python -m pytest -ra -v
python -m build
```

Keep changes narrow and preserve the writer's fail-closed behavior. Every write-path change needs a test that proves unrelated bytes remain unchanged.

Never use a real decision chain as a test fixture. Add only synthetic names, paths, questions, and IDs. Do not weaken lock checks, provenance checks, backups, or the single-parser architecture to make a test pass.

README changes must keep `README.md`, `README_de.md`, and `README.de.md` structurally and semantically synchronized (`README_de.md` and `README.de.md` must stay byte-identical). Code blocks, identifiers, paths, version numbers, and safety statements must match.

---

<a name="deutsch"></a>
## Deutsch

Beiträge sind herzlich willkommen! Bitte lesen Sie vor einem Pull Request [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [PRIVACY.md](PRIVACY.md) und [SECURITY.md](SECURITY.md).

### Lokale Prüfungen

```bash
python -m pip install -e ".[dev]"
python -m pip check
python -m compileall -q src tests
python -m ruff check .
python -m pytest -ra -v
python -m build
```

Halten Sie Änderungen eng abgegrenzt und bewahren Sie das Fail-Closed-Verhalten der Schreib-Engine. Jede Änderung am Schreibpfad erfordert einen Test, der belegt, dass unbeteiligte Bytes unverändert bleiben.

Verwenden Sie niemals eine echte Entscheidungskette als Test-Fixture. Fügen Sie ausschließlich synthetische Namen, Pfade, Fragen und IDs hinzu. Schwächen Sie weder Sperrprüfungen, Herkunftsnachweise, Vorab-Sicherungen noch die Ein-Parser-Architektur ab.

Änderungen an der Dokumentation müssen `README.md`, `README_de.md` und `README.de.md` strukturell und inhaltlich synchron halten (`README_de.md` und `README.de.md` bleiben byte-identisch).
