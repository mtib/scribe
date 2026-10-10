import os
import sys

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk

from .. import encoder, library, paths, recorder, theme
from ..jobs import Jobs
from .library_page import LibraryPage
from .record_page import RecordPage
from .transcript_page import TranscriptPage
from .util import run_bg


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="scribe", default_width=820, default_height=640)
        self.jobs = Jobs()
        self.nav = Adw.NavigationView()
        self.library = LibraryPage(self)
        self.record = RecordPage(self)
        self.nav.add(self.library)
        self.nav.add(self.record)
        self.set_content(self.nav)
        self.connect("close-request", self._on_close)
        self._recover()
        self._open_from_env()

    def _open_from_env(self):
        """SCRIBE_OPEN=record|<recording id> opens that page at startup (testing aid)."""
        target = os.environ.get("SCRIBE_OPEN")
        if target == "record":
            self.open_record()
        elif target:
            rec = next((r for r in library.load_all() if r.id == target), None)
            if rec:
                self.open_transcript(rec)

    def open_record(self):
        self.record.reset()
        self.nav.push(self.record)

    def open_transcript(self, rec):
        self.nav.push(TranscriptPage(self, rec))

    def finish_recording(self, rec):
        """Recording saved: back to the library, open it, transcribe if the model exists."""
        self.nav.pop_to_page(self.library)
        self.open_transcript(rec)
        try:
            from .. import asr
            asr.check_model()
            self.jobs.start(rec)
        except Exception:
            pass  # library banner explains; the page offers a manual transcribe button

    def confirm_delete(self, rec):
        dlg = Adw.AlertDialog(heading="delete recording?", body=f"“{rec.display_title}” and its transcript will be removed.")
        dlg.add_response("cancel", "cancel")
        dlg.add_response("delete", "delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: (library.delete(rec), self.library.refresh()) if r == "delete" else None)
        dlg.present(self)

    def _recover(self):
        """Encode temp WAVs left by a crash into 'recorded' entries."""
        for d in recorder.orphans():
            def work(d=d):
                rec_id = d.name
                wavs = {s: d / f"{s}.wav" for s in ("mic", "system") if (d / f"{s}.wav").exists() and (d / f"{s}.wav").stat().st_size > recorder.WAV_HEADER}
                if wavs:
                    encoder.encode(wavs.get("mic"), wavs.get("system"), paths.RECORDINGS_DIR / f"{rec_id}.opus")
                    dur = max(recorder.wav_duration(p) for p in wavs.values())
                    library.create(rec_id, list(wavs), dur, title="")
                import shutil
                shutil.rmtree(d, ignore_errors=True)
            run_bg(work, lambda *_: self.library.refresh())

    def _on_close(self, *_):
        rp = self.record
        if rp.rec:  # save what we have rather than losing a live recording
            rp._stop()
            GLib.timeout_add(200, self._wait_close)
            return True
        return False

    def _wait_close(self):
        if self.record.rec is None and self.record.action.get_sensitive():
            self.destroy()
            return False
        return True


class ThemeWatcher:
    def __init__(self):
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            __import__("gi.repository.Gdk", fromlist=["Gdk"]).Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.pending = None
        self.apply()
        self.monitors = []
        for d in (paths.OMARCHY_THEME_DIR.parent, paths.OMARCHY_THEME_DIR):
            if d.is_dir():
                m = Gio.File.new_for_path(str(d)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                m.connect("changed", lambda *_: self._debounce())
                self.monitors.append(m)

    def _debounce(self):
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(300, self._fire)

    def _fire(self):
        self.pending = None
        self.apply()
        return False

    def apply(self):
        colors = theme.load_colors()
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if colors.get("mode") == "light" else Adw.ColorScheme.FORCE_DARK)
        self.provider.load_from_string(theme.build_css(colors))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=os.environ.get("SCRIBE_APP_ID", "dev.mtib.scribe"))

    def do_activate(self):
        win = self.props.active_window
        if not win:
            self.theme = ThemeWatcher()
            win = Window(self)
        win.present()


def main():
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
