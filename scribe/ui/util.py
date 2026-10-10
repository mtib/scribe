import threading

import gi
gi.require_version("Adw", "1"); gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk


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


def make_header(win, back=True):
    """Header bar with text buttons: `back` (start, if back) and `quit` (end).
    The back button is exposed as bar.back_btn so pages can disable it."""
    bar = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False, show_back_button=False,
                        centering_policy=Adw.CenteringPolicy.LOOSE)
    bar.back_btn = None
    if back:
        bar.back_btn = Gtk.Button(label="back")
        bar.back_btn.connect("clicked", lambda *_: win.nav.pop())
        bar.pack_start(bar.back_btn)
    bar.pack_end(close_button(win))
    return bar


def close_button(win):
    btn = Gtk.Button(label="quit")
    btn.connect("clicked", lambda *_: win.close())
    return btn


def make_topbar(win, *widgets):
    """Plain full-width top bar (draggable): `widgets` left to right, then the close button.
    Use instead of a header bar when a child (e.g. search) must grow to fill the row."""
    box = Gtk.Box(css_classes=["topbar"])
    for w in (*widgets, close_button(win)):
        box.append(w)
    return Gtk.WindowHandle(child=box)
