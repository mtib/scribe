"""Offline acoustic echo cancellation: remove the system (loopback) signal from the mic.

Delay is estimated with GCC-PHAT, then a partitioned-block frequency-domain NLMS
filter (overlap-save) subtracts the echo. The step size shrinks when the error is much
larger than the estimated echo (someone near the mic is talking) so local speech is kept.
"""
import numpy as np

from . import audio


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


def cancel_echo(mic, ref, sr, block=512, parts=None, mu=0.5, residual=True):
    """Return mic with the (delayed, filtered) ref removed. Float arrays in, float32 out.

    A residual echo suppressor (suppress_residual) follows the linear stage, because real
    echo paths are partly nonlinear (speaker/mic processing) and a linear filter alone only
    removes a few dB there.

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
    linear = _adapt(mic_p, ref_p, W, block, mu, True, ref_pow)[:n]
    return suppress_residual(linear, ref[:n], sr) if residual else linear


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


def _stft(x, n_fft, hop):
    win = np.sqrt(np.hanning(n_fft + 1)[:-1]).astype(np.float32)
    pad = np.concatenate([np.zeros(n_fft - hop, np.float32), x, np.zeros(n_fft, np.float32)])
    frames = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    return np.fft.rfft(pad[idx] * win, axis=1), win


def _istft(S, win, hop, length):
    n_fft = len(win)
    frames = np.fft.irfft(S, axis=1) * win
    out = np.zeros(hop * (len(S) - 1) + n_fft, np.float32)
    norm = np.zeros_like(out)
    for i, f in enumerate(frames):
        out[i * hop:i * hop + n_fft] += f
        norm[i * hop:i * hop + n_fft] += win ** 2
    out /= np.maximum(norm, 1e-6)
    return out[n_fft - hop:n_fft - hop + length]


def suppress_residual(e, ref, sr, n_fft=512, hop=128, over=3.0, floor_db=-30.0, pct=60):
    """Attenuate what is left of the echo after the linear stage.

    ref must already be delay-aligned with e. While the reference is active, the lowest
    typical ratio of residual power to reference power per frequency (60th percentile: mostly
    frames with no one talking near the mic) is the residual echo coupling. Time-frequency
    bins whose power is not much above that expected echo get a Wiener-style gain below 1;
    bins with real near-end speech are far above it and pass through untouched."""
    e = np.asarray(e, np.float32)
    ref = np.asarray(ref, np.float32)[:len(e)]
    E, win = _stft(e, n_fft, hop)
    R, _ = _stft(ref, n_fft, hop)
    Ep, Rp = np.abs(E) ** 2, np.abs(R) ** 2
    # echo has a tail: use the strongest reference power over the last ~0.1 s
    k = max(1, int(0.1 * sr / hop))
    tail = np.stack([np.roll(Rp, d, axis=0) for d in range(k)], axis=0).max(axis=0)
    frame_pow = Rp.sum(axis=1)
    active = frame_pow > 0.02 * frame_pow[frame_pow > 0].mean() if np.any(frame_pow > 0) else frame_pow > 1
    if active.sum() < 10:
        return e
    ratio = Ep[active] / (tail[active] + 1e-9)
    rho = np.percentile(ratio, pct, axis=0)
    rho = np.convolve(rho, np.ones(5) / 5, mode="same")  # smooth over frequency
    S = over * rho[None, :] * tail
    floor = 10 ** (floor_db / 20)
    gain = np.sqrt(np.clip(1.0 - S / (Ep + 1e-12), floor ** 2, 1.0))
    gain[~active] = 1.0
    sm = np.empty_like(gain)  # fast attack (towards less gain), slow release: no pumping
    prev = np.ones(gain.shape[1], np.float32)
    for i in range(len(gain)):
        prev = np.minimum(gain[i], prev + 0.25 * (gain[i] - prev)) if gain[i].mean() < prev.mean() else prev + 0.35 * (gain[i] - prev)
        sm[i] = prev
    sm = np.apply_along_axis(lambda g: np.convolve(g, np.ones(3) / 3, mode="same"), 1, sm)
    return _istft(E * sm, win, hop, len(e))


def duck_mic(mic, system, sr, depth_db=-30.0, hang=0.35, lead=0.05, ramp=0.06):
    """Mute (to depth_db) the mic wherever the system track has sound.

    Used for the saved mix only: echo that survives cancellation is only audible while the
    system plays, so silencing the mic then removes it. Speech into the mic during that time
    is lost from the mix (it stays in the transcript, which does not use this). The system
    activity is widened by `hang` after and `lead` before, and gain ramps are smoothed
    over `ramp` seconds so there are no clicks."""
    n = min(len(mic), len(system))
    mask = np.zeros(n, np.float32)
    for a, b in audio.activity_intervals(system[:n], sr, frame=0.02, min_gap=0.15, min_len=0.1):
        mask[max(0, int((a - lead) * sr)):min(n, int((b + hang) * sr))] = 1.0
    k = max(3, int(ramp * sr)) | 1
    mask = np.convolve(mask, np.hanning(k) / np.hanning(k).sum(), mode="same")
    gain = 1.0 - np.clip(mask, 0, 1) * (1.0 - 10 ** (depth_db / 20))
    out = np.asarray(mic, np.float32).copy()
    out[:n] *= gain
    return out
