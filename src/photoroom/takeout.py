"""Reading a Google Takeout export of Google Photos.

Layout: Takeout/Google Photos/<folder>/<media> + a JSON sidecar per item
(<name>.json, <name>.supplemental-metadata.json, or a truncated form such as
<name>.supplemental-metad.json; copies get (1), (2)...). The sidecar's
"title" is the original file name and "url" links to the item on
photos.google.com, which is what deletion needs later.

The same item appears once per album it's in ("Photos from 2023" + "Trip"),
and edited / motion-photo files share their original's sidecar: all of them
become one *item*, keyed by its Google Photos URL.
"""

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
             ".dng", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".mkv", ".avi", ".webm", ".mts", ".mpg", ".wmv"}
EDITED = ("-edited", "-upraveno", "-upravené", "-bearbeitet", "-modifié", "-editado", "-modificato")
_COUNTER_MEDIA = re.compile(r"^(?P<stem>.*?)\((?P<n>\d+)\)(?P<ext>\.[^.]+)?$")
_COUNTER_JSON = re.compile(r"\((?P<n>\d+)\)\.json$", re.I)


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None


@dataclass
class Sidecar:
    path: Path
    title: str
    n: int
    data: dict

    @property
    def url(self) -> str:
        return self.data.get("url") or ""

    @property
    def taken(self) -> int | None:
        for k in ("photoTakenTime", "creationTime"):
            ts = (self.data.get(k) or {}).get("timestamp")
            if ts:
                try:
                    return int(ts)
                except ValueError:
                    pass
        return None

    @property
    def device_folder(self) -> str:
        origin = self.data.get("googlePhotosOrigin") or {}
        return (((origin.get("mobileUpload") or {}).get("deviceFolder") or {})
                .get("localFolderName") or "")


@dataclass
class MediaFile:
    path: Path
    kind: str
    size: int
    folder: str                  # Takeout folder (album / "Photos from 2023")
    sidecar: Sidecar | None
    role: str = "original"       # original | edited | companion
    extra: dict = field(default_factory=dict)


def load_sidecar(path: Path) -> Sidecar | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or "title" not in data:
        return None
    if not ("photoTakenTime" in data or "/photo/" in str(data.get("url", ""))):
        return None  # album metadata.json, print orders, ...
    m = _COUNTER_JSON.search(path.name)
    return Sidecar(path, str(data["title"]), int(m.group("n")) if m else 0, data)


def split_counter(name: str) -> tuple[str, int]:
    """'IMG_1(2).jpg' -> ('IMG_1.jpg', 2)"""
    m = _COUNTER_MEDIA.match(name)
    if m:
        return m.group("stem") + (m.group("ext") or ""), int(m.group("n"))
    return name, 0


def strip_edited(name: str) -> tuple[str, bool]:
    p = Path(name)
    for suffix in EDITED:
        if p.stem.lower().endswith(suffix):
            return p.stem[: -len(suffix)] + p.suffix, True
    return name, False


def match_folder(folder: Path) -> list[MediaFile]:
    """All media in one Takeout folder, each matched to its sidecar if found."""
    sidecars = [s for s in (load_sidecar(p) for p in folder.glob("*.json")) if s]
    by_title = {(s.title, s.n): s for s in sidecars}
    by_title_ci = {(s.title.lower(), s.n): s for s in sidecars}
    out = []
    for p in sorted(folder.iterdir()):
        kind = kind_of(p)
        if not kind or not p.is_file():
            continue
        name, n = split_counter(p.name)
        name, edited = strip_edited(name)
        role = "edited" if edited else "original"
        sc = by_title.get((name, n)) or by_title_ci.get((name.lower(), n))
        if sc is None:
            stem, ext = Path(name).stem.lower(), Path(name).suffix.lower()
            # Takeout truncates long file names; the sidecar title keeps the full one
            cands = [s for s in sidecars if s.n == n and s.title.lower().startswith(stem)
                     and Path(s.title).suffix.lower() == ext]
            if len(cands) == 1:
                sc = cands[0]
        if sc is None:
            # motion photo / live photo video next to its still: same stem, other extension
            stem = Path(name).stem.lower().removesuffix(".mp")
            cands = [s for s in sidecars if s.n == n and Path(s.title).stem.lower().removesuffix(".mp") == stem]
            if len(cands) == 1:
                sc, role = cands[0], "companion"
        out.append(MediaFile(p, kind, p.stat().st_size, folder.name, sc, role))
    return out


def photos_root(path: Path) -> Path:
    """The 'Google Photos' folder inside an extracted Takeout (or the path itself)."""
    for cand in (path / "Takeout" / "Google Photos", path / "Google Photos",
                 path / "Takeout" / "Fotky Google", path / "Fotky Google"):
        if cand.is_dir():
            return cand
    return path


def scan(root: Path) -> Iterator[MediaFile]:
    root = photos_root(root)
    for folder in sorted({p.parent for p in root.rglob("*") if p.is_file() and kind_of(p)}):
        yield from match_folder(folder)


def extract(zips: list[Path], dest: Path, log=print) -> None:
    """Unpack Takeout zips into dest (skipping files already there with the
    right size, so an interrupted run can continue). The result doubles as the
    local backup of the whole library."""
    dest.mkdir(parents=True, exist_ok=True)
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            log(f"{z.name}: {len(infos)} files")
            for k, info in enumerate(infos, 1):
                target = (dest / info.filename).resolve()
                if dest.resolve() not in target.parents:
                    continue  # never write outside dest
                if target.exists() and target.stat().st_size == info.file_size:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
                if k % 2000 == 0:
                    log(f"  {k}/{len(infos)}")


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def item_key(mf: MediaFile) -> str:
    if mf.sidecar and mf.sidecar.url:
        return mf.sidecar.url
    return "sha1:" + file_hash(mf.path)
