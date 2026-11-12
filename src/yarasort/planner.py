"""Finding files, planning moves (collision-safe) and applying them."""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from .classify import Classifier
from .config import Config, render_layout
from .journal import Journal

log = logging.getLogger("yarasort")

# Sorting these would be dangerous or pointless, so yarasort refuses outright.
_REFUSE_EXACT = {"/", "/home", "/mnt", "/media", "/opt", "/srv", "/tmp", "/var", "/root", "/run"}
_REFUSE_UNDER = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64",
                 "/libx32", "/proc", "/sbin", "/sys", "/usr")


class UnsafeTargetError(Exception):
    """The folder is one that must never be bulk-sorted."""


def check_safe_target(base: Path) -> Path:
    p = base.expanduser().resolve()
    s = str(p)
    if not p.is_dir():
        raise UnsafeTargetError(f"not a folder: {p}")
    if s in _REFUSE_EXACT or any(s == r or s.startswith(r + "/") for r in _REFUSE_UNDER):
        raise UnsafeTargetError(f"refusing to sort {p}: system or top-level directory")
    home = Path.home().resolve()
    if p == home or p in home.parents:
        raise UnsafeTargetError(
            f"refusing to sort {p}: it is your home directory (or contains it). "
            "Point yarasort at a specific folder such as ~/Downloads."
        )
    return p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def same_content(a: Path, b: Path) -> bool:
    try:
        if not (a.is_file() and b.is_file()):
            return False
        if a.stat().st_size != b.stat().st_size:
            return False
        return sha256_file(a) == sha256_file(b)
    except OSError:
        return False


def _matches(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def iter_candidates(
    base: Path,
    cfg: Config,
    recursive: Optional[bool] = None,
    min_age: Optional[float] = None,
    skip_managed: bool = True,
    now: Optional[float] = None,
) -> Iterator[Path]:
    """Regular files under base that are eligible for sorting."""
    recursive = cfg.recursive if recursive is None else recursive
    min_age = cfg.min_age_seconds if min_age is None else min_age
    now = time.time() if now is None else now
    managed = cfg.managed_folders() if skip_managed else set()

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        at_top = Path(dirpath) == base
        dirnames[:] = sorted(
            d for d in dirnames
            if not (cfg.skip_hidden and d.startswith("."))
            and not _matches(d, cfg.exclude)
            and not (at_top and d in managed)
        )
        if not recursive:
            dirnames.clear()
        for name in sorted(filenames):
            if cfg.skip_hidden and name.startswith("."):
                continue
            if _matches(name, cfg.exclude):
                continue
            path = Path(dirpath) / name
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if min_age > 0:
                try:
                    if now - path.stat().st_mtime < min_age:
                        continue
                except OSError:
                    continue
            yield path


@dataclass
class Move:
    src: Path
    dest: Path
    action: str  # "move" | "renamed" | "duplicate"


def free_name(folder: Path, name: str, planned: Dict[Path, Path]) -> Path:
    """First path in folder that is neither on disk nor already planned."""
    p = Path(name)
    candidate = folder / name
    n = 0
    while os.path.lexists(candidate) or candidate in planned:
        n += 1
        candidate = folder / f"{p.stem} ({n}){p.suffix}"
    return candidate


def destination_dir(base: Path, cfg: Config, folder_name: str, src: Path) -> Path:
    dt = datetime.fromtimestamp(src.stat().st_mtime)
    rel = render_layout(cfg.layout, folder_name, f"{dt:%Y}", f"{dt:%m}", src.suffix.lstrip("."))
    return base / rel


def plan_moves(
    base: Path,
    files: Sequence[Path],
    classifier: Classifier,
    cfg: Config,
) -> Tuple[List[Move], List[Tuple[Path, str]]]:
    """Decide where every file goes. Touches nothing on disk."""
    planned: Dict[Path, Path] = {}  # destination -> source, for collisions inside this batch
    moves: List[Move] = []
    errors: List[Tuple[Path, str]] = []

    for src in files:
        try:
            folder_name = classifier.classify(src)
            folder = destination_dir(base, cfg, folder_name, src)
        except OSError as exc:
            errors.append((src, str(exc)))
            continue
        except Exception as exc:  # ClassifyError and friends: skip the file, keep going
            errors.append((src, str(exc)))
            continue

        dest = folder / src.name
        if dest == src:  # already where it belongs
            continue

        occupant = dest if os.path.lexists(dest) else planned.get(dest)
        if occupant is None:
            action = "move"
        elif same_content(occupant, src):
            dest = free_name(base / cfg.duplicates_folder, src.name, planned)
            action = "duplicate"
        else:
            dest = free_name(folder, src.name, planned)
            action = "renamed"

        planned[dest] = src
        moves.append(Move(src, dest, action))
    return moves, errors


def apply_moves(moves: Sequence[Move], journal: Journal) -> Dict[str, int]:
    """Perform the planned moves. Never overwrites; every success is journaled."""
    done = skipped = failed = 0
    for m in moves:
        try:
            if os.path.lexists(m.dest):  # last-moment safety net
                log.warning("skipped, destination appeared meanwhile: %s", m.dest)
                skipped += 1
                continue
            m.dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(m.src), str(m.dest))
        except OSError as exc:
            log.error("could not move %s: %s", m.src, exc)
            failed += 1
            continue
        journal.record(m.src, m.dest, m.action)
        done += 1
    return {"moved": done, "skipped": skipped, "failed": failed}
