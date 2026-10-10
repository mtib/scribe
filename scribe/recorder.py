"""Capture mic and/or system audio with one pw-record process per source."""
import json
import shutil
import signal
import struct
import subprocess
import time
from pathlib import Path

from . import paths

WAV_HEADER = 44


class Recorder:
    def __init__(self, sources, rec_id):
        self.sources = list(sources)  # subset of {"mic", "system"}
        self.id = rec_id
        self.dir = paths.TMP_DIR / rec_id
        self.procs = {}
        self.started = 0.0

    def path(self, src):
        return self.dir / f"{src}.wav"

    def start(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "meta.json").write_text(json.dumps({"sources": self.sources, "started": time.time()}))
        for src in self.sources:
            cmd = ["pw-record", "--rate", "48000", "--format", "s16"]
            if src == "mic":
                cmd += ["--channels", "1"]
            else:
                cmd += ["--channels", "2", "-P", "{ stream.capture.sink=true }", "--target", "@DEFAULT_SINK@"]
            self.procs[src] = subprocess.Popen(cmd + [str(self.path(src))], stderr=subprocess.PIPE)
        self.started = time.time()
        time.sleep(0.3)
        for src, p in self.procs.items():
            if p.poll() is not None:
                err = p.stderr.read().decode(errors="replace").strip()
                self.abort()
                raise RuntimeError(f"{src} capture failed: {err}")

    def level(self, src, window=0.06):
        """Peak 0..1 of the last `window` seconds of a growing WAV (header-aligned)."""
        p = self.path(src)
        ch = 1 if src == "mic" else 2
        frame = 2 * ch
        try:
            size = p.stat().st_size
            n = int(48000 * window) * frame
            if size - WAV_HEADER < n:
                return 0.0
            start = WAV_HEADER + ((size - WAV_HEADER - n) // frame) * frame
            with open(p, "rb") as f:
                f.seek(start)
                raw = f.read(n)
        except OSError:
            return 0.0
        cnt = len(raw) // 2
        samples = struct.unpack(f"<{cnt}h", raw[: cnt * 2])
        return min(1.0, max((abs(s) for s in samples), default=0) / 32768)

    def elapsed(self):
        return time.time() - self.started

    def stop(self):
        """Stop capture; returns (duration, {src: wav_path}) for sources that have audio."""
        dur = self.elapsed()
        for p in self.procs.values():
            p.send_signal(signal.SIGINT)
        for p in self.procs.values():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        return dur, {s: self.path(s) for s in self.sources if self.path(s).exists() and self.path(s).stat().st_size > WAV_HEADER}

    def abort(self):
        for p in self.procs.values():
            p.kill()
        shutil.rmtree(self.dir, ignore_errors=True)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def orphans():
    """Temp recording dirs left behind by a crash."""
    if not paths.TMP_DIR.is_dir():
        return []
    return sorted(d for d in paths.TMP_DIR.iterdir() if (d / "meta.json").exists())


def wav_duration(path):
    return max(0.0, (Path(path).stat().st_size - WAV_HEADER) / (48000 * 2 * (1 if Path(path).name.startswith("mic") else 2)))
