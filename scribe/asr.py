"""Chunked Parakeet TDT transcription.

Two models, picked per recording ("language" in its JSON):
  multi  Parakeet TDT 0.6B v3 (25 European languages incl. English and German), voxtype's files
  en     Parakeet TDT 110M, English only, 2-4x faster; downloaded on first use (sherpa-onnx export)
Both emit sentencepiece tokens with start times, so everything after recognition is shared."""
import os
import tarfile
import tempfile
import threading

import numpy as np

from . import paths
from .audio import SR, speech_chunks
from .merge import tokens_to_words

LANGUAGES = {"en": "english", "multi": "english + german"}
DEFAULT_LANGUAGE = "multi"
MODEL_NAMES = {"en": "parakeet-tdt-110m-en-int8", "multi": "parakeet-tdt-0.6b-v3-int8"}
EN_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
          "sherpa-onnx-nemo-parakeet_tdt_transducer_110m-en-36000-int8.tar.bz2")
EN_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")

_lock = threading.Lock()
_models = {}


class ModelMissing(RuntimeError):
    pass


def en_model_dir():
    return paths.SCRIBE_MODELS_DIR / MODEL_NAMES["en"]


def en_model_present():
    return all((en_model_dir() / n).exists() for n in EN_FILES)


def check_model(language=DEFAULT_LANGUAGE):
    """Raise ModelMissing when the model can't be had automatically (the English one is downloaded)."""
    if language == "en":
        return
    d = paths.VOXTYPE_MODEL_DIR
    needed = ["encoder-model.int8.onnx", "decoder_joint-model.int8.onnx", "vocab.txt"]
    if not all((d / n).exists() for n in needed):
        raise ModelMissing("Parakeet model not found. Install it with: voxtype setup model")


def download_en_model(progress=None):
    """Fetch the English model; unpacked next to its final place and renamed in, so a broken
    download never looks installed."""
    from .diarize import _fetch

    paths.SCRIBE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.SCRIBE_MODELS_DIR) as tmp:
        arc = os.path.join(tmp, "model.tar.bz2")
        _fetch(EN_URL, arc, progress)
        out = os.path.join(tmp, "model")
        os.mkdir(out)
        with tarfile.open(arc) as t:
            for member in t.getmembers():
                name = os.path.basename(member.name)
                if member.isfile() and name in EN_FILES:
                    member.name = name
                    t.extract(member, out, filter="data")
        if not all(os.path.exists(os.path.join(out, n)) for n in EN_FILES):
            raise RuntimeError("English model download is incomplete")
        os.replace(out, en_model_dir())


class _SherpaTransducer:
    """sherpa-onnx recognizer with the recognize() shape of onnx-asr's timestamped models."""

    def __init__(self, d, threads):
        import sherpa_onnx as so

        self.rec = so.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
            model_type="nemo_transducer", num_threads=threads)

    def recognize(self, audio, sample_rate=SR):
        s = self.rec.create_stream()
        s.accept_waveform(sample_rate, audio)
        self.rec.decode_stream(s)
        return s.result  # .tokens / .timestamps (token start, seconds)


def load_model(language=DEFAULT_LANGUAGE):
    with _lock:
        if language not in _models:
            check_model(language)
            # Always give ONNX Runtime an explicit thread count. With the default (0) it sizes its
            # pool to every CPU in the machine and pins thread i to CPU i, which overrides the
            # process CPU mask: on the M1 that put workers on the efficiency cores (and on the
            # compositor's cores) even though they were started on the performance cores.
            threads = len(os.sched_getaffinity(0))
            if language == "en":
                if not en_model_present():
                    raise ModelMissing("English model not downloaded")
                _models[language] = _SherpaTransducer(en_model_dir(), threads)
            else:
                import onnx_asr
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = threads
                opts.inter_op_num_threads = 1
                _models[language] = onnx_asr.load_model(
                    "nemo-parakeet-tdt-0.6b-v3", str(paths.VOXTYPE_MODEL_DIR), quantization="int8", sess_options=opts
                ).with_timestamps()
        return _models[language]


def unload_model():
    """Drop the models (~1 GB resident) so later steps of a long job don't share RAM with them."""
    with _lock:
        _models.clear()
    import ctypes
    import gc

    gc.collect()
    try:  # hand freed heap pages back to the OS; glibc keeps them otherwise
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


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


def transcribe(audio, progress=None, model=None, language=DEFAULT_LANGUAGE):
    """Return words [{s,e,t}] with absolute timestamps for 16 kHz mono float32 audio."""
    model = model or load_model(language)
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
