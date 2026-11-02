"""Conservative image assessment and capture-time-based availability."""
from collections import deque
from dataclasses import dataclass
import math
from shapely.geometry import Polygon, box

VEHICLES = {'car', 'truck', 'bus', 'motorcycle', 'bicycle'}

@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box: tuple[float, float, float, float]

class Zone:
    def __init__(self, points):
        if not isinstance(points, list) or not 3 <= len(points) <= 20:
            raise ValueError('Mark between 3 and 20 zone corners.')
        if any(not isinstance(p, (list, tuple)) or len(p) != 2 or
               any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in p)
               for p in points):
            raise ValueError('Zone coordinates must be finite numbers between 0 and 1.')
        self.points = points
        self.polygon = Polygon(points)
        if not self.polygon.is_valid or self.polygon.area < .002:
            raise ValueError('The zone must have a useful area and no crossing edges.')

    def overlaps(self, detection):
        intersection = self.polygon.intersection(box(*detection.box)).area
        return intersection > 1e-8

def classify(zone, detections):
    uncertain = False
    for item in detections:
        if item.score < .25 or not zone.overlaps(item):
            continue
        if item.label in VEHICLES and item.score >= .55:
            return 'occupied'
        uncertain = True
    return 'uncertain' if uncertain else 'clear'

class Tracker:
    def __init__(self, max_age=120, confirmations=3, clear_seconds=10, max_gap=45):
        self.max_age = max_age
        self.confirmations = confirmations
        self.clear_seconds = clear_seconds
        self.max_gap = max_gap
        self.state = 'unknown'
        self.observed_at = None
        self.clear_since = None
        self.clear_count = 0
        self.ids = deque(maxlen=512)
        self.digests = deque(maxlen=512)
        self.reason = 'Waiting for fresh observations.'

    def observe(self, assessment, source_id, digest, observed_at, now):
        if assessment not in {'clear', 'occupied', 'uncertain'}:
            raise ValueError('Unknown assessment.')
        if not math.isfinite(observed_at) or not math.isfinite(now):
            raise ValueError('Capture time must be finite.')
        if not source_id or not digest:
            raise ValueError('A source ID and frame hash are required.')
        if (observed_at > now + 5 or now - observed_at >= self.max_age or
            (self.observed_at is not None and observed_at <= self.observed_at) or
            source_id in self.ids or digest in self.digests):
            return {**self.snapshot(now), 'accepted': False}
        if (self.observed_at is None or observed_at - self.observed_at > self.max_gap
            or now - self.observed_at >= self.max_age):
            self.clear_count = 0
            self.clear_since = None
        self.observed_at = observed_at
        self.ids.append(source_id)
        self.digests.append(digest)
        if assessment == 'clear':
            if self.clear_since is None:
                self.clear_since = observed_at
            self.clear_count += 1
            confirmed = self.clear_count >= self.confirmations and observed_at - self.clear_since >= self.clear_seconds
            self.state = 'available' if confirmed else 'unknown'
            self.reason = 'Clear observations confirmed.' if confirmed else 'Waiting for distinct clear observations over time.'
        else:
            self.clear_count = 0
            self.clear_since = None
            self.state = 'occupied' if assessment == 'occupied' else 'unknown'
            self.reason = 'Space obstructed.' if assessment == 'occupied' else 'The image does not establish a clear space.'
        return {**self.snapshot(now), 'accepted': True}

    def invalidate(self, reason):
        self.clear_count = 0
        self.clear_since = None
        self.state = 'unknown'
        self.reason = reason

    def snapshot(self, now):
        expired = self.observed_at is not None and now - self.observed_at >= self.max_age
        return {'state': 'unavailable' if expired else self.state,
                'reason': 'The latest observation has expired.' if expired else self.reason,
                'observed_at': self.observed_at,
                'clear_count': 0 if expired else self.clear_count}
