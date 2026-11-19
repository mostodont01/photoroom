"""Clean up Google Photos from a Takeout export: find duplicates, similar shots,
screenshots, chat images, blurry / dark photos and big videos; review; delete."""

APP_ID = "photoroom"


def main() -> None:
    import sys

    from .cli import main as cli_main
    sys.exit(cli_main())
