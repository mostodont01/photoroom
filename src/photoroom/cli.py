"""photoroom: clean up Google Photos from a Takeout export.

    photoroom import [ZIP|DIR ...]   unpack Takeout zips (default: ~/Downloads/takeout-*.zip)
                                     into the backup folder and index them
    photoroom analyze                hashes, sharpness, thumbnails (parallel, resumable)
    photoroom report                 what's there and what could go
    photoroom suggest                mark the suggested extras in duplicate / similar groups
    photoroom app                    review app: tick what goes
    photoroom marked [-o FILE]       the marked items' Google Photos links
    photoroom install-desktop        add the app to the app menu
"""

import argparse
import sys
from pathlib import Path

from . import analyze, groups, paths, takeout
from .store import Store


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def report(store: Store) -> str:
    rows = store.items()
    total = sum(r["size"] or 0 for r in rows)
    photos = [r for r in rows if r["kind"] == "image"]
    videos = [r for r in rows if r["kind"] == "video"]
    lines = [f"{len(rows)} items, {human(total)}  "
             f"(photos {len(photos)}: {human(sum(r['size'] or 0 for r in photos))}, "
             f"videos {len(videos)}: {human(sum(r['size'] or 0 for r in videos))})"]
    pending = sum(1 for r in rows if not r["analyzed"])
    if pending:
        lines.append(f"{pending} not analysed yet: run `photoroom analyze`")
    gs = groups.groups(rows)
    for kind in groups.GROUPS:
        extra = sum(g.extra_size for g in gs[kind])
        n = sum(len(g.items) - 1 for g in gs[kind])
        lines.append(f"  {groups.TITLES[kind]:<20} {len(gs[kind]):>5} groups, {n:>6} extra  {human(extra):>9}")
    ls = groups.lists(rows)
    for kind in groups.LISTS:
        size = sum(r["size"] or 0 for r in ls[kind])
        lines.append(f"  {groups.TITLES[kind]:<20} {len(ls[kind]):>6} items         {human(size):>9}")
    marked = [r for r in rows if r["mark"] and not r["deleted"]]
    lines.append(f"marked to delete: {len(marked)}, {human(sum(r['size'] or 0 for r in marked))}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="photoroom", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("import")
    s.add_argument("sources", nargs="*", type=Path)
    s.add_argument("--library", type=Path, default=None, help="where zips are unpacked")
    s = sub.add_parser("analyze")
    s.add_argument("-j", "--workers", type=int)
    sub.add_parser("report")
    sub.add_parser("suggest")
    sub.add_parser("app")
    s = sub.add_parser("install-desktop")
    s.add_argument("--uninstall", action="store_true")
    s = sub.add_parser("marked")
    s.add_argument("-o", "--output", type=Path)
    a = p.parse_args(argv)

    if a.cmd == "install-desktop":
        from .desktop import install
        print(install(a.uninstall))
        return 0
    if a.cmd == "app":
        from .app.backend import run_app
        return run_app()

    store = Store()
    if a.cmd == "import":
        library = a.library or paths.default_library()
        sources = a.sources or sorted((Path.home() / "Downloads").glob("takeout-*.zip"))
        if not sources:
            print("no Takeout zips found in ~/Downloads; give the paths", file=sys.stderr)
            return 2
        zips = [s for s in sources if s.suffix.lower() == ".zip"]
        dirs = [s for s in sources if s.is_dir()]
        if zips:
            print(f"unpacking {len(zips)} zip(s) into {library}")
            takeout.extract(zips, library)
            dirs.append(library)
        for d in dirs:
            files = list(takeout.scan(d))
            matched = sum(1 for f in files if f.sidecar)
            new, n = store.add_files(files)
            print(f"{d}: {n} new files, {new} new items "
                  f"({matched}/{len(files)} files matched to Google Photos links)")
        print(f"library: {store.count()} items")
    elif a.cmd == "analyze":
        n = analyze.run(store, a.workers)
        errors = store.db.execute("SELECT COUNT(*) FROM items WHERE error IS NOT NULL").fetchone()[0]
        print(f"analysed {n}" + (f" ({errors} unreadable)" if errors else ""))
    elif a.cmd == "report":
        print(report(store))
    elif a.cmd == "suggest":
        keys = groups.suggested_marks(groups.groups(store.items()))
        store.set_mark(keys, True)
        print(f"marked {len(keys)} extras in duplicate / similar groups")
    elif a.cmd == "marked":
        rows = store.items("mark = 1 AND deleted = 0")
        text = "\n".join(r["url"] or f"(no link) {r['path']}" for r in rows) + "\n"
        if a.output:
            a.output.write_text(text, encoding="utf-8")
            print(f"{len(rows)} links -> {a.output}")
        else:
            sys.stdout.write(text)
    return 0
