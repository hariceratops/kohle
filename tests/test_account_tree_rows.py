"""Layer 1 — pure unit tests, no fixture.

`_account_tree_rows` (issue 007) turns the flat list `ListAccount` returns
into tabulate rows shaped like a tree. It is built from `parent_id`, never
from `Account.children`, so it needs no session and no database — the
`Account` instances here are plain in-memory objects.
"""

from kohle.app.cli.cli import _account_tree_rows
from kohle.domain.models import AccountType


class FakeAccount:
    def __init__(self, id: int, name: str, parent_id: int | None = None, iban: str | None = None):
        self.id = id
        self.name = name
        self.parent_id = parent_id
        self.iban = iban
        self.type = AccountType.asset


def test_roots_appear_at_the_top_level_with_no_connector() -> None:
    accounts = [FakeAccount(1, "Checking"), FakeAccount(2, "Cash")]
    rows = _account_tree_rows(accounts)
    assert [r["account"] for r in rows] == ["Cash", "Checking"]


def test_child_is_marked_with_connector_not_leading_spaces() -> None:
    accounts = [FakeAccount(1, "Cash"), FakeAccount(2, "Groceries", parent_id=1)]
    rows = _account_tree_rows(accounts)
    child_row = next(r for r in rows if "Groceries" in r["account"])
    assert child_row["account"] == "|- Groceries"
    assert not child_row["account"].startswith(" ")


def test_parent_gets_trailing_slash_leaf_does_not() -> None:
    accounts = [FakeAccount(1, "Cash"), FakeAccount(2, "Groceries", parent_id=1)]
    rows = _account_tree_rows(accounts)
    parent_row = next(r for r in rows if r["account"].endswith("Cash/") or r["account"] == "Cash")
    assert parent_row["account"] == "Cash/"


def test_children_sorted_by_name_at_each_level() -> None:
    accounts = [
        FakeAccount(1, "Cash"),
        FakeAccount(2, "Unallocated", parent_id=1),
        FakeAccount(3, "Eating out", parent_id=1),
        FakeAccount(4, "Groceries", parent_id=1),
    ]
    rows = _account_tree_rows(accounts)
    names = [r["account"] for r in rows]
    assert names == ["Cash/", "|- Eating out", "|- Groceries", "|- Unallocated"]


def test_arbitrary_depth_renders_at_every_level() -> None:
    accounts = [
        FakeAccount(1, "Cash"),
        FakeAccount(2, "Envelopes", parent_id=1),
        FakeAccount(3, "Groceries", parent_id=2),
    ]
    rows = _account_tree_rows(accounts)
    names = [r["account"] for r in rows]
    assert names == ["Cash/", "|- Envelopes/", "|  |- Groceries"]


def test_type_and_iban_stay_visible() -> None:
    accounts = [FakeAccount(1, "Checking", iban="DE123")]
    rows = _account_tree_rows(accounts)
    assert rows[0]["type"] == "asset"
    assert rows[0]["iban"] == "DE123"


def test_missing_iban_renders_as_dash() -> None:
    accounts = [FakeAccount(1, "Checking")]
    rows = _account_tree_rows(accounts)
    assert rows[0]["iban"] == "-"


def test_root_argument_shows_only_the_named_subtree() -> None:
    accounts = [
        FakeAccount(1, "Cash"),
        FakeAccount(2, "Groceries", parent_id=1),
        FakeAccount(3, "Checking"),
    ]
    rows = _account_tree_rows(accounts, root_name="Cash")
    names = [r["account"] for r in rows]
    assert names == ["Cash/", "|- Groceries"]
