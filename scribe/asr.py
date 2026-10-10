"""Chunked Parakeet TDT transcription using voxtype's model files."""
import os
import threading

import numpy as np

from . import paths
from .audio import SR, speech_chunks
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
            import onnxruntime as ort

            # Always give ONNX Runtime an explicit thread count. With the default (0) it sizes its
            # pool to every CPU in the machine and pins thread i to CPU i, which overrides the
            # process CPU mask: on the M1 that put workers on the efficiency cores (and on the
            # compositor's cores) even though they were started on the performance cores.
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = len(os.sched_getaffinity(0))
            opts.inter_op_num_threads = 1
            _model = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", str(paths.VOXTYPE_MODEL_DIR), quantization="int8", sess_options=opts
            ).with_timestamps()
        return _model


# Parakeet (int8) sometimes returns nothing for a chunk that clearly contains speech, and
# which chunks fail depends chaotically on their exact length. Silence padding of a
# different length makes it decode, so empty-looking chunks are retried with other pads.
PADS = ((0.5, 0.5), (2.0, 1.0), (0.0, 0.0), (1.0, 0.5), (3.0, 2.0))
AUDIBLE_RMS = 0.003  # about -50 dB


def _recognize(model, chunk):
    """Words (chunk-relative times) for one chunk, retrying empty results with other pads."""
    audible = float(np.sqrt(np.mean(np.square(chunk)))) > AUDIBLE_RMS
    for lead, trail in PADS:
        padded = np.concatenate([np.zeros(int(lead * SR), np.float32), chunk, np.zeros(int(trail * SR), np.float32)])
        r = model.recognize(padded, sample_rate=SR)
        words = tokens_to_words(r.tokens, r.timestamps)
        for w in words:
            w["s"] -= lead
            w["e"] -= lead
        if words or not audible:
            return words
    return []


def transcribe(audio, progress=None, model=None):
    """Return words [{s,e,t}] with absolute timestamps for 16 kHz mono float32 audio."""
    model = model or load_model()
    chunks = speech_chunks(audio)
    words = []
    for i, (a, b) in enumerate(chunks):
        for w in _recognize(model, audio[a:b]):
            w["s"] = max(0.0, w["s"] + a / SR)
            w["e"] = max(w["s"], w["e"] + a / SR)
            words.append(w)
        if progress:
            progress((i + 1) / len(chunks))
    return words
