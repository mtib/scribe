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


def label_local_speaker(turns, mic_intervals):
    """Return the speaker id whose turns overlap mic activity most, or None."""
    totals = {}
    for t in turns:
        ov = sum(_overlap(t.start, t.end, a, b) for a, b in mic_intervals)
        totals[t.speaker] = totals.get(t.speaker, 0.0) + ov
    if not totals or max(totals.values()) <= 0:
        return None
    return max(totals, key=totals.get)


def speaker_names(turns, local=None):
    """Map raw speaker ids to display names ('You' for local, then 'Speaker N')."""
    names, n = {}, 1
    for t in sorted(turns, key=lambda t: t.start):
        if t.speaker in names:
            continue
        if t.speaker == local:
            names[t.speaker] = "You"
        else:
            n += 1
            names[t.speaker] = f"Speaker {n}"
    if local is None:  # nobody is "You": number from 1
        names = {k: f"Speaker {i + 1}" for i, k in enumerate(names)}
    return names
