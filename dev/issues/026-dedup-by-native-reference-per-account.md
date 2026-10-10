# [feat] Deduplicate imports by the statement's native reference

Dedup currently hashes date/amount/description. It moves onto the
plugin-supplied per-row reference, scoped by target account, and malformed
references reject the whole import.

Depends on: 025
Spec: `dev/specs/importer-plugins-for-assets.md`

## Acceptance Criteria

- The entry reference is the plugin-supplied reference scoped by account id.
- Importing the same file twice writes nothing the second time and reports
  zero entries imported.
- The same reference on two different accounts is two distinct entries.
- A row with an absent reference, or one duplicating another row's reference
  in the same file, rejects the import; nothing is written.
- A statement whose last row is malformed imports none of the preceding rows,
  and the `OperationGroup` audit trail is unchanged too.
