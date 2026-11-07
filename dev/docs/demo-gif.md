# The README demo GIF

`docs/demo/taste.gif` is a recording of the README's "A taste" block. It is
made from the tape `docs/demo/taste.tape` with
[VHS](https://github.com/charmbracelet/vhs) and is checked in, so it only needs
regenerating when that block changes.

## Keeping it in step

The tape types the same `kohle-cli` commands as the README block, in the same
order. `tests/test_docs_examples.py` checks the command text and order, so
changing one without the other fails the suite. It does not look at the
recording itself, so the GIF can lag the tape until someone reruns it.

The README block's output is also a checked example, which is why a change to
what a command prints means updating the block, and then the GIF.

## Regenerating it

VHS needs `ttyd` and `ffmpeg` on the PATH. None of the three is a Python
dependency, and `vhs` and `ttyd` are not in the Debian or Ubuntu repositories:
take the release binaries from their GitHub releases pages and check them
against the published checksums. `ffmpeg` is in `apt`.

From the repository root:

```bash
uv run vhs docs/demo/taste.tape
```

If `kohle-cli` is not found in VHS's shell, add `source .venv/bin/activate` to
the tape's hidden opening section.

## How the tape works

- A hidden opening section puts the ledger in a temporary directory and sets a
  neutral `$ ` prompt, so no user name, host or path appears in the recording.
- After each command the tape waits for the prompt (`Wait`, with
  `Set WaitPattern`) instead of sleeping for a guessed time. A fixed pause
  garbled the first recording, because `import-statement` took longer than the
  pause and the next command was typed over its output.
- The width is set so the longest line, the first rule in the `apply-rules`
  summary, does not wrap.

After regenerating, look at the first and last frames before committing, for
a leaked path or a garbled line:

```bash
ffmpeg -i docs/demo/taste.gif -vf "fps=1/4" frame%02d.png
```
