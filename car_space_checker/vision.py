"""CPU inference using the public YOLOX small ONNX model."""
import base64
import hashlib
import io
from pathlib import Path
import urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from .parking import Detection

MODEL_URL = 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx'
MODEL_SHA256 = 'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
MODEL_PATH = Path('models/yolox_s.onnx')
Image.MAX_IMAGE_PIXELS = 16_000_000
LABELS = {0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}

def fetch_model():
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    target = MODEL_PATH.with_suffix('.download')
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            content = response.read(60_000_001)
        if hashlib.sha256(content).hexdigest() != MODEL_SHA256:
            raise ValueError('Model checksum mismatch; the download was not installed.')
        target.write_bytes(content)
        target.replace(MODEL_PATH)
    finally:
        target.unlink(missing_ok=True)
    return str(MODEL_PATH)

def read_image(data):
    if not data or len(data) > 10_000_000:
        raise ValueError('Supply a JPEG or PNG smaller than 10 MB.')
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in {'JPEG', 'PNG'} or min(image.size) < 64 or image.width * image.height > 16_000_000:
            raise ValueError('Use a JPEG/PNG of at least 64 pixels per side and at most 16 megapixels.')
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((1920, 1920))
        return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('The supplied file could not be read as a photo.') from exc

def quality_ok(image, zone):
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).polygon([(x*image.width, y*image.height) for x,y in zone.points], fill=255)
    pixels = np.asarray(image.convert('L'))[np.asarray(mask) > 0]
    return bool(len(pixels) and np.mean(pixels) > 15 and np.std(pixels) > 6 and np.mean(pixels > 250) < .7)

def decode_predictions(raw, input_size, image_size, ratio):
    height, width = input_size
    grids, scales = [], []
    for stride in (8, 16, 32):
        yy, xx = np.mgrid[:height//stride, :width//stride]
        grids.append(np.column_stack((xx.ravel(), yy.ravel())))
        scales.append(np.full((xx.size, 1), stride))
    prediction = np.asarray(raw[0], dtype=np.float32).copy()
    grid, scale = np.concatenate(grids), np.concatenate(scales)
    if prediction.shape != (len(grid), 85) or not np.isfinite(prediction).all():
        raise ValueError('Unexpected YOLOX output shape or values.')
    centres = (prediction[:, :2] + grid) * scale
    sizes = np.exp(np.clip(prediction[:, 2:4], -20, 20)) * scale
    scores_by_class = prediction[:, 4:5] * prediction[:, 5:]
    classes = scores_by_class.argmax(axis=1)
    scores = scores_by_class[np.arange(len(prediction)), classes]
    selected = np.flatnonzero(scores >= .25)
    boxes = np.column_stack((centres - sizes/2, centres + sizes/2)) / ratio
    img_width, img_height = image_size
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, img_width)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, img_height)
    candidates = list(selected[np.argsort(scores[selected])[::-1]][:300])
    kept = []
    while candidates:
        current = candidates.pop(0)
        a = boxes[current]
        area_a = (a[2]-a[0])*(a[3]-a[1])
        if area_a <= 0:
            continue
        kept.append(current)
        remaining = []
        for candidate in candidates:
            b = boxes[candidate]
            overlap = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0, min(a[3],b[3])-max(a[1],b[1]))
            union = area_a + (b[2]-b[0])*(b[3]-b[1]) - overlap
            if union > 0 and overlap / union <= .45:
                remaining.append(candidate)
        candidates = remaining
    return [Detection(LABELS.get(int(classes[i]), 'other object'), float(scores[i]),
                      tuple(float(v) for v in boxes[i] / [img_width,img_height,img_width,img_height])) for i in kept]

class Detector:
    def __init__(self):
        self.session = None

    def detect(self, image):
        if self.session is None:
            if not MODEL_PATH.exists():
                raise ValueError('Download the local model first: docker compose run --rm checker python -m car_space_checker fetch-model')
            if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
                raise ValueError('Model checksum mismatch. Run docker compose run --rm checker python -m car_space_checker fetch-model.')
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self.session = ort.InferenceSession(str(MODEL_PATH), options, providers=['CPUExecutionProvider'])
        model_input = self.session.get_inputs()[0]
        height, width = model_input.shape[2:]
        ratio = min(width/image.width, height/image.height)
        resized = image.resize((int(image.width*ratio), int(image.height*ratio)), Image.Resampling.BILINEAR)
        # YOLOX expects unnormalised BGR pixels, top-left aligned on 114 padding.
        pixels = np.full((height,width,3), 114, dtype=np.float32)
        pixels[:resized.height, :resized.width] = np.asarray(resized)[:, :, ::-1]
        tensor = np.ascontiguousarray(pixels.transpose(2,0,1)[None])
        output = self.session.run(None, {model_input.name: tensor})[0]
        return decode_predictions(output, (height,width), image.size, ratio)

def annotated_image(image, zone, detections):
    image = image.copy()
    draw = ImageDraw.Draw(image)
    points = [(int(x*image.width),int(y*image.height)) for x,y in zone.points]
    draw.line(points + points[:1], fill='#17c99b', width=4)
    for index, point in enumerate(points):
        draw.ellipse((point[0]-5,point[1]-5,point[0]+5,point[1]+5), fill='#17c99b')
        draw.text((point[0]+7,point[1]+5), str(index+1), fill='white', stroke_width=1, stroke_fill='black')
    for item in detections:
        coords = [item.box[0]*image.width,item.box[1]*image.height,item.box[2]*image.width,item.box[3]*image.height]
        colour = '#ffb454' if zone.overlaps(item) else '#a9b6c7'
        draw.rectangle(coords, outline=colour, width=3)
        draw.text((coords[0]+4, coords[1]+4), f'{item.label} {item.score:.0%}', fill=colour, stroke_width=1, stroke_fill='black')
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=85)
    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
