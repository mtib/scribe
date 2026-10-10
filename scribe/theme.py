"""Omarchy theme -> libadwaita CSS. Pure functions plus a tiny TOML reader."""
import tomllib

from . import paths

FALLBACK = {
    "mode": "dark", "accent": "#7aa2f7", "background": "#000000", "foreground": "#ffffff",
    "muted": "#7a7a7a", "selection": "#1a1a1a", "lighter_background": "#1a1a1a",
    "dark_background": "#090909", "red": "#f7768e",
}


def load_colors(path=None):
    p = path or paths.OMARCHY_THEME_DIR / "colors.toml"
    try:
        with open(p, "rb") as f:
            return {**FALLBACK, **tomllib.load(f)}
    except (OSError, tomllib.TOMLDecodeError):
        return dict(FALLBACK)


def _on_accent(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def build_css(c):
    bg, fg, acc = c["background"], c["foreground"], c["accent"]
    line = c["selection"]
    named = {
        "window_bg_color": bg, "window_fg_color": fg, "view_bg_color": bg, "view_fg_color": fg,
        "headerbar_bg_color": bg, "headerbar_fg_color": fg, "headerbar_border_color": line,
        "card_bg_color": c["dark_background"], "card_fg_color": fg,
        "popover_bg_color": c["lighter_background"], "popover_fg_color": fg,
        "dialog_bg_color": bg, "dialog_fg_color": fg,
        "accent_bg_color": acc, "accent_fg_color": _on_accent(acc), "accent_color": acc,
        "destructive_bg_color": c["red"], "destructive_fg_color": _on_accent(c["red"]),
        "borders": line, "muted": c["muted"], "line": line,
    }
    defs = "\n".join(f"@define-color {k} {v};" for k, v in named.items())
    return defs + "\n" + STATIC_CSS


STATIC_CSS = """
* { font-family: monospace; border-radius: 0; box-shadow: none; text-shadow: none; }
window, .background { background: @window_bg_color; }
headerbar { background: @window_bg_color; border-bottom: 1px solid @line; min-height: 40px; }
button { background: transparent; border: 1px solid @line; color: @window_fg_color; padding: 4px 12px; min-height: 24px; }
button:hover { border-color: @muted; background: transparent; }
button.cta, button.suggested-action { background: @accent_bg_color; color: @accent_fg_color; border-color: @accent_bg_color; }
button.destructive-action { color: @destructive_bg_color; border-color: @destructive_bg_color; }
button.flat { border-color: transparent; }
entry, searchentry { background: transparent; border: 1px solid @line; box-shadow: none; outline: none; }
entry:focus-within, searchentry:focus-within { border-color: @accent_color; }
list, listview { background: transparent; }
row { border-bottom: 1px solid @line; padding: 0; }
row:hover { background: @card_bg_color; }
row:selected, row.active { background: @card_bg_color; border-left: 2px solid @accent_color; }
.dim { color: @muted; }
.accent { color: @accent_color; }
.status-failed { color: @destructive_bg_color; }
.timer { font-size: 56px; font-weight: 300; }
.title-1 { font-size: 15px; font-weight: bold; }
.ts { color: @muted; }
.ts:hover { color: @accent_color; }
.speaker { color: @accent_color; font-weight: bold; }
levelbar trough { background: @line; min-height: 4px; border: none; }
levelbar block.filled { background: @accent_color; }
progressbar trough { background: @line; min-height: 2px; border: none; }
progressbar progress { background: @accent_color; min-height: 2px; }
scale trough { background: @line; min-height: 2px; }
scale highlight { background: @accent_color; }
scale slider { background: @window_fg_color; min-width: 8px; min-height: 8px; }
.seg.playing { background: @card_bg_color; border-left: 2px solid @accent_color; }
banner, .banner { background: @card_bg_color; border: 1px solid @line; padding: 6px 12px; }
"""
