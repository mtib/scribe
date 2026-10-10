# scribe

Local, offline recorder + transcriber for Omarchy (GTK4 / libadwaita).

| Library | Transcript | Record |
|---|---|---|
| ![library](docs/screenshots/library.png) | ![transcript](docs/screenshots/transcript.png) | ![record](docs/screenshots/record.png) |

_Screenshots show the Vantablack theme; the app follows whichever Omarchy theme is active. The demo audio is two short LibriSpeech clips._

- Records **mic**, **system audio** or **both** to one mixed **Opus** file.
- Transcribes with **Parakeet TDT v3** using the model voxtype already downloaded
  (`~/.local/share/voxtype/models/parakeet-tdt-0.6b-v3-int8`), with **word timestamps**.
- Pick the language per recording: **english + german** (Parakeet TDT v3, 25 European languages) or
  **english** (Parakeet TDT 110M, English only, about 2x faster end to end and somewhat less accurate on
  names and fast speech). Change it on the transcript page to transcribe again.
- **Speaker diarization** (sherpa-onnx) on the mix. Speakers are anonymous ("Speaker 1", ...); the mic is
  never assumed to be one person. Rename or merge speakers, or force a speaker count.
- **Echo removal** for "both" recordings: the mic is echo-cancelled against the system track (linear
  adaptive filter + residual echo suppressor), then muted whenever the system track has sound, and mixed
  into the saved `.opus`. Speech into the mic *while the system plays* is therefore not in the saved audio,
  but it is still transcribed: each track is transcribed on its own (Parakeet drops one voice when two
  overlap in one stream). The raw tracks are kept in `.tracks.opus`.
- Name a recording before, during or after; unnamed ones show the start of the transcript.
- Follows the active Omarchy theme (`~/.local/state/omarchy/current/theme/colors.toml`).

## Run

    python -m venv --system-site-packages .venv
    .venv/bin/pip install -e . pytest
    .venv/bin/python -m scribe        # or ./scribe.sh

Recordings live in `~/Recordings/Scribe/` (`<id>.opus`, `<id>.tracks.opus` for
both-source recordings, `<id>.json` with the transcript). Diarization models
(~35 MB: pyannote segmentation + CAM++ speaker embedding) are downloaded once to `~/.local/share/scribe/models/` on first
transcription, and the English-only model (~136 MB) the first time it is picked; this is the only network access.

## Long recordings (90 min+)

Heavy work (saving/mixing, transcription) runs in separate worker processes, pinned to the fastest CPU
cores (the performance cores on Apple Silicon; override with `SCRIBE_WORKER_CPUS=4-7`), so the window
stays responsive. Measured on an M1 MacBook Air (4 performance cores, 7.4 GB RAM) with 5 minutes of
dense two-track speech, scaled to 90 minutes:

| Step | 5 min measured | ~90 min | RAM |
|---|---|---|---|
| Saving after you stop (echo removal + mix + encode) | 8.6 s | ~2.5 min | ~1-2 GB |
| Transcription (both tracks) + speaker identification, english + german | 47.7 s (0.16x realtime) | ~15 min | ~3.5 GB |
| Same with the english-only model | ~21 s (0.07x realtime) | ~7 min | |
| Temp WAVs while recording (both sources) | | ~1.5 GB disk | |

Timings vary by up to 2x with memory pressure (swap) on an 8 GB machine; compare runs made back to back.

There is no GPU/Neural-Engine path on Linux for these models (only the CPU build of ONNX Runtime is
available), so the CPU cores are the limit.

Leftover temp recordings from a crash are saved on the next launch.

## Known limitations

- Parakeet drops a voice when two people overlap in one stream (handled for mic+system by
  transcribing each track separately, but not for two people on the same track), and can return
  nothing for a chunk of clear speech (empty chunks are retried with different padding).
- The saved mix mutes the mic while the system plays, so you talking over a video is audible only in the transcript.
- System capture records everything audible on the default sink.
- Diarization may over-split speakers; use rename-to-merge or the speaker count.

## Testing aids

- `SCRIBE_OPEN=record|<recording id>` opens that page at startup.
- `SCRIBE_RECORDINGS_DIR=<dir>` uses a different library; `SCRIBE_APP_ID=<id>` allows a second instance.
- Playback uses `mpv` (JSON IPC); recording needs `pw-record` (PipeWire) and `ffmpeg` with libopus.
