"""Small persisted UI preferences (DATA_DIR/settings.json)."""
import json
import os

from . import paths


def _path():
    return paths.DATA_DIR / "settings.json"


def load():
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    return load().get(key, default)


def put(key, value):
    data = load()
    data[key] = value
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, _path())
