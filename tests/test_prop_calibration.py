import unittest
from copy import deepcopy
from decimal import Decimal as D
from pipelines.validate_prop_calibration import score


def sample(event, won):
    return dict(event_id=event, market='player_points', player='Player', line='24.5',
                predicted_at='2026-10-01T12:00:00Z', starts_at='2026-10-01T13:00:00Z',
                resolved_at='2026-10-01T16:00:00Z', probability='0.5', won=won,
                settlement='decisive', synthetic=False, outcome_source='unit-test-only', model_version='test')


class CalibrationEvaluationTests(unittest.TestCase):
    def test_hand_calculated_brier_and_log_loss(self):
        result = score([sample('a', 0), sample('b', 1)])
        self.assertEqual(D('.25'), D(result['brier']))
        self.assertAlmostEqual(float(result['log_loss']), .6931471805599453)
        self.assertEqual('0.5', result['reliability'][0]['observed_rate'])

    def test_rejects_empty_leaked_duplicate_and_unsettled_records(self):
        with self.assertRaises(ValueError):
            score([])
        row = sample('a', 1)
        with self.assertRaises(ValueError):
            score([row, row])
        for key, value in [('predicted_at','2026-10-01T14:00:00Z'), ('synthetic',True),
                           ('settlement','push'), ('won',2), ('probability','NaN')]:
            changed = deepcopy(row)
            changed[key] = value
            with self.assertRaises(ValueError):
                score([changed])
