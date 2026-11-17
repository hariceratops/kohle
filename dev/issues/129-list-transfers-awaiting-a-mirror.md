# [feat] List transfers still awaiting a mirror

A read-only listing shows transfers whose mirror has not arrived, so the user can spot a late or missing row. Depends on 127.

## Acceptance Criteria

- The listing shows transfers with no mirror, limited to counterparts that have had a statement imported.
- A transfer to a counterpart that has never had a statement imported is not listed.
- A transfer whose mirror was absorbed is not listed.
- The command is read-only and writes no operation group.
- The architect picks the command name.
- `import-and-classification.md` is updated.
- Every existing test passes unchanged.
