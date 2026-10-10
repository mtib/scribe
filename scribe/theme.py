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


def _mix(a, b, t):
    """Blend hex color a toward b by t (0..1)."""
    ha, hb = a.lstrip("#"), b.lstrip("#")
    ch = [round(int(ha[i:i + 2], 16) * (1 - t) + int(hb[i:i + 2], 16) * t) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(ch)


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
        "ctl_border": _mix(bg, c["muted"], 0.55), "ctl_border_hover": _mix(bg, fg, 0.7),
        "ctl_hover_bg": _mix(bg, fg, 0.1),
    }
    defs = "\n".join(f"@define-color {k} {v};" for k, v in named.items())
    return defs + "\n" + STATIC_CSS


STATIC_CSS = """
* { font-family: monospace; border-radius: 0; box-shadow: none; text-shadow: none; }
window, .background { background: @window_bg_color; }
headerbar { background: @window_bg_color; border-bottom: 1px solid @line; min-height: 40px; }
button, entry, searchentry, dropdown > button { background: transparent; border: 1px solid @ctl_border; color: @window_fg_color; padding: 0 12px; min-height: 28px; outline: none; }
entry, searchentry { padding: 0 8px; }
button:hover, entry:hover, searchentry:hover, dropdown > button:hover { background: @ctl_hover_bg; border-color: @ctl_border_hover; }
entry:focus-within, searchentry:focus-within { border-color: @accent_color; }
button.cta, button.suggested-action { color: @accent_color; border-color: @accent_color; }
button.cta:hover, button.suggested-action:hover { border-color: @accent_color; }
button.destructive-action { color: @destructive_bg_color; border-color: @destructive_bg_color; }
button.flat { border-color: transparent; }
button.flat:hover { border-color: @ctl_border_hover; }
button:checked, togglebutton:checked { background: @card_bg_color; border-color: @accent_color; color: @accent_color; }
windowcontrols > button { background: none; border: none; padding: 0; margin: 0 0 0 6px; min-width: 28px; min-height: 28px; }
windowcontrols > button > image { background: none; border: 1px solid @ctl_border; padding: 0; margin: 0; min-width: 28px; min-height: 28px; color: @window_fg_color; }
windowcontrols > button:hover > image { background: @ctl_hover_bg; border-color: @ctl_border_hover; }
windowcontrols > button.close:hover > image { color: @destructive_bg_color; border-color: @destructive_bg_color; }
searchentry > text, entry > text { min-height: 0; padding: 0; }
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
scale slider { background: @window_fg_color; min-width: 8px; min-height: 8px; margin: -4px; padding: 0; border: none; }
.seg.playing { background: @card_bg_color; border-left: 2px solid @accent_color; }
banner, .banner { background: @card_bg_color; border: 1px solid @line; padding: 6px 12px; }
"""
