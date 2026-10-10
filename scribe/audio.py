"""Audio helpers: decode via ffmpeg, silence-aware chunking, activity detection."""
import subprocess

import numpy as np

SR = 16000


def decode(path, channel=None):
    """Decode any audio file to 16 kHz mono float32. channel picks one input channel."""
    af = [] if channel is None else ["-af", f"pan=mono|c0=c{channel}"]
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), *af, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def split_points(audio, sr=SR, target=60.0, search=5.0, frame=0.1):
    """Cut points near every `target` seconds, placed at the quietest 100 ms frame."""
    n = len(audio)
    hop = int(frame * sr)
    cuts, pos = [], 0
    while n - pos > (target + search) * sr:
        lo = pos + int((target - search) * sr)
        hi = pos + int((target + search) * sr)
        seg = audio[lo:hi]
        k = len(seg) // hop
        if k == 0:
            break
        energy = np.square(seg[: k * hop]).reshape(k, hop).mean(axis=1)
        cut = lo + int(np.argmin(energy)) * hop + hop // 2
        cuts.append(cut)
        pos = cut
    return cuts


def activity_intervals(audio, sr=SR, frame=0.05, thresh_db=None, min_gap=0.3, min_len=0.2):
    """(start, end) seconds of speech-level energy; gaps shorter than min_gap are bridged.

    thresh_db=None adapts to the noise floor (10th percentile + 12 dB, capped at -35 dB).
    """
    hop = int(frame * sr)
    k = len(audio) // hop
    if k == 0:
        return []
    rms = np.sqrt(np.square(audio[: k * hop]).reshape(k, hop).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    if thresh_db is None:
        thresh_db = min(-35.0, float(np.percentile(db, 10)) + 12.0)
    active = db > max(thresh_db, -70.0)
    out, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            out.append([start * frame, i * frame])
            start = None
    if start is not None:
        out.append([start * frame, k * frame])
    merged = []
    for iv in out:
        if merged and iv[0] - merged[-1][1] <= min_gap:
            merged[-1][1] = iv[1]
        else:
            merged.append(iv)
    return [(a, b) for a, b in merged if b - a >= min_len]


def utterance_cuts(audio, sr=SR, min_gap=0.7, max_len=45.0):
    """Cut points at the middle of every silence >= min_gap, plus quiet-frame cuts
    inside any stretch longer than max_len. Parakeet stops decoding after a long
    pause when given one big window, so every pause becomes a chunk boundary."""
    ivs = activity_intervals(audio, sr, min_gap=min_gap)
    cuts = [int((a1 + b0) / 2 * sr) for (_, a1), (b0, _) in zip(ivs, ivs[1:])]
    bounds = [0, *cuts, len(audio)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a > max_len * sr:
            out.extend(a + c for c in split_points(audio[a:b], sr, target=max_len * 0.7, search=max_len * 0.2))
        if b < len(audio):
            out.append(b)
    return sorted(set(out))
