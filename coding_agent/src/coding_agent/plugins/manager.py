"""Explicit, bounded local plugin discovery and loading."""
from __future__ import annotations
import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path
from typing import Iterable
from coding_agent.plugins.models import PluginConfig, PluginContext, PluginDiagnostic

class PluginManager:
    def __init__(self, workspace: Path, *, authorized_roots: Iterable[Path] = ()) -> None:
        self.workspace = workspace.resolve()
        self.authorized_roots = tuple(p.expanduser().resolve() for p in authorized_roots)

    def load(self, entries: Iterable[PluginConfig]):
        addons = []
        diagnostics = []
        skill_roots = []
        seen: set[str] = set()
        addon_names: set[str] = set()
        for entry in entries:
            # Relative plugin paths are project-local; absolute paths (including
            # ``~/.symphony/plugins/...``) remain usable for user-wide plugins.
            root = entry.path.expanduser()
            if not root.is_absolute():
                candidates = (
                    self.workspace / root,
                    self.workspace / ".symphony" / "plugins" / root,
                    Path.home() / ".symphony" / "plugins" / root,
                    Path.home() / ".symphony" / root,
                )
                root = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
            root = root.resolve()
            manifest_path = root / "plugin.json"
            data: object = {}
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("manifest must be a JSON object")
                if data.get("schema_version") != 1:
                    raise ValueError("unsupported schema_version")
                plugin_id = data.get("id")
                if not isinstance(plugin_id, str) or not plugin_id or "/" in plugin_id:
                    raise ValueError("id must be a non-empty identifier")
                if plugin_id in seen:
                    raise ValueError(f"duplicate plugin id: {plugin_id}")
                seen.add(plugin_id)
                skills = data.get("skills", [])
                if not isinstance(skills, list):
                    raise ValueError("skills must be a list")
                if not entry.enabled:
                    continue
                for item in skills:
                    if not isinstance(item, str) or Path(item).is_absolute():
                        raise ValueError("skill paths must be relative")
                    skill_root = (root / item).resolve()
                    if not skill_root.is_relative_to(root) or not skill_root.is_dir():
                        raise ValueError(f"skill path escapes plugin: {item}")
                    skill_roots.append((f"plugin/{plugin_id}", skill_root))
                addon = data.get("addon")
                if addon is None:
                    continue
                if not isinstance(addon, dict):
                    raise ValueError("addon must be an object")
                if not any(root.is_relative_to(auth) for auth in self.authorized_roots):
                    diagnostics.append(PluginDiagnostic(str(root), "plugin code is not authorized"))
                    continue
                addon_file = addon.get("file")
                factory_name = addon.get("factory")
                if (not isinstance(addon_file, str) or Path(addon_file).is_absolute()
                        or not isinstance(factory_name, str) or not factory_name.isidentifier()):
                    raise ValueError("addon requires a relative file and identifier factory")
                module_path = (root / addon_file).resolve()
                if not module_path.is_relative_to(root) or not module_path.is_file():
                    raise ValueError("addon path escapes plugin or is not a file")
                safe_id = "".join(char if char.isalnum() or char == "_" else "_" for char in plugin_id)
                package_name = f"coding_agent_plugin_{safe_id}_{uuid.uuid4().hex}"
                package = types.ModuleType(package_name)
                package.__path__ = [str(root)]
                package.__package__ = package_name
                sys.modules[package_name] = package
                name = f"{package_name}.{module_path.stem}"
                spec = importlib.util.spec_from_file_location(
                    name, module_path, submodule_search_locations=[]
                )
                if spec is None or spec.loader is None:
                    raise ValueError("unable to load addon module")
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                try:
                    spec.loader.exec_module(module)
                    factory = getattr(module, factory_name)
                    addon_instance = factory(PluginContext(self.workspace, root, entry.settings))
                    addon_name = getattr(addon_instance, "name", None)
                    if not isinstance(addon_name, str) or not addon_name:
                        raise ValueError("addon factory did not return a named addon")
                    if addon_name in addon_names:
                        raise ValueError(f"duplicate addon name: {addon_name}")
                    addon_names.add(addon_name)
                    addons.append(addon_instance)
                finally:
                    sys.modules.pop(name, None)
                    sys.modules.pop(package_name, None)
            except Exception as exc:
                diagnostics.append(PluginDiagnostic(str(manifest_path), str(exc)))
        return addons, skill_roots, tuple(diagnostics)

__all__ = ["PluginManager"]
