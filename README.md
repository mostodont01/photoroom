# photoroom

Clean up Google Photos without sorting by hand. Google's Photos API can't list or delete your
library, so photoroom works from a **Google Takeout** export (which doubles as a full local backup):

1. **Import:** unpacks the Takeout zips into `~/Pictures/Google Photos backup` and indexes them.
   Album copies, edited versions and motion-photo videos are merged into one item per Google Photos
   item, keyed by its photos.google.com link (from Takeout's JSON sidecars).
2. **Analyse** (local, parallel): perceptual hash, sharpness, brightness, thumbnails, video length.
3. **Review** in the app (PySide6 + QML):
   - **Duplicates:** the same picture uploaded more than once. The best copy is kept.
   - **Similar shots:** bursts taken within minutes. The sharpest is kept.
   - **Screenshots**, **Chats & downloads** (WhatsApp, Messenger, memes...), **Blurry**, **Dark**,
     **Videos** (biggest first).
   - Click to mark, right-click to preview. Favourites are never suggested.
4. **Delete:** delete mode opens each marked item on photos.google.com (biggest first); you move it
   to the trash there and press Enter for the next one.

Nothing is uploaded anywhere; all analysis runs on your computer.

## Usage

```bash
uv tool install -e .
photoroom import            # ~/Downloads/takeout-*.zip, or give paths (zips or unpacked folders)
photoroom analyze
photoroom report
photoroom app               # or: photoroom install-desktop, then "Photoroom" in the app menu
```

## Development

```bash
QT_QPA_PLATFORM=offscreen uv run pytest
```
