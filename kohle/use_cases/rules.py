import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AddRuleError,
    EmptyRulePattern,
    InvalidRulePattern,
    PostingToNonLeafAccount,
    RuleError,
)
from kohle.domain.models import Rule
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    get_account_by_name_service,
)
from kohle.services.journal_services import Counterparty
from kohle.services.rule_services import (
    add_rule_service,
    list_rules_service,
    remove_rule_service,
)
from kohle.use_cases.conditions import (
    PATTERN_FLAGS,
    Predicate,
    When,
    compile_when,
    parse_stored_when,
    render_when_inline,
    render_when_lines,
    toml_string,
)

RULE_PRIORITY_STEP = 100


@dataclass(frozen=True, slots=True)
class StoredRule:
    """A live rule with its condition parsed. ORM rows do not cross the
    session, so everything a caller needs is copied out."""

    rule_id: int
    priority: int
    account_id: int
    account_name: str
    when: When
    note: str | None


def stored_rules(ctx: DbTransactionContext) -> Result[list[StoredRule], RuleError]:
    """Live rules in evaluation order, `list_rules_service`'s `(priority, id)`.

    A stored condition that fails to parse can only come from a hand edit; it
    fails loudly rather than being skipped, since skipping would quietly
    disable a rule."""

    def convert(rules: list[Rule]) -> Result[list[StoredRule], RuleError]:
        out = []
        for rule in rules:
            when = parse_stored_when(rule.condition)
            if when.is_err:
                return Result.err(RuleError(f"stored rule {rule.id}: {when.unwrap_err()}"))
            out.append(
                StoredRule(rule.id, rule.priority, rule.account_id, rule.account.name, when.unwrap(), rule.note)
            )
        return Result.ok(out)

    return list_rules_service(ctx).and_then(convert)


_RULE_FILE_HEADER = """\
# kohle classification rules, in priority order: the first rule that matches
# a line wins. Keys under [rule.when] must all hold; any = [...] needs one of
# its tables to hold; not = {...} must not hold.
# Leave `base` as it is: apply-rules uses it to refuse if the stored rules
# changed after this file was rendered.
"""


def _render_rule_body(rules: Sequence[StoredRule]) -> str:
    entries = []
    for rule in rules:
        lines = ["[[rule]]", f"account = {toml_string(rule.account_name)}"]
        if rule.note:
            lines.append(f"note = {toml_string(rule.note)}")
        lines.append("[rule.when]")
        lines.extend(render_when_lines(rule.when))
        entries.append("\n".join(lines) + "\n")
    return "\n".join(entries)


def rule_set_base(rules: Sequence[StoredRule]) -> str:
    """Fingerprint of the body alone, so ids and priority values, which the
    file never shows, cannot change it."""
    return hashlib.sha256(_render_rule_body(rules).encode()).hexdigest()[:16]


def render_rule_file(rules: Sequence[StoredRule]) -> str:
    text = f'{_RULE_FILE_HEADER}base = "{rule_set_base(rules)}"\n'
    if rules:
        text += "\n" + _render_rule_body(rules)
    return text


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A rule with its conditions already compiled, carrying the two ids the
    classification record needs. The compilation has to happen once per import
    rather than once per row."""

    rule_id: int
    account_id: int
    holds: Predicate


def compile_rules(rules: Iterable[StoredRule]) -> list[CompiledRule]:
    """Compile a rule set in the order the caller supplies it.

    Order-dependent and must not sort: `list_rules_service`'s
    `(priority, id)` ordering is the evaluation contract, and `match_rule`
    takes the first hit (design §2.3).

    Returns a plain list rather than a Result: `stored_rules` has already
    validated every pattern, so compilation cannot fail.
    """
    return [CompiledRule(rule.rule_id, rule.account_id, compile_when(rule.when)) for rule in rules]


def match_rule(
    compiled: Sequence[CompiledRule], description: str, counterparty: Counterparty
) -> CompiledRule | None:
    """The first rule whose conditions hold.

    Pure and session-free: making this a unit of work would open a second
    transaction inside the import loop (design §5.2).
    """
    for rule in compiled:
        if rule.holds(description, counterparty):
            return rule
    return None


class AddRule(UnitOfWork[Rule, AddRuleError]):
    def execute(self, pattern: str, account_name: str) -> Result[Rule, AddRuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[Rule, AddRuleError]:
            text = pattern.strip()
            if not text:
                return Result.err(EmptyRulePattern())

            try:
                # Compiled to reject a malformed pattern here rather than at the
                # import it would otherwise break. The compiled object is
                # discarded: the matcher compiles the rule set of the day.
                re.compile(text, PATTERN_FLAGS)
            except re.error as err:
                return Result.err(InvalidRulePattern(text, str(err)))

            return (
                get_account_by_name_service(ctx, account_name)
                .and_then(lambda account:
                    account_has_children_service(ctx, account.id)
                    .and_then(lambda has_children:
                        # A rule aimed at a parent can only ever produce entries
                        # validate_lines refuses, so refusing the rule turns a
                        # broken import into a refused rule.
                        Result.err(PostingToNonLeafAccount(account.id))
                        if has_children
                        else stored_rules(ctx).and_then(lambda live:
                            add_rule_service(
                                ctx,
                                render_when_inline(When(any_field=text)),
                                account.id,
                                # The list is in evaluation order, so the last
                                # rule holds the highest priority.
                                live[-1].priority + RULE_PRIORITY_STEP if live else RULE_PRIORITY_STEP,
                            )
                        )
                    )
                )
            )

        return self._run(use_case)


class ListRules(UnitOfWork[list[StoredRule], RuleError]):
    def execute(self) -> Result[list[StoredRule], RuleError]:
        return self._run(stored_rules)


class ShowRules(UnitOfWork[str, RuleError]):
    def execute(self) -> Result[str, RuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[str, RuleError]:
            return stored_rules(ctx).map(render_rule_file)

        return self._run(use_case)


class RemoveRule(UnitOfWork[Rule, RuleError]):
    def execute(self, rule_id: int) -> Result[Rule, RuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[Rule, RuleError]:
            return remove_rule_service(ctx, rule_id)

        return self._run(use_case)
