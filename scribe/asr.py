"""Chunked Parakeet TDT transcription using voxtype's model files."""
import threading

from . import paths
from .audio import SR, utterance_cuts
from .merge import tokens_to_words

_lock = threading.Lock()
_model = None


class ModelMissing(RuntimeError):
    pass


def check_model():
    d = paths.VOXTYPE_MODEL_DIR
    needed = ["encoder-model.int8.onnx", "decoder_joint-model.int8.onnx", "vocab.txt"]
    if not all((d / n).exists() for n in needed):
        raise ModelMissing("Parakeet model not found. Install it with: voxtype setup model")


def load_model():
    global _model
    with _lock:
        if _model is None:
            check_model()
            import onnx_asr
            _model = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", str(paths.VOXTYPE_MODEL_DIR), quantization="int8"
            ).with_timestamps()
        return _model


def transcribe(audio, progress=None, model=None):
    """Return words [{s,e,t}] with absolute timestamps for 16 kHz mono float32 audio."""
    model = model or load_model()
    bounds = [0, *utterance_cuts(audio), len(audio)]
    words = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        chunk = audio[a:b]
        if len(chunk) > SR // 4:
            r = model.recognize(chunk, sample_rate=SR)
            off = a / SR
            for w in tokens_to_words(r.tokens, r.timestamps):
                w["s"] += off
                w["e"] += off
                words.append(w)
        if progress:
            progress((i + 1) / (len(bounds) - 1))
    return words
