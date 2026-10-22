import os
import sys
import unittest
from pathlib import Path

from PIL import Image


sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "badges"
BADGE_FILES = [
    "tn.png",
    "vipref.png",
    "sponsor.png",
    "beo.png",
    "team.png",
    "hostess.png",
]
EXPECTED_SIZE = (2480, 3496)
EXPECTED_ROW_CHANGES = [184, 196, 2285, 2297]
EXPECTED_COL_CHANGES = [184, 196, 586, 598, 3301, 3313]
FRAME_COLORS = {
    "tn.png": (102, 188, 68),
    "vipref.png": (225, 195, 110),
    "sponsor.png": (255, 255, 255),
    "beo.png": (182, 88, 163),
    "team.png": (37, 45, 96),
    "hostess.png": (160, 203, 238),
}
INNER_ARTWORK_BOX = (184, 184, 2297, 3313)


def _line_changes(get_pixel, length: int) -> list[int]:
    changes: list[int] = []
    previous = get_pixel(0)
    for index in range(1, length):
        current = get_pixel(index)
        if current != previous:
            changes.append(index)
            previous = current
    return changes


class BadgeAssetGeometryTests(unittest.TestCase):
    def test_category_frame_colors_are_correct(self) -> None:
        width, height = EXPECTED_SIZE
        frame_boxes = (
            (0, 0, width, 184),
            (0, 3313, width, height),
            (0, 184, 184, 3313),
            (2297, 184, width, 3313),
        )
        for name, color in FRAME_COLORS.items():
            with self.subTest(asset=name), Image.open(ASSET_DIR / name) as image:
                for box in frame_boxes:
                    self.assertEqual(
                        tuple((channel, channel) for channel in color),
                        image.convert("RGB").crop(box).getextrema(),
                    )

    def test_category_colors_do_not_change_logo_or_inner_artwork(self) -> None:
        with Image.open(ASSET_DIR / "sponsor.png") as reference:
            expected = reference.convert("RGB").crop(INNER_ARTWORK_BOX).tobytes()
        for name in BADGE_FILES:
            with self.subTest(asset=name), Image.open(ASSET_DIR / name) as image:
                self.assertEqual(
                    expected,
                    image.convert("RGB").crop(INNER_ARTWORK_BOX).tobytes(),
                )

    def test_all_badge_assets_exist_with_expected_size_and_new_margins(self) -> None:
        for name in BADGE_FILES:
            with self.subTest(asset=name):
                path = ASSET_DIR / name
                self.assertTrue(path.exists(), f"Badge asset missing: {path}")

                with Image.open(path) as image:
                    self.assertEqual(EXPECTED_SIZE, image.size)

                    pixels = image.load()
                    width, height = image.size

                    row_changes = _line_changes(lambda x: pixels[x, 1000], width)
                    col_changes = _line_changes(lambda y: pixels[300, y], height)

                self.assertEqual(EXPECTED_ROW_CHANGES, row_changes)
                self.assertEqual(EXPECTED_COL_CHANGES, col_changes)


if __name__ == "__main__":
    unittest.main()
