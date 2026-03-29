import sys
import click
from tabulate import tabulate
from kohle.infrastructure.uow import UnitOfWork
from kohle.db.connection import session_local
from kohle.plugin.plugin_manager import load_plugins
from kohle.use_cases.debit_categories import add_debit_category, list_debit_categories
from kohle.use_cases.accounts import add_account, list_accounts
from kohle.use_cases.transactions import import_transaction_statement, query_transaction_by_period


@click.group()
def cli():
    pass


@cli.command()
@click.argument("name")
def add_category_cmd(name: str):
    with UnitOfWork(session_local()) as uow:
        res = add_debit_category(uow, name)
        if res.is_ok:
            click.echo(f"Added category {name} with id {res.unwrap().id}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_categories_cmd():
    with UnitOfWork(session_local()) as uow:
        res = list_debit_categories(uow)
        if res.is_ok:
            click.echo(tabulate(res.unwrap()))
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("name")
@click.argument("iban")
def add_account_cmd(name: str, iban: str):
    with UnitOfWork(session_local()) as uow:
        res = add_account(uow, name, iban)
        if res.is_ok:
            click.echo(f"Added account {name}, {iban} with id {res.unwrap().id}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_accounts_cmd():
    with UnitOfWork(session_local()) as uow:
        res = list_accounts(uow)
        if res.is_ok:
            for c in res.unwrap():
                click.echo(f"{c.id}: name={c.name}, iban={c.iban}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_importer_plugins():
    plugins = load_plugins()

    if not plugins:
        click.echo("No plugins found")
        return
    for name, _ in plugins.items():
        click.echo(name)


@cli.command()
@click.argument("plugin_name", required=True)
@click.argument('account_name')
@click.argument('csv_file', type=click.Path(exists=True))
def import_statement(plugin_name: str, account_name: str, csv_file):
    plugins = load_plugins()
    if plugin_name not in plugins:
        click.echo(f"Plugin not found")

    plugin = plugins[plugin_name]
    statement_res = plugin.import_statement(csv_file)
    if statement_res.is_err:
        click.echo(f"Statement processing failed, reason = {statement_res.unwrap_err()}")
        sys.exit(1)

    df = statement_res.unwrap()
    with UnitOfWork(session_local()) as uow:
        res = import_transaction_statement(uow, account_name, df)
        if res.is_ok:
            click.echo(f"Import succeded, {res.unwrap()} transactions imported")
        else:
            click.echo(f"Import failed, reason = {res.unwrap_err()}")


@cli.command()
@click.argument('account_name')
@click.argument("start")
@click.argument("end")
def transactions_in_period(account_name, start, end):
    with UnitOfWork(session_local()) as uow:
        res = query_transaction_by_period(uow, account_name, start, end)
        if res.is_ok:
            click.echo(tabulate(res.unwrap(), floatfmt=".2f"))
        else:
            click.echo(f"Querying for the period failed {res.unwrap_err()}")


if __name__ == "__main__":
    cli()

