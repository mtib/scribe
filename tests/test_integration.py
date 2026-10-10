"""End-to-end: encode two speech clips, transcribe with real Parakeet + diarization."""
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from scribe import asr, diarize, encoder, library, transcribe

MIC, SYS = os.environ.get("SCRIBE_TEST_MIC"), os.environ.get("SCRIBE_TEST_SYS")

pytestmark = pytest.mark.skipif(
    not (MIC and SYS and diarize.models_present() and (asr.paths.VOXTYPE_MODEL_DIR / "vocab.txt").exists()),
    reason="needs SCRIBE_TEST_MIC/SYS speech wavs and installed models",
)


def test_pipeline(tmp_path):
    rec = library.create("2026-10-10_160000", ["mic", "system"], 20.0, directory=tmp_path)
    # the system clip starts after the mic clip ends (fully overlapped voices transcribe as empty)
    mic, sr = sf.read(MIC, dtype="float32")
    sysa, sr2 = sf.read(SYS, dtype="float32")
    sf.write(tmp_path / "sys.wav", np.concatenate([np.zeros(len(mic) + sr, np.float32), sysa]), sr2, subtype="PCM_16")
    assert encoder.encode(Path(MIC), tmp_path / "sys.wav", rec.audio) == rec.tracks
    assert rec.audio.stat().st_size > 1000 and rec.tracks.exists()
    seen = []
    transcribe.run(rec, lambda f, l: seen.append((round(f, 2), l)))
    m = library.load_all(tmp_path)[0].meta
    assert m["status"] == "transcribed" and m["segments"] and m["words"][0]["s"] >= 0
    assert "lamps" in " ".join(w["t"] for w in m["words"]).lower() or "child" in " ".join(w["t"] for w in m["words"]).lower()
    assert seen and seen[-1][0] <= 1.0
    assert not asr._models  # the ~1 GB model is released before speaker identification
    assert all(n.startswith("Speaker") for n in m["speakers"].values())  # never auto-"You"
    print(m["speakers"], [(s["spk"], s["text"][:40]) for s in m["segments"]])


@pytest.mark.skipif(not asr.en_model_present(), reason="English model not downloaded")
def test_english_model_gives_timed_words():
    from scribe import audio

    words = asr.transcribe(audio.decode(MIC), language="en")
    asr.unload_model()
    text = " ".join(w["t"] for w in words).lower()
    assert "lamps" in text or "child" in text
    assert all(0 <= w["s"] <= w["e"] for w in words)
    assert [w["s"] for w in words] == sorted(w["s"] for w in words)
