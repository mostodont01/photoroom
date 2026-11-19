import json
import random
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

T0 = 1_700_000_000


def scene(seed: int, size=(800, 600)) -> Image.Image:
    """A sharp, distinct picture: random shapes on a random background."""
    rnd = random.Random(seed)
    im = Image.new("RGB", size, tuple(rnd.randrange(256) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        w, h = rnd.randrange(20, 250), rnd.randrange(20, 250)
        fill = tuple(rnd.randrange(256) for _ in range(3))
        (d.rectangle if rnd.random() < 0.5 else d.ellipse)([x, y, x + w, y + h], fill=fill)
    return im


def sidecar(path: Path, title: str, url: str, taken: int, folder: str = "Camera",
            favorited: bool = False, name: str | None = None) -> None:
    data = {"title": title, "url": url, "photoTakenTime": {"timestamp": str(taken)},
            "creationTime": {"timestamp": str(taken + 5)},
            "googlePhotosOrigin": {"mobileUpload": {"deviceFolder": {"localFolderName": folder},
                                                    "deviceType": "ANDROID_PHONE"}}}
    if favorited:
        data["favorited"] = True
    (path.parent / (name or f"{path.name}.supplemental-metadata.json")).write_text(json.dumps(data))


@pytest.fixture
def takeout(tmp_path) -> Path:
    """A small Takeout tree covering the cases the reader must handle."""
    root = tmp_path / "export" / "Takeout" / "Google Photos"
    year = root / "Photos from 2024"
    album = root / "Holiday"
    year.mkdir(parents=True)
    album.mkdir()

    def photo(folder, name, img, title=None, url=None, taken=T0, dev="Camera", **kw):
        p = folder / name
        img.save(p, "JPEG" if p.suffix.lower() in (".jpg", ".jpeg") else "PNG", quality=92)
        if url is not False:
            sidecar(p, title or name, url or f"https://photos.google.com/photo/{name}", taken, dev, **kw)
        return p

    # three distinct sharp photos, one also in an album (same URL)
    photo(year, "IMG_001.jpg", scene(1), taken=T0)
    photo(year, "IMG_002.jpg", scene(2), taken=T0 + 86400)
    photo(year, "IMG_003.jpg", scene(3), taken=T0 + 2 * 86400)
    photo(album, "IMG_001.jpg", scene(1), url="https://photos.google.com/photo/IMG_001.jpg", taken=T0)
    # an edited version sharing the original's sidecar
    scene(1).rotate(1).save(year / "IMG_001-edited.jpg", quality=90)
    # a burst: 3 near-identical shots seconds apart, the middle one sharpest
    base = scene(10)
    photo(year, "BURST_1.jpg", base.filter(ImageFilter.GaussianBlur(1.2)), taken=T0 + 3 * 86400)
    photo(year, "BURST_2.jpg", base, taken=T0 + 3 * 86400 + 2)
    photo(year, "BURST_3.jpg", base.filter(ImageFilter.GaussianBlur(1.5)), taken=T0 + 3 * 86400 + 4)
    # the same picture uploaded twice, a year apart (one favourite: that one is kept)
    photo(year, "DUP_a.jpg", scene(20), taken=T0 + 10 * 86400)
    photo(year, "DUP_b.jpg", scene(20), taken=T0 + 400 * 86400, favorited=True)
    # a copy with a counter: IMG_002(1).jpg <-> IMG_002.jpg.supplemental-metadata(1).json
    p = year / "IMG_002(1).jpg"
    scene(30).save(p, quality=90)
    sidecar(p, "IMG_002.jpg", "https://photos.google.com/photo/IMG_002-copy", T0 + 20 * 86400,
            name="IMG_002.jpg.supplemental-metadata(1).json")
    # a long, truncated file name with a truncated sidecar name
    long_title = "PXL_20240101_123456789_with_a_really_long_descriptive_name.jpg"
    p = year / (long_title[:47] + ".jpg")
    scene(40).save(p, quality=90)
    sidecar(p, long_title, "https://photos.google.com/photo/long", T0 + 30 * 86400,
            name=long_title[:40] + ".supplemental-met.json")
    # screenshot, WhatsApp image, blurry and dark photos
    photo(year, "Screenshot_20240101-101010.png", scene(50, (540, 1200)), dev="Screenshots",
          taken=T0 + 40 * 86400)
    photo(year, "IMG-20240101-WA0001.jpg", scene(60), dev="WhatsApp Images", taken=T0 + 50 * 86400)
    photo(year, "BLURRY.jpg", scene(70).filter(ImageFilter.GaussianBlur(12)), taken=T0 + 60 * 86400)
    photo(year, "DARK.jpg", Image.new("RGB", (800, 600), (6, 5, 8)), taken=T0 + 70 * 86400)
    # a file without any sidecar (keyed by its hash)
    photo(year, "NOSIDECAR.jpg", scene(80), url=False)
    # a video
    import imageio_ffmpeg
    v = year / "VID_001.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=320x240:rate=10", "-pix_fmt", "yuv420p", str(v)], check=True)
    sidecar(v, "VID_001.mp4", "https://photos.google.com/photo/VID_001", T0 + 80 * 86400)
    # album metadata (not a photo sidecar)
    (album / "metadata.json").write_text(json.dumps({"title": "Holiday", "date": {"timestamp": "1"}}))
    return tmp_path / "export"


@pytest.fixture
def takeout_zip(takeout, tmp_path) -> Path:
    z = tmp_path / "takeout-20261119T000000Z-001.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in takeout.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(takeout))
    return z


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOROOM_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PHOTOROOM_LIBRARY", str(tmp_path / "library"))
    return tmp_path
