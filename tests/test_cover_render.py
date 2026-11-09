from __future__ import annotations

import io
import unittest

from discvault.ui.cover_render import halfblock_text, pillow_available


@unittest.skipUnless(pillow_available(), "Pillow not installed")
class HalfblockTextTests(unittest.TestCase):
    @staticmethod
    def _png(size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", size, color).save(buf, format="PNG")
        return buf.getvalue()

    def test_fits_box_and_keeps_aspect(self) -> None:
        text = halfblock_text(self._png((400, 400), (255, 0, 0, 255)), 40, 10)
        lines = text.plain.split("\n")
        # 10 rows = 20 pixel rows, so a square image is 20 pixels wide.
        self.assertEqual(len(lines), 10)
        self.assertTrue(all(len(line) == 20 for line in lines))

    def test_never_enlarges_small_images(self) -> None:
        text = halfblock_text(self._png((4, 4), (0, 255, 0, 255)), 80, 40)
        lines = text.plain.split("\n")
        self.assertEqual((len(lines), len(lines[0])), (2, 4))

    def test_transparent_pixels_flatten_to_black(self) -> None:
        text = halfblock_text(self._png((2, 2), (255, 255, 255, 0)), 10, 10)
        self.assertIn("rgb(0,0,0)", str(text.spans[0].style))

    def test_invalid_bytes_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            halfblock_text(b"not an image", 10, 10)


if __name__ == "__main__":
    unittest.main()
