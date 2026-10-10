import time

import numpy as np

from scribe import aec

SR = 16000


def _db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)


def _scene(seconds=20, seed=1):
    rng = np.random.default_rng(seed)
    n = SR * seconds
    ref = np.convolve(rng.standard_normal(n), np.ones(8) / 8, "same").astype(np.float32) * 0.2  # "video"
    path = np.zeros(600, np.float32)
    path[[0, 40, 130, 300]] = [0.5, 0.25, -0.15, 0.08]
    echo = np.convolve(ref, path)[:n]
    echo = np.concatenate([np.zeros(1400, np.float32), echo])[:n]  # ~87 ms device latency
    near = np.zeros(n, np.float32)
    t = np.arange(SR * 4) / SR
    near[SR * 12:SR * 16] = (0.15 * np.sin(2 * np.pi * 200 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    return ref, echo, near


def test_lag_estimate():
    ref, echo, _ = _scene()
    lag, peak = aec.estimate_lag(echo, ref, SR)
    assert abs(lag - 1400) <= 3 and peak > aec.MIN_PEAK


def test_removes_echo_keeps_near_end_speech():
    ref, echo, near = _scene()
    mic = echo + near
    out = aec.cancel_echo(mic, ref, SR)
    assert len(out) == len(mic)
    quiet = slice(SR * 4, SR * 10)  # echo only
    assert _db(mic[quiet]) - _db(out[quiet]) > 12
    talk = slice(SR * 12 + 2000, SR * 16)  # local speech over echo (double talk)
    assert abs(_db(out[talk]) - _db(near[talk])) < 3  # near-end speech survives


def test_no_reference_is_passthrough():
    mic = np.random.default_rng(0).standard_normal(SR * 3).astype(np.float32)
    assert np.allclose(aec.cancel_echo(mic, np.zeros_like(mic), SR), mic)


def test_speed_is_faster_than_realtime():
    ref, echo, near = _scene(seconds=60)
    t = time.time()
    aec.cancel_echo(echo + near, ref, SR)
    assert time.time() - t < 60 / 4  # > 4x realtime


def test_uncorrelated_mic_is_untouched():
    rng = np.random.default_rng(3)
    mic = rng.standard_normal(SR * 10).astype(np.float32) * 0.1
    ref = rng.standard_normal(SR * 10).astype(np.float32) * 0.1
    assert np.array_equal(aec.cancel_echo(mic, ref, SR), mic)


def test_drop_echo_residue_keeps_real_speech():
    ref, echo, near = _scene()
    mic = echo + near
    clean = aec.cancel_echo(mic, ref, SR)
    words = [{"s": 6.0, "e": 6.5, "t": "echo"}, {"s": 13.0, "e": 13.5, "t": "speech"}]  # echo-only vs double-talk
    kept = aec.drop_echo_residue(words, clean, mic, ref, SR)
    assert [w["t"] for w in kept] == ["speech"]
