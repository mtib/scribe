"""Filesystem locations used by Scribe."""
import os
from pathlib import Path

HOME = Path.home()
RECORDINGS_DIR = Path(os.environ.get("SCRIBE_RECORDINGS_DIR") or HOME / "Recordings" / "Scribe")
DATA_DIR = HOME / ".local" / "share" / "scribe"
TMP_DIR = DATA_DIR / "tmp"
SCRIBE_MODELS_DIR = DATA_DIR / "models"
VOXTYPE_MODEL_DIR = HOME / ".local" / "share" / "voxtype" / "models" / "parakeet-tdt-0.6b-v3-int8"
OMARCHY_THEME_DIR = HOME / ".local" / "state" / "omarchy" / "current" / "theme"
