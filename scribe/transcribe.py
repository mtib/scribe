"""Transcription pipeline: ASR + diarization + merge, persisted to the recording JSON.

Both-source recordings: the mic is echo-cancelled against the system track and each
track is transcribed on its own (Parakeet drops one voice when two overlap in one
stream). Speakers come only from diarization on the mix - the mic is never assumed
to be a particular person, because several people can share it.
"""
from . import aec, asr, audio, diarize, merge


def _words(rec, p):
    """(words, mix_audio) for a recording; p(fraction, label) reports progress."""
    mix = audio.decode(rec.audio)
    if not rec.tracks.exists():
        return asr.transcribe(mix, lambda f: p(f * 0.5, "transcribing")), mix
    mic = audio.decode(rec.tracks, channel=0)
    system = audio.decode(rec.tracks, channel=1)
    raw = mic
    mic = aec.cancel_echo(raw, system, audio.SR)
    mic_words = asr.transcribe(mic, lambda f: p(f * 0.25, "transcribing mic"))
    mic_words = aec.drop_echo_residue(mic_words, mic, raw, system, audio.SR)
    sys_words = asr.transcribe(system, lambda f: p(0.25 + f * 0.25, "transcribing system"))
    words = merge.drop_bleed_duplicates(mic_words, sys_words) + sys_words
    return sorted(words, key=lambda w: w["s"]), mix


def run(rec, progress=None, num_speakers=None):
    """progress(fraction, label). Raises ModelMissing if the Parakeet model is absent."""
    p = progress or (lambda f, l: None)
    rec.update(status="transcribing", error=None)
    try:
        words, mix = _words(rec, p)
        turns, notice = [], None
        try:
            if not diarize.models_present():
                diarize.download_models(lambda f, l: p(0.5, l))
            turns = diarize.diarize(mix, num_speakers, lambda f: p(0.5 + f * 0.5, "identifying speakers"))
        except Exception as e:  # diarization is best-effort; keep the transcript
            notice = f"speaker identification failed: {e}"
        merge.assign_speakers(words, turns)
        names = merge.speaker_names(turns) if turns else {"S0": "Speaker 1"}
        rec.update(
            status="transcribed", model="parakeet-tdt-0.6b-v3-int8", notice=notice,
            speakers=names, words=words, segments=merge.group_segments(words),
        )
    except Exception as e:
        rec.update(status="failed", error=str(e))
        raise
