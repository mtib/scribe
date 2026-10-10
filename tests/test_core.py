import numpy as np

from scribe import audio, export, library, merge
from scribe.merge import Turn


def test_tokens_to_words_groups_and_times():
    w = merge.tokens_to_words([" A", "fter", " n", "ight", ","], [0.32, 0.48, 1.04, 1.2, 1.36])
    assert [x["t"] for x in w] == ["After", "night,"]
    assert w[0]["s"] == 0.32 and w[0]["e"] <= w[1]["s"]


def test_assign_and_group():
    words = [{"s": 0, "e": 1, "t": "hi"}, {"s": 1, "e": 2, "t": "there"}, {"s": 5, "e": 6, "t": "yo"}]
    merge.assign_speakers(words, [Turn(0, 2.5, "S0"), Turn(4, 7, "S1")])
    segs = merge.group_segments(words)
    assert [(s["spk"], s["text"]) for s in segs] == [("S0", "hi there"), ("S1", "yo")]


def test_nearest_turn_fallback():
    words = [{"s": 10, "e": 11, "t": "x"}]
    merge.assign_speakers(words, [Turn(0, 1, "S0"), Turn(8, 9, "S1")])
    assert words[0]["spk"] == "S1"


def test_local_speaker_label_and_names():
    turns = [Turn(0, 5, "S0"), Turn(5, 10, "S1"), Turn(10, 15, "S0")]
    local = merge.label_local_speaker(turns, [(5.5, 9.5)])
    assert local == "S1"
    assert merge.speaker_names(turns, local) == {"S0": "Speaker 2", "S1": "You"}
    assert merge.speaker_names(turns, None) == {"S0": "Speaker 1", "S1": "Speaker 2"}


def test_split_points_pick_quiet_frames():
    sr = audio.SR
    a = np.ones(130 * sr, dtype=np.float32) * 0.5
    a[58 * sr:58 * sr + 2000] = 0
    cuts = audio.split_points(a, sr)
    assert abs(cuts[0] - 58 * sr) < 3000


def test_activity_intervals():
    sr = audio.SR
    a = np.zeros(3 * sr, dtype=np.float32)
    a[sr:2 * sr] = 0.3
    iv = audio.activity_intervals(a)
    assert len(iv) == 1 and abs(iv[0][0] - 1) < 0.1 and abs(iv[0][1] - 2) < 0.1


def test_display_title_fallbacks(tmp_path):
    rec = library.create("2026-10-10_143000", ["mic"], 5.0, directory=tmp_path)
    assert rec.display_title == "2026-10-10 14:30"
    rec.meta["segments"] = [{"s": 0, "e": 1, "spk": "S0", "text": "Hello team, " + "x" * 80}]
    assert rec.display_title.startswith("Hello team,") and rec.display_title.endswith("…")
    rec.rename("  Standup ")
    assert rec.display_title == "Standup"
    rec.rename("")
    assert rec.display_title.startswith("Hello team")
    assert [r.id for r in library.load_all(tmp_path)] == [rec.id]


def test_create_with_title_and_delete(tmp_path):
    rec = library.create("2026-10-10_150000", ["mic", "system"], 9.0, title="Call", directory=tmp_path)
    assert library.load_all(tmp_path)[0].display_title == "Call"
    library.delete(rec)
    assert library.load_all(tmp_path) == []


def test_exports():
    meta = {"speakers": {"S0": "You"}, "segments": [{"s": 3.5, "e": 65.25, "spk": "S0", "text": "hi"}]}
    assert export.to_txt(meta) == "[00:03] You: hi\n"
    assert "00:00:03,500 --> 00:01:05,250" in export.to_srt(meta)


def test_utterance_cuts_at_pauses_and_long_runs():
    sr = audio.SR
    rng = np.random.default_rng(0)
    speech = lambda sec: (rng.standard_normal(int(sec * sr)) * 0.1).astype(np.float32)
    quiet = lambda sec: np.zeros(int(sec * sr), np.float32)
    a = np.concatenate([speech(5), quiet(1.5), speech(4)])
    cuts = audio.utterance_cuts(a)
    assert len(cuts) == 1 and abs(cuts[0] / sr - 5.75) < 0.2
    long = speech(100)
    assert len(audio.utterance_cuts(long)) >= 2
