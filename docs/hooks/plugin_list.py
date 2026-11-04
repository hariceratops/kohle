from kohle.plugin.plugin_manager import load_plugins, load_price_plugins

PLACEHOLDER = "<!-- generated: plugin-list -->"
NOT_STATED = "not stated by the plugin"


def _accepts(plugin: object) -> str:
    # Not inspect.getdoc: it falls back to the base class and would print the
    # contract text as if the plugin had said it.
    doc = type(plugin).__doc__
    if not doc or not doc.strip():
        return NOT_STATED
    return " ".join(doc.strip().split("\n\n")[0].split())


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def plugin_table() -> str:
    plugins = [("importer", p) for p in load_plugins().values()]
    plugins += [("price", p) for p in load_price_plugins().values()]
    lines = ["| Plugin | Kind | Accepts |", "|---|---|---|"]
    for kind, plugin in sorted(plugins, key=lambda item: (item[0], item[1].name)):
        lines.append(f"| {_cell(plugin.name)} | {kind} | {_cell(_accepts(plugin))} |")
    return "\n".join(lines)


def on_page_markdown(markdown, *, page, config, files):
    return markdown.replace(PLACEHOLDER, plugin_table())
