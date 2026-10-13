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


def frame_db(audio, sr=SR, frame=0.05):
    """RMS level in dB of every whole `frame`-second frame."""
    hop = int(frame * sr)
    k = len(audio) // hop
    rms = np.sqrt(np.square(audio[: k * hop]).reshape(k, hop).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms)


def noise_threshold(db):
    """Speech threshold adapted to the noise floor: 10th percentile + 12 dB, clamped to -65..-35 dB."""
    return max(-65.0, min(-35.0, float(np.percentile(db, 10)) + 12.0))


def activity_intervals(audio, sr=SR, frame=0.05, thresh_db=None, min_gap=0.3, min_len=0.2):
    """(start, end) seconds of speech-level energy; gaps shorter than min_gap are bridged.

    thresh_db=None adapts to the noise floor (10th percentile + 12 dB, clamped to -65..-35 dB).
    """
    k = len(audio) // int(frame * sr)
    if k == 0:
        return []
    db = frame_db(audio, sr, frame)
    if thresh_db is None:
        thresh_db = noise_threshold(db)
    active = db > thresh_db
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


def speech_chunks(audio, sr=SR, pad=0.3, min_gap=0.7, max_len=45.0, thresh_db=None):
    """(start, end) sample ranges to transcribe: each speech stretch plus `pad` seconds,
    silence skipped. Parakeet stops decoding after a long pause when given one big window,
    and emits stray words stamped at the end frame when fed trailing silence, so every
    pause is a chunk boundary and silence is never sent. Stretches longer than max_len are
    split at their quietest frames. Digital silence returns []; audio no detector call
    finds speech in (very noisy) is returned whole."""
    if float(np.abs(audio).max(initial=0.0)) < 1e-4:
        return []
    ivs = activity_intervals(audio, sr, thresh_db=thresh_db, min_gap=min_gap)
    if not ivs:
        ivs = [(0.0, len(audio) / sr)]
    out = []
    for a, b in ivs:
        lo, hi = max(0, int((a - pad) * sr)), min(len(audio), int((b + pad) * sr))
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    final = []
    for lo, hi in out:
        if hi - lo > max_len * sr:
            cuts = [lo + c for c in split_points(audio[lo:hi], sr, target=max_len * 0.7, search=max_len * 0.2)]
            bounds = [lo, *cuts, hi]
            final.extend(zip(bounds, bounds[1:]))
        else:
            final.append((lo, hi))
    return final
