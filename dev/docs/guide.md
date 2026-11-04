# Checked guide examples

Every `console` block in the user guide (`docs/*.md`) is run as a test by
`tests/test_docs_examples.py`, so the guide's output cannot drift from the
CLI. The syntax for page authors is the module docstring of
[`tests/docs_examples.py`](https://github.com/hariceratops/kohle/blob/main/tests/docs_examples.py).

Run just those tests:

```bash
uv run pytest tests/test_docs_examples.py
```

## The pinned date

The examples run with today pinned to `DOCS_TODAY`, a constant in
`tests/docs_examples.py`. The guide's index page states the same date in one
sentence, so change both together.

## Serving the guide

```bash
uv run --with-requirements docs/requirements.txt mkdocs serve -f docs/mkdocs.yml
```

`--with-requirements` layers the docs toolchain over the project environment
for that run only. kohle must be importable because the generated command
reference and the installed-plugins list import it.

The checker never scans `dev/`, so the blocks on this site are not run.
