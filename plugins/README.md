# Plugins

Drop custom plugin `.py` files into this folder.

The app will scan this folder and show what loaded in the `Plugins` window.

Quick start:

1. Copy `plugin_template.py.example`
2. Rename the copy to something like `my_plugin.py`
3. Edit `PLUGIN_NAME`, `PLUGIN_DESCRIPTION`, and `register(app)`
4. Reload plugins from the app

Current minimal API:

- `PLUGIN_NAME = "Your Plugin Name"`
- `PLUGIN_DESCRIPTION = "Short description"`
- `def register(app): ...`
