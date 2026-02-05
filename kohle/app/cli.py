import click
from kohle.db.connection import session_local
from kohle.db.uow import UnitOfWork
from kohle.services.debit_categories import add_debit_category

@click.group()
def cli():
    pass

@cli.command()
@click.argument("name")
def add_debit_category_cmd(name):
    """Add a new debit category."""
    uow = UnitOfWork(session_local)
    result = add_debit_category(uow, name)

    if result.is_ok:
        click.secho(f"✅ Category '{name}' added with ID {result.unwrap()}", fg="green")
    else:
        click.secho(f"❌ {result.unwrap_err()}", fg="red")

if __name__ == "__main__":
    cli()

