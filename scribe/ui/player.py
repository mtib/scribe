"""Playback of a recording. Decodes to a cached WAV so no GStreamer opus plugin is needed."""
import subprocess
from pathlib import Path

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gio, Gst

from .. import paths

Gst.init(None)
CACHE = paths.DATA_DIR / "cache"


class Player:
    def __init__(self, rec_audio):
        self.src = Path(rec_audio)
        self.wav = CACHE / (self.src.stem + ".wav")
        self.pipe = Gst.ElementFactory.make("playbin", None)

    def prepare(self):
        """Blocking; call from a worker thread."""
        if not self.wav.exists():
            CACHE.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(self.src), "-ac", "1", "-ar", "24000", str(self.wav)], check=True)
        self.pipe.set_property("uri", Gio.File.new_for_path(str(self.wav)).get_uri())
        self.pipe.set_state(Gst.State.PAUSED)

    @property
    def playing(self):
        return self.pipe.get_state(0)[1] == Gst.State.PLAYING

    def toggle(self):
        self.pipe.set_state(Gst.State.PAUSED if self.playing else Gst.State.PLAYING)

    def play(self):
        self.pipe.set_state(Gst.State.PLAYING)

    def position(self):
        ok, pos = self.pipe.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else 0.0

    def duration(self):
        ok, d = self.pipe.query_duration(Gst.Format.TIME)
        return d / Gst.SECOND if ok else 0.0

    def seek(self, sec):
        self.pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(sec * Gst.SECOND))

    def close(self):
        self.pipe.set_state(Gst.State.NULL)
