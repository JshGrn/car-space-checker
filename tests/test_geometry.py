import unittest
from car_space_checker.geometry import Calibration, assess_gap
from car_space_checker.parking import Detection, Zone

RECT = [[0, 0], [1, 0], [1, 1], [0, 1]]

class GapTests(unittest.TestCase):
    def calibration(self):
        return Calibration(RECT, [[.1, .5], [.5, .5]], .2)

    def test_reference_car_establishes_relative_zone_length(self):
        self.assertAlmostEqual(self.calibration().zone_length, 2.5)

    def test_contiguous_gap_not_sum_of_separate_gaps(self):
        detections = [Detection('car', .9, (.3, .2, .7, .8))]
        result = assess_gap(Zone(RECT), self.calibration(), detections)
        self.assertEqual(result['assessment'], 'occupied')
        self.assertAlmostEqual(result['gap_car_lengths'], .7)

    def test_gap_larger_than_reference_plus_clearance_is_clear(self):
        result = assess_gap(Zone(RECT), self.calibration(), [Detection('car', .9, (0, .2, .4, .8))])
        self.assertEqual(result['assessment'], 'clear')
        self.assertAlmostEqual(result['gap_car_lengths'], 1.45)

    def test_overlap_intervals_are_merged(self):
        result = assess_gap(Zone(RECT), self.calibration(), [Detection('car', .9, (0, .2, .3, .8)), Detection('bus', .9, (.2, .2, .6, .8))])
        self.assertAlmostEqual(result['gap_car_lengths'], .95)

    def test_perspective_maps_both_ends_of_same_kerb_rectangle(self):
        calibration = Calibration([[.2, .2], [.8, .2], [1, 1], [0, 1]], [[.2, .2], [.5, .2]], .2)
        self.assertAlmostEqual(calibration.zone_length, 2)
        self.assertAlmostEqual(calibration.project([.5, 1])[0], .5)

    def test_foreground_occluder_cannot_create_available_gap(self):
        zone = Zone([[.1, .1], [.9, .1], [.9, .7], [.1, .7]])
        calibration = Calibration(zone.points, [[.1, .4], [.5, .4]], .2)
        result = assess_gap(zone, calibration, [Detection('car', .9, (.4, .3, .6, .95))])
        self.assertEqual(result['assessment'], 'uncertain')

    def test_invalid_reference_or_dimensions_rejected(self):
        for reference, margin in [([[.1,.1],[.1,.9]], .2), ([[-1,.5],[.5,.5]], .2), ([[.1,.5],[.5,.5]], -1)]:
            with self.subTest(reference=reference, margin=margin), self.assertRaises(ValueError):
                Calibration(RECT, reference, margin)

class CalibrationDegeneracyRegression(unittest.TestCase):
    def test_collinear_corners_do_not_produce_a_fake_metric_scale(self):
        with self.assertRaises(ValueError):
            Calibration([[.2,.2],[.4,.4],[.6,.6],[.2,.8]], [[.2,.2],[.45,.45]], .2)

class LocalUncertaintyRegression(unittest.TestCase):
    def test_uncertain_object_in_occupied_end_does_not_hide_clear_gap_elsewhere(self):
        zone=Zone(RECT); calibration=Calibration(RECT,[[.1,.5],[.5,.5]],.2)
        detections=[Detection('car',.9,(0,.2,.4,.8)),Detection('car',.3,(.1,.1,.3,.7))]
        result=assess_gap(zone,calibration,detections)
        self.assertEqual(result['assessment'],'clear')
        self.assertAlmostEqual(result['gap_car_lengths'],1.45)

    def test_uncertain_object_inside_candidate_gap_prevents_clear(self):
        result=assess_gap(Zone(RECT),Calibration(RECT,[[.1,.5],[.5,.5]],.2),[Detection('car',.9,(0,.2,.4,.8)),Detection('person',.7,(.6,.1,.8,.8))])
        self.assertEqual(result['assessment'],'uncertain')

class ChargingPlacementTests(unittest.TestCase):
    def assess(self, reach, detections=(), preferred=None):
        calibration=Calibration(RECT,[[.1,.5],[.4,.5]],.2)
        return assess_gap(Zone(RECT),calibration,detections,charging={'rear_range':reach,'preferred':preferred})

    def test_large_gap_left_of_cable_reach_is_not_chargeable(self):
        result=self.assess([[.8,.5],[1,.5]],[Detection('car',.9,(.65,.1,1,.8))])
        self.assertEqual(result['assessment'],'occupied')
        self.assertIsNone(result['placement'])

    def test_left_facing_car_can_have_front_left_of_bin_but_rear_right(self):
        result=self.assess([[.65,.5],[.7,.5]],[Detection('car',.9,(.76,.1,1,.8))])
        self.assertEqual(result['assessment'],'clear')
        self.assertEqual(result['placement']['facing'],'left')
        self.assertGreaterEqual(result['placement']['rear'],.65)
        self.assertLess(result['placement']['car_interval'][0],.65)

    def test_right_facing_car_can_fit_when_left_facing_rear_cannot_reach(self):
        result=self.assess([[.3,.5],[.35,.5]],[Detection('car',.9,(0,.1,.24,.8))])
        self.assertEqual(result['placement']['facing'],'right')
        self.assertGreater(result['placement']['car_interval'][1],.35)

    def test_preferred_position_centres_car_in_front_of_wall(self):
        result=self.assess([[.1,.5],[.95,.5]],preferred=[.7,.5])
        start,end=result['placement']['car_interval']
        self.assertAlmostEqual((start+end)/2,.7,places=3)

    def test_invalid_rear_range_rejected(self):
        for reach in [[[.7,.5],[.2,.5]], [[-1,.5],[.9,.5]], [[.5,.5],[.5,.5]]]:
            with self.subTest(reach=reach), self.assertRaises(ValueError): self.assess(reach)

class ObstacleProjectionRegression(unittest.TestCase):
    def test_clipping_sloping_zone_must_not_shrink_a_car_to_its_front(self):
        zone=Zone([[0,0],[1,.2],[1,1],[0,.8]])
        calibration=Calibration(zone.points,[[.1,.42],[.5,.5]],.2)
        result=assess_gap(zone,calibration,[Detection('car',.9,(.1,.2,.8,.93))])
        self.assertNotEqual(result['assessment'],'clear')

    def test_small_area_overlap_cannot_disappear_from_candidate_gap(self):
        result=assess_gap(Zone(RECT),Calibration(RECT,[[.1,.5],[.2,.5]],0),[Detection('car',.99,(.4,.4,.5,.45))],charging={'rear_range':[[.4,.5],[.45,.5]],'preferred':[.45,.5]})
        self.assertNotEqual(result['assessment'],'clear')
