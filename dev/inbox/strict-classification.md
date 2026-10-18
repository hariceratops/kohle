# Strict classification: no unclassified bucket

## Goal

Make classification mandatory: an imported line must end up in a real
category, and the ledger never holds lines parked as unclassified.

The problem behind it: a line matching no rule lands in `Unclassified Expense`
or `Unclassified Income`. That keeps the import moving, but the bucket becomes
a place where decisions are deferred indefinitely and every report that groups
by category quietly includes it.

## Considerations surfaced

**The trade-off is deliberate.** Strictness adds friction: an import that
stops on an unmatched line can put the user off using the app at all. It also
forces the discipline of deciding at import time, so the ledger never carries
an undecided line. Both outcomes are real and this brief does not pick between
them; the design should make the cost of a refusal as low as possible.

**What "strict" could mean.** The import refuses the whole file; or it imports
the matched lines and holds the rest outside the ledger; or it prompts per
line. Each moves the unclassified queue somewhere other than a ledger account.

**Existing machinery assumes the bucket.** `list-unclassified` lists lines
sitting in the two unclassified accounts, `reclassify` moves a line out of
one with an adjusting entry, and the README and several issues describe the
bucket. Removing it changes those, and existing databases already contain
lines in it that need a migration path.

**Import idempotence.** Deduplication by native reference per account means a
refused import can be re-run safely after adding rules. That is what makes
refusal tolerable and should be preserved.

**Pairs with richer rules.** A rule that can express more
(`complex-classification-rules`) makes strictness easier to live with, since
fewer lines fall through.

## Directions rejected

None yet.

## Open questions

- Refuse the file, hold the unmatched lines, or prompt per line?
- Where do held lines live, and which command works through them?
- What happens to lines already in the unclassified accounts?
- Is strictness a global rule or a per-import option?
