"""Background transcription jobs with pollable progress (no GTK).

Each job is a separate worker process (scribe.worker), not a thread: the pipeline has
Python-level loops and C calls that would otherwise starve the UI of the GIL, which made
the window stall (and the compositor call it "not responding") on long recordings."""
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading


def _child_setup():
    os.nice(10)  # keep the UI responsive when the worker saturates the cores
    try:  # Linux: die with the app instead of lingering as an orphan
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


class Jobs:
    def __init__(self):
        self.state = {}  # rec id -> {"frac": float, "label": str}
        self._lock = threading.Lock()

    def active(self, rec_id=None):
        with self._lock:
            return bool(self.state) if rec_id is None else rec_id in self.state

    def progress(self, rec_id):
        with self._lock:
            return dict(self.state.get(rec_id) or {})

    def start(self, rec, num_speakers=None, on_done=None):
        if self.active(rec.id):
            return
        with self._lock:
            self.state[rec.id] = {"frac": 0.0, "label": "starting"}
        cmd = [sys.executable, "-m", "scribe.worker", str(rec.dir), rec.id, str(num_speakers or "")]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, preexec_fn=_child_setup)
        threading.Thread(target=self._watch, args=(rec, proc, on_done), daemon=True).start()

    def _watch(self, rec, proc, on_done):
        """Mostly blocked reading the pipe (releases the GIL); relays progress."""
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "f" in msg:
                with self._lock:
                    self.state[rec.id] = {"frac": msg["f"], "label": msg["l"]}
        code = proc.wait()
        if code not in (0, 1, 2):  # crashed / killed: the worker could not record the failure itself
            rec.update(status="failed", error=f"transcription process stopped unexpectedly (exit {code})")
        with self._lock:
            self.state.pop(rec.id, None)
        if on_done:
            on_done(rec)


def encode_recording(tmp_dir, rec_id, title, seconds, sources):
    """Mix and encode a finished recording in a worker process (blocking; call off the UI thread).
    Returns the registered Recording; raises RuntimeError with the worker's error on failure."""
    from . import library, paths

    cmd = [sys.executable, "-m", "scribe.worker", "encode", str(tmp_dir), rec_id, title, str(seconds), ",".join(sources)]
    r = subprocess.run(cmd, capture_output=True, text=True, preexec_fn=_child_setup)
    if r.returncode != 0:
        raise RuntimeError("saving failed: " + (r.stderr.strip().splitlines() or ["worker exited"])[-1])
    return library.load(paths.RECORDINGS_DIR, rec_id)
