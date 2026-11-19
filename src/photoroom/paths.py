"""Where photoroom keeps things. Nothing private ever lives in the repo."""

import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("PHOTOROOM_DATA") or Path.home() / ".local/share/photoroom")


def database() -> Path:
    return data_dir() / "photos.db"


def thumbs() -> Path:
    return data_dir() / "thumbs"


def default_library() -> Path:
    """Where Takeout zips are unpacked: also the local backup of the library."""
    return Path(os.environ.get("PHOTOROOM_LIBRARY") or Path.home() / "Pictures/Google Photos backup")
