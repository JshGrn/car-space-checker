"""Experimental ground-plane calibration for a straight, flat parking strip."""
import math
import numpy as np
from shapely.geometry import LineString, Point, box
from .parking import Zone, VEHICLES

class Calibration:
    def __init__(self, corners, reference, clearance=.2):
        zone = Zone(corners)
        self.zone = zone
        if len(corners) != 4 or not zone.polygon.equals(zone.polygon.convex_hull):
            raise ValueError('Gap estimation needs four corners of a convex ground-plane rectangle.')
        vertices = np.asarray(corners, dtype=float)
        for i in range(4):
            a = vertices[(i+1)%4] - vertices[i]
            b = vertices[(i+2)%4] - vertices[(i+1)%4]
            if abs(a[0]*b[1] - a[1]*b[0]) < 1e-5:
                raise ValueError('Each of the four corners must be distinct and non-collinear.')
        if not isinstance(clearance, (int, float)) or not math.isfinite(clearance) or not 0 <= clearance <= 1:
            raise ValueError('Clearance must be between 0 and 100 percent of the reference car length.')
        if not isinstance(reference, list) or len(reference) != 2:
            raise ValueError('Mark both ends of the reference car on the ground plane.')
        for point in reference:
            if not isinstance(point, (list, tuple)) or len(point) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) or not zone.polygon.covers(Point(point)):
                raise ValueError('Both reference endpoints must lie inside the zone.')
        # Solve the eight homography parameters mapping the four ground corners
        # to a unit rectangle. The first two corners follow the kerb direction.
        rows, targets = [], []
        for (x, y), (u, v) in zip(corners, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            rows.extend([[x,y,1,0,0,0,-u*x,-u*y], [0,0,0,x,y,1,-v*x,-v*y]])
            targets.extend([u, v])
        try:
            self.matrix = np.append(np.linalg.solve(rows, targets), 1).reshape(3, 3)
        except np.linalg.LinAlgError as exc:
            raise ValueError('The zone corners cannot be calibrated.') from exc
        if not np.isfinite(self.matrix).all() or any(
            not np.allclose(self.project(p), target, atol=1e-6)
            for p,target in zip(corners, [(0,0),(1,0),(1,1),(0,1)])
        ):
            raise ValueError('The marked corners do not form a usable perspective calibration.')
        a, b = (self.project(p) for p in reference)
        span = abs(a[0] - b[0])
        if span < .05 or abs(a[1] - b[1]) > .25:
            raise ValueError('Mark the full car length parallel to the kerb, not across the road.')
        self.zone_length = 1 / span
        self.required_length = 1 + clearance

    def project(self, point):
        mapped = self.matrix @ [*point, 1]
        if abs(mapped[2]) < 1e-9:
            raise ValueError('Point is outside the usable perspective plane.')
        return mapped[:2] / mapped[2]

def charging_bounds(calibration, charging):
    if not isinstance(charging, dict):
        raise ValueError('Mark the rear charging range on the road plane.')
    def position(point):
        if (not isinstance(point, (list, tuple)) or len(point) != 2
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)
            or not calibration.zone.polygon.covers(Point(point))):
            raise ValueError('Charging markers must lie inside the parking zone on the road plane.')
        return float(calibration.project(point)[0] * calibration.zone_length)
    reach = charging.get('rear_range')
    if not isinstance(reach, list) or len(reach) != 2:
        raise ValueError('Mark two rear charging limits, from left to right.')
    lower, upper = map(position, reach)
    if upper - lower < .02:
        raise ValueError('Rear charging limits must run from left to right along the kerb.')
    preferred = charging.get('preferred')
    return lower, upper, position(preferred) if preferred is not None else (lower+upper)/2


def choose_placement(gaps, calibration, charging):
    lower, upper, preferred = charging_bounds(calibration, charging)
    margin = (calibration.required_length - 1) / 2
    candidates = []
    for start, end in gaps:
        if end-start < calibration.required_length:
            continue
        # Rear is left endpoint when facing right, right endpoint facing left.
        for facing, offset in [('right', 0), ('left', 1)]:
            left_min = max(start+margin, lower-offset)
            left_max = min(end-margin-1, upper-offset)
            if left_max + 1e-9 < left_min:
                continue
            left = max(left_min, min(left_max, preferred-.5))
            candidates.append((abs(left+.5-preferred), facing, left, left+offset, (start,end)))
    if not candidates:
        return None, None
    _, facing, left, rear, gap = min(candidates, key=lambda item:item[0])
    length = calibration.zone_length
    return {'facing':facing, 'rear':round(rear/length,4),
            'car_interval':[round(left/length,4),round((left+1)/length,4)]}, gap


def assess_gap(zone, calibration, detections, charging=None):
    intervals = []
    uncertain = False
    for item in detections:
        if item.score < .25 or not zone.overlaps(item):
            continue
        x1, y1, x2, y2 = item.box
        bottom = LineString([(x1, y2), (x2, y2)])
        base = bottom.intersection(zone.polygon)
        reliable_base = item.label in VEHICLES and item.score >= .55 and base.geom_type == 'LineString' and base.length >= .001 and zone.polygon.covers(bottom)
        if reliable_base:
            footprint = list(base.coords)
        else:
            # Reserve the entire occluded part of the zone. Uncertainty there
            # must not erase a separate, clearly visible gap elsewhere.
            uncertain = True
            footprint = list(zone.polygon.intersection(box(*item.box)).exterior.coords)
        positions = [calibration.project(p)[0] * calibration.zone_length for p in footprint]
        # Allow 5% of the reference car length at each detected vehicle end.
        intervals.append((max(0, min(positions) - .05), min(calibration.zone_length, max(positions) + .05)))
    cursor = 0.0
    gaps = []
    best = (0.0, 0.0)
    for start, end in sorted(intervals) + [(calibration.zone_length, calibration.zone_length)]:
        if start > cursor:
            gaps.append((cursor, start))
        if start - cursor > best[1] - best[0]:
            best = (cursor, start)
        cursor = max(cursor, end)
    placement = None
    if charging is not None:
        placement, selected = choose_placement(gaps, calibration, charging)
        if selected is not None:
            best = selected
    gap = best[1] - best[0]
    fits = gap >= calibration.required_length and (charging is None or placement is not None)
    placement_points = []
    if placement:
        inverse = np.linalg.inv(calibration.matrix)
        for x in placement['car_interval']:
            p = inverse @ [x, .5, 1]
            placement_points.append((p[:2]/p[2]).tolist())
    return {'assessment': 'clear' if fits else ('uncertain' if uncertain else 'occupied'),
            'gap_car_lengths': round(gap, 3), 'required_car_lengths': round(calibration.required_length, 3),
            'zone_car_lengths': round(calibration.zone_length, 3),
            'gap_interval': [round(v / calibration.zone_length, 4) for v in best],
            'placement': placement, 'placement_points': placement_points, 'charging_checked': charging is not None,
            'method': 'experimental_ground_plane'}
