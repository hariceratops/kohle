# [fix] Exit non-zero when a CLI command fails

Every command prints its failure and returns normally, so the process exits
0 whether it succeeded or not:

```
$ uv run kohle-cli add-account checking --type asset
Failed: Account checking already exists
exit=0
```

The commands that do exit non-zero (`import-statement`, on a missing plugin
or a failed parse) do it with a bare `sys.exit(1)`, so the behaviour is
inconsistent as well as mostly absent.

This makes the CLI unscriptable — `kohle-cli ... || handle-failure` never
fires, and a shell loop over several imports cannot tell which ones landed.
It also makes `result.exit_code` useless as a test assertion, which surfaced
while writing the tests for issue 009: a CLI test asserting `exit_code == 0`
passes even when the command failed outright.

Found while implementing 009. Pre-existing, and deliberately left out of that
slice.

## Acceptance Criteria

- A command whose use case returns an error exits non-zero.
- A command that succeeds exits 0.
- The failure message still goes to the user; this changes the exit status,
  not the output.
- Error output goes to stderr rather than stdout, so `kohle-cli ... > file`
  captures results and not failures.
- The existing ad-hoc `sys.exit(1)` calls in `import-statement` are folded
  into whatever single mechanism this introduces.
- A CLI test asserts a failing command's exit code, which is only meaningful
  once this lands.
