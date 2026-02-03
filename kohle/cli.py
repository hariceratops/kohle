# kohle/cli.py
import click
from sqlalchemy.orm import Session
from kohle.db import session_local
from kohle.services.categories import add_debit_category

@click.group()
def cli():
    pass


@cli.command()
@click.argument("name")
def add_debit_category_cmd(name):
    """Add a new debit category."""
    session: Session = session_local()
    try:
        result = add_debit_category(session, name)
    except ValueError as e:
        click.secho(f"❌ {e}", fg="red")
        return
    finally:
        session.close()

    if result.added:
        click.secho(f"✅ Category '{name}' added", fg="green")
    else:
        click.secho(f"⚠ Category '{name}' already exists", fg="yellow")

    for w in result.warnings:
        click.secho(f"⚠ Similar category exists: {w}", fg="yellow")


if __name__ == "__main__":
    cli()

