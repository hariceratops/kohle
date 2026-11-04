# Installed plugins

The importer and price plugins installed in this environment. A plugin
appears here as soon as it is installed, with no edit to this guide.

The table is generated when the site is built, from the `kohle.plugins` entry
points. On GitHub it is not shown; run `kohle-cli list-importer-plugins` to see
the importer names installed on your machine. The "Accepts" column is the first
paragraph of the plugin's own class docstring, and a plugin that has none shows
"not stated by the plugin". To add a plugin of your own, see
[Writing plugins](writing-plugins.md).

<!-- generated: plugin-list -->

The importers are used with `import-statement`, and the price plugins are bound
to a unit with `set-price-source`. The importers installed here are:

```console
$ kohle-cli list-importer-plugins
kohle-deutsche-bank
kohle-simple-broker
```
