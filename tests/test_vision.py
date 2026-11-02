import io
import unittest
import numpy as np
from PIL import Image
from car_space_checker.vision import read_image, decode_predictions, quality_ok
from car_space_checker.parking import Zone

class VisionTests(unittest.TestCase):
    def test_yolox_raw_cell_decodes_car_box_and_suppresses_duplicate(self):
        output = np.zeros((1, 3549, 85), dtype=np.float32)
        # Grid x=10, y=10, stride 8; predicted centre 84,84, size 32x32.
        for row in [530, 531]:
            output[0, row, :4] = [.5 if row == 530 else -.5, .5, np.log(4), np.log(4)]
            output[0, row, 4] = .9
            output[0, row, 7] = .9  # COCO car index 2.
        items = decode_predictions(output, (416,416), (416,416), 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, 'car')
        self.assertAlmostEqual(items[0].box[0], 68/416, places=5)
        self.assertAlmostEqual(items[0].score, .81, places=5)

    def test_bad_file_and_tiny_image_rejected(self):
        with self.assertRaises(ValueError):
            read_image(b'not a photo')
        stream = io.BytesIO()
        Image.new('RGB', (8, 8)).save(stream, format='PNG')
        with self.assertRaises(ValueError):
            read_image(stream.getvalue())

    def test_black_or_featureless_zone_cannot_be_treated_as_clear(self):
        self.assertFalse(quality_ok(Image.new('RGB', (200,200), 'black'), Zone([[0,0],[1,0],[1,1],[0,1]])))
        self.assertFalse(quality_ok(Image.new('RGB', (200,200), 'gray'), Zone([[0,0],[1,0],[1,1],[0,1]])))
