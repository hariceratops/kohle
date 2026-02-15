
## You said
Lets build the complete the code again with transactions - importer plugin, discovery, bulk insert, uow adaptations, table updates, migrations, tui, cli and tests
Skip result we already have the code and it has no changes
Assume categories and accounts are designed
This Implementation will be parked before categories anf accounts are implemented 

## ChatGPT said:

✅ Unit of Work
✅ No exceptions in services
✅ Plugins return data only
✅ Bulk insert
✅ Dedup via hash
✅ CLI + TUI
✅ Migration
✅ Discovery
✅ Tests


Final Architecture

kohle/
 ├── db/
 │     models.py
 │     uow.py
 │
 ├── transactions/
 │     services.py
 │     schema.py
 │
 ├── plugins/
 │     base.py
 │     manager.py
 │     generic_csv.py
 │
 ├── cli/
 │     transactions.py
 │
 ├── tui/
 │     transaction_table.py
 │
 └── tests/
       test_import.py

### Transaction Table (SQLAlchemy)
Assume accounts/categories exist later — we reference them.

db/models.py
Models
models/account.py

```python
from sqlalchemy import Column, Integer, String
from kohle.db import base


class Account(base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
```

models/transaction.py
```python
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Numeric,
    ForeignKey,
    UniqueConstraint,
)

from kohle.db import base


class Transaction(base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    hash = Column(String(64), nullable=False, unique=True)
    description = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    # signed!
    amount = Column(Numeric(12, 2), nullable=False)
    __table_args__ = (
        UniqueConstraint("hash", name="uq_transaction_hash"),
    )
```


### Alembic Migration
Generate:
```bash
uv run alembic revision --autogenerate -m "transactions"
```

Migration will resemble:
```python
op.create_table(
    "transactions",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("hash", sa.String(64), nullable=False),
    sa.Column("description", sa.String(), nullable=False),
    sa.Column("date", sa.Date(), nullable=False),
    sa.Column("amount", sa.Numeric(12,2), nullable=False),
    sa.Column("direction", sa.String(6)),
    sa.Column("plugin", sa.String(50)),
    sa.UniqueConstraint("hash"),
)

```
Then:
```bash
uv run alembic upgrade head
```

### Plugin Contract
plugins/base.py
```python
from abc import ABC, abstractmethod
import pandas as pd


class StatementPlugin(ABC):
    name: str

    @abstractmethod
    def load(self, path: str) -> pd.DataFrame:
        """
        Must return dataframe with columns:

        date
        description
        amount
        """
```
No DB access allowed.

Example Plugin
plugins/generic_csv.py

```python
import pandas as pd
from .base import StatementPlugin

class GenericCSVPlugin(StatementPlugin):
    name = "generic_csv"

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        required = {"date", "description", "credit", "debit"}
        if not required.issubset(df.columns):
            raise ValueError("CSV missing required columns")
        df["amount"] = df["credit"].fillna(0) - df["debit"].fillna(0)
        return df[["date", "description", "amount"]]
```

### Plugin Discovery
plugins/manager.py

```python
from importlib.metadata import entry_points
from .base import StatementPlugin


def discover_plugins():
    plugins = {}
    for ep in entry_points(group="kohle.plugins"):
        cls = ep.load()
        if not issubclass(cls, StatementPlugin):
            raise TypeError(f"{ep.name} is not a StatementPlugin")
        plugins[ep.name] = cls
    return plugins
```

pyproject.toml
```toml
[project.entry-points."kohle.plugins"]
generic_csv = "kohle.plugins.generic_csv:GenericCSVPlugin"
```

### UoW Adaptation for Bulk Insert
db/uow.py

```python
from sqlalchemy import insert
from .models import Transaction


class UnitOfWork:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def __enter__(self):
        self.session = self.session_factory()
        return self

    def __exit__(self, *args):
        self.session.close()

    # todo encapsulate this better
    def bulk_insert_transactions(self, rows):
        self.session.execute(insert(Transaction), rows)

    def existing_hashes(self, hashes):
        result = self.session.query(Transaction.hash).filter(
            Transaction.hash.in_(hashes)
        )
        return {r[0] for r in result}

    def commit(self):
        self.session.commit()

#alternative in services to keep encapsulation

from sqlalchemy import insert, select
from kohle.models.transaction import Transaction
from kohle.result import Result
from kohle.domain.errors.transaction import DuplicateTransactionError
import hashlib

def bulk_insert_transactions(uow, df):
    with uow:
        # ---------- build hashes vectorized ----------
        df["hash"] = (
            df["account"].astype(str)
            + "|"
            + df["date"].astype(str)
            + "|"
            + df["amount"].astype(str)
            + "|"
            + df["description"].str.lower()
        ).apply(lambda x: hashlib.sha256(x.encode()).hexdigest())

        # ---------- detect duplicates ----------
        existing_hashes = set(
            h for (h,) in uow.session.execute(
                select(Transaction.hash).where(
                    Transaction.hash.in_(df["hash"].tolist())
                )
            )
        )

        new_df = df[~df["hash"].isin(existing_hashes)]
        if new_df.empty:
            return Result.ok(0)
        records = new_df.to_dict("records")
        uow.session.execute(
            insert(Transaction),
            records,
        )

        commit_result = uow.commit()
        if commit_result.is_err():
            return Result.err(DuplicateTransactionError())
        return Result.ok(len(records))
```
Bulk insert is 10–50x faster than ORM adds. Always use it for imports.

### Import Service
transactions/services.py

```python
import hashlib


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def import_dataframe(uow, df, plugin_name):
    df["hash"] = df["description"].apply(sha256)
    hashes = df["hash"].tolist()
    with uow as tx:
        existing = tx.existing_hashes(hashes)
        new_df = df[~df["hash"].isin(existing)]
        rows = new_df.to_dict(orient="records")
        for r in rows:
            r["direction"] = "credit" if r["amount"] > 0 else "debit"
            r["plugin"] = plugin_name
        tx.bulk_insert_transactions(rows)
        tx.commit()
    return {
        "inserted": len(rows),
        "duplicates": len(existing),
    }

#alternative

def import_dataframe(uow: UnitOfWork, df):
    with uow:
        accounts = {
            a.name: a.id
            for a in uow.session.query(Account).all()
        }

        if not accounts:
            return Result.err(AccountNotFoundError())
        df["account_id"] = df["account"].map(accounts)
        if df["account_id"].isna().any():
            return Result.err(AccountNotFoundError())
        df["hash"] = df.apply(build_hash, axis=1)

        existing = set(
            h for (h,) in uow.session.execute(
                select(Transaction.hash).where(
                    Transaction.hash.in_(df["hash"].tolist())
                )
            )
        )

        new_df = df[~df["hash"].isin(existing)]
        if new_df.empty:
            return Result.ok(0)

        records = new_df[
            ["account_id", "hash", "description", "date", "amount"]
        ].to_dict("records")

        uow.session.execute(insert(Transaction), records)
        uow.commit()
        return Result.ok(len(records))
```
Notice: zero ORM objects, pure vectorized pandas, bulk insert. This is how high-performance ingestion is done.

### CLI
cli/transactions.py
```python
import click
from kohle.plugins.manager import discover_plugins
from kohle.transactions.services import import_dataframe
from kohle.db.uow import UnitOfWork
from kohle.db.session import SessionLocal


@click.group()
def transactions():
    pass


@transactions.command()
def plugins():
    for name in discover_plugins():
        click.echo(name)


@transactions.command()
@click.option("--plugin", required=True)
@click.argument("path")
def import_stmt(plugin, path):
    plugins = discover_plugins()
    if plugin not in plugins:
        click.echo("Unknown plugin")
        return
    df = plugins[plugin]().load(path)
    report = import_dataframe(
        UnitOfWork(SessionLocal),
        df,
        plugin,
    )
    click.echo(report)
```

### TUI DataTable
tui/transaction_table.py

```python
from textual.app import App
from textual.widgets import DataTable
from sqlalchemy import select
from kohle.db.models import Transaction
from kohle.db.session import SessionLocal


class TransactionTUI(App):
    def compose(self):
        yield DataTable()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns(
            "ID",
            "Date",
            "Description",
            "Amount",
            "Plugin",
        )
        with SessionLocal() as s:
            rows = s.execute(select(Transaction)).scalars()
            for t in rows:
                table.add_row(
                    str(t.id),
                    str(t.date),
                    t.description,
                    str(t.amount),
                    t.plugin,
                )
```

### Tests
tests/test_import.py
```python
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kohle.db.models import Base
from kohle.db.uow import UnitOfWork
from kohle.transactions.services import import_dataframe


def test_bulk_import():

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    df = pd.DataFrame({
        "date": ["2024-01-01"],
        "description": ["salary"],
        "amount": [1000],
    })

    report = import_dataframe(
        UnitOfWork(Session),
        df,
        "test_plugin",
    )

    assert report["inserted"] == 1
```

One Strong Recommendation

Add index:

Index("idx_transaction_hash", Transaction.hash)

For large imports this matters massively.

## Open Points
### Return type of import use case
Instead of returning int. Return: inserted, duplicates

### Maintaining import history
Before parsing, sha256(file_bytes). If exists, abort immediately.
This gives you, O(1) duplicate detection.

ImportReport table
Track: file name, plugin, inserted, duplicates, duration

### Plugins metadata:
Return metadata. Plugins should describe themselves.
Example:
```python
class N26Plugin(StatementPlugin):
    name = "n26"
    version = "1.0"
    supported_formats = ["csv"]
```
Then:
```bash
kohle plugins --verbose
```
Outputs:
```bash
n26 (v1.0) — CSV export from N26 bank
```



