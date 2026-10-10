import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import encoder, library, paths
from ..recorder import Recorder
from .util import run_bg

SOURCES = {"mic": ["mic"], "system": ["system"], "both": ["mic", "system"]}


class RecordPage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="new recording", tag="record")
        self.win = win
        self.rec = None
        self.timer_id = None

        header = Adw.HeaderBar()
        self.name = Gtk.Entry(placeholder_text="name this recording (optional)", hexpand=True, max_width_chars=48)

        self.source_btns = {}
        srcbox = Gtk.Box(spacing=0, halign=Gtk.Align.CENTER, css_classes=["linked"])
        first = None
        for key in SOURCES:
            b = Gtk.ToggleButton(label=key, group=first)
            first = first or b
            self.source_btns[key] = b
            srcbox.append(b)
        self.source_btns["both"].set_active(True)

        self.clock = Gtk.Label(label="00:00", css_classes=["timer"], margin_top=24, margin_bottom=8)
        self.meters = {k: Gtk.LevelBar(min_value=0, max_value=1, hexpand=True) for k in ("mic", "system")}
        meters = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=16)
        self.meter_rows = {}
        for k, m in self.meters.items():
            row = Gtk.Box(spacing=12)
            row.append(Gtk.Label(label=k, css_classes=["dim"], width_chars=7, xalign=0))
            row.append(m)
            self.meter_rows[k] = row
            meters.append(row)

        self.error = Gtk.Label(wrap=True, css_classes=["status-failed"], visible=False, margin_top=12)
        self.action = Gtk.Button(label="start", css_classes=["cta"], halign=Gtk.Align.CENTER, margin_top=24)
        self.action.connect("clicked", self._on_action)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=24, margin_start=24, margin_end=24, margin_bottom=24, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width_request=420)
        for w in (self.name, srcbox, self.clock, meters, self.error, self.action):
            col.append(w)
        tv = Adw.ToolbarView(content=col)
        tv.add_top_bar(header)
        self.set_child(tv)
        for b in self.source_btns.values():
            b.connect("toggled", lambda *_: self._sync_meters())
        self._sync_meters()

    def _selected(self):
        return next(k for k, b in self.source_btns.items() if b.get_active())

    def _sync_meters(self):
        sel = SOURCES[self._selected()]
        for k, row in self.meter_rows.items():
            row.set_visible(k in sel)

    def _on_action(self, *_):
        self._stop() if self.rec else self._start()

    def _start(self):
        self.error.set_visible(False)
        self.rec_id = library.new_id()
        self.sources = SOURCES[self._selected()]
        rec = Recorder(self.sources, self.rec_id)
        try:
            rec.start()
        except Exception as e:
            self.error.set_label(str(e))
            self.error.set_visible(True)
            return
        self.rec = rec
        self.action.set_label("stop")
        self.set_can_pop(False)
        for b in self.source_btns.values():
            b.set_sensitive(False)
        self.timer_id = GLib.timeout_add(80, self._tick)

    def _tick(self):
        if not self.rec:
            return False
        m, s = divmod(int(self.rec.elapsed()), 60)
        self.clock.set_label(f"{m:02}:{s:02}")
        for src in self.sources:
            self.meters[src].set_value(min(1.0, self.rec.level(src) * 2.5))
        return True

    def _stop(self):
        rec, self.rec = self.rec, None
        self.action.set_sensitive(False)
        self.action.set_label("saving…")
        title = self.name.get_text().strip()
        rec_id = self.rec_id

        def work():
            dur, wavs = rec.stop()
            if not wavs:
                raise RuntimeError("nothing was captured")
            out = paths.RECORDINGS_DIR / f"{rec_id}.opus"
            paths.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            encoder.encode(wavs.get("mic"), wavs.get("system"), out)
            r = library.create(rec_id, list(wavs), dur, title=title)
            rec.cleanup()
            return r

        run_bg(work, self._saved)

    def _saved(self, recording, err):
        self.action.set_sensitive(True)
        self.action.set_label("start")
        self.set_can_pop(True)
        self.clock.set_label("00:00")
        for m in self.meters.values():
            m.set_value(0)
        for b in self.source_btns.values():
            b.set_sensitive(True)
        self.name.set_text("")
        if err:
            self.error.set_label(f"save failed: {err}")
            self.error.set_visible(True)
            return
        self.win.finish_recording(recording)

    def reset(self):
        self.error.set_visible(False)
