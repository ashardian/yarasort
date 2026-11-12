"""Journal of every move, so a run can be inspected and undone."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("yarasort")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "yarasort" / "journal"


class Journal:
    """Append-only JSON-lines log of one run. Created lazily on the first move."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = Path(directory) if directory else state_dir()
        self.run_id: Optional[str] = None
        self.path: Optional[Path] = None
        self._fh = None

    def _open(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run, n = stamp, 0
        while (self.directory / f"{run}.jsonl").exists() or (
            self.directory / f"{run}.jsonl.undone"
        ).exists():
            n += 1
            run = f"{stamp}-{n}"
        self.run_id = run
        self.path = self.directory / f"{run}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")

    def record(self, src: Path, dst: Path, action: str) -> None:
        if self._fh is None:
            self._open()
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "src": str(src),
                 "dst": str(dst), "action": action}
        self._fh.write(json.dumps(entry) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _read_entries(path: Path) -> List[dict]:
    entries = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def list_runs(directory: Optional[Path] = None) -> List[Dict]:
    directory = Path(directory) if directory else state_dir()
    if not directory.is_dir():
        return []
    runs = []
    for p in sorted(directory.iterdir()):
        if p.name.endswith(".jsonl") or p.name.endswith(".jsonl.undone"):
            undone = p.name.endswith(".undone")
            run_id = p.name.split(".jsonl")[0]
            try:
                count = len(_read_entries(p))
            except (OSError, ValueError):
                count = -1
            runs.append({"run_id": run_id, "path": p, "moves": count, "undone": undone})
    return runs


def resolve_run(ident: str, directory: Optional[Path] = None) -> Dict:
    runs = list_runs(directory)
    if ident == "last":
        pending = [r for r in runs if not r["undone"]]
        if not pending:
            raise LookupError("no runs to undo")
        return pending[-1]
    for r in runs:
        if r["run_id"] == ident:
            return r
    raise LookupError(f"no such run: {ident} (see `yarasort history`)")


def undo_run(run: Dict, apply: bool) -> List[tuple]:
    """Reverse a run. Returns [(status, src, dst)]; moves nothing unless apply.

    Statuses: restore, missing (file no longer at its new place),
    blocked (something already sits at the original path), failed.
    """
    results = []
    for entry in reversed(_read_entries(run["path"])):
        src, dst = Path(entry["src"]), Path(entry["dst"])
        if not os.path.lexists(dst):
            status = "missing"
        elif os.path.lexists(src):
            status = "blocked"
        else:
            status = "restore"
            if apply:
                try:
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
                except OSError as exc:
                    log.error("could not restore %s: %s", dst, exc)
                    status = "failed"
        results.append((status, src, dst))
    if apply and all(s in ("restore", "missing") for s, _, _ in results):
        path = Path(run["path"])
        if path.name.endswith(".jsonl"):
            path.rename(path.with_name(path.name + ".undone"))
    return results
