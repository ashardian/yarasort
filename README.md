# yarasort

**Sort files by what they really are, not by what their extension claims.**

![license](https://img.shields.io/badge/license-MIT-blue)
![platform](https://img.shields.io/badge/platform-Linux-informational)

`yarasort` is a command-line file organizer for Linux. It looks inside each file with [YARA](https://virustotal.github.io/yara/) rules (magic bytes and internal structure), so a PDF renamed to `holiday.jpg` still ends up in `Documents/`. It is built to be safe on a messy Downloads folder: it previews by default, never overwrites, leaves your own subfolders untouched, and every move can be undone.

```
$ yarasort scan ~/Downloads
Category           Files        Size
Other                  1        21 B
Documents              1       209 B
Images                 1       208 B
Archives               1       118 B
Audio                  1       205 B
Executables            1       512 B
Total                  6      1.2 KB

$ yarasort sort ~/Downloads
[move     ] notes.txt  ->  Other/notes.txt
[move     ] paper.pdf  ->  Documents/paper.pdf
[move     ] pic.png  ->  Images/pic.png
[move     ] plain.zip  ->  Archives/plain.zip
[move     ] song.mp3  ->  Audio/song.mp3
[move     ] tool.exe  ->  Executables/tool.exe

Summary: move=6
Dry run only, nothing was moved. Re-run with --apply to move files.
```

Only the loose files in the folder are sorted. Your own subfolders (a project folder, an existing `Documents/`) and everything inside them stay exactly where they are.

## Features

- **Content-based detection.** Over 40 formats in 10 categories, recognised from the bytes inside the file. Extensions are ignored.
- **Safe by default.** `sort`, `watch` and `undo` only preview until you add `--apply`.
- **Leaves your folders alone.** Existing subfolders are never entered, so a project folder keeps its files and its location. Sorting inside subfolders is opt-in with `--recursive`.
- **Collision-proof.** Two files with the same name never overwrite each other (see [Name collisions](#name-collisions)).
- **Undo.** Every move is journaled; `yarasort undo` restores the original layout.
- **Watch mode.** Keeps a folder sorted continuously, and waits until a file has stopped changing so it never grabs a half-finished download.
- **Configurable.** TOML config, date-based folder layouts, exclude patterns, and your own YARA rules.
- **Duplicate finder.** `yarasort dupes` lists byte-identical files (report only, it never deletes).
- **Installable system-wide** with a single script, plus an optional systemd user service.

## Install

Requirements: Linux, Python 3.9+, the `venv` module (`sudo apt install python3-venv` on Debian/Ubuntu/Mint), and internet access during install so pip can fetch `yara-python`.

```bash
git clone https://github.com/ashardian/yarasort.git
cd yarasort

sudo ./install.sh        # system-wide: /usr/local/bin/yarasort, config in /etc/yarasort
# or
./install.sh --user      # just for you: ~/.local/bin/yarasort (make sure ~/.local/bin is on PATH)
```

The installer creates an isolated virtual environment (no system Python packages are touched), links the `yarasort` command, writes a default config if none exists, installs a systemd user unit (not enabled), and finishes by running `yarasort doctor`.

If pip cannot install `yara-python` (offline, or no build tools), the installer falls back to the distribution package. Run `sudo apt install python3-yara`, then re-run the installer.

Check the installation at any time with:

```bash
yarasort doctor
```

## Quick start

```bash
yarasort scan ~/Downloads             # what is in there? changes nothing
yarasort sort ~/Downloads             # preview the moves
yarasort sort ~/Downloads --apply     # do it
yarasort undo --apply                 # changed your mind
```

To keep Downloads tidy automatically:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yarasort-watch
journalctl --user -u yarasort-watch -f      # see what it is doing
```

## Commands

| Command | What it does |
| --- | --- |
| `yarasort scan PATH` | Count and size per category. `--list` shows the files, `--json` is machine-readable. |
| `yarasort sort PATH` | Plan the moves (preview). `--apply` performs them. `--layout`, `--min-age` and `--recursive` adjust a single run. |
| `yarasort watch [PATH...]` | Poll folders and sort files once they settle. Without paths it uses `[watch] paths` from the config. Needs `--apply` to move anything. |
| `yarasort history` | List recorded runs. |
| `yarasort undo [RUN]` | Reverse a run (default: the last one). Preview unless `--apply`. |
| `yarasort dupes PATH` | List byte-identical files and the space they waste. Never deletes. |
| `yarasort config` | `--print-default` prints the default config, `--path` shows which file is in use, with no flag it shows the effective settings. |
| `yarasort doctor` | Check Python, YARA, config, rules and the journal folder. |

Shared options: `--config FILE` and `-q/--quiet`. `scan`, `sort` and `watch` also accept `--rules PATH` (repeatable) for extra YARA rules.

## Name collisions

Two different files can want the same name: a file that already exists in the destination from an earlier run, or, with `--recursive`, `a/logo.png` and `b/logo.png`. `yarasort` never overwrites. It compares file contents (SHA-256) only when a name is already taken:

| Situation | Result |
| --- | --- |
| Same name, **identical** content | The extra copy goes to `_Duplicates/`. Nothing is deleted. |
| Same name, **different** content | The newcomer is renamed: `logo (1).png`, `logo (2).png`, ... |
| Name already exists from an earlier run | The same rules apply, so re-running is safe. |

## Undo and history

Each `--apply` run (and each watch session) writes a journal to `~/.local/state/yarasort/journal/`.

```bash
yarasort history                        # 20261112-035829   13 move(s)
yarasort undo                           # preview undoing the last run
yarasort undo 20261112-035829 --apply   # really undo that run
```

Undo never overwrites. If something new now occupies a file's original path, that file is reported as `blocked` and left where it is. Empty category folders are not removed.

## Watch mode

```bash
yarasort watch ~/Downloads --apply
```

- Polls every `poll_interval_seconds` (default 5).
- A file is moved only after its size and modification time have stayed unchanged for `settle_seconds` (default 5), so in-progress downloads are left alone. Browser temp files (`*.part`, `*.crdownload`) are excluded outright.
- A file that fails to move is not retried on every poll; it is retried only if it changes.
- Without `--apply` it only logs what it would do.

The installer provides `yarasort-watch.service` as a systemd **user** unit, so the daemon runs as you with your permissions. It is installed but not enabled; the quick start above shows how to enable it.

## Configuration

Config search order: `--config FILE`, `~/.config/yarasort/config.toml`, `/etc/yarasort/config.toml`, then the built-in defaults. Generate a starting point with:

```bash
mkdir -p ~/.config/yarasort
yarasort config --print-default > ~/.config/yarasort/config.toml
```

Highlights:

```toml
[general]
layout = "{category}/{year}-{month}"     # Images/2026-11/photo.png (date = file's modified time)
exclude = ["*.part", "*.crdownload", "node_modules"]
min_age_seconds = 60                      # leave very recent files alone
recursive = false                         # default; true pulls files OUT of subfolders (flattens them)
skip_hidden = true

[watch]
paths = ["~/Downloads", "~/Desktop"]
settle_seconds = 10
```

Layout placeholders: `{category}`, `{year}`, `{month}`, `{ext}`. Layouts must be relative paths and cannot contain `..`.

### Your own categories

Write a YARA rule, point `extra_rules` at it, and map the rule name to a folder with `[[custom_category]]`. Custom categories are checked first, and the built-in categories keep working.

`~/.config/yarasort/rules/vaults.yar`:

```yara
rule KeePass_Database
{
    strings:
        $sig = { 03 D9 A2 9A 67 FB 4B B5 }
    condition:
        $sig at 0
}
```

`~/.config/yarasort/config.toml`:

```toml
[general]
extra_rules = ["~/.config/yarasort/rules"]

[[custom_category]]
rule = "KeePass_Database"
folder = "Vaults"
```

`yarasort doctor` reports a failure if a configured category names a rule that no YARA file defines.

## What it recognises

| Category (default folder) | Formats |
| --- | --- |
| Executables | Windows PE (exe, dll), Linux ELF (binaries, `.so`, AppImage) |
| Packages | Android APK, Java JAR, Debian `.deb`, RPM, Flatpak ref |
| Documents | PDF, docx / xlsx / pptx, OpenDocument, EPUB, RTF, legacy Office (OLE2, which also matches `.msi`) |
| Images | PNG, JPEG, GIF, BMP, TIFF, WebP, SVG |
| Audio | MP3, FLAC, OGG, WAV, M4A |
| Video | MP4 / MOV, MKV / WebM, AVI |
| Data | SQLite |
| Web | HTML, XML |
| Scripts | anything starting with `#!`, plus Python (heuristic) |
| Archives | ZIP, RAR5, TAR, 7z, gzip, bzip2, xz, zstd, ISO |
| Other | everything no rule recognises |

When a file matches several categories (a `.docx` is also a ZIP), the first one in the config list wins. Documents is listed before Archives, so a `.docx` goes to Documents.

## Safety design

- Preview by default; `--apply` is always explicit.
- Never overwrites a file, including a last-moment check before each move.
- Refuses to run on `/`, system directories, top-level directories such as `/home` or `/mnt`, and your home directory itself. Point it at a specific folder.
- Does not enter your existing subfolders by default, so project folders and anything else you organised yourself stay intact. `--recursive` (or `recursive = true`) opts in, and then files are pulled out of subfolders and flattened, so do not use it on folders that contain projects.
- Skips symlinks, hidden files and folders (configurable), and never rescans a top-level folder that shares a name with a category folder. Files can still be added to such a folder, for example an existing `Documents/`; what was already inside stays put.
- Journals every move and can undo it.
- `dupes` and the duplicate handling never delete anything.
- Watch mode runs as a user service, not as root.

## Limitations

- These are file-type triage rules, **not malware detection**. A file in `Documents/` is not necessarily safe.
- Files larger than `max_scan_mb` (default 64) are classified from their first and last bytes only. That is enough for every bundled rule, but custom rules that look in the middle of huge files will not see that data.
- The Python and `#!` script rules are heuristics, and plain text, JSON and CSV have no reliable signature, so they land in `Other`.
- Watch mode polls instead of using inotify. That is simple and dependency-free, but very large watched trees (especially with `recursive = true`) cost more CPU.
- Moving within one filesystem is a rename; across filesystems it is a copy followed by a delete.
- Linux only. Developed and tested on Python 3.12.

## Uninstall

```bash
sudo ./uninstall.sh            # or: ./uninstall.sh --user
sudo ./uninstall.sh --purge    # also removes the config
```

Your journal (`~/.local/state/yarasort`) is kept so old runs can still be inspected. Delete it manually if you want it gone.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
yarasort doctor
```

```
src/yarasort/
  cli.py        command-line interface
  classify.py   YARA classifier
  planner.py    file discovery, safety checks, collision-safe move planning
  journal.py    move journal, history, undo
  watcher.py    watch mode
  config.py     defaults, TOML loading, validation
  data/filetype_triage.yar   bundled rules
install.sh, uninstall.sh, systemd/yarasort-watch.service
```

To add a format to the bundled rules, add a `private rule fmt_...` and reference it from the right category rule in `src/yarasort/data/filetype_triage.yar`. Try it with `yarasort scan` on a folder containing a sample of that format.

## License

MIT, see [LICENSE](LICENSE).
