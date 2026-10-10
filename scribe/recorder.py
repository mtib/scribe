"""Capture mic and/or system audio with one pw-record process per source."""
import atexit
import json
import threading
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
            cmd = capture_cmd(src, 48000, self.path(src))
            self.procs[src] = subprocess.Popen(cmd, stderr=subprocess.PIPE)
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


def capture_cmd(src, rate, out, channels=None):
    """pw-record command for a source ('mic' or the default sink's monitor)."""
    ch = channels or (1 if src == "mic" else 2)
    cmd = ["pw-record", "--rate", str(rate), "--format", "s16", "--channels", str(ch)]
    if src == "system":
        cmd += ["-P", "{ stream.capture.sink=true }", "--target", "@DEFAULT_SINK@"]
    return cmd + [str(out)]


class Monitor:
    """Level-only capture so meters move before recording starts (nothing is stored)."""

    CHUNK = 1600  # samples @16 kHz = 100 ms

    def __init__(self):
        self.procs = {}
        self.levels = {}
        atexit.register(self.stop)

    def start(self, sources):
        self.stop()
        for src in sources:
            try:
                p = subprocess.Popen(capture_cmd(src, 16000, "-", channels=1), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                continue
            self.procs[src] = p
            self.levels[src] = 0.0
            threading.Thread(target=self._read, args=(src, p), daemon=True).start()

    def _read(self, src, proc):
        import numpy as np
        out = proc.stdout
        out.read(WAV_HEADER)
        while True:
            raw = out.read(self.CHUNK * 2)
            if len(raw) < self.CHUNK * 2:
                break
            a = np.frombuffer(raw, dtype=np.int16)
            self.levels[src] = float(np.abs(a).max()) / 32768
        self.levels[src] = 0.0

    def level(self, src):
        return self.levels.get(src, 0.0)

    def stop(self):
        procs, self.procs = self.procs, {}
        for p in procs.values():
            p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
        self.levels = {}


def orphans():
    """Temp recording dirs left behind by a crash."""
    if not paths.TMP_DIR.is_dir():
        return []
    return sorted(d for d in paths.TMP_DIR.iterdir() if (d / "meta.json").exists())


def wav_duration(path):
    return max(0.0, (Path(path).stat().st_size - WAV_HEADER) / (48000 * 2 * (1 if Path(path).name.startswith("mic") else 2)))
