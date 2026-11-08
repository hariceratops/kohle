"""Layer 1 — replay of currency lots (issues 111, 113, 115, 117). Design §3, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_remittance_gives_one_exact_lot() -> None:
    # TODO: a 1,000 EUR / 90,000 INR remittance is one INR holding costing exactly Decimal(1000)
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_purchase_takes_cost_from_inr_lots() -> None:
    # TODO: the spec's 1,000/90,000, 1,100/100,000, buy-for-120,000 example: stock lot 1,330, INR 70,000 at 770, no Sale
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_one_payment_for_two_stocks_apportions_exactly() -> None:
    # TODO: shares of the consumed cost sum to the whole
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_reconversion_realises_fx_gain() -> None:
    # TODO: a Sale of unit INR with proceeds, FIFO cost and gain
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_move_between_own_accounts_carries_lots() -> None:
    # TODO: no Sale; the later payment from B uses A's costs
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_payment_beyond_the_lots_is_a_shortfall() -> None:
    # TODO: exact LotShortfall text for a payment and for a disposal
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_people_account_is_refused() -> None:
    # TODO: CurrencyWithPeople for a People credit, a People debit and a People-only entry
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_security_shortfall_is_ignored_when_only_currencies_are_replayed() -> None:
    # TODO: lots_for=_foreign_currency
    raise NotImplementedError
