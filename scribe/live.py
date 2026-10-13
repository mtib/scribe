"""Transcribe while recording, so little is left to do after Stop.

A worker process (`python -m scribe.worker live <tmp dir> <sources,csv>`) follows the growing
temp WAVs, cuts each source at pauses exactly like audio.speech_chunks does offline, and
appends every finished stretch to `live.jsonl` as {"src", "a", "b", "words"} (a, b: 16 kHz
sample range, words with absolute times; silence is covered by spans without words).
transcribe.run later recognizes only what these spans don't cover (asr.transcribe(done=...)).

Mic audio of a both-source recording is only transcribed live while the system track is quiet:
otherwise it still has to go through the echo canceller, which needs the whole recording, so
that stretch is left as a hole for the offline pass."""
import json
import time
from pathlib import Path

import numpy as np

from . import asr
from .audio import SR, activity_intervals, frame_db, noise_threshold, speech_chunks
from .recorder import WAV_HEADER

FILE = "live.jsonl"
RATE = 48000  # recorder.capture_cmd records at this rate
DECIM = RATE // SR
TICK = 1.0
MIN_HISTORY = 10.0  # s of audio before the noise floor is trusted
TAIL_QUIET = 2.0  # s of silence kept unprocessed at the end of a silent buffer
ECHO_REACH = 1.0  # s: the echo canceller looks this far back for the delay
SYS_QUIET_DB = -50.0  # same floor aec.drop_echo_residue uses
FRAME = 0.05
MIN_GAP, PAD = 0.7, 0.3  # audio.speech_chunks defaults

_TAPS = 97
_FIR = np.sinc(2 * 7500 / RATE * (np.arange(_TAPS) - _TAPS // 2)) * np.hamming(_TAPS)  # low-pass at 7.5 kHz
_FIR = (_FIR / _FIR.sum()).astype(np.float32)


class Source:
    """A growing 48 kHz s16 WAV, read incrementally into a 16 kHz mono float32 buffer."""

    def __init__(self, name, wav):
        self.name = name
        self.wav = Path(wav)
        self.channels = 1 if name == "mic" else 2
        self.offset = WAV_HEADER  # bytes consumed
        self.carry = np.zeros(_TAPS - 1, np.float32)  # filter state (previous 48 kHz samples)
        self.base = 0  # absolute sample index of buf[0]
        self.buf = np.zeros(0, np.float32)
        self.pos = 0  # absolute sample index up to which this source has been handled
        self.db = np.zeros(0, np.float32)  # frame levels of everything seen (noise floor)
        self._db_rem = np.zeros(0, np.float32)

    @property
    def end(self):
        return self.base + len(self.buf)

    def read(self):
        """Pull newly written audio; returns the number of 16 kHz samples added."""
        frame = 2 * self.channels * DECIM
        try:
            size = self.wav.stat().st_size
            n = (size - self.offset) // frame * frame
            if n <= 0:
                return 0
            with open(self.wav, "rb") as f:
                f.seek(self.offset)
                raw = f.read(n)
        except OSError:
            return 0
        n = len(raw) // frame * frame
        self.offset += n
        x = np.frombuffer(raw[:n], dtype="<i2").astype(np.float32) / 32768
        x = x.reshape(-1, self.channels).mean(axis=1)
        ext = np.concatenate([self.carry, x])
        self.carry = ext[-(_TAPS - 1):]
        y = np.convolve(ext, _FIR, mode="valid")[::DECIM].astype(np.float32)
        self.buf = np.concatenate([self.buf, y])
        hop = int(FRAME * SR)
        rem = np.concatenate([self._db_rem, y])
        k = len(rem) // hop
        if k:
            self.db = np.concatenate([self.db, frame_db(rem[: k * hop])])
        self._db_rem = rem[k * hop:]
        return len(y)

    def threshold(self):
        return noise_threshold(self.db) if len(self.db) * FRAME >= MIN_HISTORY else None

    def window(self, a, b):
        return self.buf[max(0, a - self.base): max(0, b - self.base)]

    def trim(self, keep_from):
        cut = keep_from - self.base
        if cut > 0:
            self.buf = self.buf[cut:]
            self.base = keep_from


def _quiet(src, a, b):
    """True when `src` has no audible frame in samples [a, b)."""
    w = src.window(a, b)
    return len(w) < int(FRAME * SR) or float(frame_db(w).max()) < SYS_QUIET_DB


def next_span(src, thresh):
    """The next finished stretch of `src` as (start, end) absolute samples, or None.

    A stretch is finished once a pause longer than speech_chunks' min_gap follows it; a
    long stretch of only silence is skipped over."""
    buf = src.window(src.pos, src.end)
    secs = len(buf) / SR
    ivs = activity_intervals(buf, thresh_db=thresh, min_gap=MIN_GAP)
    done = [iv for iv in ivs if iv[1] + MIN_GAP + PAD <= secs]
    if done:
        return src.pos, src.pos + min(len(buf), int((done[-1][1] + PAD) * SR))
    if not ivs and secs > MIN_HISTORY / 2:
        return src.pos, src.end - int(TAIL_QUIET * SR)
    return None


class LiveTranscriber:
    def __init__(self, tmp_dir, sources, model=None):
        self.dir = Path(tmp_dir)
        self.sources = {s: Source(s, self.dir / f"{s}.wav") for s in sources}
        self.model = model
        self.out = open(self.dir / FILE, "a", buffering=1)

    def _emit(self, src, a, b, words):
        self.out.write(json.dumps({"src": src.name, "a": a, "b": b, "words": words}, ensure_ascii=False) + "\n")

    def _recognize(self, chunk, at):
        """Words of one chunk starting at absolute sample `at`."""
        if self.model is None:
            self.model = asr.load_model()
        out = []
        for w in asr._recognize(self.model, chunk):
            s = max(0.0, w["s"] + at / SR)
            out.append({"s": s, "e": max(s, w["e"] + at / SR), "t": w["t"]})
        return out

    def _needs_aec(self, src, a, b):
        """A mic stretch of a both-source recording that overlaps system sound."""
        other = self.sources.get("system")
        return src.name == "mic" and other is not None and not _quiet(other, a - int(ECHO_REACH * SR), b)

    def _process(self, src, a, b, thresh):
        """Transcribe samples [a, b) of `src` and record them as covered, except mic chunks that
        still need echo cancelling (those stay holes)."""
        chunk = src.window(a, b)
        pieces, start = [], a  # (start, end, words): covered ranges between the holes
        words = []
        for lo, hi in speech_chunks(chunk, thresh_db=thresh):
            if self._needs_aec(src, a + lo, a + hi):
                if a + lo > start:
                    pieces.append((start, a + lo, words))
                start, words = a + hi, []
            else:
                words += self._recognize(chunk[lo:hi], a + lo)
        if b > start:
            pieces.append((start, b, words))
        for pa, pb, ws in pieces:
            self._emit(src, pa, pb, ws)
        return any(ws for _, _, ws in pieces)

    def step(self):
        """One pass over every source; returns True when something was transcribed."""
        for s in self.sources.values():
            s.read()
        busy = False
        for src in self.sources.values():
            thresh = src.threshold()
            if thresh is None:
                continue
            while (span := next_span(src, thresh)) is not None:
                a, b = span
                if src.name == "mic" and "system" in self.sources and self.sources["system"].end < b:
                    break  # the system track hasn't caught up yet
                busy = self._process(src, a, b, thresh) or busy
                src.pos = b
        keep = min(s.pos for s in self.sources.values()) - int(2 * ECHO_REACH * SR)
        for s in self.sources.values():
            s.trim(max(0, keep))
        return busy

    def run(self):
        while True:
            self.step()
            time.sleep(TICK)


def load(path):
    """{source: [(a, b, words)]} from a live.jsonl; a torn last line (killed mid-write) is ignored."""
    spans = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return spans
    for line in lines:
        try:
            d = json.loads(line)
            spans.setdefault(d["src"], []).append((d["a"], d["b"], d["words"]))
        except (ValueError, KeyError):
            continue
    return spans
