# scribe

Local, offline recorder + transcriber for Omarchy (GTK4 / libadwaita).

- Records **mic**, **system audio** or **both** to one mixed **Opus** file.
- Transcribes with **Parakeet TDT v3** using the model voxtype already downloaded
  (`~/.local/share/voxtype/models/parakeet-tdt-0.6b-v3-int8`), with **word timestamps**.
- **Speaker diarization** (sherpa-onnx). With "both", the speaker overlapping mic
  activity is labelled *You*. Rename or merge speakers, or force a speaker count.
- Name a recording before, during or after; unnamed ones show the start of the transcript.
- Follows the active Omarchy theme (`~/.local/state/omarchy/current/theme/colors.toml`).

## Run

    python -m venv --system-site-packages .venv
    .venv/bin/pip install -e . pytest
    .venv/bin/python -m scribe        # or ./scribe.sh

Recordings live in `~/Recordings/Scribe/` (`<id>.opus`, `<id>.tracks.opus` for
both-source recordings, `<id>.json` with the transcript). Diarization models
(~45 MB) are downloaded once to `~/.local/share/scribe/models/` on first
transcription; this is the only network access.

## Known limitations

- Parakeet returns nothing when two people talk at the same time over the same
  stretch; pauses are handled by cutting at silences.
- System capture records everything audible on the default sink.
- Diarization may over-split speakers; use rename-to-merge or the speaker count.

`SCRIBE_OPEN=record|<recording id>` opens that page at startup (testing aid).
