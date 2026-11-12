"""yarasort command line."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from . import __version__
from .classify import Classifier, ClassifyError, RuleError, compile_rules, rule_names
from .config import DEFAULT_CONFIG_TOML, Config, ConfigError, find_config, load_config, validate_layout
from .journal import Journal, list_runs, resolve_run, state_dir, undo_run
from .planner import (UnsafeTargetError, apply_moves, check_safe_target, iter_candidates,
                      plan_moves, sha256_file)
from .watcher import run_watch

log = logging.getLogger("yarasort")


# ----------------------------------------------------------------- helpers

def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def make_classifier(cfg: Config, extra_rules: Optional[List[str]] = None) -> Classifier:
    return Classifier(
        cfg.categories,
        list(cfg.extra_rules) + list(extra_rules or []),
        cfg.max_scan_mb * 1024 * 1024,
        cfg.other_folder,
    )


def prepare(args) -> Config:
    cfg = load_config(args.config)
    if getattr(args, "layout", None):
        validate_layout(args.layout)
        cfg.layout = args.layout
    return cfg


# ---------------------------------------------------------------- commands

def cmd_scan(args) -> int:
    cfg = prepare(args)
    base = check_safe_target(args.path)
    classifier = make_classifier(cfg, args.rules)
    files = list(iter_candidates(base, cfg, recursive=args.recursive, min_age=0))
    stats = defaultdict(lambda: [0, 0])
    listing = defaultdict(list)
    errors = 0
    for f in files:
        try:
            folder = classifier.classify(f)
            size = f.stat().st_size
        except (ClassifyError, OSError) as exc:
            errors += 1
            log.warning("skipped %s: %s", f, exc)
            continue
        stats[folder][0] += 1
        stats[folder][1] += size
        listing[folder].append(str(f.relative_to(base)))

    if args.json:
        out = {k: {"files": v[0], "bytes": v[1], **({"paths": listing[k]} if args.list else {})}
               for k, v in sorted(stats.items())}
        print(json.dumps(out, indent=2))
        return 0

    print(f"{'Category':<16}{'Files':>8}{'Size':>12}")
    for folder, (count, size) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
        print(f"{folder:<16}{count:>8}{human(size):>12}")
        if args.list:
            for rel in listing[folder]:
                print(f"    {rel}")
    total_files = sum(v[0] for v in stats.values())
    print(f"{'Total':<16}{total_files:>8}{human(sum(v[1] for v in stats.values())):>12}")
    if errors:
        print(f"({errors} file(s) could not be read)")
    return 0


def cmd_sort(args) -> int:
    cfg = prepare(args)
    if args.min_age is not None:
        cfg.min_age_seconds = args.min_age
    base = check_safe_target(args.path)
    classifier = make_classifier(cfg, args.rules)
    files = list(iter_candidates(base, cfg, recursive=args.recursive))
    moves, errors = plan_moves(base, files, classifier, cfg)

    counts = defaultdict(int)
    for m in moves:
        counts[m.action] += 1
        if not args.quiet:
            print(f"[{m.action:9}] {m.src.relative_to(base)}  ->  {m.dest.relative_to(base)}")
    for path, msg in errors:
        print(f"[error    ] {path}: {msg}", file=sys.stderr)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to do"
    print(f"\nSummary: {summary}" + (f", errors={len(errors)}" if errors else ""))

    if not args.apply:
        if moves:
            print("Dry run only, nothing was moved. Re-run with --apply to move files.")
        return 0

    with Journal() as journal:
        result = apply_moves(moves, journal)
        run_id = journal.run_id
    print(f"Moved {result['moved']} file(s)"
          + (f", skipped {result['skipped']}" if result["skipped"] else "")
          + (f", failed {result['failed']}" if result["failed"] else "") + ".")
    if run_id:
        print(f"Run {run_id} recorded. Undo with:  yarasort undo {run_id} --apply")
    return 1 if result["failed"] else 0


def cmd_watch(args) -> int:
    cfg = prepare(args)
    raw = [str(p) for p in args.paths] if args.paths else cfg.watch_paths
    if not raw:
        raise ConfigError("nothing to watch: give folders or set [watch] paths")
    bases = []
    for item in raw:
        p = Path(item).expanduser()
        if not p.is_dir():
            log.warning("not a folder, skipping: %s", p)
            continue
        bases.append(check_safe_target(p))
    if not bases:
        raise ConfigError("none of the watch folders exist")
    classifier = make_classifier(cfg, args.rules)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with Journal() as journal:
        run_watch(bases, cfg, classifier, args.apply, journal, stop)
        if journal.run_id:
            log.info("session %s recorded; undo with: yarasort undo %s --apply",
                     journal.run_id, journal.run_id)
    return 0


def cmd_history(args) -> int:
    runs = list_runs()
    if not runs:
        print(f"No runs recorded yet ({state_dir()}).")
        return 0
    for r in runs:
        flag = "  (undone)" if r["undone"] else ""
        print(f"{r['run_id']:<20}{r['moves']:>6} move(s){flag}")
    return 0


def cmd_undo(args) -> int:
    run = resolve_run(args.run)
    results = undo_run(run, apply=args.apply)
    counts = defaultdict(int)
    for status, src, dst in results:
        counts[status] += 1
        if not args.quiet:
            print(f"[{status:8}] {dst}  ->  {src}")
    print("\nSummary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not args.apply:
        print("Preview only. Re-run with --apply to restore the files.")
    elif counts.get("blocked") or counts.get("failed"):
        print("Some files could not be restored (original path occupied or error); "
              "the run stays in history so you can retry.")
        return 1
    return 0


def cmd_dupes(args) -> int:
    cfg = prepare(args)
    base = check_safe_target(args.path)
    by_size = defaultdict(list)
    recursive = True if args.recursive is None else args.recursive  # read-only, so search deep
    for f in iter_candidates(base, cfg, recursive=recursive, min_age=0, skip_managed=False):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size >= args.min_size:
            by_size[size].append(f)
    groups = []
    for size, same_size in by_size.items():
        if len(same_size) < 2:
            continue
        by_hash = defaultdict(list)
        for f in same_size:
            try:
                by_hash[sha256_file(f)].append(f)
            except OSError as exc:
                log.warning("could not read %s: %s", f, exc)
        groups.extend((size, sorted(g)) for g in by_hash.values() if len(g) > 1)
    if not groups:
        print("No duplicate files found.")
        return 0
    wasted = 0
    for size, paths in sorted(groups, key=lambda g: -g[0]):
        wasted += size * (len(paths) - 1)
        print(f"{human(size)} x {len(paths)}")
        for p in paths:
            print(f"    {p.relative_to(base)}")
    print(f"\n{len(groups)} duplicate set(s); about {human(wasted)} could be reclaimed. "
          "Nothing was changed.")
    return 0


def cmd_config(args) -> int:
    if args.print_default:
        sys.stdout.write(DEFAULT_CONFIG_TOML)
        return 0
    if args.path_only:
        found = find_config(args.config)
        print(found if found else "(none found; using built-in defaults)")
        return 0
    cfg = load_config(args.config)
    data = asdict(cfg)
    print(json.dumps(data, indent=2))
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def check(label: str, fn) -> None:
        nonlocal ok
        try:
            detail = fn()
            print(f"[ ok ] {label}: {detail}")
        except Exception as exc:
            ok = False
            print(f"[FAIL] {label}: {exc}")

    import yara

    check("python", lambda: sys.version.split()[0])
    check("yara-python", lambda: getattr(yara, "__version__", "installed"))
    cfg_holder = {}

    def _cfg():
        cfg_holder["cfg"] = load_config(args.config)
        return f"{cfg_holder['cfg'].source} ({len(cfg_holder['cfg'].categories)} categories)"

    check("config", _cfg)

    def _rules():
        cfg = cfg_holder["cfg"]
        names = rule_names(compile_rules(cfg.extra_rules))
        missing = [r for r, _ in cfg.categories if names and r not in names]
        if missing:
            raise RuntimeError("category rule(s) not defined in any YARA file: " + ", ".join(missing))
        return f"compiled, {len(names)} rules"

    if "cfg" in cfg_holder:
        check("rules", _rules)

    def _journal():
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("x")
        probe.unlink()
        return str(d)

    check("journal folder writable", _journal)
    if "cfg" in cfg_holder:
        for p in cfg_holder["cfg"].watch_paths:
            exists = Path(p).expanduser().is_dir()
            print(f"[{' ok ' if exists else 'warn'}] watch folder {p}: "
                  f"{'exists' if exists else 'does not exist'}")
    print("\nAll checks passed." if ok else "\nSome checks failed.")
    return 0 if ok else 1


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, metavar="FILE", help="use this config file")
    common.add_argument("-q", "--quiet", action="store_true", help="less output")

    rules_opt = argparse.ArgumentParser(add_help=False)
    rules_opt.add_argument("--rules", action="append", default=[], metavar="PATH",
                           help="extra YARA file or folder (repeatable)")
    rec_opt = argparse.ArgumentParser(add_help=False)
    rec_opt.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None,
                         help="also sort files inside subfolders, pulling them out (default: off)")

    p = argparse.ArgumentParser(
        prog="yarasort",
        description="Sort files into folders by what they really are (content, not extension).",
    )
    p.add_argument("--version", action="version", version=f"yarasort {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    s = sub.add_parser("scan", parents=[common, rules_opt, rec_opt],
                       help="report what is in a folder, change nothing")
    s.add_argument("path", type=Path)
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--list", action="store_true", help="also list the files per category")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("sort", parents=[common, rules_opt, rec_opt],
                       help="sort a folder (preview unless --apply)")
    s.add_argument("path", type=Path)
    s.add_argument("--apply", action="store_true", help="really move the files")
    s.add_argument("--layout", help='folder template, e.g. "{category}/{year}"')
    s.add_argument("--min-age", type=float, metavar="SECONDS",
                   help="ignore files modified more recently than this")
    s.set_defaults(func=cmd_sort)

    s = sub.add_parser("watch", parents=[common, rules_opt],
                       help="keep folders sorted continuously")
    s.add_argument("paths", nargs="*", type=Path,
                   help="folders to watch (default: [watch] paths from the config)")
    s.add_argument("--apply", action="store_true", help="really move files (default: log only)")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("history", parents=[common], help="list recorded runs")
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("undo", parents=[common], help="reverse a run (preview unless --apply)")
    s.add_argument("run", nargs="?", default="last", help="run id (default: last)")
    s.add_argument("--apply", action="store_true", help="really restore the files")
    s.set_defaults(func=cmd_undo)

    s = sub.add_parser("dupes", parents=[common, rec_opt],
                       help="list byte-identical duplicate files, change nothing")
    s.add_argument("path", type=Path)
    s.add_argument("--min-size", type=int, default=1, metavar="BYTES")
    s.set_defaults(func=cmd_dupes)

    s = sub.add_parser("config", parents=[common], help="show or generate configuration")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--print-default", action="store_true", help="print the default config file")
    g.add_argument("--path", dest="path_only", action="store_true",
                   help="print which config file is in use")
    s.set_defaults(func=cmd_config)

    s = sub.add_parser("doctor", parents=[common], help="check the installation")
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        return args.func(args)
    except (ConfigError, RuleError, UnsafeTargetError, LookupError) as exc:
        print(f"yarasort: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
