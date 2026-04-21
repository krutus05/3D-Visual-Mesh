from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedPlugin:
    name: str
    description: str
    status: str
    path: Path
    error: str | None = None


def ensure_plugin_template(template_path: Path):
    template_path.parent.mkdir(parents=True, exist_ok=True)
    if template_path.exists():
        return

    template_path.write_text(
        """PLUGIN_NAME = "Example Plugin"
PLUGIN_DESCRIPTION = "Shows how a drop-in plugin can talk to the app."


def register(app):
    app.append_status("Example Plugin loaded.")
""",
        encoding="utf-8",
    )


def load_plugins(app, plugins_dir: Path) -> list[LoadedPlugin]:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    loaded: list[LoadedPlugin] = []

    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue

        module_name = f"threedvisualmesh_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Could not create import spec.")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_name = getattr(module, "PLUGIN_NAME", path.stem.replace("_", " ").title())
            description = getattr(module, "PLUGIN_DESCRIPTION", "No description provided.")

            register = getattr(module, "register", None)
            if callable(register):
                register(app)
                status = "Loaded"
            else:
                status = "Loaded (no register hook)"

            loaded.append(
                LoadedPlugin(
                    name=plugin_name,
                    description=description,
                    status=status,
                    path=path,
                )
            )
        except Exception:
            loaded.append(
                LoadedPlugin(
                    name=path.stem.replace("_", " ").title(),
                    description="Plugin failed to load.",
                    status="Error",
                    path=path,
                    error=traceback.format_exc(limit=3),
                )
            )

    return loaded
