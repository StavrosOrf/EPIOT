"""Install the mod_spatialite SQLite extension on Windows.

Linux and macOS ship mod_spatialite through their package managers
(``libsqlite3-mod-spatialite``, ``brew install libspatialite``), so the loader
finds it on the default search path and this script is not needed there.
Windows has no such package: the gaia-gis project publishes a prebuilt bundle
instead, as a .7z archive. This unpacks that bundle into ./.spatialite, which
is where backend.spatialite looks for it.

Usage:
    uv run python scripts/install_spatialite.py [--force]
"""

import argparse
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import py7zr

BUNDLE_URL = (
    "https://www.gaia-gis.it/gaia-sins/windows-bin-amd64/"
    "mod_spatialite-5.1.0-win-amd64.7z"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / ".spatialite"
LIBRARY_NAME = "mod_spatialite.dll"


def download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    # The site rejects the default urllib User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length", 0))
        read = 0
        with open(dest, "wb") as ouf:
            while chunk := response.read(1 << 16):
                ouf.write(chunk)
                read += len(chunk)
                if total:
                    print(f"\r  {read * 100 // total}%", end="", flush=True)
    print("\r  done")


def extract(archive: Path, workdir: Path) -> Path:
    """Unpack the archive and return the directory holding the DLLs.

    The bundle wraps everything in a single versioned top-level directory, so
    return that rather than the extraction root.
    """
    with py7zr.SevenZipFile(archive, "r") as sevenzip:
        sevenzip.extractall(workdir)

    if (workdir / LIBRARY_NAME).exists():
        return workdir

    for candidate in workdir.iterdir():
        if candidate.is_dir() and (candidate / LIBRARY_NAME).exists():
            return candidate

    raise SystemExit(f"{LIBRARY_NAME} not found in {archive.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="reinstall even if .spatialite already exists",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print(
            "This script is Windows-only. On Linux install "
            "libsqlite3-mod-spatialite, on macOS run `brew install libspatialite`."
        )
        return 0

    if (TARGET_DIR / LIBRARY_NAME).exists() and not args.force:
        print(f"Already installed at {TARGET_DIR}. Re-run with --force to replace.")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / "mod_spatialite.7z"
        download(BUNDLE_URL, archive)
        unpacked = extract(archive, tmpdir / "unpacked")

        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        # copytree rather than move: the temp dir may be on another volume.
        shutil.copytree(unpacked, TARGET_DIR)

    print(f"Installed {LIBRARY_NAME} into {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
