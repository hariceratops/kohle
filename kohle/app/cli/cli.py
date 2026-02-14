# kohle/cli.py
import click
from kohle.domain.domain_errors import CategoryError
from kohle.use_cases.debit_categories import add_category, list_categories

@click.group()
def cli():
    pass

@cli.command()
@click.argument("name")
def add_category_cmd(name: str):
    res = add_category(name)
    if res.is_ok:
        click.echo(f"Added category id {res.unwrap()}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")

@cli.command()
def list_categories_cmd():
    res = list_categories()
    if res.is_ok:
        for c in res.unwrap():
            click.echo(f"{c['id']}: {c['category']}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")

if __name__ == "__main__":
    cli()

