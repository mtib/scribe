"""Recording library: one <id>.opus + <id>.json per recording in RECORDINGS_DIR."""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


@dataclass
class Recording:
    id: str
    dir: Path
    meta: dict = field(default_factory=dict)

    @property
    def audio(self): return self.dir / f"{self.id}.opus"
    @property
    def tracks(self): return self.dir / f"{self.id}.tracks.opus"
    @property
    def json_path(self): return self.dir / f"{self.id}.json"
    @property
    def title(self): return (self.meta.get("title") or "").strip()
    @property
    def date_label(self):
        return time.strftime("%Y-%m-%d %H:%M", time.strptime(self.id, "%Y-%m-%d_%H%M%S"))

    @property
    def display_title(self):
        """User-set name, else the start of the transcript, else the date."""
        if self.title:
            return self.title
        segs = self.meta.get("segments") or []
        if segs:
            text = segs[0]["text"].strip()
            return text if len(text) <= 60 else text[:59].rstrip() + "…"
        return self.date_label

    def rename(self, name):
        self.update(title=name.strip())
    @property
    def status(self): return self.meta.get("status", "recorded")
    @property
    def duration(self): return float(self.meta.get("duration", 0))

    def save(self):
        tmp = self.json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False))
        os.replace(tmp, self.json_path)
        _cache.pop(self.json_path, None)

    def update(self, **kw):
        self.meta.update(kw)
        self.save()

    def search_text(self):
        return (self.display_title + " " + " ".join(s["text"] for s in self.meta.get("segments", []))).lower()


def new_id(now=None):
    return time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now))


def create(rec_id, sources, duration, title="", directory=None):
    d = Path(directory or paths.RECORDINGS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    rec = Recording(rec_id, d, {"title": title.strip(), "duration": duration, "sources": sources, "status": "recorded"})
    rec.save()
    return rec


_cache = {}  # json path -> (mtime_ns, size, Recording): the UI polls often, transcripts can be large


def _load_path(jp, d):
    try:
        st = jp.stat()
        hit = _cache.get(jp)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        rec = Recording(jp.stem, d, json.loads(jp.read_text()))
    except (OSError, json.JSONDecodeError):
        return None
    _cache[jp] = (st.st_mtime_ns, st.st_size, rec)
    return rec


def load(directory, rec_id):
    """One recording by id, or None."""
    d = Path(directory)
    return _load_path(d / f"{rec_id}.json", d)


def load_all(directory=None):
    d = Path(directory or paths.RECORDINGS_DIR)
    if not d.is_dir():
        return []
    out = [r for r in (_load_path(jp, d) for jp in d.glob("*.json")) if r]
    out.sort(key=lambda r: r.id, reverse=True)
    return out


def delete(rec):
    _cache.pop(rec.json_path, None)
    for p in (rec.audio, rec.tracks, rec.json_path):
        p.unlink(missing_ok=True)
