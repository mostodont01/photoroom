"""Review app, Python side: categories, items / groups, marks, previews."""

import sys
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex, QObject, Qt, QUrl, Property,
                            Signal, Slot)
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .. import groups, paths
from ..cli import human
from ..store import Store

QML_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# Design tokens (same as VL, School Notes, Reel Triage); a context property so
# inline QML components see them too.
THEME = {
    "background": "#17191d", "panel": "#202329", "panelRaised": "#282c33", "border": "#383d46",
    "text": "#e3e7ed", "muted": "#929ba8", "faint": "#687280", "accent": "#72a7ff",
    "ok": "#6fcf97", "warn": "#e5b567", "error": "#f28b82",
}


def file_url(path: str | None) -> str:
    return QUrl.fromLocalFile(path).toString() if path else ""


def item_dict(r, keep: str = "") -> dict:
    taken = r["taken"]
    return {
        "key": r["key"],
        "thumb": file_url(r["thumb"]),
        "title": r["title"] or "",
        "kind": r["kind"],
        "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(taken)) if taken else "",
        "size": human(r["size"] or 0),
        "duration": f"{int(r['duration'] // 60)}:{int(r['duration'] % 60):02d}" if r["duration"] else "",
        "keep": r["key"] == keep,
        "favorite": bool(r["favorited"]),
    }


class ItemList(QAbstractListModel):
    """Rows of the current category: items (lists) or groups (each with items)."""
    ROLES = ["key", "thumb", "title", "kind", "date", "size", "duration", "keep", "favorite", "items",
             "extra"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def roleNames(self):
        return {Qt.UserRole + i: QByteArray(n.encode()) for i, n in enumerate(self.ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)) or role < Qt.UserRole:
            return None
        return self._rows[index.row()].get(self.ROLES[role - Qt.UserRole])

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row(self, i: int) -> dict:
        return self._rows[i] if 0 <= i < len(self._rows) else {}


class Backend(QObject):
    changed = Signal()       # categories / totals
    marksChanged = Signal()  # bump: delegates re-read isMarked()
    categoryChanged = Signal()
    previewChanged = Signal()
    deletingChanged = Signal()
    message = Signal(str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._model = ItemList(self)
        self._category = ""
        self._rev = 0
        self._preview = ""
        self._queue: list[str] = []
        self._qpos = 0
        self._deleting = False
        self._marks: set[str] = set()
        self._rows: dict[str, object] = {}
        self._lists: dict[str, list] = {}
        self._groups: dict[str, list] = {}
        self.reload()

    # data
    def reload(self) -> None:
        rows = self.store.items()
        self._rows = {r["key"]: r for r in rows}
        self._marks = {r["key"] for r in rows if r["mark"] and not r["deleted"]}
        self._lists = groups.lists(rows)
        self._groups = groups.groups(rows)
        if not self._category:
            self._category = next((c["id"] for c in self.categories if c["count"]), "duplicates")
        self._fill()
        self.changed.emit()

    def _fill(self) -> None:
        c = self._category
        if c in self._groups:
            out = []
            for g in self._groups[c]:
                out.append({"key": g.items[0]["key"], "items": [item_dict(r, g.keep) for r in g.items],
                            "extra": human(g.extra_size),
                            "date": item_dict(g.items[0])["date"]})
            self._model.set_rows(out)
        elif c == "marked":
            self._model.set_rows([item_dict(self._rows[k]) for k in
                                  sorted(self._marks, key=lambda k: -(self._rows[k]["size"] or 0))])
        else:
            self._model.set_rows([item_dict(r) for r in self._lists.get(c, [])])

    def _bump(self) -> None:
        self._rev += 1
        self.marksChanged.emit()
        self.changed.emit()

    # properties
    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(int, notify=marksChanged)
    def rev(self):
        return self._rev

    @Property(str, notify=categoryChanged)
    def category(self):
        return self._category

    @Property(bool, notify=categoryChanged)
    def isGroups(self):
        return self._category in self._groups

    @Property(str, notify=categoryChanged)
    def hint(self):
        if self._category == "marked":
            return "Everything you marked. Click to unmark. These are the ones to delete in Google Photos."
        return groups.HINTS.get(self._category, "")

    @Property("QVariantList", notify=changed)
    def categories(self):
        out = []
        for c in groups.GROUPS:
            gs = self._groups.get(c, [])
            out.append({"id": c, "title": groups.TITLES[c], "count": len(gs),
                        "size": human(sum(g.extra_size for g in gs)), "unit": "groups"})
        for c in groups.LISTS:
            items = self._lists.get(c, [])
            out.append({"id": c, "title": groups.TITLES[c], "count": len(items),
                        "size": human(sum(r["size"] or 0 for r in items)), "unit": ""})
        return out

    @Property(int, notify=changed)
    def markedCount(self):
        return len(self._marks)

    @Property(str, notify=changed)
    def markedSize(self):
        return human(sum(self._rows[k]["size"] or 0 for k in self._marks if k in self._rows))

    @Property(str, notify=changed)
    def librarySummary(self):
        total = sum(r["size"] or 0 for r in self._rows.values())
        return f"{len(self._rows)} items · {human(total)}"

    @Property(str, notify=previewChanged)
    def preview(self):
        return self._preview

    # slots
    @Slot(str)
    def showPreview(self, key: str) -> None:
        if key != self._preview:
            self._preview = key
            self.previewChanged.emit()

    @Slot(str)
    def select(self, category: str) -> None:
        if category != self._category:
            self._category = category
            self._fill()
            self.categoryChanged.emit()

    @Slot(str, result=bool)
    def isMarked(self, key: str) -> bool:
        return key in self._marks

    @Slot(str)
    def toggle(self, key: str) -> None:
        mark = key not in self._marks
        if mark and self._rows.get(key) is not None and self._rows[key]["favorited"]:
            self.message.emit("That's a favourite. Marked anyway: click again to undo.")
        (self._marks.add if mark else self._marks.discard)(key)
        self.store.set_mark([key], mark)
        self._bump()

    def _visible_keys(self) -> list[str]:
        c = self._category
        if c in self._groups:
            return [r["key"] for g in self._groups[c] for r in g.items]
        if c == "marked":
            return list(self._marks)
        return [r["key"] for r in self._lists.get(c, [])]

    @Slot()
    def markSuggested(self) -> None:
        """Groups: every item except the keeper. Lists: everything (but favourites)."""
        c = self._category
        if c in self._groups:
            keys = groups.suggested_marks({c: self._groups[c]})
        else:
            keys = {k for k in self._visible_keys() if not self._rows[k]["favorited"]}
        self._marks |= keys
        self.store.set_mark(keys, True)
        self._bump()
        self.message.emit(f"Marked {len(keys)}")

    @Slot()
    def unmarkAll(self) -> None:
        keys = set(self._visible_keys()) & self._marks
        self._marks -= keys
        self.store.set_mark(keys, False)
        self._bump()
        if self._category == "marked":
            self._fill()

    @Slot(str, result="QVariantMap")
    def details(self, key: str) -> dict:
        r = self._rows.get(key)
        if r is None:
            return {}
        d = item_dict(r)
        d.update({
            "image": self.preview_url(r),
            "url": r["url"] or "",
            "path": r["path"],
            "folder": r["device_folder"] or "",
            "dims": f"{r['width']}×{r['height']}" if r["width"] else "",
            "sharpness": f"{r['blur']:.0f}" if r["blur"] is not None else "",
            "camera": " ".join(x for x in (r["make"], r["model"]) if x),
        })
        return d

    def preview_url(self, r) -> str:
        if r["kind"] == "video":
            return file_url(r["thumb"])
        if Path(r["path"]).suffix.lower() in QML_IMAGE_EXT:
            return file_url(r["path"])
        # HEIC etc.: Qt can't show it, make a JPEG once
        out = paths.data_dir() / "previews" / (Path(r["thumb"] or r["key"]).stem + ".jpg")
        if not out.exists():
            try:
                from PIL import Image, ImageOps
                from .. import analyze  # noqa: F401  (registers the HEIF opener)
                out.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(r["path"]) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((2000, 2000))
                    im.save(out, "JPEG", quality=88)
            except Exception:  # noqa: BLE001
                return file_url(r["thumb"])
        return file_url(str(out))

    @Slot(str)
    def openInGoogle(self, key: str) -> None:
        r = self._rows.get(key)
        if r is not None and r["url"]:
            QDesktopServices.openUrl(QUrl(r["url"]))

    @Slot(str)
    def openFile(self, key: str) -> None:
        r = self._rows.get(key)
        if r is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(r["path"]))

    # delete mode
    @Property(bool, notify=deletingChanged)
    def deleting(self):
        return self._deleting

    @Property("QVariantMap", notify=deletingChanged)
    def deleteCurrent(self):
        if not self._deleting or self._qpos >= len(self._queue):
            return {}
        return item_dict(self._rows[self._queue[self._qpos]])

    @Property(str, notify=deletingChanged)
    def deleteProgress(self):
        return f"{min(self._qpos + 1, len(self._queue))} / {len(self._queue)}"

    @Slot()
    def startDeleting(self) -> None:
        """Biggest first, so the space comes back fastest. Items without a
        Google Photos link (no sidecar) can't be opened and are left out."""
        self._queue = [k for k in sorted(self._marks, key=lambda k: -(self._rows[k]["size"] or 0))
                       if self._rows[k]["url"]]
        missing = len(self._marks) - len(self._queue)
        if missing:
            self.message.emit(f"{missing} marked items have no Google Photos link and are skipped")
        self._qpos = 0
        self._deleting = bool(self._queue)
        self.deletingChanged.emit()
        self.deleteOpen()

    @Slot()
    def deleteOpen(self) -> None:
        if self._deleting and self._qpos < len(self._queue):
            self.openInGoogle(self._queue[self._qpos])

    @Slot()
    def deleteDone(self) -> None:
        if not self._deleting:
            return
        key = self._queue[self._qpos]
        self.store.set_deleted([key])
        self._marks.discard(key)
        self._rows[key] = self.store.items("key = ?", (key,))[0]
        self._advance()

    @Slot()
    def deleteSkip(self) -> None:
        if self._deleting:
            self._advance()

    def _advance(self) -> None:
        self._qpos += 1
        if self._qpos >= len(self._queue):
            self.stopDeleting()
            self.message.emit("All done. Empty the trash in Google Photos to get the space back now.")
            return
        self.deletingChanged.emit()
        self._bump()
        self.deleteOpen()

    @Slot()
    def stopDeleting(self) -> None:
        self._deleting = False
        self.deletingChanged.emit()
        self.reload()

    @Slot(result=str)
    def exportLinks(self) -> str:
        out = paths.data_dir() / "marked-links.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = [self._rows[k] for k in self._marks]
        out.write_text("\n".join(r["url"] for r in rows if r["url"]) + "\n", encoding="utf-8")
        self.message.emit(f"Saved {len(rows)} links to {out}")
        return str(out)


def run_app(argv=None) -> int:
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    app = QGuiApplication(argv or sys.argv)
    app.setApplicationName("Photoroom")
    app.setDesktopFileName("photoroom")
    QQuickStyle.setStyle("Basic")
    backend = Backend(Store())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("app", backend)
    engine.rootContext().setContextProperty("theme", THEME)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    return app.exec()
