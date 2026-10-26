import tomllib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import assert_never

import click
from tabulate import tabulate

from kohle.db.connection import ledger_path
from kohle.db.schema import migrate_ledger, open_ledger
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    DeviceKeyNotASetting,
    StateNotSet,
    UnknownDeviceKey,
)
from kohle.domain.models import DEFAULT_RULE_PRIORITY, AccountType, UnitKind
from kohle.infrastructure.device_config import (
    DEVICE_KEYS,
    DeviceConfig,
    config_dir,
    effective,
    load_device_config,
)
from kohle.plugin.plugin_manager import load_plugins, load_price_plugins
from kohle.use_cases.accounts import AddAccount, ListAccount, ListChildAccounts
from kohle.use_cases.classification import ListUnclassified, Reclassify
from kohle.use_cases.journal import (
    BASE_CURRENCY,
    CrossUnitLine,
    ImportStatement,
    LineInput,
    QueryJournalByPeriod,
    RecordSimpleEntry,
    RecordSplitEntry,
)
from kohle.use_cases.ledger import init_ledger
from kohle.use_cases.lots import QueryRealised, realised_gain
from kohle.use_cases.operations import ListOperations
from kohle.use_cases.prices import (
    AlreadyStored,
    AppendPrices,
    FetchOutcome,
    Fresh,
    ListPriceTargets,
    NoClose,
    Priced,
    SetPriceSource,
    Stale,
    Unbound,
    Unpriced,
    call_price_plugins,
)
from kohle.use_cases.reporting import (
    EstimateSummary,
    NetWorthHistory,
    QueryPositions,
    QueryValuedBalance,
    ValuedBalance,
    ValuedNetWorth,
    ValuedRow,
    at_market,
    fifo_cost,
    summarise,
    unrealised_gain,
)
from kohle.use_cases.rules import AddRule, ListRules, RemoveRule
from kohle.use_cases.sampling import STATES, PeriodEnd
from kohle.use_cases.settings import ListSettings, SetSettings, validate_init_settings
from kohle.use_cases.splitting import (
    AddSplitGroup,
    PersonShare,
    SettleUp,
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

MAX_AGE_DAYS = click.option(
    "--max-age-days", type=click.IntRange(min=0), default=7, show_default=True,
    help="Days a close stays fresh; older closes are marked stale",
)


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


_DEVICE_CONFIG = "kohle.device_config"
pass_device_config = click.decorators.pass_meta_key(
    _DEVICE_CONFIG, doc_description="the device config read for this command"
)


class _KohleCommand(click.Command):
    """Reads config.toml, then opens and checks the ledger, before the body
    runs. Both happen in invoke because Click runs the group callback before
    parsing the subcommand's arguments, and `<command> --help` must work with
    a bad config file or no ledger. opens_ledger=False skips only the ledger.
    A factory injected through obj (tests) is the caller's schema, unchecked;
    the config file is read regardless."""

    def __init__(self, *args, opens_ledger: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.opens_ledger = opens_ledger

    def invoke(self, ctx: click.Context) -> object:
        loaded = load_device_config()
        if loaded.is_err:
            raise click.ClickException(str(loaded.unwrap_err()))
        config = loaded.unwrap()
        ctx.meta[_DEVICE_CONFIG] = config
        if self.opens_ledger and ctx.obj is None:
            opened = open_ledger(ledger_path(config))
            if opened.is_err:
                raise click.ClickException(str(opened.unwrap_err()))
            ctx.obj = opened.unwrap()
        return super().invoke(ctx)


class _KohleGroup(click.Group):
    # Every command declared on `cli` reads the config and, unless it passes
    # opens_ledger=False, opens the ledger. Nothing passes cls=.
    command_class = _KohleCommand


@click.group(cls=_KohleGroup)
def cli() -> None:
    pass


def _init_file_path() -> Path:
    return config_dir() / "init.rc"


def _read_init_file(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise click.ClickException(
            f'no init file at {path}; create it with a line such as state = "BW"'
        ) from None
    except tomllib.TOMLDecodeError as e:
        raise click.ClickException(f"{path}: {e}") from None


@cli.command(name="init", opens_ledger=False)
@pass_device_config
def init_cmd(config: DeviceConfig) -> None:
    rc = _init_file_path()
    raw = _read_init_file(rc)
    validated = validate_init_settings(raw)
    if validated.is_err:
        raise click.ClickException(f"{rc}: {validated.unwrap_err()}")
    res = init_ledger(ledger_path(config), validated.unwrap())
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    done = res.unwrap()
    if done.created:
        click.echo(f"Initialized ledger at {done.path}, revision {done.revision}")
    else:
        click.echo(f"already initialized at {done.path}, revision {done.revision}")


@cli.command(name="migrate", opens_ledger=False)
@pass_device_config
def migrate_cmd(config: DeviceConfig) -> None:
    path = ledger_path(config)
    res = migrate_ledger(path)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    m = res.unwrap()
    if m.before == m.after:
        click.echo(f"ledger at {path} is already at revision {m.after}")
    else:
        click.echo(f"Migrated ledger at {path} from revision {m.before or 'none'} to {m.after}")


def _with_source(value: object, source: str) -> str:
    return f"{value}  ({source})"


@cli.command(opens_ledger=False)
@pass_device_config
def list_config_cmd(config: DeviceConfig) -> None:
    for key in DEVICE_KEYS:
        e = effective(config, key)
        click.echo(f"{key} = {_with_source(e.value, e.source)}")
    click.echo()
    click.echo(f"file: {config.path}{'' if config.found else ' (not found)'}")


@cli.command(opens_ledger=False)
@click.argument("key")
@pass_device_config
def get_config_cmd(config: DeviceConfig, key: str) -> None:
    if key not in DEVICE_KEYS:
        raise click.ClickException(str(UnknownDeviceKey(key, list(DEVICE_KEYS))))
    click.echo(str(effective(config, key).value))


@cli.command()
@pass_device_config
@click.pass_obj
def list_settings_cmd(make_session, config: DeviceConfig):
    res = ListSettings(make_session()).execute()
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    report = res.unwrap()
    for key, value in report.values.items():
        click.echo(f"{key} = {'(unset)' if value is None else value}")
    click.echo()
    ledger = report.ledger and _with_source(report.ledger, effective(config, "ledger.path").source)
    click.echo(f"ledger:   {ledger or '(in memory)'}")
    click.echo(f"revision: {report.revision or '(none)'}")


@cli.command()
@click.argument("key")
@click.argument("value")
@pass_device_config
@click.pass_obj
def set_setting_cmd(make_session, config: DeviceConfig, key: str, value: str):
    if key in DEVICE_KEYS:
        raise click.ClickException(str(DeviceKeyNotASetting(key, config.path)))
    res = SetSettings(make_session()).execute({key: value})
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Set {key} to {value}")


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
@click.argument("cash_account")
@click.argument("instrument_account", nargs=-1, metavar="[INSTRUMENT_ACCOUNT]")
@click.argument("statement_file", type=click.Path(exists=True))
@click.pass_obj
def import_statement(
    make_session, plugin_name: str, cash_account: str, instrument_account: tuple[str, ...], statement_file
):
    if len(instrument_account) > 1:
        raise click.BadParameter("at most one INSTRUMENT_ACCOUNT may be given", param_hint="INSTRUMENT_ACCOUNT")

    plugins = load_plugins()
    if plugin_name not in plugins:
        raise click.ClickException("Plugin not found")

    plugin = plugins[plugin_name]
    statement_res = plugin.import_statement(statement_file)
    if statement_res.is_err:
        raise click.ClickException(str(statement_res.unwrap_err()))

    rows = statement_res.unwrap()
    import_use_case = ImportStatement(make_session())
    res = import_use_case.execute(cash_account, rows, instrument_account[0] if instrument_account else None)
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
@MAX_AGE_DAYS
@click.pass_obj
def balance_cmd(make_session, account_name: str, max_age_days: int):
    res = QueryValuedBalance(make_session()).execute(account_name, date.today(), max_age_days)  # noqa: DTZ011 - the user's local date, by design
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    valued = res.unwrap()
    if not valued:
        click.echo("No holdings")
        return
    rows = [
        {
            "unit": v.balance.unit_identifier,
            "quantity": v.balance.quantity,
            **_market_columns(v),
            "average cost": v.balance.average_cost,
        }
        for v in valued
    ]
    if len(valued) == 1 and valued[0].balance.unit_identifier == BASE_CURRENCY:
        rows.append({
            "unit": "Total (base currency)",
            "quantity": valued[0].balance.quantity,
            **_market_columns(valued[0]),
            "average cost": None,
        })
    # missingval renders None as "-" without putting a str into the
    # column: a str in an otherwise-Decimal column makes tabulate treat
    # the whole column as non-numeric, silently disabling floatfmt for
    # every other row in it (not just the one with the missing value).
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))
    # Gated on `holdings`, not on "any non-base row": a sold-out security is a
    # non-base row but not a holding. The total sums `valued`, never `rows`,
    # so the restatement row cannot be counted.
    summary = summarise(valued)
    if summary.holdings > 0:
        click.echo(f"\nMarket value: {at_market(valued):.2f}")
        click.echo(_estimates_line(summary))


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


def _market_columns(row: ValuedRow) -> dict[str, object]:
    price: Decimal | None
    price_date: date | None
    status: str | None
    match row.close:
        case Fresh(c):
            price, price_date, status = c.price, c.price_date, "fresh"
        case Stale(c):
            price, price_date, status = c.price, c.price_date, f"stale ({c.price_date.isoformat()})"
        case NoClose():
            price, price_date, status = None, None, "no price (at cost)"
        case None:
            price, price_date, status = None, None, None
        case _:
            assert_never(row.close)
    return {
        "price": price,
        "price date": price_date,
        "market value": row.market_value,
        "status": status,
    }


def _net_worth_rows(section: str, rows: list[ValuedBalance]) -> list[dict]:
    return [
        {
            "section": section,
            "unit": r.balance.unit_identifier,
            "quantity": r.balance.quantity,
            **_market_columns(r),
            "at cost": r.balance.at_cost,
        }
        for r in rows
    ]


def _estimates_line(summary: EstimateSummary) -> str:
    if summary.estimated == 0:
        return f"0 of {summary.holdings} holdings estimated"
    return (
        f"{summary.estimated} of {summary.holdings} holdings estimated "
        f"({summary.stale} stale, {summary.no_price} at cost)"
    )


@cli.command()
@MAX_AGE_DAYS
@click.pass_obj
def net_worth_cmd(make_session, max_age_days: int):
    res = ValuedNetWorth(make_session()).execute(date.today(), max_age_days)  # noqa: DTZ011 - the user's local date, by design
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    report = res.unwrap()
    rows = _net_worth_rows("Own accounts", report.own) + _net_worth_rows(
        "Receivables (People)", report.receivables
    )
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))
    # The total folds receivables in rather than reporting them separately
    # (design §2.4) — the breakdown above is what makes that checkable
    # rather than a bare number the user has to trust.
    click.echo(f"\nNet worth (at cost): {report.at_cost.net_worth_at_cost:.2f}")
    click.echo(f"Net worth (at market): {report.net_worth_at_market:.2f}")
    click.echo(_estimates_line(report.estimates))


@cli.command()
@MAX_AGE_DAYS
@click.pass_obj
def positions_cmd(make_session, max_age_days: int):
    res = QueryPositions(make_session()).execute(date.today(), max_age_days)  # noqa: DTZ011 - the user's local date, by design
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    positions = res.unwrap()
    if not positions:
        click.echo("No positions")
    else:
        rows = [
            {
                "unit": p.holding.unit_identifier,
                "quantity": p.holding.quantity,
                **_market_columns(p),
                "FIFO cost": p.holding.fifo_cost,
                "unrealised gain": p.unrealised_gain,
            }
            for p in positions
        ]
        click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))
    click.echo(f"\nMarket value: {at_market(positions):.2f}")
    click.echo(f"FIFO cost: {fifo_cost(positions):.2f}")
    click.echo(f"Unrealised gain: {unrealised_gain(positions):.2f}")
    click.echo(_estimates_line(summarise(positions)))


@cli.command()
@click.option(
    "--year", type=click.IntRange(min=1), default=None,
    help="Only sales dated in this year; their cost still comes from earlier lots",
)
@click.pass_obj
def realised_cmd(make_session, year: int | None):
    res = QueryRealised(make_session()).execute(year)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    sales = res.unwrap()
    if not sales:
        click.echo("No sales")
    else:
        rows = [
            {
                "date": s.entry_date,
                "account": s.account_name,
                "unit": s.unit_identifier,
                "quantity": s.quantity,
                "proceeds": s.proceeds,
                "FIFO cost": s.fifo_cost,
                "gain": s.gain,
            }
            for s in sales
        ]
        click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))
    click.echo(f"\nRealised gain: {realised_gain(sales):.2f}")


@cli.command()
@click.option(
    "--group", "group_name", default=None,
    help="Restrict to one group's participants, keeping their full balances (design §8.2)",
)
@click.pass_obj
def settle_up_cmd(make_session, group_name: str | None):
    res = SettleUp(make_session()).execute(group_name)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    transfers = res.unwrap()
    if not transfers:
        click.echo("No transfers needed")
        return

    rows = [
        {
            "payer": transfer.payer or "you",
            "payee": transfer.payee or "you",
            "unit": transfer.unit_identifier,
            "quantity": transfer.quantity,
        }
        for transfer in transfers
    ]
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))

    # The command has no way to know which cash account either side of a
    # transfer touching "you" should use, and a "default cash account"
    # setting would be a configuration mechanism this codebase does not
    # have — the user supplies their own account and fills in the date and
    # description (design §8.3).
    for transfer in transfers:
        payer = transfer.payer or "<your account>"
        payee = transfer.payee or "<your account>"
        click.echo(
            f'Settle with: kohle-cli record <date> "<description>" {transfer.quantity:.2f} '
            f"--from {payer} --to {payee}"
        )


@cli.command()
@click.argument("unit")
@click.argument("plugin")
@click.argument("symbol")
@click.pass_obj
def set_price_source_cmd(make_session, unit: str, plugin: str, symbol: str):
    res = SetPriceSource(make_session()).execute(unit, plugin, symbol, sorted(load_price_plugins()))
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    binding = res.unwrap()
    click.echo(f"Price source for {unit}: {binding.plugin_name} {binding.symbol}")


def _fetch_row(outcome: FetchOutcome) -> dict[str, str]:
    match outcome:
        case Priced():
            previous = outcome.previous
            detail = f"previous {previous.price} on {previous.price_date}" if previous else "previous none"
            return {
                "unit": outcome.unit.identifier,
                "source": f"{outcome.plugin_name}:{outcome.symbol}",
                "outcome": "priced",
                "date": str(outcome.close.price_date),
                "close": str(outcome.close.price),
                "detail": detail,
            }
        case AlreadyStored():
            return {
                "unit": outcome.unit.identifier,
                "source": f"{outcome.plugin_name}:{outcome.symbol}",
                "outcome": "already stored",
                "date": str(outcome.price_date),
                "close": "-",
                "detail": "-",
            }
        case Unpriced():
            return {
                "unit": outcome.unit.identifier,
                "source": f"{outcome.plugin_name}:{outcome.symbol}",
                "outcome": "unpriced",
                "date": "-",
                "close": "-",
                "detail": str(outcome.reason),
            }
        case Unbound():
            return {
                "unit": outcome.unit.identifier,
                "source": "-",
                "outcome": "unbound",
                "date": "-",
                "close": "-",
                "detail": "-",
            }
        case _:
            assert_never(outcome)


@cli.command()
@click.pass_obj
def fetch_prices_cmd(make_session):
    targets_res = ListPriceTargets(make_session()).execute()
    if targets_res.is_err:
        raise click.ClickException(str(targets_res.unwrap_err()))
    targets = targets_res.unwrap()
    if not targets.by_plugin and not targets.unbound:
        click.echo("No held securities")
        return

    plugins = load_price_plugins() if targets.by_plugin else {}
    fetched = call_price_plugins(targets, plugins)
    report_res = AppendPrices(make_session()).execute(targets, fetched, date.today())  # noqa: DTZ011 - the user's local date, by design
    if report_res.is_err:
        raise click.ClickException(str(report_res.unwrap_err()))
    report = report_res.unwrap()
    outcomes = report.outcomes

    click.echo(tabulate([_fetch_row(outcome) for outcome in outcomes], headers="keys"))
    for unrequested in report.ignored:
        click.echo(str(unrequested))
    unpriced = sum(isinstance(outcome, Unpriced) for outcome in outcomes)
    if unpriced:
        raise click.ClickException(f"{unpriced} held securities unpriced")


@cli.command()
@click.option(
    "--from", "start", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
    help="First date sampled; defaults to the earliest ledger entry",
)
@click.option(
    "--to", "end", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
    help="Last date sampled, not after today; defaults to today",
)
@click.option(
    "--period-end", "period_end", type=click.Choice([p.value for p in PeriodEnd]),
    default=PeriodEnd.last_working_day.value, show_default=True,
    help="The month's second sample date: the calendar last day or the last working day",
)
@click.option(
    "--state", type=click.Choice(STATES), default=None,
    help="Bundesland whose public holidays are not working days, for this run only; "
    "defaults to the ledger's state setting; ignored with month-end",
)
@MAX_AGE_DAYS
@click.pass_obj
def net_worth_history_cmd(make_session, start, end, period_end: str, state: str | None, max_age_days: int):
    today = date.today()  # noqa: DTZ011 - the user's local date, by design
    end_date = end.date() if end is not None else today
    start_date = start.date() if start is not None else None
    if end_date > today:
        raise click.BadParameter(f"{end_date.isoformat()} is after today", param_hint="--to")
    if start_date is not None and start_date > end_date:
        raise click.BadParameter(
            f"{start_date.isoformat()} is after the last date {end_date.isoformat()}", param_hint="--from"
        )
    if state is None:
        listed = ListSettings(make_session()).execute()
        if listed.is_err:
            raise click.ClickException(str(listed.unwrap_err()))
        state = listed.unwrap().values["state"]
        if state is None:
            raise click.ClickException(str(StateNotSet()))
    res = NetWorthHistory(make_session()).execute(
        start_date, end_date, max_age_days, PeriodEnd(period_end), state
    )
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    rows = [
        {
            "date": r.on,
            "at cost": r.report.at_cost.net_worth_at_cost,
            "at market": r.report.net_worth_at_market,
            "estimated": f"{r.report.estimates.estimated} of {r.report.estimates.holdings}",
        }
        for r in res.unwrap()
    ]
    click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))


if __name__ == "__main__":
    cli()
