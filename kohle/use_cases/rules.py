import re

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AddRuleError,
    EmptyRulePattern,
    InvalidRulePattern,
    PostingToNonLeafAccount,
    RuleError,
)
from kohle.domain.models import DEFAULT_RULE_PRIORITY, Rule
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    get_account_by_name_service,
)
from kohle.services.rule_services import (
    add_rule_service,
    list_rules_service,
    remove_rule_service,
)

# Matching is case-insensitive because bank exports are inconsistently cased —
# REWE SAGT DANKE and Rewe Markt GmbH are the same payee and a user writing
# 'rewe' means both. (?-i:...) restores case sensitivity within a pattern.
PATTERN_FLAGS = re.IGNORECASE


class AddRule(UnitOfWork[Rule, AddRuleError]):
    def execute(
        self, pattern: str, account_name: str, priority: int = DEFAULT_RULE_PRIORITY
    ) -> Result[Rule, AddRuleError]:
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
                        else add_rule_service(ctx, text, account.id, priority)
                    )
                )
            )

        return self._run(use_case)


class ListRules(UnitOfWork[list[Rule], RuleError]):
    def execute(self) -> Result[list[Rule], RuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Rule], RuleError]:
            return list_rules_service(ctx)

        return self._run(use_case)


class RemoveRule(UnitOfWork[Rule, RuleError]):
    def execute(self, rule_id: int) -> Result[Rule, RuleError]:
        def use_case(ctx: DbTransactionContext) -> Result[Rule, RuleError]:
            return remove_rule_service(ctx, rule_id)

        return self._run(use_case)
