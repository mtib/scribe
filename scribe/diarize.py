"""Speaker diarization via sherpa-onnx (pyannote segmentation + speaker embeddings)."""
import urllib.request
import tarfile
import tempfile
from pathlib import Path

from . import paths
from .merge import Turn

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEG_URL = f"{BASE}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMB_URL = f"{BASE}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
SEG_FILE = "pyannote-segmentation-3-0.onnx"
EMB_FILE = "3dspeaker-eres2net-base-16k.onnx"
THRESHOLD = 0.7


def models_present():
    return all((paths.SCRIBE_MODELS_DIR / f).exists() for f in (SEG_FILE, EMB_FILE))


def _fetch(url, dest, progress):
    def hook(blocks, bs, total):
        if progress and total > 0:
            progress(min(1.0, blocks * bs / total))
    urllib.request.urlretrieve(url, dest, hook)


def download_models(progress=None):
    """One-time download (the app's only network access). progress(fraction, label)."""
    paths.SCRIBE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if not (paths.SCRIBE_MODELS_DIR / SEG_FILE).exists():
            arc = Path(tmp) / "seg.tar.bz2"
            _fetch(SEG_URL, arc, lambda f: progress and progress(f * 0.2, "downloading segmentation model"))
            with tarfile.open(arc) as t:
                member = t.getmember("sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
                member.name = SEG_FILE
                t.extract(member, paths.SCRIBE_MODELS_DIR, filter="data")
        if not (paths.SCRIBE_MODELS_DIR / EMB_FILE).exists():
            tmpf = Path(tmp) / EMB_FILE
            _fetch(EMB_URL, tmpf, lambda f: progress and progress(0.2 + f * 0.8, "downloading speaker model"))
            tmpf.replace(paths.SCRIBE_MODELS_DIR / EMB_FILE) if tmpf.stat().st_dev == paths.SCRIBE_MODELS_DIR.stat().st_dev \
                else (paths.SCRIBE_MODELS_DIR / EMB_FILE).write_bytes(tmpf.read_bytes())


def diarize(audio, num_speakers=None, progress=None, threads=4):
    """Return Turn list with ids like 'S0'. num_speakers=None auto-estimates."""
    import sherpa_onnx as so
    m = str(paths.SCRIBE_MODELS_DIR) + "/"
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=m + SEG_FILE), num_threads=threads),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=m + EMB_FILE, num_threads=threads),
        clustering=so.FastClusteringConfig(num_clusters=num_speakers or -1, threshold=THRESHOLD),
    )
    sd = so.OfflineSpeakerDiarization(cfg)
    cb = (lambda done, total: (progress(done / total), 0)[1]) if progress else None
    res = sd.process(audio, callback=cb) if cb else sd.process(audio)
    return [Turn(s.start, s.end, f"S{s.speaker}") for s in res.sort_by_start_time()]
