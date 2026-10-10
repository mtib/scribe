import shutil
import time

import pytest

from scribe import audio, encoder, paths, recorder

pytestmark = pytest.mark.skipif(not shutil.which("pw-record"), reason="needs PipeWire")


def test_record_both_and_encode(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TMP_DIR", tmp_path / "tmp")
    rec = recorder.Recorder(["mic", "system"], "t1")
    rec.start()
    time.sleep(1.5)
    assert 0.0 <= rec.level("mic") <= 1.0
    dur, wavs = rec.stop()
    assert set(wavs) == {"mic", "system"} and dur >= 1.4
    out = tmp_path / "t1.opus"
    assert encoder.encode(wavs["mic"], wavs["system"], out) == out.with_suffix(".tracks.opus")
    assert 1.0 < len(audio.decode(out)) / audio.SR < 2.5
    assert len(audio.decode(out.with_suffix(".tracks.opus"), channel=1)) > 0
    rec.cleanup()
    assert recorder.orphans() == []
