"""Make pygame importable in the browser build."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import sys
from pathlib import Path


_ALIASES = {"pg_math": "math", "pg_time": "time"}
_REVERSE_ALIASES = {value: key for key, value in _ALIASES.items()}


def _note(message: str) -> None:
    try:
        import js  # type: ignore[import-not-found]

        js.console.log(f"[shardlight] {message}")
    except Exception:
        pass


def _find_base_so() -> Path | None:
    for entry in list(sys.path):
        if not entry:
            continue
        candidate = Path(entry) / "pygame" / "base.cpython-312-wasm32-emscripten.so"
        if candidate.is_file():
            return candidate
    return None


class _AliasLoader:
    def __init__(self, requested: str, load_name: str, base_path: Path):
        self.requested = requested
        self.load_name = load_name
        self.base_path = base_path
        self.real_loader = importlib.machinery.ExtensionFileLoader(load_name, str(base_path))

    def create_module(self, spec):
        real_spec = importlib.util.spec_from_file_location(self.load_name, str(self.base_path), loader=self.real_loader)
        module = self.real_loader.create_module(real_spec)
        if module is None:
            module = importlib.util.module_from_spec(real_spec)
        sys.modules[self.requested] = module
        module.__name__ = self.load_name
        module.__package__ = "pygame"
        return module

    def exec_module(self, module):
        module.__name__ = self.load_name
        self.real_loader.exec_module(module)
        module.__name__ = self.requested
        module.__package__ = "pygame"


class _BaseSoFinder:
    def __init__(self, base_path: Path, init_names: set[str]):
        self.base_path = base_path
        self.init_names = init_names

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("pygame."):
            return None
        name = fullname.split(".", 1)[1]
        init_name = _REVERSE_ALIASES.get(name, name)
        if init_name not in self.init_names:
            return None

        if init_name != name:
            load_name = f"pygame.{init_name}"
            loader = _AliasLoader(fullname, load_name, self.base_path)
            return importlib.util.spec_from_file_location(fullname, str(self.base_path), loader=loader)

        loader = importlib.machinery.ExtensionFileLoader(fullname, str(self.base_path))
        return importlib.util.spec_from_file_location(fullname, str(self.base_path), loader=loader)


def _clean_pygame_modules() -> None:
    for name in list(sys.modules):
        if name == "pygame" or name.startswith("pygame."):
            del sys.modules[name]


def install_pygame_constants() -> bool:
    _clean_pygame_modules()

    base_path = _find_base_so()
    if base_path is None:
        _note("bootstrap: base shared object not found")
        return False

    data = base_path.read_bytes()
    init_names = {match.group(1).decode("ascii") for match in re.finditer(rb"PyInit_([A-Za-z0-9_]+)", data)}

    finder = _BaseSoFinder(base_path, init_names)
    if finder not in sys.meta_path:
        sys.meta_path.insert(0, finder)

    try:
        import pygame.constants  # noqa: F401

        _note("bootstrap: pygame.constants ok")
        return True
    except Exception as exc:
        _note(f"bootstrap: pygame import failed: {exc}")
        return False
