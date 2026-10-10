"""Background transcription jobs with pollable progress (no GTK)."""
import threading

from . import transcribe


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

        def progress(frac, label):
            with self._lock:
                self.state[rec.id] = {"frac": frac, "label": label}

        def work():
            try:
                transcribe.run(rec, progress, num_speakers)
            except Exception:
                pass  # recorded in rec.meta["error"] by transcribe.run
            finally:
                with self._lock:
                    self.state.pop(rec.id, None)
                if on_done:
                    on_done(rec)

        threading.Thread(target=work, daemon=True).start()
