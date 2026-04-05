import sys
import click
from tabulate import tabulate
from kohle.db.connection import session_local
from kohle.plugin.plugin_manager import load_plugins
from kohle.use_cases.debit_categories import AddDebitCategory, ListCategories
from kohle.use_cases.accounts import ListAccount, AddAccount
from kohle.use_cases.transactions import ImportTransactionStatement, QueryTransactionByPeriod


@click.group()
def cli():
    pass


@cli.command()
@click.argument("name")
def add_category_cmd(name: str):
    add_debit_category = AddDebitCategory(session_local())
    res = add_debit_category.execute(name)
    if res.is_ok:
        click.echo(f"Added category {name} with id {res.unwrap().id}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_categories_cmd():
    list_debit_categories = ListCategories(session_local())
    res = list_debit_categories.execute()
    if res.is_ok:
        click.echo(tabulate(res.unwrap()))
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("name")
@click.argument("iban")
def add_account_cmd(name: str, iban: str):
    add_account = AddAccount(session_local())
    res = add_account.execute(name, iban)
    if res.is_ok:
        click.echo(f"Added account {name}, {iban} with id {res.unwrap().id}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_accounts_cmd():
    list_accounts = ListAccount(session_local())
    res = list_accounts.execute()
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
    import_transaction_statement = ImportTransactionStatement(session_local())
    res = import_transaction_statement.execute(account_name, df)
    if res.is_ok:
        click.echo(f"Import succeded, {res.unwrap()} transactions imported")
    else:
        click.echo(f"Import failed, reason = {res.unwrap_err()}")


@cli.command()
@click.argument('account_name')
@click.argument("start")
@click.argument("end")
def transactions_in_period(account_name, start, end):
    query_transactions_by_period = QueryTransactionByPeriod(session_local())
    res = query_transactions_by_period.execute(account_name, start, end)
    if res.is_ok:
        click.echo(tabulate(res.unwrap(), floatfmt=".2f"))
    else:
        click.echo(f"Querying for the period failed {res.unwrap_err()}")


if __name__ == "__main__":
    cli()

