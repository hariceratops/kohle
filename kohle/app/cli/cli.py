from decimal import Decimal, InvalidOperation

import click
from tabulate import tabulate

from kohle.db.connection import session_local
from kohle.domain.domain_errors import AccountNotFoundError
from kohle.domain.models import DEFAULT_RULE_PRIORITY, AccountType, UnitKind
from kohle.plugin.plugin_manager import load_plugins
from kohle.use_cases.accounts import AddAccount, ListAccount, ListChildAccounts
from kohle.use_cases.classification import ListUnclassified, Reclassify
from kohle.use_cases.journal import (
    BASE_CURRENCY,
    CrossUnitLine,
    ImportStatement,
    LineInput,
    QueryAccountBalance,
    QueryJournalByPeriod,
    RecordSimpleEntry,
    RecordSplitEntry,
)
from kohle.use_cases.operations import ListOperations
from kohle.use_cases.rules import AddRule, ListRules, RemoveRule
from kohle.use_cases.splitting import (
    AddSplitGroup,
    PersonShare,
    SplitImportedEntry,
    UnsplitEntry,
    WhoOwesWhat,
    WhoOwesWhatByGroup,
)
from kohle.use_cases.units import AddUnit, ListUnits


class DecimalParamType(click.ParamType):
    name = "decimal"

    def convert(self, value, param, ctx):
        try:
            return Decimal(value)
        except InvalidOperation:
            self.fail(f"{value!r} is not a valid decimal", param, ctx)


DECIMAL = DecimalParamType()


def _parse_line(raw: str) -> LineInput:
    fields = raw.split(":")
    if len(fields) != 5:
        raise click.BadParameter(f"{raw!r} does not split into ACCOUNT:QUANTITY:UNIT:PRICE:SIDE")
    account_name, quantity_str, unit_identifier, price_str, side = fields

    try:
        quantity = Decimal(quantity_str)
    except InvalidOperation:
        raise click.BadParameter(f"{raw!r}: {quantity_str!r} is not a valid decimal quantity") from None

    try:
        unit_price = Decimal(price_str)
    except InvalidOperation:
        raise click.BadParameter(f"{raw!r}: {price_str!r} is not a valid decimal price") from None

    if side not in ("debit", "credit"):
        raise click.BadParameter(f"{raw!r}: {side!r} must be 'debit' or 'credit'")

    return LineInput(account_name, quantity, unit_identifier, unit_price, is_debit=side == "debit")


def _parse_lines(ctx, param, values: tuple[str, ...]) -> list[LineInput]:
    return [_parse_line(value) for value in values]


def _parse_share(raw: str) -> PersonShare:
    name, _, quantity_str = raw.rpartition(":")
    if not name:
        raise click.BadParameter(f"{raw!r} does not split into NAME:QUANTITY")
    try:
        quantity = Decimal(quantity_str)
    except InvalidOperation:
        raise click.BadParameter(f"{raw!r}: {quantity_str!r} is not a valid decimal quantity") from None
    return PersonShare(name, quantity)


def _parse_shares(ctx, param, values: tuple[str, ...]) -> list[PersonShare]:
    return [_parse_share(value) for value in values]


def _account_tree_rows(accounts: list, root_name: str | None = None) -> list[dict]:
    """Flatten accounts into tabulate rows shaped like a tree.

    Built from `parent_id`, never from `Account.children`: `children` is a
    lazy relationship and the session is closed by the time the CLI holds
    these objects, so touching it raises `DetachedInstanceError`.
    """
    children_by_parent: dict[int | None, list] = {}
    for account in accounts:
        children_by_parent.setdefault(account.parent_id, []).append(account)
    for children in children_by_parent.values():
        children.sort(key=lambda a: a.name)

    if root_name is None:
        roots = children_by_parent.get(None, [])
    else:
        roots = [a for a in accounts if a.name == root_name]

    rows: list[dict] = []

    def walk(account, depth: int) -> None:
        children = children_by_parent.get(account.id, [])
        label = f"{account.name}/" if children else account.name
        connector = "|  " * (depth - 1) + "|- " if depth else ""
        rows.append({"account": f"{connector}{label}", "type": account.type.name, "iban": account.iban or "-"})
        for child in children:
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)

    return rows


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = ctx.obj or session_local


@cli.command()
@click.argument("name")
@click.option("--type", "account_type", type=click.Choice([t.name for t in AccountType]), default="expense")
@click.option("--iban", default=None)
@click.option("--parent", default=None, help="Name of the parent account, for virtual sub-accounts")
@click.pass_obj
def add_account_cmd(make_session, name: str, account_type: str, iban: str | None, parent: str | None):
    add_account = AddAccount(make_session())
    res = add_account.execute(name, AccountType[account_type], iban, parent)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Added account {name} ({account_type}) with id {res.unwrap().id}")


@cli.command()
@click.argument("account", required=False)
@click.pass_obj
def list_accounts_cmd(make_session, account: str | None):
    list_accounts = ListAccount(make_session())
    res = list_accounts.execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))

    accounts = res.unwrap()
    if account is not None and not any(a.name == account for a in accounts):
        raise click.ClickException(str(AccountNotFoundError(account)))

    rows = _account_tree_rows(accounts, account)
    if not rows:
        click.echo("No accounts")
        return
    click.echo(tabulate(rows, headers="keys"))


@cli.command()
@click.argument("parent_name")
@click.pass_obj
def list_child_accounts_cmd(make_session, parent_name: str):
    list_children = ListChildAccounts(make_session())
    res = list_children.execute(parent_name)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    for a in res.unwrap():
        click.echo(f"{a.id}: name={a.name}, type={a.type.name}")


@cli.command()
@click.argument("identifier")
@click.argument("name")
@click.option("--kind", type=click.Choice([k.name for k in UnitKind]), default="security")
@click.pass_obj
def add_unit_cmd(make_session, identifier: str, name: str, kind: str):
    add_unit = AddUnit(make_session())
    res = add_unit.execute(identifier, name, UnitKind[kind])
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Added unit {identifier} ({kind}) with id {res.unwrap().id}")


@cli.command()
@click.pass_obj
def list_units_cmd(make_session):
    list_units = ListUnits(make_session())
    res = list_units.execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    for u in res.unwrap():
        click.echo(f"{u.id}: {u.identifier} ({u.kind.name}) {u.name}")


@cli.command()
def list_importer_plugins():
    plugins = load_plugins()

    if not plugins:
        click.echo("No plugins found")
        return
    for name in plugins:
        click.echo(name)


@cli.command()
@click.argument("plugin_name", required=True)
@click.argument('account_name')
@click.argument('csv_file', type=click.Path(exists=True))
@click.pass_obj
def import_statement(make_session, plugin_name: str, account_name: str, csv_file):
    plugins = load_plugins()
    if plugin_name not in plugins:
        raise click.ClickException("Plugin not found")

    plugin = plugins[plugin_name]
    statement_res = plugin.import_statement(csv_file)
    if statement_res.is_err:
        raise click.ClickException(str(statement_res.unwrap_err()))

    df = statement_res.unwrap()
    import_use_case = ImportStatement(make_session())
    res = import_use_case.execute(account_name, df)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Import succeded, {res.unwrap()} entries imported")


@cli.command()
@click.argument("entry_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("description")
@click.argument("quantity", type=DECIMAL)
@click.option("--from", "from_account", required=True, help="Account to credit")
@click.option("--to", "to_account", required=True, help="Account to debit")
@click.option("--from-unit", default=None, help="Non-base unit carried by the credit side")
@click.option("--from-price", type=DECIMAL, default=None, help="Price of --from-unit")
@click.option("--to-unit", default=None, help="Non-base unit carried by the debit side")
@click.option("--to-price", type=DECIMAL, default=None, help="Price of --to-unit")
@click.pass_obj
def record_cmd(
    make_session,
    entry_date,
    description: str,
    quantity: Decimal,
    from_account: str,
    to_account: str,
    from_unit: str | None,
    from_price: Decimal | None,
    to_unit: str | None,
    to_price: Decimal | None,
):
    if from_unit and to_unit:
        raise click.BadParameter("only one of --from-unit / --to-unit may be given")
    if from_price is not None and from_unit is None:
        raise click.BadParameter("--from-price requires --from-unit")
    if to_price is not None and to_unit is None:
        raise click.BadParameter("--to-price requires --to-unit")

    cross = None
    if from_unit is not None:
        if from_price is None:
            raise click.BadParameter("--from-unit requires --from-price")
        cross = CrossUnitLine(from_unit, from_price, is_debit=False)
    elif to_unit is not None:
        if to_price is None:
            raise click.BadParameter("--to-unit requires --to-price")
        cross = CrossUnitLine(to_unit, to_price, is_debit=True)

    record = RecordSimpleEntry(make_session())
    res = record.execute(entry_date.date(), description, quantity, from_account, to_account, cross)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    if cross is None:
        click.echo(f"Recorded {quantity} {BASE_CURRENCY}: credited {from_account}, debited {to_account}")
    else:
        click.echo(
            f"Recorded {quantity} {cross.identifier} @ {cross.price}: "
            f"credited {from_account}, debited {to_account}"
        )


@cli.command()
@click.argument("entry_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("description")
@click.option(
    "--line",
    "lines",
    multiple=True,
    callback=_parse_lines,
    help="ACCOUNT:QUANTITY:UNIT:PRICE:SIDE, repeatable, one per journal line; SIDE is debit or credit",
)
@click.pass_obj
def record_split_cmd(make_session, entry_date, description: str, lines: list[LineInput]):
    record = RecordSplitEntry(make_session())
    res = record.execute(entry_date.date(), description, lines)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    entry = res.unwrap()
    click.echo(f"Recorded entry with {len(entry.lines)} lines")


@cli.command()
@click.argument('account_name')
@click.argument("start")
@click.argument("end")
@click.pass_obj
def entries_in_period(make_session, account_name, start, end):
    query = QueryJournalByPeriod(make_session())
    res = query.execute(account_name, start, end)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    rows = [
        {
            # First column, matching list-unclassified: it is split-line's
            # handle onto the line, and entries-in-period is otherwise the
            # only place a classified-away line's id can be read at all
            # (design §4.1).
            "entry_id": line.entry.id,
            "date": line.entry.entry_date,
            "description": line.entry.description,
            "counterparty": line.entry.counterparty_name or "-",
            "side": "dr" if line.is_debit else "cr",
            "quantity": line.quantity,
            "unit": line.unit.identifier,
            "value": line.value,
        }
        for line in res.unwrap()
    ]
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))


@cli.command()
@click.argument("account_name")
@click.pass_obj
def balance_cmd(make_session, account_name: str):
    query = QueryAccountBalance(make_session())
    res = query.execute(account_name)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    balances = res.unwrap()
    if not balances:
        click.echo("No holdings")
        return
    rows = [
        {
            "unit": b.unit_identifier,
            "quantity": b.quantity,
            "average cost": b.average_cost,
        }
        for b in balances
    ]
    if len(balances) == 1 and balances[0].unit_identifier == BASE_CURRENCY:
        rows.append({
            "unit": "Total (base currency)",
            "quantity": balances[0].quantity,
            "average cost": None,
        })
    # missingval renders None as "-" without putting a str into the
    # column: a str in an otherwise-Decimal column makes tabulate treat
    # the whole column as non-numeric, silently disabling floatfmt for
    # every other row in it (not just the one with the missing value).
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))


@cli.command()
@click.pass_obj
def list_operations_cmd(make_session):
    list_operations = ListOperations(make_session())
    res = list_operations.execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    rows = [
        {
            "group": op.group_id,
            "entity_type": op.entity_type,
            "entity_id": op.entity_id,
            "action": op.action,
        }
        for op in res.unwrap()
    ]
    if not rows:
        click.echo("No operations")
        return
    click.echo(tabulate(rows, headers="keys"))


@cli.command()
@click.argument("pattern")
@click.argument("account")
@click.option(
    "--priority",
    type=int,
    default=DEFAULT_RULE_PRIORITY,
    help="Lower numbers are evaluated first; ties break on rule id",
)
@click.pass_obj
def add_rule_cmd(make_session, pattern: str, account: str, priority: int):
    add_rule = AddRule(make_session())
    res = add_rule.execute(pattern, account, priority)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Added rule {res.unwrap().id}: {pattern} -> {account} (priority {priority})")


@cli.command()
@click.pass_obj
def list_rules_cmd(make_session):
    list_rules = ListRules(make_session())
    res = list_rules.execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    rules = res.unwrap()
    if not rules:
        click.echo("No rules")
        return
    # Rendered in evaluation order, with the id remove-rule takes: the order
    # rules fire in is only useful if it is the order they are printed in.
    rows = [
        {
            "id": rule.id,
            "priority": rule.priority,
            "pattern": rule.pattern,
            "account": rule.account.name,
        }
        for rule in rules
    ]
    click.echo(tabulate(rows, headers="keys"))


@cli.command()
@click.argument("rule_id", type=int)
@click.pass_obj
def remove_rule_cmd(make_session, rule_id: int):
    remove_rule = RemoveRule(make_session())
    res = remove_rule.execute(rule_id)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Removed rule {rule_id}")


@cli.command()
@click.pass_obj
def list_unclassified_cmd(make_session):
    list_unclassified = ListUnclassified(make_session())
    res = list_unclassified.execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    lines = res.unwrap()
    if not lines:
        click.echo("No unclassified lines")
        return
    # entry_id first, matching list-rules printing the id remove-rule takes:
    # it is reclassify's handle onto the line (design §2.4).
    rows = [
        {
            "entry_id": line.entry_id,
            "date": line.entry_date,
            "description": line.description,
            "counterparty": line.counterparty_name or "-",
            "amount": line.amount,
            "account": line.account_name,
        }
        for line in lines
    ]
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))


@cli.command()
@click.argument("entry_id", type=int)
@click.argument("account")
@click.pass_obj
def reclassify_cmd(make_session, entry_id: int, account: str):
    reclassify = Reclassify(make_session())
    res = reclassify.execute(entry_id, account)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Reclassified entry {entry_id} to {account}")


@cli.command()
@click.argument("name")
@click.pass_obj
def add_group_cmd(make_session, name: str):
    add_group = AddSplitGroup(make_session())
    res = add_group.execute(name)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Added split group {name} with id {res.unwrap().id}")


@cli.command()
@click.argument("entry_id", type=int)
@click.option("--mine", "own_share", type=DECIMAL, required=True, help="Your own share of the line")
@click.option(
    "--share",
    "shares",
    multiple=True,
    required=True,
    callback=_parse_shares,
    help="PERSON:QUANTITY, repeatable, one per person account",
)
@click.option(
    "--group", "group_name", default=None,
    help="Trip/label to tag the split under; absent clears it, present sets or moves it",
)
@click.pass_obj
def split_line_cmd(
    make_session, entry_id: int, own_share: Decimal, shares: list[PersonShare], group_name: str | None
):
    split = SplitImportedEntry(make_session())
    res = split.execute(entry_id, own_share, shares, group_name)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Split entry {entry_id}: {own_share} own, " + ", ".join(f"{s.person_name} {s.quantity}" for s in shares))


@cli.command()
@click.argument("entry_id", type=int)
@click.pass_obj
def unsplit_line_cmd(make_session, entry_id: int):
    unsplit = UnsplitEntry(make_session())
    res = unsplit.execute(entry_id)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Undid the split of entry {entry_id}")


@cli.command()
@click.option("--by-group", is_flag=True, default=False, help="Break the view down per group instead")
@click.pass_obj
def who_owes_what_cmd(make_session, by_group: bool):
    if by_group:
        _print_who_owes_what_by_group(make_session)
        return

    res = WhoOwesWhat(make_session()).execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    people = res.unwrap()
    if not people:
        click.echo("No person accounts")
        return
    # A person with no balances at all (never split against) renders "-",
    # distinct from a settled person's UnitBalance(quantity=0) rendering
    # "0.00" — the distinction issue 022's last criterion asks for (design
    # §7.1).
    rows = [
        row
        for person in people
        for row in (
            [{"person": person.person_name, "unit": "-", "balance": "-"}]
            if not person.balances
            else [
                {"person": person.person_name, "unit": b.unit_identifier, "balance": b.quantity}
                for b in person.balances
            ]
        )
    ]
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))


def _print_who_owes_what_by_group(make_session):
    res = WhoOwesWhatByGroup(make_session()).execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    groups = res.unwrap()
    if not groups:
        click.echo("No split groups")
        return
    for group in groups:
        click.echo(f"\n{group.group_name}")
        if not group.allocations:
            click.echo("  No splits in this group")
            continue
        rows = [
            {"person": person.person_name, "unit": b.unit_identifier, "from splits": b.quantity}
            for person in group.allocations
            for b in person.balances
        ]
        click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))
    # These figures are a historical allocation, not a live balance: they
    # do not fall as debts get settled, unlike who-owes-what's own totals
    # (design §2.3, §7.2).
    click.echo("\nNote: group figures are historical allocations, not settlement-adjusted balances.")


if __name__ == "__main__":
    cli()
