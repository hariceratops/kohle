"""Schema lifecycle for the ledger.

Alembic is imported only inside the functions that need it: importing it costs
a noticeable fraction of every command's start-up.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.config import Config

SCRIPT_LOCATION = "kohle.db:migrations"


def alembic_config() -> "Config":
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config
