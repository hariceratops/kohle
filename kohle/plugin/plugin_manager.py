from importlib.metadata import entry_points
from kohle.plugin.importer_plugin import StatementImporterPlugin


def load_plugins() -> dict[str, StatementImporterPlugin]:
    plugins: dict[str, StatementImporterPlugin] = {}

    _entry_points = entry_points(group="kohle.plugins")
    for entry_point in _entry_points:
        plugin_class = entry_point.load()

        if not issubclass(plugin_class, StatementImporterPlugin):
            raise TypeError(f"{entry_point.name} is not a valid StatementImporterPlugin")
        instance = plugin_class()
        if instance.name in plugins:
            raise ValueError("fDuplicate plugin name: {instance.name}")
        plugins[instance.name] = instance

    return plugins

