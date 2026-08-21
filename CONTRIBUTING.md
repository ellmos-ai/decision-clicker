# Contributing

Contributions are welcome after the repository becomes public.

## Local checks

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m build
```

Keep changes narrow and preserve the writer's fail-closed behavior. Every
write-path change needs a test that proves unrelated bytes remain unchanged.

Never use a real decision chain as a test fixture. Add only synthetic names,
paths, questions, and IDs. Do not weaken lock checks, provenance checks,
backups, or the single-parser architecture to make a test pass.

README changes must keep `README.md` and `README.de.md` structurally and
semantically synchronized. Code blocks, identifiers, paths, version numbers,
and safety statements must match.
