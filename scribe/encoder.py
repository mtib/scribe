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


def encode(mic, system, out_opus):
    """Encode available sources. Returns the tracks sidecar path or None."""
    out_opus = Path(out_opus)
    srcs = [p for p in (mic, system) if p]
    if not srcs:
        raise ValueError("no sources to encode")
    if len(srcs) == 1:
        _run(["-i", str(srcs[0]), "-ac", "1", *OPUS, str(out_opus)])
        return None
    with tempfile.TemporaryDirectory() as tmp:
        # remove the speakers' echo from the mic (using the system track as reference)
        # before mixing; the raw tracks are kept untouched in the sidecar below
        clean = Path(tmp) / "mic_clean.wav"
        sf.write(clean, aec.cancel_echo(audio.decode(mic), audio.decode(system), audio.SR), audio.SR, subtype="PCM_16")
        _run(["-i", str(clean), "-i", str(system),
              "-filter_complex",
              "[0:a]aformat=channel_layouts=mono,aresample=48000[m];"
              "[1:a]aformat=channel_layouts=mono,aresample=48000[s];"
              "[m][s]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[o]",
              "-map", "[o]", *OPUS, str(out_opus)])
    tracks = out_opus.with_suffix(".tracks.opus")
    _run(["-i", str(mic), "-i", str(system),
          "-filter_complex",
          "[0:a]aformat=channel_layouts=mono,aresample=48000[m];"
          "[1:a]aformat=channel_layouts=mono,aresample=48000[s];"
          "[m][s]join=inputs=2:channel_layout=stereo[o]",
          "-map", "[o]", "-c:a", "libopus", "-b:a", "48k", str(tracks)])
    return tracks
