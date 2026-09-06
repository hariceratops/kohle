"""Layer 2 — service tests against the `session` fixture.

The recursive descendant query behind `balance` rollup (issue 003).

The cycle test below is the regression guard for a non-obvious property: with
cyclic parentage, UNION projecting only `Account.id` terminates, while UNION
ALL and UNION projecting (id, depth) both hang — a monotonic column makes
every row distinct, so deduplication never fires. Someone adding a depth
column "for display" would turn this query into a hang.

That is also why the cycle tests carry a timeout with `method="thread"`: the
hang this guards against happens inside SQLite's C code, below the Python
interpreter, and a signal-based timeout (pytest-timeout's default) can only
fire between bytecode instructions, so it never gets a chance to interrupt a
thread blocked in C. The thread method runs a watchdog that kills the process
outright on expiry, which takes the whole test run down rather than failing
just the one test — a worse failure mode than a normal timeout, but the
alternative is an unattended run that never finishes at all.
"""

import pytest
from sqlalchemy.orm import Session

from kohle.domain.models import Account, AccountType
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import descendant_account_ids_service
from kohle.use_cases.accounts import AddAccount


def test_leaf_returns_itself(session: Session) -> None:
    leaf = AddAccount(session).execute("Groceries", AccountType.expense).unwrap()

    result = descendant_account_ids_service(DbTransactionContext(session), leaf.id)

    assert result.is_ok
    assert result.unwrap() == [leaf.id]


def test_parent_returns_itself_plus_direct_children(session: Session) -> None:
    parent = AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    child_a = AddAccount(session).execute("Unallocated", AccountType.asset, None, "Cash").unwrap()
    child_b = AddAccount(session).execute("Groceries", AccountType.asset, None, "Cash").unwrap()

    result = descendant_account_ids_service(DbTransactionContext(session), parent.id)

    assert result.is_ok
    assert set(result.unwrap()) == {parent.id, child_a.id, child_b.id}


def test_deep_chain_returns_every_level(session: Session) -> None:
    root = AddAccount(session).execute("L0", AccountType.asset).unwrap()
    ids = [root.id]
    parent_name = "L0"
    for depth in range(1, 6):
        name = f"L{depth}"
        acc = AddAccount(session).execute(name, AccountType.asset, None, parent_name).unwrap()
        ids.append(acc.id)
        parent_name = name

    result = descendant_account_ids_service(DbTransactionContext(session), root.id)

    assert result.is_ok
    assert set(result.unwrap()) == set(ids)


def test_wide_tree_returns_all_siblings(session: Session) -> None:
    parent = AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    children = [
        AddAccount(session).execute(f"Envelope{i}", AccountType.asset, None, "Cash").unwrap()
        for i in range(10)
    ]

    result = descendant_account_ids_service(DbTransactionContext(session), parent.id)

    assert result.is_ok
    assert set(result.unwrap()) == {parent.id} | {c.id for c in children}


def test_unrelated_subtree_excluded(session: Session) -> None:
    cash = AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    AddAccount(session).execute("Unallocated", AccountType.asset, None, "Cash").unwrap()
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    AddAccount(session).execute("Savings", AccountType.asset, None, "Checking").unwrap()

    result = descendant_account_ids_service(DbTransactionContext(session), cash.id)

    assert result.is_ok
    descendant_ids = result.unwrap()
    assert checking.id not in descendant_ids


@pytest.mark.timeout(10, method="thread")
def test_cycle_terminates_and_returns_reachable_set(session: Session) -> None:
    # The cycle is built by setting parent_id directly on committed rows: no
    # use case can create one, so this guards against corrupt data rather than
    # a reachable state. Do not "fix" it by routing through AddAccount.
    #
    # method="thread" is required, not cosmetic: the default signal-based
    # timeout only fires between bytecode instructions, and a hang in the
    # recursive CTE blocks inside SQLite's C code, where no bytecode runs to
    # deliver the signal to. Only the thread watchdog, which kills the
    # process on expiry, can actually stop it — verified by swapping the
    # service's UNION for UNION ALL and confirming plain timeout(10) does not
    # catch it while method="thread" does, at ~10s.
    a = AddAccount(session).execute("A", AccountType.asset).unwrap()
    b = AddAccount(session).execute("B", AccountType.asset, None, "A").unwrap()
    c = AddAccount(session).execute("C", AccountType.asset, None, "B").unwrap()

    session.query(Account).filter(Account.id == a.id).update({"parent_id": c.id})
    session.commit()

    result = descendant_account_ids_service(DbTransactionContext(session), a.id)

    assert result.is_ok
    assert set(result.unwrap()) == {a.id, b.id, c.id}


@pytest.mark.timeout(10, method="thread")
def test_self_parented_account_terminates(session: Session) -> None:
    # See the comment on test_cycle_terminates_and_returns_reachable_set:
    # method="thread" is required because the hang this guards against
    # happens below the interpreter, where a signal-based timeout cannot
    # reach it.
    a = AddAccount(session).execute("Loopy", AccountType.asset).unwrap()

    session.query(Account).filter(Account.id == a.id).update({"parent_id": a.id})
    session.commit()

    result = descendant_account_ids_service(DbTransactionContext(session), a.id)

    assert result.is_ok
    assert result.unwrap() == [a.id]
