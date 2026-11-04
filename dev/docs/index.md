# kohle developer notes

Notes for people working on kohle itself. The user guide lives in `docs/` and
is published separately; this site is not part of it and is not built in CI.

- [Writing migrations](migrations.md)
- [Running the tests](tests.md)
- [Checked guide examples](guide.md)

## Serving it

From the repo root:

```bash
uv run --with-requirements docs/requirements.txt mkdocs serve -f dev/docs/mkdocs.yml
```

To check it builds, which fails on any broken link:

```bash
uv run --with-requirements docs/requirements.txt mkdocs build --strict -f dev/docs/mkdocs.yml
```

The output goes to `site-dev/`, which git ignores. The site shares the user
guide's pinned toolchain in `docs/requirements.txt`. Nothing builds it
automatically, so a broken link here is caught only when someone builds it.
