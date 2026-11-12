"""Configuration: built-in defaults, optional TOML overrides, validation."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.9 / 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


class ConfigError(Exception):
    """The configuration file is invalid."""


DEFAULT_CONFIG_TOML = """\
# yarasort configuration
#
# Search order: --config FILE, ~/.config/yarasort/config.toml,
#               /etc/yarasort/config.toml, then the built-in defaults.
# Delete any setting to fall back to its default.

[general]
# Where sorted files go, relative to the folder being sorted.
# Placeholders: {category} {year} {month} {ext}
# (year and month come from the file's modified time)
# Examples: "{category}"   "{category}/{year}"   "{category}/{year}-{month}"
layout = "{category}"

other_folder = "Other"             # files no rule recognises
duplicates_folder = "_Duplicates"  # byte-identical copies are parked here, never deleted
recursive = false                  # false: only files directly inside the folder are sorted;
                                   # subfolders and everything in them stay exactly where they are.
                                   # true: also pull files OUT of subfolders (this flattens them)
skip_hidden = true                 # ignore dotfiles and dot-folders
min_age_seconds = 0                # `sort` ignores files modified more recently than this
max_scan_mb = 64                   # bigger files are classified from their first and last bytes

# Names or globs to ignore (matched against every part of the path).
exclude = ["*.part", "*.crdownload", "*.tmp", "*.swp", "*~", "node_modules", "__pycache__"]

# Extra YARA files or folders. Add rules there, then map them with [[category]] below.
extra_rules = []

[watch]
paths = ["~/Downloads"]
poll_interval_seconds = 5
settle_seconds = 5                 # a file must stop changing this long before it is moved
recursive = false

# To ADD a category for your own YARA rule, put a [[custom_category]] block in your
# config (rule = "...", folder = "..."). Custom categories are checked first and the
# built-in list below stays as it is. Only redefine [[category]] if you want to
# replace the whole list.
#
# Order is priority: when a file matches several rules, the first one listed wins.
[[category]]
rule = "Executable_Files"
folder = "Executables"

[[category]]
rule = "Package_Files"
folder = "Packages"

[[category]]
rule = "Document_Files"
folder = "Documents"

[[category]]
rule = "Image_Files"
folder = "Images"

[[category]]
rule = "Audio_Files"
folder = "Audio"

[[category]]
rule = "Video_Files"
folder = "Video"

[[category]]
rule = "Data_Files"
folder = "Data"

[[category]]
rule = "Web_And_Markup_Files"
folder = "Web"

[[category]]
rule = "Script_Files"
folder = "Scripts"

[[category]]
rule = "Archive_Files"
folder = "Archives"
"""

_GENERAL_KEYS = {
    "layout", "other_folder", "duplicates_folder", "recursive", "skip_hidden",
    "min_age_seconds", "max_scan_mb", "exclude", "extra_rules",
}
_WATCH_KEYS = {"paths", "poll_interval_seconds", "settle_seconds", "recursive"}
_TOP_KEYS = {"general", "watch", "category", "custom_category"}


@dataclass
class Config:
    layout: str
    other_folder: str
    duplicates_folder: str
    recursive: bool
    skip_hidden: bool
    min_age_seconds: float
    max_scan_mb: int
    exclude: List[str]
    extra_rules: List[str]
    categories: List[Tuple[str, str]]  # (YARA rule name, folder), in priority order
    watch_paths: List[str]
    poll_interval: float
    settle_seconds: float
    watch_recursive: bool
    source: str = "built-in defaults"

    def managed_folders(self) -> set:
        """Top-level folder names yarasort itself creates (and therefore skips)."""
        names = {folder for _, folder in self.categories}
        names.update({self.other_folder, self.duplicates_folder})
        return names


def render_layout(layout: str, category: str, year: str, month: str, ext: str) -> Path:
    """Expand the layout template into a relative folder path, safely."""
    ext = re.sub(r"[^a-z0-9]", "", ext.lower()) or "noext"
    try:
        rel = layout.format(category=category, year=year, month=month, ext=ext)
    except (KeyError, IndexError, ValueError) as exc:
        raise ConfigError(f"bad layout {layout!r}: {exc!r}") from exc
    parts = [p for p in rel.split("/") if p]
    if rel.startswith("/") or not parts or any(p in (".", "..") for p in parts):
        raise ConfigError(f"layout {layout!r} must be a relative path without '..'")
    return Path(*parts)


def _safe_folder(name: object, what: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise ConfigError(f"{what} must be a single folder name, got {name!r}")
    return name


def _require_toml() -> None:
    if tomllib is None:
        raise ConfigError(
            "no TOML parser available (Python < 3.11 needs 'tomli'): "
            "pip install tomli   or   sudo apt install python3-tomli"
        )


def find_config(explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        return explicit
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    for candidate in (xdg / "yarasort" / "config.toml", Path("/etc/yarasort/config.toml")):
        if candidate.is_file():
            return candidate
    return None


def _merge(base: dict, user: dict) -> dict:
    unknown = set(user) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level setting(s): {', '.join(sorted(unknown))}")
    merged = {"general": dict(base["general"]), "watch": dict(base["watch"]),
              "category": base["category"], "custom_category": []}
    for table, allowed in (("general", _GENERAL_KEYS), ("watch", _WATCH_KEYS)):
        section = user.get(table, {})
        bad = set(section) - allowed
        if bad:
            raise ConfigError(f"unknown setting(s) in [{table}]: {', '.join(sorted(bad))}")
        merged[table].update(section)
    if "category" in user:
        merged["category"] = user["category"]
    if "custom_category" in user:
        merged["custom_category"] = user["custom_category"]
    return merged


def load_config(explicit: Optional[Path] = None) -> Config:
    _require_toml()
    data = tomllib.loads(DEFAULT_CONFIG_TOML)
    data["custom_category"] = []
    path = find_config(explicit)
    source = "built-in defaults"
    if path is not None:
        try:
            data = _merge(data, tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        except ConfigError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        source = str(path)

    g, w = data["general"], data["watch"]
    categories: List[Tuple[str, str]] = []
    for i, entry in enumerate(list(data["custom_category"]) + list(data["category"]), start=1):
        if not isinstance(entry, dict) or set(entry) != {"rule", "folder"}:
            raise ConfigError(f"[[category]] #{i} needs exactly 'rule' and 'folder'")
        categories.append((str(entry["rule"]), _safe_folder(entry["folder"], f"category #{i} folder")))
    if len({rule for rule, _ in categories}) != len(categories):
        raise ConfigError("the same rule is listed in two [[category]] entries")

    cfg = Config(
        layout=str(g["layout"]),
        other_folder=_safe_folder(g["other_folder"], "other_folder"),
        duplicates_folder=_safe_folder(g["duplicates_folder"], "duplicates_folder"),
        recursive=bool(g["recursive"]),
        skip_hidden=bool(g["skip_hidden"]),
        min_age_seconds=float(g["min_age_seconds"]),
        max_scan_mb=int(g["max_scan_mb"]),
        exclude=[str(x) for x in g["exclude"]],
        extra_rules=[str(Path(x).expanduser()) for x in g["extra_rules"]],
        categories=categories,
        watch_paths=[str(Path(x).expanduser()) for x in w["paths"]],
        poll_interval=max(float(w["poll_interval_seconds"]), 0.5),
        settle_seconds=max(float(w["settle_seconds"]), 0.0),
        watch_recursive=bool(w["recursive"]),
        source=source,
    )
    validate_layout(cfg.layout)
    if cfg.max_scan_mb < 1:
        raise ConfigError("max_scan_mb must be at least 1")
    return cfg


def validate_layout(layout: str) -> None:
    render_layout(layout, "Category", "2000", "01", "ext")
