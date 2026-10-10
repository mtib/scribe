import threading

import gi
gi.require_version("Adw", "1"); gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk


GAP = 8  # the one spacing between controls, everywhere


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


def back_button(win):
    btn = Gtk.Button(label="back")
    btn.connect("clicked", lambda *_: win.nav.pop())
    return btn


def make_header(win):
    """Header bar with a text `back` button, exposed as bar.back_btn so pages can disable it."""
    bar = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False, show_back_button=False,
                        centering_policy=Adw.CenteringPolicy.LOOSE)
    bar.back_btn = back_button(win)
    bar.pack_start(bar.back_btn)
    return bar


def make_topbar(*widgets):
    """Plain full-width draggable top bar. Use instead of a header bar when a child
    (search, name entry) must grow to fill the row."""
    box = Gtk.Box(spacing=GAP, css_classes=["topbar"])
    for w in widgets:
        box.append(w)
    return Gtk.WindowHandle(child=box)
