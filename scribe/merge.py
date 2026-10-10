"""Turn ASR tokens into words and align words with diarization turns."""
from dataclasses import dataclass

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


def assign_speakers(words, turns):
    """Give each word the speaker with the most overlap, else the nearest turn."""
    for w in words:
        best, best_ov = None, 0.0
        for t in turns:
            ov = _overlap(w["s"], w["e"], t.start, t.end)
            if ov > best_ov:
                best, best_ov = t.speaker, ov
        if best is None and turns:
            mid = (w["s"] + w["e"]) / 2
            best = min(turns, key=lambda t: min(abs(mid - t.start), abs(mid - t.end))).speaker
        w["spk"] = best or "S0"
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
    keep = []
    for w in mic_words:
        mid = (w["s"] + w["e"]) / 2
        dup = any(abs((o["s"] + o["e"]) / 2 - mid) <= tol and _norm(o["t"]) == _norm(w["t"]) for o in sys_words)
        if not dup:
            keep.append(w)
    return keep


def speaker_names(turns):
    """Anonymous display names in order of first appearance: Speaker 1, Speaker 2, ..."""
    names = {}
    for t in sorted(turns, key=lambda t: t.start):
        names.setdefault(t.speaker, f"Speaker {len(names) + 1}")
    return names
