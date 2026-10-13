"""Live (while recording) transcription: chunking, mic deferral and reuse by asr.transcribe."""
from types import SimpleNamespace

import numpy as np

from scribe import asr, live
from scribe.audio import SR


class FakeModel:
    """Says one word per chunk, stamped at the chunk's first tenth of a second."""

    def __init__(self):
        self.calls = 0

    def recognize(self, audio, sample_rate=SR):
        self.calls += 1
        return SimpleNamespace(tokens=[" w%d" % self.calls], timestamps=[0.6])  # 0.5 s lead pad + 0.1


def wav48(path, secs, bursts, channels):
    """48 kHz s16 WAV (header only 44 bytes, like a still-growing pw-record file) with noise bursts."""
    rng = np.random.default_rng(0)
    x = np.zeros(int(secs * 48000), np.float32)
    for a, b in bursts:
        x[int(a * 48000):int(b * 48000)] = 0.2 * rng.standard_normal(int((b - a) * 48000))
    x = np.repeat(x[:, None], channels, axis=1).reshape(-1)
    path.write_bytes(b"\0" * 44 + (x * 32767).astype("<i2").tobytes())


def run_live(tmp_path, sources, model):
    lt = live.LiveTranscriber(tmp_path, sources, model=model)
    lt.step()
    return live.load(tmp_path / live.FILE)


def test_mic_only_is_cut_at_pauses_and_covers_silence(tmp_path):
    wav48(tmp_path / "mic.wav", 30, [(2, 4), (12, 14)], 1)
    spans = run_live(tmp_path, ["mic"], FakeModel())["mic"]
    words = [w for _, _, ws in spans for w in ws]
    assert len(words) == 2 and 1.5 < words[0]["s"] < 3 and 11 < words[1]["s"] < 13
    assert spans[0][0] == 0 and all(a == b0 for (_, a, _), (b0, _, _) in zip(spans, spans[1:]))  # contiguous
    assert spans[-1][1] < 30 * SR  # the open tail is left for later


def test_both_defers_mic_while_system_plays(tmp_path):
    wav48(tmp_path / "mic.wav", 40, [(2, 4), (22, 24)], 1)
    wav48(tmp_path / "system.wav", 40, [(1, 5)], 2)  # plays during the first mic burst only
    spans = run_live(tmp_path, ["mic", "system"], FakeModel())
    mic_words = [w for _, _, ws in spans["mic"] for w in ws]
    assert len(mic_words) == 1 and mic_words[0]["s"] > 20  # the first burst is a hole
    assert any(ws for _, _, ws in spans["system"])
    assert spans["mic"][0][0] > 0 or spans["mic"][0][1] < 6 * SR  # hole is not covered


def test_transcribe_only_recognizes_what_live_did_not(tmp_path):
    wav48(tmp_path / "mic.wav", 30, [(2, 4), (12, 14), (28, 29.5)], 1)
    done = run_live(tmp_path, ["mic"], FakeModel())["mic"]
    audio = np.zeros(30 * SR, np.float32)
    rng = np.random.default_rng(1)
    for a, b in [(2, 4), (12, 14), (28, 29.5)]:
        audio[int(a * SR):int(b * SR)] = 0.2 * rng.standard_normal(int(b * SR) - int(a * SR))
    model = FakeModel()
    words = asr.transcribe(audio, model=model, done=done)
    assert model.calls == 1  # only the third burst, past what was live-covered
    assert len(words) == 3 and [w["s"] for w in words] == sorted(w["s"] for w in words)


def test_load_ignores_torn_last_line(tmp_path):
    p = tmp_path / live.FILE
    p.write_text('{"src": "mic", "a": 0, "b": 5, "words": []}\n{"src": "mic", "a"')
    assert live.load(p) == {"mic": [(0, 5, [])]}
