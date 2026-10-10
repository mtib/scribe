import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import export, library
from .player import Player
from .util import run_bg


class TranscriptPage(Adw.NavigationPage):
    def __init__(self, win, rec):
        super().__init__(title=rec.display_title, tag="transcript")
        self.win, self.rec = win, rec
        self.player = Player(rec.audio)
        self.ready = False
        self.rows = []
        self.last_status = None
        self.alive = True

        header = Adw.HeaderBar()
        self.name = Gtk.Entry(text=rec.title, placeholder_text=rec.display_title, width_chars=34, max_width_chars=48, xalign=0.5)
        self.name.connect("activate", self._rename)
        fc = Gtk.EventControllerFocus()
        fc.connect("leave", self._rename)
        self.name.add_controller(fc)
        header.set_title_widget(self.name)
        for label, kind in (("srt", "srt"), ("txt", "txt")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, k=kind: self._export(k))
            header.pack_end(b)

        # playback bar
        self.play_btn = Gtk.Button(label="play", sensitive=False)
        self.play_btn.connect("clicked", self._toggle)
        self.scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, draw_value=False)
        self.scale.set_range(0, max(1.0, rec.duration))
        self.scale.connect("change-value", self._on_scrub)
        self.time = Gtk.Label(label="00:00", css_classes=["dim"], width_chars=6)
        bar = Gtk.Box(spacing=12, margin_start=16, margin_end=16, margin_top=8, margin_bottom=8)
        for w in (self.play_btn, self.scale, self.time):
            bar.append(w)

        # status area (progress / error / retry)
        self.status = Gtk.Label(xalign=0, wrap=True, margin_start=16, margin_end=16, css_classes=["dim"])
        self.progress = Gtk.ProgressBar(margin_start=16, margin_end=16, margin_top=4)
        self.retry = Gtk.Button(label="transcribe", halign=Gtk.Align.START, margin_start=16, margin_top=4, margin_bottom=4)
        self.retry.connect("clicked", lambda *_: self._start_job())

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)

        # speaker-count control
        self.count = Gtk.DropDown.new_from_strings(["auto"] + [str(i) for i in range(1, 9)])
        redo = Gtk.Button(label="re-identify speakers")
        redo.connect("clicked", lambda *_: self._start_job(self._speakers()))
        foot = Gtk.Box(spacing=8, margin_start=16, margin_end=16, margin_top=8, margin_bottom=8)
        foot.append(Gtk.Label(label="speakers", css_classes=["dim"]))
        foot.append(self.count)
        foot.append(redo)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for w in (bar, self.status, self.progress, self.retry, scroller, foot):
            box.append(w)
        self.toasts = Adw.ToastOverlay(child=box)
        tv = Adw.ToolbarView(content=self.toasts)
        tv.add_top_bar(header)
        self.set_child(tv)

        run_bg(self.player.prepare, self._player_ready)
        GLib.timeout_add(250, self._tick)
        self.connect("hidden", lambda *_: self.close())
        self._reload()

    def close(self):
        self.alive = False
        self.player.close()

    # ---- state ----
    def _speakers(self):
        i = self.count.get_selected()
        return None if i == 0 else i

    def _start_job(self, n=None):
        self.win.jobs.start(self.rec, n, on_done=lambda r: None)
        self.last_status = None

    def _reload(self):
        fresh = {r.id: r for r in library.load_all()}.get(self.rec.id)
        if fresh:
            self.rec = fresh
        job = self.win.jobs.progress(self.rec.id)
        state = ("job", self.rec.status) if job else ("idle", self.rec.status)
        self.progress.set_visible(bool(job))
        if job:
            self.progress.set_fraction(job["frac"])
            self.status.set_label(f"{job['label']} · {int(job['frac'] * 100)}%")
        self.status.set_visible(bool(job) or self.rec.status != "transcribed" or bool(self.rec.meta.get("notice")))
        if not job:
            if self.rec.status == "failed":
                self.status.set_label(f"failed: {self.rec.meta.get('error')}")
            elif self.rec.status != "transcribed":
                self.status.set_label("not transcribed yet")
            elif self.rec.meta.get("notice"):
                self.status.set_label(self.rec.meta["notice"])
        self.retry.set_visible(not job and self.rec.status in ("recorded", "failed", "transcribing"))
        self.retry.set_label("retry" if self.rec.status == "failed" else "transcribe")
        if state != self.last_status:
            self.last_status = state
            self._render_segments()

    def _render_segments(self):
        while (r := self.list.get_row_at_index(0)) is not None:
            self.list.remove(r)
        self.rows = []
        meta = self.rec.meta
        for seg in meta.get("segments", []):
            ts = Gtk.Button(label=export.short_ts(seg["s"]), css_classes=["flat", "ts"], valign=Gtk.Align.START)
            ts.connect("clicked", lambda _b, t=seg["s"]: self._seek(t))
            spk = Gtk.Button(label=export.name_of(meta, seg["spk"]), css_classes=["flat", "speaker"], valign=Gtk.Align.START, halign=Gtk.Align.START, width_request=110)
            spk.get_child().set_xalign(0)
            spk.connect("clicked", lambda _b, s=seg["spk"]: self._rename_speaker(s))
            txt = Gtk.Label(label=seg["text"], wrap=True, xalign=0, hexpand=True, selectable=True, margin_top=6, margin_bottom=6)
            line = Gtk.Box(spacing=8, margin_start=8, margin_end=16, css_classes=["seg"])
            for w in (ts, spk, txt):
                line.append(w)
            row = Gtk.ListBoxRow(child=line, activatable=False)
            self.list.append(row)
            self.rows.append((seg, line))

    # ---- actions ----
    def _rename(self, *_):
        new = self.name.get_text().strip()
        if new != self.rec.title:
            self.rec.rename(new)
            self.name.set_placeholder_text(self.rec.display_title)
            self.set_title(self.rec.display_title)

    def _rename_speaker(self, spk):
        meta = self.rec.meta
        entry = Gtk.Entry(text=export.name_of(meta, spk))
        dlg = Adw.AlertDialog(heading="rename speaker", body="Use the same name as another speaker to merge them.")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "cancel")
        dlg.add_response("ok", "rename")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        entry.connect("activate", lambda *_: dlg.response("ok") if False else dlg.close())

        def done(_d, resp):
            name = entry.get_text().strip()
            if resp == "ok" and name:
                speakers = dict(meta.get("speakers", {}))
                speakers[spk] = name
                self.rec.update(speakers=speakers)
                self.last_status = None
                self._reload()
        dlg.connect("response", done)
        dlg.present(self.win)

    def _export(self, kind):
        meta = self.rec.meta
        if not meta.get("segments"):
            self.toasts.add_toast(Adw.Toast.new("nothing to export yet"))
            return
        out = self.rec.dir / f"{self.rec.id}.{kind}"
        out.write_text(export.to_srt(meta) if kind == "srt" else export.to_txt(meta))
        self.toasts.add_toast(Adw.Toast.new(f"saved {out}"))

    # ---- playback ----
    def _player_ready(self, _res, err):
        if err or not self.alive:
            if err:
                self.toasts.add_toast(Adw.Toast.new(f"playback unavailable: {err}"))
            return
        self.ready = True
        self.play_btn.set_sensitive(True)

    def _toggle(self, *_):
        self.player.toggle()

    def _seek(self, t):
        if self.ready:
            self.player.seek(t)
            self.player.play()

    def _on_scrub(self, _scale, _scroll, value):
        if self.ready:
            self.player.seek(value)
        return False

    def _tick(self):
        if not self.alive:
            return False
        self._reload()
        if self.ready:
            pos = self.player.position()
            self.play_btn.set_label("pause" if self.player.playing else "play")
            self.time.set_label(export.short_ts(pos))
            dur = self.player.duration()
            if dur:
                self.scale.set_range(0, dur)
            self.scale.set_value(pos)
            for seg, line in self.rows:
                (line.add_css_class if seg["s"] <= pos < seg["e"] + 0.6 and self.player.playing else line.remove_css_class)("playing")
        return True
