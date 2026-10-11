from importlib.metadata import entry_points

from kohle.plugin.importer_plugin import StatementImporterPlugin
from kohle.plugin.price_plugin import PriceFetcherPlugin


def _load[P: (StatementImporterPlugin, PriceFetcherPlugin)](kind: type[P]) -> dict[str, P]:
    plugins: dict[str, P] = {}

    for entry_point in entry_points(group="kohle.plugins"):
        plugin_class = entry_point.load()

        if not issubclass(plugin_class, (StatementImporterPlugin, PriceFetcherPlugin)):
            raise TypeError(
                f"{entry_point.name} is neither a StatementImporterPlugin nor a PriceFetcherPlugin"
            )
        if not issubclass(plugin_class, kind):
            continue
        instance = plugin_class()
        if instance.name in plugins:
            raise ValueError(f"Duplicate plugin name: {instance.name}")
        plugins[instance.name] = instance

    return plugins


def load_plugins() -> dict[str, StatementImporterPlugin]:
    return _load(StatementImporterPlugin)  # type: ignore[type-abstract]


def load_price_plugins() -> dict[str, PriceFetcherPlugin]:
    return _load(PriceFetcherPlugin)  # type: ignore[type-abstract]
