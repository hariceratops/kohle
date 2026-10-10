# [feat] List lines no rule classified

Once import auto-applies rules, what is left in the unclassified buckets is
the queue of work: lines needing a new rule or a manual correction. Finding
them by scanning `entries-in-period` by hand is the friction this command
removes.

Depends on: 015
Spec: `dev/specs/expense-classification.md`

## Acceptance Criteria

- A CLI command lists the imported lines that no rule classified, read from
  the classification records written in 015.
- Each row shows enough to write a rule from it: date, description,
  counterparty, amount, and the account the line landed on.
- Output uses `tabulate`, matching the other listing commands.
- The command is read-only and creates no operations of its own — with the
  lazy `OperationGroup` behaviour from issue 011, that means it leaves no
  group behind either.
- An empty result — everything classified, or nothing imported yet — reports
  emptiness, not an error.
- Lines corrected through 017 no longer appear, since they are no longer
  unclassified. If 017 has not landed yet, state that in the design rather
  than leaving the interaction undefined.
