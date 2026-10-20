"""Failing controls for the observed portrait distortion and native capture race."""
import math
import unittest

from tools.verify_desktop import avatar_geometry_valid


def portraits():
    return {name: dict(loaded=True, naturalWidth=768, naturalHeight=512,
            frameContentWidth=80, frameContentHeight=80, imageContentWidth=240,
            imageContentHeight=160, gridColumns=3, gridRows=2, objectFit="contain",
            image={"width": 240, "height": 160},
            overflowX="hidden", overflowY="hidden", src="/assets/" + name + ".jpg")
            for name in ("david", "lucy")}


class PortraitEvidenceTests(unittest.TestCase):
    def test_original_sprite_cell_keeps_aspect(self):
        self.assertTrue(avatar_geometry_valid(portraits()))

    def test_horizontally_stretched_image_rejected(self):
        data = portraits(); data["david"]["imageContentWidth"] = 480
        self.assertFalse(avatar_geometry_valid(data))

    def test_entire_sprite_shrunk_to_frame_rejected(self):
        data = portraits(); data["lucy"]["imageContentWidth"] = 80
        data["lucy"]["imageContentHeight"] = 80 * 2 / 3
        self.assertFalse(avatar_geometry_valid(data))

    def test_css_transform_stretch_rejected_even_when_computed_size_unchanged(self):
        data = portraits(); data["david"]["image"]["width"] = 480
        self.assertFalse(avatar_geometry_valid(data))

    def test_wide_frame_rejected(self):
        data = portraits(); data["david"]["frameContentWidth"] = 160
        self.assertFalse(avatar_geometry_valid(data))

    def test_unloaded_or_missing_portrait_rejected(self):
        data = portraits(); data["lucy"]["loaded"] = False
        self.assertFalse(avatar_geometry_valid(data))
        data = portraits(); del data["lucy"]
        self.assertFalse(avatar_geometry_valid(data))

    def test_external_source_and_distorting_fit_rejected(self):
        for field, value in (("src", "https://example.invalid/avatar.jpg"), ("objectFit", "fill"),
                             ("overflowX", "visible"), ("gridColumns", 2)):
            data = portraits(); data["david"][field] = value
            self.assertFalse(avatar_geometry_valid(data))

    def test_zero_and_nonfinite_geometry_rejected(self):
        for value in (0, -1, math.nan, math.inf, True, "80"):
            data = portraits(); data["david"]["frameContentWidth"] = value
            self.assertFalse(avatar_geometry_valid(data))


if __name__ == "__main__":
    unittest.main()
