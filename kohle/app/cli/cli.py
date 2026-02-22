import click
from kohle.infrastructure.uow import UnitOfWork
from kohle.db.connection import session_local
from kohle.use_cases.debit_categories import add_debit_category, list_debit_categories
from kohle.use_cases.accounts import add_account

@click.group()
def cli():
    pass

@cli.command()
@click.argument("name")
def add_category_cmd(name: str):
    with UnitOfWork(session_local()) as uow:
        res = add_debit_category(uow, name)
        if res.is_ok:
            click.echo(f"Added category id {res.unwrap()}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_categories_cmd():
    with UnitOfWork(session_local()) as uow:
        res = list_debit_categories(uow)
        if res.is_ok:
            for c in res.unwrap():
                click.echo(f"{c['id']}: {c['category']}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("name")
@click.argument("iban")
def add_account_cmd(name: str, iban: str):
    with UnitOfWork(session_local()) as uow:
        res = add_account(uow, name, iban)
        if res.is_ok:
            click.echo(f"Added category id {res.unwrap()}")
        else:
            click.echo(f"Failed: {res.unwrap_err()}")


if __name__ == "__main__":
    cli()

