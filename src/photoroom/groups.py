"""Turning the analysis into things to review.

Groups (keep the best, delete the rest):
  duplicates   the same picture uploaded more than once (any date)
  similar      bursts / near-identical shots taken within minutes
Lists (pick what goes):
  screenshots, chats (WhatsApp / Messenger / downloads / memes), blurry, dark, videos

Favourites are never suggested for deletion.
"""

import re
from dataclasses import dataclass, field

from .analyze import hamming

SIMILAR_WINDOW_S = 10 * 60
SIMILAR_MAX_DIST = 8
DUPLICATE_MAX_DIST = 2
BLURRY_MAX = 40.0       # Laplacian variance at 512 px
DARK_MAX = 22.0         # mean brightness 0..255

SCREENSHOT_FOLDERS = ("screenshot", "screen record", "snímky obrazovky", "screencast")
CHAT_FOLDERS = ("whatsapp", "messenger", "telegram", "download", "instagram", "snapchat", "discord",
                "facebook", "tiktok", "reddit", "pinterest", "twitter", "viber", "signal")
_WA_NAME = re.compile(r"^(IMG|VID)-\d{8}-WA\d+", re.I)
_SCREENSHOT_NAME = re.compile(r"^(screenshot|screen_?record|snímek obrazovky)", re.I)

LISTS = ["screenshots", "chats", "blurry", "dark", "videos"]
GROUPS = ["duplicates", "similar"]
TITLES = {
    "duplicates": "Duplicates", "similar": "Similar shots", "screenshots": "Screenshots",
    "chats": "Chats & downloads", "blurry": "Blurry", "dark": "Dark", "videos": "Videos",
}
HINTS = {
    "duplicates": "The same picture uploaded more than once. The best copy is kept.",
    "similar": "Shots taken within minutes that look nearly the same. The sharpest is kept.",
    "screenshots": "From your Screenshots folder or named like one.",
    "chats": "Saved from WhatsApp, Messenger, Instagram, downloads... often memes.",
    "blurry": "Least sharp first. Some may be on purpose (motion, bokeh).",
    "dark": "Almost black: pocket shots, lens covered.",
    "videos": "Biggest first. One minute of video takes as much as ~100 photos.",
}


def is_screenshot(r) -> bool:
    folder = (r["device_folder"] or "").lower()
    return any(s in folder for s in SCREENSHOT_FOLDERS) or bool(_SCREENSHOT_NAME.match(r["title"] or ""))


def is_chat(r) -> bool:
    folder = (r["device_folder"] or "").lower()
    if any(s in folder for s in CHAT_FOLDERS):
        return True
    return bool(_WA_NAME.match(r["title"] or ""))


def lists(rows) -> dict[str, list]:
    out = {k: [] for k in LISTS}
    for r in rows:
        if r["favorited"] or r["deleted"]:
            continue
        if r["kind"] == "video":
            out["videos"].append(r)
            if is_chat(r):
                out["chats"].append(r)
            continue
        if is_screenshot(r):
            out["screenshots"].append(r)
        elif is_chat(r):
            out["chats"].append(r)
        else:
            if r["blur"] is not None and r["blur"] < BLURRY_MAX:
                out["blurry"].append(r)
            if r["bright"] is not None and r["bright"] < DARK_MAX:
                out["dark"].append(r)
    out["blurry"].sort(key=lambda r: r["blur"])
    out["dark"].sort(key=lambda r: r["bright"])
    out["videos"].sort(key=lambda r: -(r["size"] or 0))
    for k in ("screenshots", "chats"):
        out[k].sort(key=lambda r: -(r["taken"] or 0))
    return out


@dataclass
class Group:
    kind: str
    items: list = field(default_factory=list)
    keep: str = ""  # key of the suggested keeper

    @property
    def extra_size(self) -> int:
        return sum(r["size"] or 0 for r in self.items if r["key"] != self.keep)


def _uf_groups(n: int, pairs) -> list[list[int]]:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    out: dict[int, list[int]] = {}
    for i in range(n):
        out.setdefault(find(i), []).append(i)
    return [g for g in out.values() if len(g) > 1]


def best(items) -> str:
    """Favourite first, then the sharpest, then the biggest file."""
    return max(items, key=lambda r: (bool(r["favorited"]), r["blur"] or 0,
                                     (r["width"] or 0) * (r["height"] or 0), r["size"] or 0))["key"]


def groups(rows) -> dict[str, list[Group]]:
    imgs = [r for r in rows if r["kind"] == "image" and r["phash"] is not None and not r["deleted"]]
    # duplicates: (nearly) identical hash and same aspect, any time apart
    by_hash: dict[int, list[int]] = {}
    for i, r in enumerate(imgs):
        by_hash.setdefault(r["phash"], []).append(i)
    pairs = []
    keys = sorted(by_hash)
    for idxs in by_hash.values():
        pairs += [(idxs[0], j) for j in idxs[1:]]
    if DUPLICATE_MAX_DIST:
        # near-identical hashes: with <= 3 differing bits, at least one of the four
        # 16-bit chunks is identical, so only hashes sharing a chunk are compared
        seen = set()
        for shift in (0, 16, 32, 48):
            buckets: dict[int, list[int]] = {}
            for h in keys:
                buckets.setdefault((h >> shift) & 0xFFFF, []).append(h)
            for hs in buckets.values():
                for a_i, a in enumerate(hs[:2000]):
                    for b in hs[a_i + 1:2000]:
                        if (a, b) not in seen and hamming(a, b) <= DUPLICATE_MAX_DIST:
                            seen.add((a, b))
                            pairs.append((by_hash[a][0], by_hash[b][0]))

    def is_duplicate(a, b):
        ra, rb = imgs[a], imgs[b]
        if ra["taken"] and rb["taken"] and abs(ra["taken"] - rb["taken"]) <= SIMILAR_WINDOW_S:
            return False  # a burst: handled as similar shots
        return same_shape(a, b)

    def same_shape(a, b):
        ra, rb = imgs[a], imgs[b]
        if not (ra["width"] and rb["width"]):
            return True
        return abs(ra["width"] / ra["height"] - rb["width"] / rb["height"]) < 0.02
    dup_sets = _uf_groups(len(imgs), [(a, b) for a, b in pairs if is_duplicate(a, b)])
    in_dup = {i for g in dup_sets for i in g}
    duplicates = []
    for g in dup_sets:
        items = [imgs[i] for i in g]
        duplicates.append(Group("duplicates", items, best(items)))

    # similar: close in time and in look (not already a duplicate set)
    order = sorted((i for i in range(len(imgs)) if i not in in_dup and imgs[i]["taken"]),
                   key=lambda i: imgs[i]["taken"])
    pairs = []
    for a_pos, a in enumerate(order):
        for b in order[a_pos + 1:]:
            if imgs[b]["taken"] - imgs[a]["taken"] > SIMILAR_WINDOW_S:
                break
            if hamming(imgs[a]["phash"], imgs[b]["phash"]) <= SIMILAR_MAX_DIST:
                pairs.append((a, b))
    similar = []
    for g in _uf_groups(len(imgs), pairs):
        items = sorted((imgs[i] for i in g), key=lambda r: r["taken"])
        similar.append(Group("similar", items, best(items)))
    duplicates.sort(key=lambda g: -g.extra_size)
    similar.sort(key=lambda g: -(g.items[0]["taken"] or 0))
    return {"duplicates": duplicates, "similar": similar}


def suggested_marks(gs: dict[str, list[Group]]) -> set[str]:
    """Everything in a group except its keeper (never favourites)."""
    return {r["key"] for kind in gs.values() for g in kind for r in g.items
            if r["key"] != g.keep and not r["favorited"]}
