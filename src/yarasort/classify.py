"""Content-based classification using YARA."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple

import yara


class RuleError(Exception):
    """The YARA rules could not be loaded or compiled."""


def bundled_rules_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "filetype_triage.yar"


def _expand_rule_sources(paths: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            files.extend(sorted(x for x in p.iterdir() if x.suffix in (".yar", ".yara")))
        elif p.is_file():
            files.append(p)
        else:
            raise RuleError(f"extra rules path not found: {p}")
    return files


def compile_rules(extra_rules: Iterable[str] = ()) -> "yara.Rules":
    sources = {"bundled": str(bundled_rules_path())}
    for i, f in enumerate(_expand_rule_sources(extra_rules)):
        sources[f"extra{i}"] = str(f)
    try:
        return yara.compile(filepaths=sources)
    except yara.Error as exc:
        raise RuleError(f"could not compile YARA rules: {exc}") from exc


def rule_names(rules: "yara.Rules") -> Set[str]:
    """Identifiers of all rules in a compiled set (empty if unsupported)."""
    try:
        return {r.identifier for r in rules}
    except TypeError:  # very old yara-python cannot iterate
        return set()


class ClassifyError(Exception):
    """A single file could not be classified."""


class Classifier:
    def __init__(
        self,
        categories: Sequence[Tuple[str, str]],
        extra_rules: Iterable[str] = (),
        max_scan_bytes: int = 64 * 1024 * 1024,
        other_folder: str = "Other",
    ) -> None:
        self.categories = list(categories)
        self.other_folder = other_folder
        self.max_scan_bytes = max_scan_bytes
        self.rules = compile_rules(extra_rules)

    def matched_rules(self, path: Path) -> Set[str]:
        try:
            size = path.stat().st_size
            if size == 0:
                return set()
            if size <= self.max_scan_bytes:
                matches = self.rules.match(filepath=str(path), timeout=60)
            else:
                # Huge file: header plus trailer is enough for every bundled rule
                # (magic bytes live at the start, ZIP names at the end).
                half = self.max_scan_bytes // 2
                with path.open("rb") as fh:
                    head = fh.read(half)
                    fh.seek(-half, os.SEEK_END)
                    tail = fh.read(half)
                matches = self.rules.match(data=head + tail, timeout=60)
        except (OSError, yara.Error) as exc:
            raise ClassifyError(f"{path}: {exc}") from exc
        return {m.rule for m in matches}

    def classify(self, path: Path) -> str:
        """Destination folder name for this file, by YARA category priority."""
        hits = self.matched_rules(path)
        for rule, folder in self.categories:
            if rule in hits:
                return folder
        return self.other_folder
