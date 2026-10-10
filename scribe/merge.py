"""Turn ASR tokens into words and align words with diarization turns."""
import bisect
from dataclasses import dataclass

import numpy as np

TOKEN_STEP = 0.16  # Parakeet TDT frame step (s); used to estimate word ends
SEGMENT_GAP = 1.2  # silence (s) that splits a same-speaker segment


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


def tokens_to_words(tokens, timestamps):
    """Group sentencepiece tokens (leading space = word start) into timed words."""
    words = []
    for tok, ts in zip(tokens, timestamps):
        starts_word = tok.startswith(" ") or not words
        text = tok.strip()
        if not text:
            continue
        if starts_word:
            words.append({"s": float(ts), "e": float(ts) + TOKEN_STEP, "t": text})
        else:
            words[-1]["t"] += text
            words[-1]["e"] = float(ts) + TOKEN_STEP
    for cur, nxt in zip(words, words[1:]):
        cur["e"] = min(cur["e"], nxt["s"])
    return words


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speakers(words, turns, chunk=2000):
    """Give each word the speaker with the most overlap, else the nearest turn (vectorised)."""
    if not words:
        return words
    if not turns:
        for w in words:
            w["spk"] = "S0"
        return words
    ts = np.array([t.start for t in turns])
    te = np.array([t.end for t in turns])
    sp = [t.speaker for t in turns]
    for i in range(0, len(words), chunk):
        part = words[i:i + chunk]
        ws = np.array([w["s"] for w in part])[:, None]
        we = np.array([w["e"] for w in part])[:, None]
        ov = np.clip(np.minimum(we, te[None, :]) - np.maximum(ws, ts[None, :]), 0.0, None)
        best = ov.argmax(axis=1)
        none = ov[np.arange(len(part)), best] <= 0
        if none.any():
            mid = (ws + we) / 2
            dist = np.minimum(np.abs(mid - ts[None, :]), np.abs(mid - te[None, :]))
            best = np.where(none, dist.argmin(axis=1), best)
        for w, j in zip(part, best):
            w["spk"] = sp[int(j)]
    return words


def group_segments(words):
    """Merge consecutive words from one speaker into display segments."""
    segs = []
    for w in words:
        last = segs[-1] if segs else None
        if last and last["spk"] == w["spk"] and w["s"] - last["e"] <= SEGMENT_GAP:
            last["e"] = w["e"]
            last["text"] += " " + w["t"]
        else:
            segs.append({"s": w["s"], "e": w["e"], "spk": w["spk"], "text": w["t"]})
    return segs


def _norm(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())


def drop_bleed_duplicates(mic_words, sys_words, tol=0.45):
    """Remove mic words that repeat a system word at the same moment (speaker bleed)."""
    sys_sorted = sorted(sys_words, key=lambda o: o["s"] + o["e"])
    mids = [(o["s"] + o["e"]) / 2 for o in sys_sorted]
    keep = []
    for w in mic_words:
        mid = (w["s"] + w["e"]) / 2
        i, j = bisect.bisect_left(mids, mid - tol), bisect.bisect_right(mids, mid + tol)
        if not any(_norm(sys_sorted[x]["t"]) == _norm(w["t"]) for x in range(i, j)):
            keep.append(w)
    return keep


MIN_TALK = 1.5  # seconds: a "speaker" with less total talk time than this is a clustering artefact


def drop_tiny_speakers(turns, min_talk=MIN_TALK):
    """Remove turns of speakers who barely talk (spurious clusters); keeps everything if only one remains."""
    talk = {}
    for t in turns:
        talk[t.speaker] = talk.get(t.speaker, 0.0) + (t.end - t.start)
    real = {s for s, v in talk.items() if v >= min_talk}
    if not real or len(real) == len(talk):
        return turns
    return [t for t in turns if t.speaker in real]


def speaker_names(words):
    """Anonymous names for the speakers who actually have words, in order of first appearance."""
    names = {}
    for w in sorted(words, key=lambda w: w["s"]):
        names.setdefault(w["spk"], f"Speaker {len(names) + 1}")
    return names
