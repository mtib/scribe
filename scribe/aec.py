"""Offline acoustic echo cancellation: remove the system (loopback) signal from the mic.

Delay is estimated with GCC-PHAT, then a partitioned-block frequency-domain NLMS
filter (overlap-save) subtracts the echo. The step size shrinks when the error is much
larger than the estimated echo (someone near the mic is talking) so local speech is kept.
"""
import numpy as np


MIN_PEAK = 0.06  # GCC-PHAT peak below this = no measurable echo (e.g. headphones)


def estimate_lag(mic, ref, sr, max_lag_s=1.0, window_s=30.0):
    """(lag, peak): samples by which `mic` lags `ref`, and the GCC-PHAT correlation peak
    (computed on the loudest window of `ref`)."""
    w = int(window_s * sr)
    if len(ref) > w:
        hop = w // 2
        starts = range(0, len(ref) - w + 1, hop)
        s = max(starts, key=lambda i: float(np.sum(ref[i:i + w] ** 2)))
    else:
        s, w = 0, len(ref)
    x, r = mic[s:s + w].astype(np.float64), ref[s:s + w].astype(np.float64)
    n = 2 * w
    spec = np.fft.rfft(x, n) * np.conj(np.fft.rfft(r, n))
    cc = np.fft.irfft(spec / (np.abs(spec) + 1e-12), n)
    m = int(max_lag_s * sr)
    cc = np.concatenate([cc[-m:], cc[:m + 1]])
    k = int(np.argmax(np.abs(cc)))
    return k - m, float(abs(cc[k]))


def _shift(x, lag):
    """Delay x by `lag` samples (negative = advance), zero filled, same length."""
    out = np.zeros_like(x)
    if lag >= 0:
        out[lag:] = x[:len(x) - lag] if lag < len(x) else 0
    else:
        out[:lag] = x[-lag:]
    return out


def _adapt(mic_p, ref_p, W, block, mu, guard, ref_pow):
    """One pass of the partitioned-block filter; updates W in place, returns the error signal.
    guard=True shrinks the step when the error dwarfs the echo estimate (near-end speech).
    ref_pow is the typical per-sample power of the reference while it is active: adaptation
    is frozen when the reference is far below it (nothing to learn from, and dividing by a
    near-zero power would blow the weights up) and the normalisation is floored relative to it."""
    parts, bins = W.shape
    nb = len(mic_p) // block
    X = np.zeros((parts, bins), np.complex64)
    prev = np.zeros(block, np.float32)
    zeros = np.zeros(block, np.float32)
    out = np.empty_like(mic_p)
    for k in range(nb):
        sl = slice(k * block, (k + 1) * block)
        xb = ref_p[sl]
        X = np.roll(X, 1, axis=0)
        X[0] = np.fft.rfft(np.concatenate([prev, xb]))
        prev = xb
        y = np.fft.irfft((W * X).sum(axis=0))[block:].astype(np.float32)
        e = mic_p[sl] - y
        out[sl] = e
        step = mu if float(xb @ xb) / block > 0.02 * ref_pow else 0.0
        if guard and step:
            ep, yp = float(e @ e) + 1e-9, float(y @ y)
            step = mu * min(1.0, max(0.1, yp / ep))
        E = np.fft.rfft(np.concatenate([zeros, e]))
        P = (np.abs(X) ** 2).sum(axis=0) + 0.05 * parts * 2 * block * ref_pow + 1e-9
        G = np.fft.irfft(np.conj(X) * (E / P), axis=1)
        G[:, block:] = 0  # gradient constraint (overlap-save)
        W += (step * np.fft.rfft(G, axis=1)).astype(np.complex64)
    return out


def cancel_echo(mic, ref, sr, block=512, parts=None, mu=0.5):
    """Return mic with the (delayed, filtered) ref removed. Float arrays in, float32 out.

    Two passes over the file: the first (no guard) learns the echo path; the second starts
    from it and adapts cautiously, so local speech is left alone. The echo path is
    assumed stationary for the recording."""
    mic = np.asarray(mic, dtype=np.float32)
    ref = np.asarray(ref, dtype=np.float32)
    n = min(len(mic), len(ref))
    if n < block * 4 or not np.any(ref[:n]):
        return mic.copy()
    mic, ref = mic[:n], ref[:n]
    lag, peak = estimate_lag(mic, ref, sr)
    if peak < MIN_PEAK:
        return mic.copy()
    ref = _shift(ref, lag)
    parts = parts or max(4, int(0.08 * sr / block) + 1)  # ~80 ms of echo path
    pad = -n % block
    mic_p = np.concatenate([mic, np.zeros(pad, np.float32)])
    ref_p = np.concatenate([ref, np.zeros(pad, np.float32)])
    rb = (ref_p.reshape(-1, block) ** 2).mean(axis=1)
    active = rb[rb > 0.01 * rb.max()]
    ref_pow = float(active.mean())
    W = np.zeros((parts, block + 1), np.complex64)
    _adapt(mic_p, ref_p, W, block, mu * 0.6, False, ref_pow)
    return _adapt(mic_p, ref_p, W, block, mu, True, ref_pow)[:n]


def drop_echo_residue(words, clean, raw, system, sr, max_ratio_db=-4.0, sys_floor_db=-50.0):
    """Drop mic words that are mostly speaker echo: while the system track is active, the
    echo canceller removed most of the energy under the word (>4 dB), whereas a person
    actually speaking into the mic passes through it unchanged (~0 dB)."""
    def rms_db(x):
        return 20 * np.log10(float(np.sqrt(np.mean(np.square(x)))) + 1e-9) if len(x) else -180.0

    keep = []
    for w in words:
        a, b = int(w["s"] * sr), max(int(w["e"] * sr), int(w["s"] * sr) + 160)
        if rms_db(system[a:b]) > sys_floor_db and rms_db(clean[a:b]) - rms_db(raw[a:b]) < max_ratio_db:
            continue
        keep.append(w)
    return keep
