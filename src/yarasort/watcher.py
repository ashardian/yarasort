"""Watch mode: poll folders and sort files once they have stopped changing."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .classify import Classifier
from .config import Config
from .journal import Journal
from .planner import apply_moves, iter_candidates, plan_moves

log = logging.getLogger("yarasort")


class SettleTracker:
    """Reports a file as ready only after its size and mtime stop changing.

    This keeps yarasort from grabbing a download that is still being written.
    """

    def __init__(self, settle_seconds: float) -> None:
        self.settle = settle_seconds
        # path -> [signature, first_seen_with_this_signature, handled]
        self._seen: Dict[Path, list] = {}

    def update(self, files: Iterable[Path], now: float) -> List[Path]:
        ready: List[Path] = []
        current = set()
        for path in files:
            try:
                st = path.stat()
            except OSError:
                continue
            current.add(path)
            sig = (st.st_size, st.st_mtime_ns)
            entry = self._seen.get(path)
            if entry is None or entry[0] != sig:
                self._seen[path] = [sig, now, False]
            elif not entry[2] and now - entry[1] >= self.settle:
                ready.append(path)
        for gone in [p for p in self._seen if p not in current]:
            del self._seen[gone]
        return ready

    def mark_handled(self, paths: Iterable[Path]) -> None:
        """Do not offer these again until they change (avoids retry spam)."""
        for p in paths:
            if p in self._seen:
                self._seen[p][2] = True


def watch_pass(
    base: Path,
    tracker: SettleTracker,
    cfg: Config,
    classifier: Classifier,
    apply: bool,
    journal: Journal,
    now: Optional[float] = None,
) -> int:
    """One polling pass over one folder. Returns the number of files handled."""
    now = time.time() if now is None else now
    files = iter_candidates(base, cfg, recursive=cfg.watch_recursive, min_age=0, now=now)
    ready = tracker.update(files, now)
    if not ready:
        return 0
    moves, errors = plan_moves(base, ready, classifier, cfg)
    for path, msg in errors:
        log.warning("skipped %s: %s", path, msg)
    for m in moves:
        verb = m.action if apply else f"would {m.action}"
        log.info("[%s] %s -> %s", verb, m.src.name, m.dest.relative_to(base))
    if apply and moves:
        apply_moves(moves, journal)
    tracker.mark_handled(ready)
    return len(ready)


def run_watch(
    bases: List[Path],
    cfg: Config,
    classifier: Classifier,
    apply: bool,
    journal: Journal,
    stop: threading.Event,
) -> None:
    trackers = {base: SettleTracker(cfg.settle_seconds) for base in bases}
    log.info("watching %s (%s)", ", ".join(str(b) for b in bases),
             "applying moves" if apply else "dry run, nothing will be moved")
    while not stop.is_set():
        for base in bases:
            try:
                watch_pass(base, trackers[base], cfg, classifier, apply, journal)
            except Exception:  # a daemon must survive one bad pass
                log.exception("error while scanning %s", base)
        stop.wait(cfg.poll_interval)
    log.info("stopped")
