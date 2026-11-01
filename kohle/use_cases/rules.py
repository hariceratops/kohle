import hashlib
import re
import tomllib
from bisect import bisect_left
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    AddRuleError,
    ApplyRulesError,
    DuplicateRule,
    EmptyRulePattern,
    InvalidRulePattern,
    MalformedRuleFile,
    PostingToNonLeafAccount,
    RuleError,
    RulesChanged,
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
    update_rule_service,
)
from kohle.use_cases.conditions import (
    PATTERN_FLAGS,
    Predicate,
    When,
    compile_when,
    parse_stored_when,
    parse_when,
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
class FileRule:
    position: int  # 1-based index among the [[rule]] entries
    account: str
    note: str | None
    when: When


@dataclass(frozen=True, slots=True)
class RuleFile:
    base: str | None
    rules: tuple[FileRule, ...]


def _parse_file_rule(position: int, raw: dict) -> Result[FileRule, MalformedRuleFile]:
    for key in raw:
        if key not in ("account", "note", "when"):
            return Result.err(MalformedRuleFile(position, key, "is not a known key"))
    account = raw.get("account")
    if account is None:
        return Result.err(MalformedRuleFile(position, "account", "is required"))
    if not isinstance(account, str) or not account.strip():
        return Result.err(MalformedRuleFile(position, "account", "must be a non-empty string"))
    note = raw.get("note")
    if note is not None and not isinstance(note, str):
        return Result.err(MalformedRuleFile(position, "note", "must be a string"))
    if "when" not in raw:
        return Result.err(MalformedRuleFile(position, "when", "is required"))
    return (
        parse_when(raw["when"])
        .map_err(lambda err: err.at(position))
        # Patterns and notes are taken verbatim: a quoted TOML string's spaces
        # are deliberate. An empty note means no note.
        .map(lambda when: FileRule(position, account, note or None, when))
    )


def parse_rule_file(text: str) -> Result[RuleFile, MalformedRuleFile]:
    try:
        # Decimal keeps amount bounds exact; a float would not.
        data = tomllib.loads(text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as err:
        return Result.err(MalformedRuleFile(None, None, f"not valid TOML: {err}"))
    for key in data:
        if key not in ("base", "rule"):
            return Result.err(MalformedRuleFile(None, key, "is not a known key"))
    base = data.get("base")
    if base is not None and not isinstance(base, str):
        return Result.err(MalformedRuleFile(None, "base", "must be a string"))
    raw_rules = data.get("rule", [])
    if not isinstance(raw_rules, list) or not all(isinstance(raw, dict) for raw in raw_rules):
        return Result.err(MalformedRuleFile(None, "rule", "must be an array of tables"))

    rules: list[FileRule] = []
    # Account names are globally unique, so the name stands in for the id here.
    seen: dict[tuple[When, str], int] = {}
    for position, raw in enumerate(raw_rules, start=1):
        parsed = _parse_file_rule(position, raw)
        if parsed.is_err:
            return Result.err(parsed.unwrap_err())
        rule = parsed.unwrap()
        earlier = seen.setdefault((rule.when, rule.account), position)
        if earlier != position:
            return Result.err(
                MalformedRuleFile(position, None, f"has the same account and conditions as rule {earlier}")
            )
        rules.append(rule)
    return Result.ok(RuleFile(base, tuple(rules)))


@dataclass(frozen=True, slots=True)
class PlannedRule:
    rule: FileRule
    account_id: int
    kept: StoredRule | None  # None: added
    priority: int  # priority after the apply


@dataclass(frozen=True, slots=True)
class RulePlan:
    base: str  # fingerprint of the stored set planned against
    rules: tuple[PlannedRule, ...]  # file order
    retired: tuple[StoredRule, ...]  # evaluation order
    reordered: frozenset[int]  # ids of kept rules that moved

    @property
    def added(self) -> tuple[PlannedRule, ...]:
        return tuple(p for p in self.rules if p.kept is None)

    @property
    def renoted(self) -> tuple[PlannedRule, ...]:
        return tuple(p for p in self.rules if p.kept is not None and p.kept.note != p.rule.note)

    @property
    def unchanged(self) -> int:
        kept = [p.kept for p in self.rules if p.kept is not None]
        renoted = {p.kept.rule_id for p in self.renoted if p.kept is not None}
        return sum(1 for k in kept if k.rule_id not in self.reordered and k.rule_id not in renoted)

    @property
    def updates(self) -> tuple[PlannedRule, ...]:
        """Kept rules whose stored priority or note changes."""
        return tuple(
            p for p in self.rules
            if p.kept is not None and (p.kept.priority != p.priority or p.kept.note != p.rule.note)
        )

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.retired and not self.updates


def _longest_increasing(values: Sequence[int]) -> set[int]:
    """Positions of one longest strictly increasing subsequence (patience
    sorting with predecessor links)."""
    tails: list[int] = []
    previous: list[int | None] = []
    for position, value in enumerate(values):
        slot = bisect_left(tails, value, key=lambda t: values[t])
        previous.append(tails[slot - 1] if slot else None)
        if slot == len(tails):
            tails.append(position)
        else:
            tails[slot] = position
    chain: set[int] = set()
    node = tails[-1] if tails else None
    while node is not None:
        chain.add(node)
        node = previous[node]
    return chain


def _fit_into_gaps(matches: Sequence[StoredRule | None]) -> list[int] | None:
    """Priorities that keep every kept rule's own, or None when an added run
    has no room. Rules in one run share a priority and are ordered by id,
    which holds because the apply inserts them in file order and new ids are
    larger than every existing id."""
    priorities = [0] * len(matches)
    previous: StoredRule | None = None
    i = 0
    while i < len(matches):
        kept = matches[i]
        if kept is not None:
            priorities[i] = kept.priority
            previous = kept
            i += 1
            continue
        j = i
        while j < len(matches) and matches[j] is None:
            j += 1
        following = matches[j] if j < len(matches) else None
        for offset in range(j - i):
            if previous is None and following is None:
                priorities[i + offset] = RULE_PRIORITY_STEP * (offset + 1)
            elif previous is None:
                assert following is not None
                priorities[i + offset] = following.priority - RULE_PRIORITY_STEP
            elif following is None:
                priorities[i + offset] = previous.priority + RULE_PRIORITY_STEP
            elif following.priority > previous.priority:
                priorities[i + offset] = (previous.priority + following.priority) // 2
            else:
                return None
        i = j
    return priorities


def _assign_priorities(matches: Sequence[StoredRule | None]) -> list[int]:
    kept_keys = [(m.priority, m.rule_id) for m in matches if m is not None]
    if all(a < b for a, b in pairwise(kept_keys)):
        fitted = _fit_into_gaps(matches)
        if fitted is not None:
            return fitted
    return [RULE_PRIORITY_STEP * (i + 1) for i in range(len(matches))]


def plan_rule_changes(
    stored: Sequence[StoredRule], file: RuleFile, account_ids: Mapping[str, int], base: str
) -> RulePlan:
    """Pure. A file rule keeps a live rule's id when `(when, account)` match;
    the first unmatched live rule wins, which only matters for legacy
    duplicates."""
    pool: dict[tuple[When, int], deque[StoredRule]] = {}
    for rule in stored:
        pool.setdefault((rule.when, rule.account_id), deque()).append(rule)
    matches: list[StoredRule | None] = []
    for file_rule in file.rules:
        queue = pool.get((file_rule.when, account_ids[file_rule.account]))
        matches.append(queue.popleft() if queue else None)

    kept_ids = {m.rule_id for m in matches if m is not None}
    retired = tuple(r for r in stored if r.rule_id not in kept_ids)

    evaluation_index = {r.rule_id: i for i, r in enumerate(stored)}
    kept_in_file_order = [m for m in matches if m is not None]
    stay = _longest_increasing([evaluation_index[m.rule_id] for m in kept_in_file_order])
    reordered = frozenset(m.rule_id for i, m in enumerate(kept_in_file_order) if i not in stay)

    priorities = _assign_priorities(matches)
    planned = tuple(
        PlannedRule(file_rule, account_ids[file_rule.account], kept, priority)
        for file_rule, kept, priority in zip(file.rules, matches, priorities, strict=True)
    )
    return RulePlan(base, planned, retired, reordered)


def _plan(
    ctx: DbTransactionContext, rule_file: RuleFile, expected_base: str | None
) -> Result[RulePlan, ApplyRulesError]:
    stored = stored_rules(ctx)
    if stored.is_err:
        return Result.err(stored.unwrap_err())
    live = stored.unwrap()
    current = rule_set_base(live)
    # A file without a base is planned against the current set: that is the
    # only reading under which an empty file can retire everything.
    for claimed in (rule_file.base, expected_base):
        if claimed is not None and claimed != current:
            return Result.err(RulesChanged(claimed, current))

    account_ids: dict[str, int] = {}
    for file_rule in rule_file.rules:
        if file_rule.account in account_ids:
            continue
        found = get_account_by_name_service(ctx, file_rule.account)
        if found.is_err:
            err = found.unwrap_err()
            if isinstance(err, AccountNotFoundError):
                return Result.err(
                    MalformedRuleFile(file_rule.position, "account", f"no account named '{file_rule.account}'")
                )
            return Result.err(err)
        account = found.unwrap()
        has_children = account_has_children_service(ctx, account.id)
        if has_children.is_err:
            return Result.err(has_children.unwrap_err())
        if has_children.unwrap():
            return Result.err(
                MalformedRuleFile(
                    file_rule.position,
                    "account",
                    f"'{file_rule.account}' has sub-accounts; a rule must send lines to a leaf account",
                )
            )
        account_ids[file_rule.account] = account.id
    return Result.ok(plan_rule_changes(live, rule_file, account_ids, current))


class PlanRuleFile(UnitOfWork[RulePlan, ApplyRulesError]):
    def execute(self, text: str) -> Result[RulePlan, ApplyRulesError]:
        parsed = parse_rule_file(text)
        if parsed.is_err:
            return Result.err(parsed.unwrap_err())
        rule_file = parsed.unwrap()
        return self._run(lambda ctx: _plan(ctx, rule_file, None))


class ApplyRuleFile(UnitOfWork[RulePlan, ApplyRulesError]):
    def execute(self, text: str, base: str) -> Result[RulePlan, ApplyRulesError]:
        parsed = parse_rule_file(text)
        if parsed.is_err:
            return Result.err(parsed.unwrap_err())
        rule_file = parsed.unwrap()

        def use_case(ctx: DbTransactionContext) -> Result[RulePlan, ApplyRulesError]:
            # Re-planned inside the writing transaction: the plan the user
            # confirmed was made in another one, and the base check here is
            # what refuses a change that landed in between.
            planned = _plan(ctx, rule_file, base)
            if planned.is_err or planned.unwrap().is_empty:
                return planned
            plan = planned.unwrap()
            for rule in plan.retired:
                retired = remove_rule_service(ctx, rule.rule_id)
                if retired.is_err:
                    return Result.err(retired.unwrap_err())
            for item in plan.updates:
                assert item.kept is not None
                updated = update_rule_service(ctx, item.kept.rule_id, item.priority, item.rule.note)
                if updated.is_err:
                    return Result.err(updated.unwrap_err())
            for item in plan.added:
                added = add_rule_service(
                    ctx, render_when_inline(item.rule.when), item.account_id, item.priority, item.rule.note
                )
                if added.is_err:
                    return Result.err(added.unwrap_err())
            return planned

        return self._run(use_case)


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
    compiled: Sequence[CompiledRule], description: str, counterparty: Counterparty, amount: Decimal
) -> CompiledRule | None:
    """The first rule whose conditions hold.

    Pure and session-free: making this a unit of work would open a second
    transaction inside the import loop (design §5.2).
    """
    for rule in compiled:
        if rule.holds(description, counterparty, amount):
            return rule
    return None


def _add_unless_duplicate(
    ctx: DbTransactionContext, live: Sequence[StoredRule], when: When, account_id: int
) -> Result[Rule, RuleError]:
    for rule in live:
        if rule.when == when and rule.account_id == account_id:
            return Result.err(DuplicateRule(rule.rule_id))
    return add_rule_service(
        ctx,
        render_when_inline(when),
        account_id,
        # The list is in evaluation order, so the last rule holds the highest
        # priority.
        live[-1].priority + RULE_PRIORITY_STEP if live else RULE_PRIORITY_STEP,
    )


class AddRule(UnitOfWork[Rule, AddRuleError]):
    def execute(self, pattern: str, account_name: str) -> Result[Rule, RuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[Rule, RuleError]:
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
                            _add_unless_duplicate(ctx, live, When(any_field=text), account.id)
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
