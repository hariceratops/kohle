from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import ListPendingRemittancesError
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.classification_services import pending_remittances_service
from kohle.use_cases.conditions import Direction
from kohle.use_cases.posting import statement_amount, statement_line


@dataclass(frozen=True, slots=True)
class PendingRemittance:
    entry_id: int
    entry_date: date
    description: str
    direction: Direction
    amount: Decimal  # unsigned: the direction says which way it went
    account_name: str  # the euro account
    counterpart_name: str
    unit_identifier: str


class ListPendingRemittances(UnitOfWork[list[PendingRemittance], ListPendingRemittancesError]):
    """Remittances waiting for their other half. A separate listing from
    list-unclassified: a rule has classified them, and what they need is an
    amount, through a different command."""

    def execute(self) -> Result[list[PendingRemittance], ListPendingRemittancesError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[PendingRemittance], ListPendingRemittancesError]:
            def convert(classifications):
                out = []
                for c in classifications:
                    amount = statement_amount(c)
                    assert c.remittance_account is not None and c.remittance_unit is not None
                    out.append(
                        PendingRemittance(
                            entry_id=c.entry.id,
                            entry_date=c.entry.entry_date,
                            description=c.entry.description,
                            direction=Direction.outgoing if amount < 0 else Direction.incoming,
                            amount=abs(amount),
                            account_name=statement_line(c).account.name,
                            counterpart_name=c.remittance_account.name,
                            unit_identifier=c.remittance_unit.identifier,
                        )
                    )
                return out

            return pending_remittances_service(ctx).map(convert)

        return self._run(use_case)
