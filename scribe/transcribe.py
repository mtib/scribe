"""Transcription pipeline: ASR + diarization + merge, persisted to the recording JSON."""
from . import asr, audio, diarize, merge


def run(rec, progress=None, num_speakers=None):
    """progress(fraction, label). Raises ModelMissing if the Parakeet model is absent."""
    p = progress or (lambda f, l: None)
    rec.update(status="transcribing", error=None)
    try:
        samples = audio.decode(rec.audio)
        words = asr.transcribe(samples, lambda f: p(f * 0.5, "transcribing"))
        turns, local, notice = [], None, None
        try:
            if not diarize.models_present():
                diarize.download_models(lambda f, l: p(0.5, l))
            turns = diarize.diarize(samples, num_speakers, lambda f: p(0.5 + f * 0.5, "identifying speakers"))
            if rec.tracks.exists():
                mic = audio.decode(rec.tracks, channel=0)
                local = merge.label_local_speaker(turns, audio.activity_intervals(mic))
        except Exception as e:  # diarization is best-effort; keep the transcript
            notice = f"speaker identification failed: {e}"
            turns = []
        merge.assign_speakers(words, turns)
        names = merge.speaker_names(turns, local) if turns else {"S0": "Speaker 1"}
        rec.update(
            status="transcribed", model="parakeet-tdt-0.6b-v3-int8", notice=notice,
            speakers=names, words=words, segments=merge.group_segments(words),
        )
    except Exception as e:
        rec.update(status="failed", error=str(e))
        raise
