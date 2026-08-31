# Automatic expense classification

## Goal

Assign an expense account to imported lines automatically, starting with a rule
engine matching description and counterparty, and later replacing or augmenting
it with a trained model.

The problem behind it: with expenses modelled as accounts, every imported line
needs a destination account, and doing that by hand for every transaction is the
work that makes people abandon a ledger.

## Considerations surfaced

The rule engine is the training set. Whatever classifies lines in phase one
produces exactly the labelled data the ML phase would need — but only if it
records what it proposed, what the account ended up being, and whether a human
changed it. If corrections are not captured from the first day, the later phase
starts from nothing. This is the one decision in this brief that is expensive to
retrofit and nearly free to build in now.

Classification interacts with the existing operation-tracking machinery.
Reclassifying a line after the fact is either an edit to history or an adjusting
entry, and the `Operation` / `OperationGroup` audit log already has opinions
about how changes are recorded.

Classification can run at import time or as a separate pass over unclassified
lines. Those produce different user experiences — one blocks the import, the
other leaves a queue.

The ML phase is a genuinely separate track, not a continuation. It brings model
choice, local versus hosted, and an ongoing accuracy-tuning cost that the rule
engine does not have.

## Directions rejected

Building the rule engine and the model together. The rule engine has to run
first regardless, because it is what generates the labels.

## Open questions

- Does the classifier propose and wait for confirmation, or auto-apply and let
  the user correct afterwards?
- Where do rules live — a database table editable from the TUI, or a config
  file?
- Does reclassification rewrite the original line or post an adjusting entry?
- What is captured per classification to make the later ML phase possible —
  proposed account, matched rule, final account, corrected flag?
- Is the eventual model local or an API call, and does that change what can be
  sent off the machine?
