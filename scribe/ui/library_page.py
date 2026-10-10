import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango

from .. import asr, library
from .util import fmt_dur


class LibraryPage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="scribe", tag="library")
        self.win = win
        self.query = ""

        header = Adw.HeaderBar()
        header.set_show_back_button(False)
        self.search = Gtk.SearchEntry(placeholder_text="search recordings and transcripts", hexpand=True, max_width_chars=60)
        self.search.connect("search-changed", self._on_search)
        header.set_title_widget(self.search)
        new = Gtk.Button(label="new recording", css_classes=["cta"])
        new.connect("clicked", lambda *_: win.open_record())
        header.pack_end(new)

        self.banner = Gtk.Label(wrap=True, xalign=0, css_classes=["banner"], margin_start=16, margin_end=16, margin_top=8)
        self.banner.set_visible(False)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["rows"])
        self.list.connect("row-activated", lambda _l, row: win.open_transcript(row.rec))
        self.empty = Gtk.Label(label="no recordings yet\npress “new recording” to start", justify=Gtk.Justification.CENTER, css_classes=["dim"], vexpand=True)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)
        self.stack = Gtk.Stack()
        self.stack.add_named(scroller, "list")
        self.stack.add_named(self.empty, "empty")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for w in (self.banner, self.stack):
            box.append(w)
        tv = Adw.ToolbarView(content=box)
        tv.add_top_bar(header)
        self.set_child(tv)

        self.connect("showing", lambda *_: self.refresh())
        GLib.timeout_add(500, self._tick)
        self.refresh()

    def _on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.refresh()

    def _tick(self):
        if self.win.jobs.active():
            self.refresh()
        return True

    def _status(self, rec):
        job = self.win.jobs.progress(rec.id)
        if job:
            return f"{job['label']} {int(job['frac'] * 100)}%", "accent"
        return {"transcribed": ("transcribed", "dim"), "failed": ("failed", "status-failed"),
                "recorded": ("not transcribed", "dim"), "transcribing": ("not transcribed", "dim")}.get(rec.status, (rec.status, "dim"))

    def refresh(self):
        try:
            asr.check_model()
            self.banner.set_visible(False)
        except asr.ModelMissing as e:
            self.banner.set_label(f"{e}  (recording still works)")
            self.banner.set_visible(True)
        recs = [r for r in library.load_all() if not self.query or self.query in r.search_text()]
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for rec in recs:
            self.list.append(self._row(rec))
        self.stack.set_visible_child_name("list" if recs or self.query else "empty")

    def _row(self, rec):
        status, css = self._status(rec)
        title = Gtk.Label(label=rec.display_title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        sub = Gtk.Label(xalign=0, css_classes=["dim"])
        sub.set_markup(f"{GLib.markup_escape_text(rec.date_label)} · {fmt_dur(rec.duration)} · <span>{GLib.markup_escape_text(status)}</span>")
        if css != "dim":
            sub.add_css_class(css)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        text.append(title)
        text.append(sub)
        rm = Gtk.Button(label="delete", css_classes=["flat", "dim"], valign=Gtk.Align.CENTER)
        rm.connect("clicked", lambda *_: self.win.confirm_delete(rec))
        box = Gtk.Box(spacing=12, margin_start=16, margin_end=16, margin_top=10, margin_bottom=10)
        box.append(text)
        box.append(rm)
        row = Gtk.ListBoxRow(child=box, activatable=True)
        row.rec = rec
        return row
