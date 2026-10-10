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


def test_speaker_names_only_for_speakers_with_words_in_order_of_appearance():
    words = [{"s": 5, "e": 6, "t": "a", "spk": "S1"}, {"s": 0, "e": 1, "t": "b", "spk": "S0"}, {"s": 9, "e": 10, "t": "c", "spk": "S0"}]
    assert merge.speaker_names(words) == {"S0": "Speaker 1", "S1": "Speaker 2"}


def test_tiny_speakers_are_dropped_but_never_all():
    turns = [Turn(0, 20, "S0"), Turn(20, 30, "S1"), Turn(31, 31.4, "S2")]
    assert {t.speaker for t in merge.drop_tiny_speakers(turns)} == {"S0", "S1"}
    only_short = [Turn(0, 0.5, "S0"), Turn(1, 1.2, "S1")]
    assert merge.drop_tiny_speakers(only_short) == only_short


def test_assign_speakers_scales_to_ninety_minutes_of_words():
    import time
    rng = np.random.default_rng(0)
    words = [{"s": i * 0.2, "e": i * 0.2 + 0.15, "t": "w"} for i in range(27000)]  # ~90 min of speech
    turns = [Turn(i * 4.0, i * 4.0 + 3.8, f"S{i % 3}") for i in range(1350)]
    t = time.time(); merge.assign_speakers(words, turns); assert time.time() - t < 10
    assert words[0]["spk"] == "S0" and words[25]["spk"] == "S1"


def test_bleed_dedupe_matches_brute_force_and_scales():
    import time
    rng = np.random.default_rng(1)
    vocab = ["the", "a", "yes", "no", "okay"]
    mic = [{"s": float(x), "e": float(x) + 0.2, "t": vocab[int(rng.integers(5))]} for x in sorted(rng.uniform(0, 200, 400))]
    sysw = [{"s": float(x), "e": float(x) + 0.2, "t": vocab[int(rng.integers(5))]} for x in sorted(rng.uniform(0, 200, 400))]
    brute = [w for w in mic if not any(abs((o["s"] + o["e"]) / 2 - (w["s"] + w["e"]) / 2) <= 0.45 and merge._norm(o["t"]) == merge._norm(w["t"]) for o in sysw)]
    assert merge.drop_bleed_duplicates(mic, sysw) == brute
    big = [{"s": i * 0.3, "e": i * 0.3 + 0.2, "t": "word"} for i in range(15000)]
    t = time.time(); merge.drop_bleed_duplicates(big, big); assert time.time() - t < 5


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


def test_speech_chunks_skip_silence_and_split_at_pauses():
    sr = audio.SR
    rng = np.random.default_rng(0)
    speech = lambda sec: (rng.standard_normal(int(sec * sr)) * 0.1).astype(np.float32)
    quiet = lambda sec: np.zeros(int(sec * sr), np.float32)
    a = np.concatenate([quiet(8), speech(5), quiet(1.5), speech(4), quiet(5)])
    ch = audio.speech_chunks(a)
    assert len(ch) == 2
    assert abs(ch[0][0] / sr - 7.7) < 0.2 and abs(ch[1][1] / sr - 18.8) < 0.2  # padded, no leading/trailing silence
    assert audio.speech_chunks(quiet(10)) == []
    assert len(audio.speech_chunks(speech(100))) >= 2  # long runs are split


def test_quiet_speech_is_not_mistaken_for_silence():
    sr = audio.SR
    a = (np.random.default_rng(1).standard_normal(5 * sr) * 0.004).astype(np.float32)  # about -48 dB
    ch = audio.speech_chunks(a)
    assert ch and ch[0][0] == 0 and ch[-1][1] == len(a)
