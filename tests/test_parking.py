import unittest
from car_space_checker.parking import Detection, Zone, classify, Tracker

ZONE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]

class ZoneTests(unittest.TestCase):
    def test_vehicle_overlapping_edge_blocks_even_when_center_outside(self):
        self.assertEqual(classify(Zone(ZONE), [Detection('car', .9, (.7, .3, 1., .7))]), 'occupied')

    def test_vehicle_outside_zone_does_not_block(self):
        self.assertEqual(classify(Zone(ZONE), [Detection('car', .9, (0., 0., .1, .1))]), 'clear')

    def test_weak_vehicle_detection_and_person_occlusion_are_uncertain(self):
        for label, score in [('car', .35), ('person', .95)]:
            with self.subTest(label=label):
                self.assertEqual(classify(Zone(ZONE), [Detection(label, score, (.3, .3, .5, .5))]), 'uncertain')

    def test_self_crossing_out_of_bounds_and_tiny_zones_rejected(self):
        for points in [[[0, 0], [1, 1], [0, 1], [1, 0]], [[0, 0], [2, 0], [1, 1]], [[0, 0], [.001, 0], [0, .001]]]:
            with self.subTest(points=points), self.assertRaises(ValueError):
                Zone(points)

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker(max_age=120, confirmations=3, clear_seconds=10, max_gap=45)

    def observe(self, result='clear', observed_at=1000, source_id='a', digest='a', now=None):
        return self.tracker.observe(result, source_id, digest, observed_at, now if now is not None else observed_at)

    def confirm(self):
        self.observe(observed_at=1000)
        self.observe(observed_at=1005, source_id='b', digest='b')
        return self.observe(observed_at=1010, source_id='c', digest='c')

    def test_requires_three_distinct_observations_spanning_ten_seconds(self):
        self.assertEqual(self.observe()['state'], 'unknown')
        self.assertEqual(self.observe(observed_at=1005, source_id='b', digest='b')['state'], 'unknown')
        self.assertEqual(self.observe(observed_at=1010, source_id='c', digest='c')['state'], 'available')

    def test_repeated_id_or_frame_cannot_confirm_or_refresh(self):
        self.observe()
        self.observe(observed_at=1005, source_id='a', digest='different')
        result = self.observe(observed_at=1010, source_id='c', digest='a')
        self.assertEqual(result['clear_count'], 1)
        self.assertEqual(result['observed_at'], 1000)
        self.assertEqual(self.tracker.snapshot(1121)['state'], 'unavailable')

    def test_expiry_and_restart_do_not_restore_available(self):
        self.assertEqual(self.confirm()['state'], 'available')
        self.assertEqual(self.tracker.snapshot(1130)['state'], 'unavailable')
        self.assertEqual(Tracker().snapshot(1011)['state'], 'unknown')

    def test_old_or_future_capture_rejected_without_advancing_state(self):
        self.confirm()
        for capture, now in [(999, 1011), (1200, 1011), (800, 1011)]:
            result = self.observe('occupied', capture, str(capture), str(capture), now)
            self.assertEqual(result['observed_at'], 1010)
        self.assertEqual(self.tracker.snapshot(1011)['state'], 'available')

    def test_occupied_and_uncertain_immediately_remove_available(self):
        self.confirm()
        self.assertEqual(self.observe('occupied', 1011, 'd', 'd')['state'], 'occupied')
        self.assertEqual(self.observe('clear', 1012, 'e', 'e')['state'], 'unknown')
        self.assertEqual(self.observe('uncertain', 1013, 'f', 'f')['clear_count'], 0)

    def test_clear_streak_cannot_cross_long_gap(self):
        self.confirm()
        self.assertEqual(self.observe('clear', 1060, 'd', 'd')['state'], 'unknown')

    def test_same_capture_time_cannot_count_as_distinct_observation(self):
        self.observe()
        self.observe(source_id='b', digest='b')
        self.assertEqual(self.observe(source_id='c', digest='c')['clear_count'], 1)

    def test_rapid_burst_does_not_confirm_and_expired_streak_resets(self):
        self.observe()
        self.observe(observed_at=1001, source_id='b', digest='b')
        self.assertEqual(self.observe(observed_at=1002, source_id='c', digest='c')['state'], 'unknown')
        self.assertEqual(self.observe(observed_at=1200, source_id='d', digest='d')['clear_count'], 1)

if __name__ == '__main__':
    unittest.main()

class ExpiredStreakRegression(unittest.TestCase):
    def test_late_arriving_frame_cannot_revive_expired_clear_streak(self):
        tracker=Tracker()
        for timestamp in [1000,1005,1010]:
            tracker.observe('clear',str(timestamp),str(timestamp),timestamp,timestamp)
        self.assertEqual(tracker.snapshot(1130)['state'],'unavailable')
        result=tracker.observe('clear','late','late',1040,1131)
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['clear_count'],1)
