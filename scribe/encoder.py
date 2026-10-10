"""Mix recorded WAVs into the deliverable Opus file (+ a 2-channel tracks sidecar)."""
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf

from . import aec, audio

OPUS = ["-c:a", "libopus", "-b:a", "32k", "-application", "voip"]


def _run(args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()}")


def encode(mic, system, out_opus, write_tracks=True):
    """Encode available sources. Returns the tracks sidecar path or None."""
    out_opus = Path(out_opus)
    srcs = [p for p in (mic, system) if p]
    if not srcs:
        raise ValueError("no sources to encode")
    if len(srcs) == 1:
        _run(["-i", str(srcs[0]), "-ac", "1", *OPUS, str(out_opus)])
        return None
    with tempfile.TemporaryDirectory() as tmp:
        # the raw tracks are kept untouched in the sidecar below
        clean = Path(tmp) / "mic_clean.wav"
        mic16, sys16 = audio.decode(mic), audio.decode(system)
        # cancel the echo, then (saved mix only) mute the mic while the system plays
        cleaned = aec.duck_mic(aec.cancel_echo(mic16, sys16, audio.SR), sys16, audio.SR)
        sf.write(clean, cleaned, audio.SR, subtype="PCM_16")
        _run(["-i", str(clean), "-i", str(system),
              "-filter_complex",
              "[0:a]aformat=channel_layouts=mono,aresample=48000[m];"
              "[1:a]aformat=channel_layouts=mono,aresample=48000[s];"
              "[m][s]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[o]",
              "-map", "[o]", *OPUS, str(out_opus)])
    if not write_tracks:
        return None
    tracks = out_opus.with_suffix(".tracks.opus")
    _run(["-i", str(mic), "-i", str(system),
          "-filter_complex",
          "[0:a]aformat=channel_layouts=mono,aresample=48000[m];"
          "[1:a]aformat=channel_layouts=mono,aresample=48000[s];"
          "[m][s]join=inputs=2:channel_layout=stereo[o]",
          "-map", "[o]", "-c:a", "libopus", "-b:a", "48k", str(tracks)])
    return tracks


def remix(rec):
    """Re-render rec's saved mix from its raw tracks sidecar (e.g. to apply echo
    cancellation to a recording made before it existed). The tracks stay untouched."""
    if not rec.tracks.exists():
        raise ValueError("this recording has no separate tracks to remix")
    with tempfile.TemporaryDirectory() as tmp:
        wavs = {}
        for ch, name in ((0, "mic"), (1, "system")):
            wavs[name] = Path(tmp) / f"{name}.wav"
            _run(["-i", str(rec.tracks), "-af", f"pan=mono|c0=c{ch}", "-ar", "48000", str(wavs[name])])
        new = Path(tmp) / "mix.opus"
        encode(wavs["mic"], wavs["system"], new, write_tracks=False)
        new.replace(rec.audio)
