"""SQLite index of the library: one row per Google Photos item, plus its files."""

import sqlite3
from pathlib import Path

from . import paths
from .takeout import MediaFile, item_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key TEXT PRIMARY KEY,       -- Google Photos URL, or sha1:<hash> without a sidecar
    url TEXT, title TEXT, kind TEXT,
    taken INTEGER, device_folder TEXT, favorited INTEGER, archived INTEGER,
    size INTEGER, path TEXT,    -- the original file (what Google counts)
    width INTEGER, height INTEGER, duration REAL, make TEXT, model TEXT,
    phash INTEGER, blur REAL, bright REAL, thumb TEXT,
    analyzed INTEGER DEFAULT 0, error TEXT,
    mark INTEGER DEFAULT 0,     -- 1 = delete from Google Photos
    deleted INTEGER DEFAULT 0   -- 1 = done (moved to the trash in Google Photos)
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, key TEXT, role TEXT, folder TEXT, size INTEGER
);
CREATE INDEX IF NOT EXISTS files_key ON files(key);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

ROLE_RANK = {"original": 0, "edited": 1, "companion": 2}


class Store:
    def __init__(self, path: Path | None = None):
        path = path or paths.database()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add_files(self, files: list[MediaFile], log=print) -> tuple[int, int]:
        """(new items, files). Re-importing is harmless."""
        before = self.count()
        known = {r[0] for r in self.db.execute("SELECT path FROM files")}
        n = 0
        for mf in files:
            if str(mf.path) in known:
                continue
            key = item_key(mf)
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
                            (str(mf.path), key, mf.role, mf.folder, mf.size))
            row = self.db.execute("SELECT path, size FROM items WHERE key = ?", (key,)).fetchone()
            sc = mf.sidecar
            if row is None:
                self.db.execute("""INSERT INTO items (key, url, title, kind, taken, device_folder,
                                   favorited, archived, size, path) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                    key, sc.url if sc else "", sc.title if sc else mf.path.name,
                    mf.kind, sc.taken if sc else None, sc.device_folder if sc else "",
                    int(bool(sc and sc.data.get("favorited"))), int(bool(sc and sc.data.get("archived"))),
                    mf.size, str(mf.path)))
            else:
                cur_role = self.db.execute("SELECT role FROM files WHERE path = ?", (row["path"],)).fetchone()
                better = ROLE_RANK[mf.role] < ROLE_RANK.get(cur_role[0] if cur_role else "companion", 2)
                if better:
                    self.db.execute("UPDATE items SET path = ?, size = ?, kind = ?, analyzed = 0 WHERE key = ?",
                                    (str(mf.path), mf.size, mf.kind, key))
            n += 1
            if n % 5000 == 0:
                self.db.commit()
                log(f"  indexed {n} files")
        self.db.commit()
        return self.count() - before, n

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def items(self, where: str = "1", params=()) -> list[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM items WHERE {where} ORDER BY taken, key", params).fetchall()

    def update_analysis(self, key: str, values: dict) -> None:
        cols = ", ".join(f"{k} = ?" for k in values)
        self.db.execute(f"UPDATE items SET {cols}, analyzed = 1 WHERE key = ?", (*values.values(), key))

    def set_mark(self, keys, mark: bool) -> None:
        self.db.executemany("UPDATE items SET mark = ? WHERE key = ?", [(int(mark), k) for k in keys])
        self.db.commit()

    def set_deleted(self, keys, deleted: bool = True) -> None:
        self.db.executemany("UPDATE items SET deleted = ? WHERE key = ?", [(int(deleted), k) for k in keys])
        self.db.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self.db.commit()
