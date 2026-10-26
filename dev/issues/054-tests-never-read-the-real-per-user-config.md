# [chore] Tests never read the real per-user config

Every test runs with `XDG_CONFIG_HOME` pointing at a temp dir, so the device
config file that later slices read can never leak in from the developer's
machine.

Depends on: none
Spec: `dev/specs/device-config.md`

## Acceptance Criteria

- An autouse fixture points `XDG_CONFIG_HOME` at a per-test temp dir.
- A test proves the real `~/.config/kohle/config.toml` is not read: with
  `HOME` and `XDG_CONFIG_HOME` both redirected, no path under the real home
  is opened.
- Tests that write an `init.toml` keep working through the same fixture.
- Existing tests pass.
