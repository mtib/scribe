"""Heavy work in its own process so it can never hold the GIL of the UI process.

  python -m scribe.worker <recordings dir> <recording id> [speakers]   transcribe
  python -m scribe.worker encode <tmp dir> <id> <title> <seconds> <sources,csv>   mix + encode a recording
  python -m scribe.worker live <tmp dir> <sources,csv>   transcribe a recording in progress (until killed)

Transcription progress goes to stdout as JSON lines: {"f": 0..1, "l": "label"}."""
import json
import sys
from pathlib import Path


def encode_main(argv):
    """Mix the temp WAVs of a finished recording into its .opus (echo cancelled) and register it."""
    import shutil

    from . import encoder, library, live, paths

    tmp, rec_id, title, seconds, sources = Path(argv[2]), argv[3], argv[4], float(argv[5]), argv[6].split(",")
    wavs = {s: tmp / f"{s}.wav" for s in sources}
    paths.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    encoder.encode(wavs.get("mic"), wavs.get("system"), paths.RECORDINGS_DIR / f"{rec_id}.opus")
    if (tmp / live.FILE).exists():
        shutil.copy(tmp / live.FILE, paths.RECORDINGS_DIR / f"{rec_id}.live.jsonl")
    library.create(rec_id, sources, seconds, title=title)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


def live_main(argv):
    from . import live

    live.LiveTranscriber(argv[2], argv[3].split(",")).run()
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "encode":
        return encode_main(argv)
    if len(argv) > 1 and argv[1] == "live":
        return live_main(argv)
    directory, rec_id = Path(argv[1]), argv[2]
    speakers = int(argv[3]) if len(argv) > 3 and argv[3] else None
    from . import library, transcribe

    rec = library.load(directory, rec_id)
    if rec is None:
        print(json.dumps({"error": f"recording {rec_id} not found"}), flush=True)
        return 2

    def progress(frac, label):
        print(json.dumps({"f": frac, "l": label}), flush=True)

    try:
        transcribe.run(rec, progress, speakers)
    except Exception as e:  # already recorded in the recording's JSON by transcribe.run
        print(json.dumps({"error": str(e)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
