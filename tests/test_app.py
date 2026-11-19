from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQml")

from PySide6.QtCore import QtMsgType, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401  (rootObjects come back as QQuickWindow)
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from photoroom import analyze  # noqa: E402
from photoroom import takeout as tk  # noqa: E402
from photoroom.app.backend import THEME, Backend  # noqa: E402
from photoroom.store import Store  # noqa: E402


@pytest.fixture
def backend(env, takeout, qapp):
    store = Store()
    store.add_files(list(tk.scan(takeout)), log=lambda *_: None)
    analyze.run(store, workers=1, log=lambda *_: None)
    return Backend(store)


def test_backend_categories_marks(backend):
    cats = {c["id"]: c for c in backend.categories}
    assert cats["similar"]["count"] == 1 and cats["duplicates"]["count"] == 1
    assert cats["screenshots"]["count"] == 1
    backend.select("similar")
    assert backend.isGroups and backend.model.rowCount() == 1
    group = backend.model.row(0)
    assert len(group["items"]) == 3 and sum(i["keep"] for i in group["items"]) == 1
    backend.markSuggested()
    assert backend.markedCount == 2
    backend.select("screenshots")
    key = backend.model.row(0)["key"]
    backend.toggle(key)
    assert backend.isMarked(key) and backend.markedCount == 3
    backend.select("marked")
    assert backend.model.rowCount() == 3
    backend.unmarkAll()
    assert backend.markedCount == 0 and backend.model.rowCount() == 0
    # marks are saved
    backend.select("screenshots")
    backend.toggle(key)
    assert Backend(backend.store).markedCount == 1


def test_backend_details_and_links(backend, env):
    backend.select("videos")
    key = backend.model.row(0)["key"]
    d = backend.details(key)
    assert d["url"].startswith("https://photos.google.com/") and d["image"].startswith("file://")
    backend.toggle(key)
    out = Path(backend.exportLinks())
    assert d["url"] in out.read_text()


def test_qml_loads_without_errors(backend):
    errors = []

    def handler(mode, ctx, msg):
        if mode != QtMsgType.QtDebugMsg:
            errors.append(msg)
    old = qInstallMessageHandler(handler)
    try:
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("app", backend)
        engine.rootContext().setContextProperty("theme", THEME)
        qml = Path(__file__).parents[1] / "src/photoroom/app/qml/Main.qml"
        engine.load(QUrl.fromLocalFile(str(qml)))
        assert engine.rootObjects(), errors
        for cat in ("similar", "duplicates", "screenshots", "videos", "marked"):
            backend.select(cat)
        backend.showPreview(backend.model.row(0).get("key", "") if backend.model.rowCount() else "")
        backend.select("videos")
        backend.showPreview(backend.model.row(0)["key"])
        backend.showPreview("")
    finally:
        qInstallMessageHandler(old)
    assert not errors, errors


def test_screenshots(backend, qtbot, tmp_path):
    """Renders the app; with PHOTOROOM_SHOTS=dir the images are kept for a look."""
    import os
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("app", backend)
    engine.rootContext().setContextProperty("theme", THEME)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "src/photoroom/app/qml/Main.qml")))
    win = engine.rootObjects()[0]
    out = Path(os.environ.get("PHOTOROOM_SHOTS") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    backend.select("similar")
    backend.markSuggested()
    for cat in ("similar", "blurry", "marked"):
        backend.select(cat)
        qtbot.wait(400)
        img = win.grabWindow()
        assert not img.isNull()
        img.save(str(out / f"{cat}.png"))
    backend.select("videos")
    backend.showPreview(backend.model.row(0)["key"])
    qtbot.wait(400)
    win.grabWindow().save(str(out / "preview.png"))
    win.close()
    win.deleteLater()
    del engine
    qtbot.wait(50)


def test_delete_mode(backend, monkeypatch):
    opened = []
    monkeypatch.setattr(backend, "openInGoogle", lambda key: opened.append(key))
    backend.select("similar")
    backend.markSuggested()
    backend.select("screenshots")
    backend.toggle(backend.model.row(0)["key"])
    assert backend.markedCount == 3
    backend.startDeleting()
    assert backend.deleting and backend.deleteProgress == "1 / 3" and len(opened) == 1
    first = opened[0]
    backend.deleteDone()       # deleted
    backend.deleteSkip()       # skipped: stays marked
    assert backend.deleteProgress == "3 / 3" and len(opened) == 3
    backend.deleteDone()
    assert not backend.deleting
    assert backend.markedCount == 1
    rows = {r["key"]: r for r in backend.store.items()}
    assert rows[first]["deleted"] == 1 and rows[first]["mark"] == 1
    # deleted items leave the lists
    assert all(backend.model.row(i)["key"] != first for i in range(backend.model.rowCount()))
