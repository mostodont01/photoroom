"""Add Photoroom to the Linux app menu (current user): `photoroom install-desktop [--uninstall]`."""

import os
import shutil
import sys
from pathlib import Path

from . import APP_ID

ICON = Path(__file__).parent / "app" / "assets" / "photoroom.svg"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_file() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def desktop_entry(python: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Photoroom
GenericName=Photo cleanup
Comment=Find duplicates, screenshots, blurry photos and big videos in your Google Photos
Exec="{python}" -m photoroom app
Icon={APP_ID}
Terminal=false
Categories=Graphics;Utility;
Keywords=google;photos;duplicates;cleanup;storage;
"""


def install(uninstall: bool = False) -> str:
    if uninstall:
        for f in (desktop_file(), icon_file()):
            f.unlink(missing_ok=True)
        return "removed"
    desktop_file().parent.mkdir(parents=True, exist_ok=True)
    icon_file().parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON, icon_file())
    desktop_file().write_text(desktop_entry(sys.executable), encoding="utf-8")
    return str(desktop_file())
