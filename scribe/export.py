"""Transcript exports generated from stored segments."""


def _ts(sec, comma=False):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{',' if comma else '.'}{ms:03}"


def short_ts(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def name_of(meta, spk):
    return meta.get("speakers", {}).get(spk, spk)


def to_txt(meta):
    return "\n".join(f"[{short_ts(s['s'])}] {name_of(meta, s['spk'])}: {s['text']}" for s in meta.get("segments", [])) + "\n"


def to_srt(meta):
    out = []
    for i, s in enumerate(meta.get("segments", []), 1):
        out.append(f"{i}\n{_ts(s['s'], True)} --> {_ts(s['e'], True)}\n{name_of(meta, s['spk'])}: {s['text']}\n")
    return "\n".join(out)
