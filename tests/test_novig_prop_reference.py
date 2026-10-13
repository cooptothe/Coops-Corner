import unittest
from corner.prop_markets import build_bets, SHARP_BOOKS, PROP_SHARP_BOOKS, _fair_first_side
from tests import test_prop_markets as fixtures

class NovigProps(unittest.TestCase):
    def test_novig_counts_for_props_and_remains_a_target(self):
        self.assertIn('novig', PROP_SHARP_BOOKS)
        self.assertNotIn('novig', SHARP_BOOKS)
        event = fixtures.FanDuelReference.stored({'novig': (1.91, 1.91), 'pinnacle': (1.91, 1.91),
                                       'fanduel': (1.91, 1.91), 'draftkings': (2.2, 1.65)})
        bets = build_bets({'e': event})
        self.assertTrue(any(b['book'] == 'novig' for b in bets))
        self.assertTrue(any(b['book'] == 'draftkings' and 'novig' in b['sharps'] for b in bets))
        self.assertTrue(all(b['book'] not in b['sharps'] for b in bets))

    def test_novig_does_not_get_soccer_single_reference_exception(self):
        self.assertEqual((None, []), _fair_first_side({'novig': {0: 1.91, 1: 1.91}}, sport_key='soccer_epl'))
