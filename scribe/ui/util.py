import threading

from gi.repository import GLib


def run_bg(fn, done):
    """Run fn() in a thread, then done(result, error) on the GTK main loop."""
    def work():
        try:
            res, err = fn(), None
        except Exception as e:  # surfaced to the UI by `done`
            res, err = None, e
        GLib.idle_add(lambda: (done(res, err), False)[1])
    threading.Thread(target=work, daemon=True).start()


def fmt_dur(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02}m" if h else (f"{m}m {s:02}s" if m else f"{s}s")
