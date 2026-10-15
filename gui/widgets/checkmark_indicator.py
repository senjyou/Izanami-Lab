# -*- coding: utf-8 -*-
"""A real checkmark for ttk checkbuttons under the `clam` theme.

The problem
-----------
Tk's `clam` theme draws a selected checkbutton indicator as a filled box
containing a glyph that, at 16 px, reads as an "X" -- the opposite of what a
checkbox means. Verified by rendering it: the selected state is indistinguishable
from a cancel/close mark, while the radiobutton beside it correctly shows a filled
dot.

Why not just switch themes
--------------------------
`gui/app.py` tunes `clam` extensively -- buttons, entries, treeview, spinbox,
scrollbar -- against clam's element names and colours. Switching the app theme to
one that draws a checkmark (`alt`, `vista`, `winnative`, `xpnative`) would discard
that styling wholesale to fix one glyph.

What this does instead
----------------------
Replaces the indicator element alone. Tk cannot override a built-in element name
(`element_create` refuses with "Duplicate element"), so a NEW element name is
created and the checkbutton layout is pointed at it. That leaves every other clam
element untouched.

The tick is drawn with PIL at 4x and downsampled, because a 1-pixel-wide diagonal
stroke drawn directly at 15 px looks ragged; supersampling is what makes the glyph
read as a tick rather than as a smudge.
"""

import tkinter as tk
from tkinter import ttk

# Supersampling factor for the glyph. Drawing at 4x and downsampling gives clean
# diagonal strokes, which a direct 15 px render does not.
_SUPERSAMPLE = 4

# Base indicator size in pixels at scaling 1.0. Matches what clam uses, so the
# replacement occupies the same space and does not shift any layout.
_BASE_SIZE = 15

# Every generated image is retained here. Tk frees a PhotoImage as soon as the
# last Python reference goes, which would leave the indicator blank.
_IMAGE_REFS = []

# Element names must be unique per creation (Tk rejects a duplicate), so each
# install gets its own element. The STYLE name, however, is stable: widgets and
# call sites refer to it by name, and ttk re-reads a style's layout whenever the
# style changes, so re-installing simply updates what that one name draws.
_INSTALL_COUNT = 0

# The style whose layout is replaced. This is the BUILT-IN name on purpose: every
# ttk.Checkbutton in the app that has no explicit style resolves to it, so
# overriding it here gives them all the tick with no rebinding and no per-widget
# style name to keep in sync. (Verified that Tk accepts a layout override on a
# built-in name; only element_create refuses a duplicate.)
CHECKBUTTON_STYLE = "TCheckbutton"


def _indicator_size(widget):
    """The indicator's pixel size, following the display's Tk scaling."""
    try:
        scaling = float(widget.tk.call("tk", "scaling"))
    except (tk.TclError, TypeError, ValueError):
        scaling = 1.0
    # Clamp: a scaling below 1 should not shrink the glyph into illegibility, and
    # an extreme value should not produce a giant box.
    scaling = min(2.5, max(1.0, scaling))
    return max(_BASE_SIZE, int(round(_BASE_SIZE * scaling)))


def _make_images(size, surface, border, accent, accent_fg):
    """Build the unchecked and checked indicator images.

    Returns ``(unchecked, checked)`` as PhotoImages, or ``(None, None)`` when PIL
    is unavailable -- the caller then leaves the theme alone rather than crashing
    the style pass.
    """
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None, None

    big = size * _SUPERSAMPLE

    def blank():
        return Image.new("RGBA", (big, big), (0, 0, 0, 0))

    def frame(img, fill, outline):
        draw = ImageDraw.Draw(img)
        # Inset by one supersampled pixel so the outline is not clipped.
        draw.rectangle([0, 0, big - 1, big - 1], fill=fill, outline=outline,
                       width=_SUPERSAMPLE)
        return draw

    unchecked = blank()
    frame(unchecked, surface, border)

    checked = blank()
    draw = frame(checked, accent, accent)
    # The tick: a short down-stroke and a longer up-stroke, positioned by
    # proportion so the glyph stays centred at any size.
    width = max(2, big // 8)
    draw.line([(big * 0.24, big * 0.52), (big * 0.43, big * 0.71)],
              fill=accent_fg, width=width, joint="curve")
    draw.line([(big * 0.43, big * 0.71), (big * 0.77, big * 0.30)],
              fill=accent_fg, width=width, joint="curve")

    final = (size, size)
    return (ImageTk.PhotoImage(unchecked.resize(final, Image.LANCZOS)),
            ImageTk.PhotoImage(checked.resize(final, Image.LANCZOS)))


def install(style, scheme, widget):
    """Point the app's checkbuttons at a tick indicator.

    ``style`` is the app's ``ttk.Style``, ``scheme`` its colour dict and
    ``widget`` any widget on the same interpreter (used for scaling and as the
    image master). Safe to call repeatedly: each call replaces the previous
    indicator, which is what a light/dark switch needs.

    Returns True when the indicator was installed, False when it could not be
    (no PIL, or Tk refused the element), so the caller can carry on with the
    theme's own indicator rather than failing.

    Tk refuses to redefine a built-in ELEMENT name ("Duplicate element"), but it
    does allow the built-in LAYOUT name to be re-set. So a new element is created
    and the plain ``TCheckbutton`` layout is pointed at it -- which means every
    existing checkbutton picks the tick up with no rebinding and no per-widget
    style name to keep in sync.
    """
    global _INSTALL_COUNT

    size = _indicator_size(widget)
    unchecked, checked = _make_images(
        size,
        scheme.get("surface", "#e6e9ef"),
        scheme.get("border", "#bcc0cc"),
        scheme.get("accent", "#1e66f5"),
        scheme.get("accent_fg", "#ffffff"))
    if unchecked is None or checked is None:
        return False

    _INSTALL_COUNT += 1
    element = f"Tick.Checkbutton.indicator.{_INSTALL_COUNT}"

    try:
        style.element_create(element, "image", unchecked, ("selected", checked),
                             border=2, sticky="")
    except tk.TclError:
        return False

    try:
        style.layout(CHECKBUTTON_STYLE, [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                (element, {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w",
                                       "children": [
                                           ("Checkbutton.label",
                                            {"sticky": "nswe"})]}),
            ]}),
        ])
    except tk.TclError:
        return False

    _IMAGE_REFS.extend([unchecked, checked])
    return True
