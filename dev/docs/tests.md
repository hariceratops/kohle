# Running the tests

Install the dev dependencies and run the tests from the repo root:

```bash
uv sync --extra dev
uv run pytest tests/
```

`--extra dev` is not optional for the test run: a bare `uv sync` prunes the
dev dependencies and `pytest` disappears from the venv.
