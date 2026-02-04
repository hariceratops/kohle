# kohle
A command line money manager  
Kohle ist umgangssprachlich für 'Geld' im Deutschen

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
