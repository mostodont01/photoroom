"""Per-item analysis: size, camera, perceptual hash, sharpness, brightness,
thumbnail; video duration + poster frame. Runs in parallel worker processes."""

import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import paths
from .store import Store

THUMB = 320
_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass


def dhash(gray_img) -> int:
    """64-bit difference hash (signed, to fit SQLite INTEGER)."""
    from PIL import Image
    small = gray_img.resize((9, 8), Image.Resampling.LANCZOS)
    px = small.tobytes()  # 'L' mode: one byte per pixel
    h = 0
    for row in range(8):
        for col in range(8):
            h = (h << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return h - (1 << 64) if h >= (1 << 63) else h


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


def sharpness(gray_img) -> float:
    """Variance of the Laplacian on a 512 px version: low = blurry."""
    import numpy as np
    g = gray_img.copy()
    g.thumbnail((512, 512))
    a = np.asarray(g, dtype=np.float32)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:])
    return float(lap.var())


def thumb_path(key: str) -> Path:
    import hashlib
    h = hashlib.sha1(key.encode()).hexdigest()
    return paths.thumbs() / h[:2] / f"{h}.jpg"


def analyze_image(path: str, key: str) -> dict:
    from PIL import Image, ImageOps, ImageStat
    with Image.open(path) as im:
        exif = im.getexif()
        make = str(exif.get(0x010F, "") or "").strip("\x00 ")
        model = str(exif.get(0x0110, "") or "").strip("\x00 ")
        w, h = im.size
        if exif.get(0x0112) in (5, 6, 7, 8):  # rotated 90°
            w, h = h, w
        im.draft("RGB", (1024, 1024))  # fast JPEG decode at reduced size
        rgb = ImageOps.exif_transpose(im).convert("RGB")
    gray = rgb.convert("L")
    t = thumb_path(key)
    t.parent.mkdir(parents=True, exist_ok=True)
    small = rgb.copy()
    small.thumbnail((THUMB, THUMB))
    small.save(t, "JPEG", quality=80)
    return {"width": w, "height": h, "make": make, "model": model, "phash": dhash(gray),
            "blur": sharpness(gray), "bright": ImageStat.Stat(gray).mean[0], "thumb": str(t)}


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def analyze_video(path: str, key: str) -> dict:
    t = thumb_path(key)
    t.parent.mkdir(parents=True, exist_ok=True)
    info = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = _DURATION.search(info)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    dims = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    seek = "1" if (duration or 0) > 2 else "0"
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", seek, "-i", path,
                    "-frames:v", "1", "-vf", f"scale={THUMB}:-2", str(t)], capture_output=True)
    return {"duration": duration, "width": int(dims.group(1)) if dims else None,
            "height": int(dims.group(2)) if dims else None,
            "thumb": str(t) if t.exists() else None}


def analyze_one(key: str, path: str, kind: str) -> tuple[str, dict]:
    try:
        return key, (analyze_video if kind == "video" else analyze_image)(path, key)
    except Exception as e:  # noqa: BLE001 - a broken file must not stop the run
        return key, {"error": f"{type(e).__name__}: {e}"[:300]}


def run(store: Store, workers: int | None = None, log=print) -> int:
    todo = store.items("analyzed = 0")
    if not todo:
        return 0
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    log(f"analysing {len(todo)} items with {workers} workers")
    done = 0
    if workers == 1:
        results = (analyze_one(r["key"], r["path"], r["kind"]) for r in todo)
        for key, values in results:
            store.update_analysis(key, values)
            done += 1
    else:
        with ProcessPoolExecutor(workers) as pool:
            futs = [pool.submit(analyze_one, r["key"], r["path"], r["kind"]) for r in todo]
            for f in as_completed(futs):
                key, values = f.result()
                store.update_analysis(key, values)
                done += 1
                if done % 500 == 0:
                    store.db.commit()
                    log(f"  {done}/{len(todo)}")
    store.db.commit()
    return done
