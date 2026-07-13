import base64
import unittest

import numpy as np

from app.services.road_mask import encode_mask_data_url, road_class_ids


class RoadMaskServiceTests(unittest.TestCase):
    def test_only_road_labels_are_selected(self):
        labels = {0: "road", 1: "sidewalk", 2: "building", 3: "Road"}

        self.assertEqual(road_class_ids(labels), {0, 3})

    def test_mask_is_encoded_as_a_png_data_url(self):
        mask = np.array([[0, 255], [255, 0]], dtype=np.uint8)

        data_url = encode_mask_data_url(mask)

        self.assertTrue(data_url.startswith("data:image/png;base64,"))
        self.assertGreater(len(base64.b64decode(data_url.split(",", 1)[1])), 8)


if __name__ == "__main__":
    unittest.main()
