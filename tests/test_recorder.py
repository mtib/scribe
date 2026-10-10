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


def test_monitor_reports_system_level():
    import subprocess
    import tempfile
    import numpy as np
    import soundfile as sf
    tone = tempfile.mktemp(suffix=".wav")
    sf.write(tone, (0.3 * np.sin(2 * np.pi * 440 * np.arange(48000 * 3) / 48000)).astype(np.float32), 48000)
    mon = recorder.Monitor()
    mon.start(["system"])
    player = subprocess.Popen(["pw-play", tone])
    time.sleep(2.0)
    peak = max(mon.level("system") for _ in range(1))
    seen = []
    for _ in range(10):
        seen.append(mon.level("system")); time.sleep(0.1)
    player.terminate()
    mon.stop()
    assert max(seen + [peak]) > 0.05, seen
    assert mon.procs == {}


def test_worker_cpu_selection():
    import os
    from scribe import jobs
    os.environ["SCRIBE_WORKER_CPUS"] = "4-7"
    try:
        assert jobs.performance_cpus() == {4, 5, 6, 7}
        os.environ["SCRIBE_WORKER_CPUS"] = "0,2"
        assert jobs.performance_cpus() == {0, 2}
    finally:
        del os.environ["SCRIBE_WORKER_CPUS"]
    fast = jobs.performance_cpus()  # detection from sysfs
    assert fast is None or (fast and len(fast) < os.cpu_count())
