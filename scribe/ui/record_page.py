import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import asr, library, settings
from ..jobs import encode_recording
from ..recorder import Monitor, Recorder
from .util import GAP, make_header, run_bg

SOURCES = {"mic": ["mic"], "system": ["system"], "both": ["mic", "system"]}


class RecordPage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="new recording", tag="record")
        self.win = win
        self.rec = None
        self.monitor = Monitor()
        self.shown_levels = {}

        header = make_header(win)
        self.back_btn = header.back_btn
        self.name = Gtk.Entry(placeholder_text="name this recording (optional)", hexpand=True, max_width_chars=48)

        self.source_btns = {}
        srcbox = Gtk.Box(spacing=GAP, halign=Gtk.Align.CENTER)
        first = None
        for key in SOURCES:
            b = Gtk.ToggleButton(label=key, group=first)
            first = first or b
            self.source_btns[key] = b
            srcbox.append(b)
        self.source_btns["both"].set_active(True)

        # which transcription model: English-only is 2-4x faster, the other also does German
        self.lang_btns = {}
        langbox = Gtk.Box(spacing=GAP, halign=Gtk.Align.CENTER)
        first = None
        for key, label in asr.LANGUAGES.items():
            b = Gtk.ToggleButton(label=label, group=first)
            first = first or b
            self.lang_btns[key] = b
            langbox.append(b)
        saved = settings.get("language", asr.DEFAULT_LANGUAGE)
        self.lang_btns[saved if saved in self.lang_btns else asr.DEFAULT_LANGUAGE].set_active(True)
        for key, b in self.lang_btns.items():
            b.connect("toggled", lambda b, k=key: b.get_active() and settings.put("language", k))

        self.clock = Gtk.Label(label="00:00", css_classes=["timer"], margin_top=24, margin_bottom=8)
        self.meters = {k: Gtk.LevelBar(min_value=0, max_value=1, hexpand=True) for k in ("mic", "system")}
        meters = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=GAP, margin_top=16)
        self.meter_rows = {}
        for k, m in self.meters.items():
            row = Gtk.Box(spacing=GAP)
            row.append(Gtk.Label(label=k, css_classes=["dim"], width_chars=7, xalign=0))
            row.append(m)
            self.meter_rows[k] = row
            meters.append(row)

        self.error = Gtk.Label(wrap=True, css_classes=["status-failed"], visible=False, margin_top=12)
        self.action = Gtk.Button(label="start", css_classes=["cta"], halign=Gtk.Align.CENTER, margin_top=24)
        self.action.connect("clicked", self._on_action)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=GAP, margin_top=24, margin_start=24, margin_end=24, margin_bottom=24, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width_request=420)
        for w in (self.name, srcbox, langbox, self.clock, meters, self.error, self.action):
            col.append(w)
        tv = Adw.ToolbarView(content=col)
        tv.add_top_bar(header)
        self.set_child(tv)
        for b in self.source_btns.values():
            b.connect("toggled", lambda *_: (self._sync_meters(), self._monitor_on()))
        self._sync_meters()
        self.connect("showing", lambda *_: self._monitor_on())
        self.connect("hidden", lambda *_: self.monitor.stop())
        GLib.timeout_add(80, self._tick)

    def _language(self):
        return next(k for k, b in self.lang_btns.items() if b.get_active())

    def _selected(self):
        return next(k for k, b in self.source_btns.items() if b.get_active())

    def _sync_meters(self):
        sel = SOURCES[self._selected()]
        for k, row in self.meter_rows.items():
            row.set_visible(k in sel)

    def _monitor_on(self):
        """Live meters for the selected sources while idle (nothing is recorded)."""
        if not self.rec:
            self.monitor.start(SOURCES[self._selected()])

    def _on_action(self, *_):
        self._stop() if self.rec else self._start()

    def _start(self):
        self.error.set_visible(False)
        self.rec_id = library.new_id()
        self.sources = SOURCES[self._selected()]
        rec = Recorder(self.sources, self.rec_id)
        self.monitor.stop()
        try:
            rec.start()
        except Exception as e:
            self.error.set_label(str(e))
            self.error.set_visible(True)
            self._monitor_on()
            return
        self.rec = rec
        self.action.set_label("stop")
        self.set_can_pop(False)
        self.back_btn.set_sensitive(False)
        for b in self.source_btns.values():
            b.set_sensitive(False)

    def _tick(self):
        if self.rec:
            m, sec = divmod(int(self.rec.elapsed()), 60)
            self.clock.set_label(f"{m:02}:{sec:02}")
        for src in SOURCES[self._selected()]:
            raw = self.rec.level(src) if self.rec else self.monitor.level(src)
            lvl = max(min(1.0, raw * 2.5), self.shown_levels.get(src, 0.0) * 0.85)  # fast attack, soft decay
            self.shown_levels[src] = lvl
            self.meters[src].set_value(lvl)
        return True

    def _stop(self):
        rec, self.rec = self.rec, None
        self.action.set_sensitive(False)
        self.action.set_label("saving…")
        title = self.name.get_text().strip()
        rec_id = self.rec_id
        language = self._language()

        def work():
            dur, wavs = rec.stop()
            if not wavs:
                raise RuntimeError("nothing was captured")
            saved = encode_recording(rec.dir, rec_id, title, dur, list(wavs))
            saved.update(language=language)
            return saved

        run_bg(work, self._saved)

    def _saved(self, recording, err):
        self.action.set_sensitive(True)
        self.action.set_label("start")
        self.set_can_pop(True)
        self.back_btn.set_sensitive(True)
        self.clock.set_label("00:00")
        for m in self.meters.values():
            m.set_value(0)
        for b in self.source_btns.values():
            b.set_sensitive(True)
        self.name.set_text("")
        if err:
            self.error.set_label(f"save failed: {err}")
            self.error.set_visible(True)
            self._monitor_on()
            return
        self.win.finish_recording(recording)

    def reset(self):
        self.error.set_visible(False)
