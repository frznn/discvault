"""Terminal rendering of cover art without terminal graphics protocols.

Pillow is an optional dependency (the ``images`` extra). Everything here
degrades to "unavailable" instead of raising at import time, so the TUI can
fall back to the system image opener.
"""
from __future__ import annotations

import io

from rich.style import Style
from rich.text import Text


def pillow_available() -> bool:
    """Return True when Pillow can be imported."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


# ``textual-image`` probes the terminal (cell size, graphics support) when it
# is first imported, which must happen before the Textual app takes over the
# terminal; imported lazily from inside a running app it blocks on the reply.
# So it is imported here, once, when the TUI module loads.
try:
    import textual_image.widget as _textual_image_widget  # noqa: F401
except Exception:  # missing extra, or a probe that fails: no graphics renderer
    _textual_image_widget = None


def textual_image_available() -> bool:
    """Return True when the ``textual-image`` widget (and Pillow) were imported."""
    return _textual_image_widget is not None


def low_resolution_renderer() -> bool:
    """Return True when the viewer can only draw the image from character cells.

    That is the case for Pillow half-blocks and for ``textual-image`` when the
    terminal supports neither the Kitty (``tgp``) nor the Sixel protocol.
    """
    if _textual_image_widget is None:
        return True
    try:
        from textual_image.renderable import Image as _Renderable
    except Exception:
        return True
    return _Renderable.__module__.rsplit(".", 1)[-1] not in {"tgp", "sixel"}


def viewer_available() -> bool:
    """Return True when the TUI can show an image itself (either renderer)."""
    return textual_image_available() or pillow_available()


def halfblock_text(data: bytes, max_cols: int, max_rows: int) -> Text:
    """Render image bytes as half-block characters fitted to a terminal box.

    Each text cell shows two vertically stacked pixels: the upper half block
    ``▀`` takes the top pixel as foreground and the bottom pixel as background,
    so a ``max_rows`` box has ``2 * max_rows`` pixel rows. The aspect ratio is
    preserved and the image is never enlarged past its own size.

    Raises ``ValueError`` when the bytes are not a decodable image and
    ``RuntimeError`` when Pillow is not installed.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is not installed") from exc

    max_cols = max(1, max_cols)
    max_rows = max(1, max_rows)
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ValueError(f"cannot decode image: {exc}") from exc

    # Flatten transparency onto black so alpha never reaches the terminal.
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    rgb = Image.alpha_composite(background, rgba).convert("RGB")

    width, height = rgb.size
    scale = min(max_cols / width, (max_rows * 2) / height, 1.0)
    new_w = max(1, int(width * scale))
    # Even pixel height so every text row has a top and a bottom pixel.
    new_h = max(2, int(height * scale) // 2 * 2)
    rgb = rgb.resize((new_w, new_h), Image.LANCZOS)
    pixels = rgb.load()

    text = Text(no_wrap=True, overflow="crop")
    for row in range(0, new_h, 2):
        for col in range(new_w):
            top = pixels[col, row]
            bottom = pixels[col, row + 1]
            text.append(
                "▀",
                Style(color=f"rgb({top[0]},{top[1]},{top[2]})",
                      bgcolor=f"rgb({bottom[0]},{bottom[1]},{bottom[2]})"),
            )
        if row + 2 < new_h:
            text.append("\n")
    return text
