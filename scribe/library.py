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


def load_all(directory=None):
    d = Path(directory or paths.RECORDINGS_DIR)
    if not d.is_dir():
        return []
    out = []
    for jp in d.glob("*.json"):
        try:
            out.append(Recording(jp.stem, d, json.loads(jp.read_text())))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda r: r.id, reverse=True)
    return out


def delete(rec):
    for p in (rec.audio, rec.tracks, rec.json_path):
        p.unlink(missing_ok=True)
