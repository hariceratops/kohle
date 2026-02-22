# kohle
A command line money manager  
Kohle ist umgangssprachlich für 'Geld' im Deutschen

> [!WARNING]
> The app is highly personalized

### Running
To run the app, install the application into a uv venv, activate the venv and run the application
```bash
uv init
uv sync
source .venv/bin/activate
kohle-cli
kohle-tui
```

To run the tests, install dev dependencies and run tests from the root folder
```bash
uv sync --extra dev
uv run pytest tests/
```

### Writing importer plugins
A new plugin can be rolled out by defining an entry point to kohle plugins
```toml

[project]
name = "kohle-hello-plugin"
version = "0.1.0"
description = "Hello world plugin for Kohle"

dependencies = ["kohle"]

[project.entry-points."kohle.plugins"]
hello_world = "kohle_hello_plugin.plugin:HelloWorldPlugin"
```

A importer plugin shalll satisfy the contract of base class StatementImporterPlugin defined in kohle.plugin.importer_plugin
```python
class StatementImporterPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, csv_path: str) -> pd.DataFrame:
        pass
```
