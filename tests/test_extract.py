import subprocess
import tempfile
import unittest
from pathlib import Path
from car_space_checker.__main__ import extract_frame

class ExtractTests(unittest.TestCase):
    def test_out_of_range_offset_cannot_return_a_previous_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'clip.mp4'; output=Path(directory)/'frame.jpg'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=64x64:d=1','-c:v','mpeg4',str(video)],check=True)
            extract_frame(video,0,output)
            original=output.read_bytes()
            with self.assertRaises(ValueError): extract_frame(video,20,output)
            self.assertEqual(output.read_bytes(),original)
            for offset in [-1,float('nan'),float('inf')]:
                with self.assertRaises(ValueError): extract_frame(video,offset,output)
