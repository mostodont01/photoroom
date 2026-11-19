import zipfile

import pytest

from photoroom import analyze, groups
from photoroom import takeout as tk
from photoroom.cli import main
from photoroom.store import Store


def index(env, takeout_dir) -> Store:
    store = Store()
    store.add_files(list(tk.scan(takeout_dir)), log=lambda *_: None)
    return store


def by_title(store):
    return {r["title"]: r for r in store.items()}


def test_split_counter_and_edited():
    assert tk.split_counter("IMG_1(2).jpg") == ("IMG_1.jpg", 2)
    assert tk.split_counter("IMG_1.jpg") == ("IMG_1.jpg", 0)
    assert tk.strip_edited("IMG_1-edited.jpg") == ("IMG_1.jpg", True)
    assert tk.strip_edited("IMG_1.jpg") == ("IMG_1.jpg", False)


def test_scan_matches_sidecars(takeout):
    files = {f"{f.folder}/{f.path.name}": f for f in tk.scan(takeout)}
    assert files["Photos from 2024/IMG_001.jpg"].sidecar.url.endswith("IMG_001.jpg")
    assert files["Holiday/IMG_001.jpg"].sidecar.url.endswith("IMG_001.jpg")
    edited = files["Photos from 2024/IMG_001-edited.jpg"]
    assert edited.role == "edited" and edited.sidecar.title == "IMG_001.jpg"
    assert files["Photos from 2024/IMG_002(1).jpg"].sidecar.url.endswith("IMG_002-copy")
    long = [f for k, f in files.items() if k.startswith("Photos from 2024/PXL_")][0]
    assert long.sidecar and long.sidecar.url.endswith("/long")
    assert files["Photos from 2024/NOSIDECAR.jpg"].sidecar is None
    assert files["Photos from 2024/VID_001.mp4"].kind == "video"
    assert files["Photos from 2024/Screenshot_20240101-101010.png"].sidecar.device_folder == "Screenshots"


def test_index_merges_album_copies_and_edits(env, takeout):
    store = index(env, takeout)
    rows = store.items()
    urls = [r["key"] for r in rows]
    assert len(urls) == len(set(urls))
    img1 = [r for r in rows if r["key"].endswith("/IMG_001.jpg")]
    assert len(img1) == 1 and img1[0]["path"].endswith("IMG_001.jpg")  # original, not the edit
    assert store.db.execute("SELECT COUNT(*) FROM files WHERE key = ?", (img1[0]["key"],)).fetchone()[0] == 3
    assert any(r["key"].startswith("sha1:") for r in rows)
    # re-importing changes nothing
    new, n = store.add_files(list(tk.scan(takeout)), log=lambda *_: None)
    assert (new, n) == (0, 0)


def test_extract_skips_existing_and_stays_inside(takeout_zip, tmp_path):
    dest = tmp_path / "lib"
    with zipfile.ZipFile(takeout_zip, "a") as zf:
        zf.writestr("../evil.txt", "nope")
    tk.extract([takeout_zip], dest, log=lambda *_: None)
    assert (dest / "Takeout/Google Photos/Photos from 2024/IMG_001.jpg").exists()
    assert not (tmp_path / "evil.txt").exists()
    tk.extract([takeout_zip], dest, log=lambda *_: None)  # second run: nothing to do


def test_dhash_and_hamming():
    from conftest import scene
    from PIL import ImageFilter
    a = analyze.dhash(scene(1).convert("L"))
    b = analyze.dhash(scene(1).filter(ImageFilter.GaussianBlur(1)).convert("L"))
    c = analyze.dhash(scene(2).convert("L"))
    assert analyze.hamming(a, a) == 0
    assert analyze.hamming(a, b) <= groups.SIMILAR_MAX_DIST
    assert analyze.hamming(a, c) > 16
    assert -(1 << 63) <= a < (1 << 63)


@pytest.fixture
def analysed(env, takeout):
    store = index(env, takeout)
    assert analyze.run(store, workers=1, log=lambda *_: None) == store.count()
    return store


def test_analysis_values(analysed):
    t = by_title(analysed)
    assert t["BLURRY.jpg"]["blur"] < groups.BLURRY_MAX < t["IMG_003.jpg"]["blur"]
    assert t["DARK.jpg"]["bright"] < groups.DARK_MAX
    assert t["IMG_003.jpg"]["width"] == 800
    v = t["VID_001.mp4"]
    assert 2.5 < v["duration"] < 3.5 and v["width"] == 320
    assert all(r["thumb"] for r in analysed.items())
    assert analyze.run(analysed, workers=1, log=lambda *_: None) == 0  # resumable


def test_analysis_survives_broken_file(env, tmp_path):
    store = Store()
    folder = tmp_path / "broken" / "Photos from 2024"
    folder.mkdir(parents=True)
    (folder / "bad.jpg").write_bytes(b"not a jpeg")
    store.add_files(list(tk.scan(tmp_path / "broken")), log=lambda *_: None)
    analyze.run(store, workers=1, log=lambda *_: None)
    assert store.items()[0]["error"]


def test_groups_and_lists(analysed):
    rows = analysed.items()
    gs = groups.groups(rows)
    dup = [g for g in gs["duplicates"] if any(r["title"] == "DUP_a.jpg" for r in g.items)]
    assert len(dup) == 1
    keep = [r for r in dup[0].items if r["key"] == dup[0].keep][0]
    assert keep["title"] == "DUP_b.jpg"  # the favourite
    burst = [g for g in gs["similar"] if any(r["title"] == "BURST_2.jpg" for r in g.items)]
    assert len(burst) == 1 and len(burst[0].items) == 3
    assert [r["title"] for r in burst[0].items if r["key"] == burst[0].keep] == ["BURST_2.jpg"]
    # distinct photos are not grouped
    grouped = {r["title"] for k in gs.values() for g in k for r in g.items}
    assert not grouped & {"IMG_001.jpg", "IMG_002.jpg", "IMG_003.jpg"}

    ls = groups.lists(rows)
    titles = {k: [r["title"] for r in v] for k, v in ls.items()}
    assert titles["screenshots"] == ["Screenshot_20240101-101010.png"]
    assert titles["chats"] == ["IMG-20240101-WA0001.jpg"]
    assert "BLURRY.jpg" in titles["blurry"] and "IMG_003.jpg" not in titles["blurry"]
    assert titles["dark"] == ["DARK.jpg"]
    assert titles["videos"] == ["VID_001.mp4"]

    marks = groups.suggested_marks(gs)
    t = by_title(analysed)
    assert t["DUP_a.jpg"]["key"] in marks and t["DUP_b.jpg"]["key"] not in marks
    assert t["BURST_1.jpg"]["key"] in marks and t["BURST_2.jpg"]["key"] not in marks


def test_cli_end_to_end(env, takeout_zip, capsys):
    assert main(["import", str(takeout_zip)]) == 0
    out = capsys.readouterr().out
    assert "matched to Google Photos links" in out
    assert (env / "library/Takeout/Google Photos/Holiday/IMG_001.jpg").exists()
    assert main(["analyze", "-j", "2"]) == 0
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "Similar shots" in out and "Screenshots" in out
    assert main(["suggest"]) == 0
    assert main(["marked", "-o", str(env / "links.txt")]) == 0
    links = (env / "links.txt").read_text().split()
    assert "https://photos.google.com/photo/BURST_1.jpg" in links
    assert "https://photos.google.com/photo/BURST_2.jpg" not in links


def test_install_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert main(["install-desktop"]) == 0
    entry = (tmp_path / "applications/photoroom.desktop").read_text()
    assert "-m photoroom app" in entry
    assert (tmp_path / "icons/hicolor/scalable/apps/photoroom.svg").exists()
    assert main(["install-desktop", "--uninstall"]) == 0
    assert not (tmp_path / "applications/photoroom.desktop").exists()
