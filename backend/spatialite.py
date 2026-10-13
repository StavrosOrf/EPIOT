"""Point GeoAlchemy2 at the mod_spatialite SQLite extension.

GeoAlchemy2 reads SPATIALITE_LIBRARY_PATH and passes it straight to sqlite3's
load_extension(), so the value has to be a name the platform loader can
resolve. Linux and macOS package managers put the library on the default
search path, so the bare name is enough. Windows has no such package:
scripts/install_spatialite.py unpacks the official bundle into ./.spatialite,
and that directory must also be on the DLL search path, because
mod_spatialite.dll loads its own dependencies (geos, proj, freexl) from
alongside itself.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = PROJECT_ROOT / ".spatialite"

_DEFAULT_LIBRARY = {
    "linux": "mod_spatialite.so",
    "linux2": "mod_spatialite.so",
    "darwin": "mod_spatialite.dylib",
    "win32": "mod_spatialite",
}


def configure_spatialite() -> str:
    """Set SPATIALITE_LIBRARY_PATH if unset and return the value in effect.

    An existing SPATIALITE_LIBRARY_PATH is always respected, so a system-wide
    or conda-provided install still wins over the bundled copy.
    """
    if sys.platform == "win32" and BUNDLE_DIR.is_dir():
        # Prepend rather than replace: PATH is the search path sqlite3's
        # LoadLibrary call uses for the extension and its dependencies.
        os.environ["PATH"] = f"{BUNDLE_DIR}{os.pathsep}{os.environ.get('PATH', '')}"

    configured = os.environ.get("SPATIALITE_LIBRARY_PATH")
    if configured is not None:
        return configured

    try:
        library = _DEFAULT_LIBRARY[sys.platform]
    except KeyError:
        raise EnvironmentError(
            f"Unsupported platform for mod_spatialite: {sys.platform}"
        ) from None

    os.environ["SPATIALITE_LIBRARY_PATH"] = library
    return library
