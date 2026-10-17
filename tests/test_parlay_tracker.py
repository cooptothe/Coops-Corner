import copy
import tempfile
import unittest
from corner.tracker_store import TrackerStore, TrackerError, profit_cents

def parlay(key='p1'):
    return dict(client_key=key, strategy='parlay', book='fanduel', matchup='2-leg parlay',
                selection='Cross-game parlay', odds='4', stake='25', legs=[
                    dict(key=f'leg-{i}', event_id=f'event-{i}', source='ev' if i == 0 else 'prop',
                         book='fanduel', matchup=f'A{i} at B{i}', starts_at='2030-01-01T20:00:00Z',
                         sport_key='basketball_nba', market='h2h' if i == 0 else 'player_points',
                         selection='Home' if i == 0 else 'Player Over 20.5', odds='2', ref={'game_id': f'event-{i}'})
                    for i in range(2)])

class ParlayTracker(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.db = TrackerStore(f'{temp.name}/tracker.sqlite3'); self.addCleanup(self.db.close)
        self.ledger = self.db.ledger(self.db.create_user('User', 'user', 'hash')['id'])

    def test_parent_stake_and_payout_are_counted_once_and_idempotent(self):
        first = self.ledger.add_bets([parlay()])[0]
        second = self.ledger.add_bets([parlay()])[0]
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(1, len(self.ledger.state()['bets']))
        self.assertEqual(2500, first['stake_cents'])
        self.assertEqual(2, len(first['legs']))
        self.assertTrue(all('stake_cents' not in leg for leg in first['legs']))
        won = self.ledger.settle_bet(first['id'], 'won')
        self.assertEqual(10000, won['returned_cents'])
        self.assertEqual(7500, profit_cents(won))

    def test_leg_results_do_not_settle_parent_cash_and_survive_notes_edit(self):
        saved = self.ledger.add_bets([parlay()])[0]
        graded = self.ledger.set_parlay_leg(saved['id'], 'leg-0', 'lost')
        self.assertEqual('pending', graded['status'])
        self.assertEqual('lost', graded['suggested_result'])
        self.assertIsNone(graded['returned_cents'])
        edited = self.ledger.update_bet(saved['id'], {'notes': 'Receipt checked'})
        self.assertEqual('lost', edited['legs'][0]['status'])

    def test_void_leg_requires_actual_return_and_preserves_it_after_edit(self):
        saved = self.ledger.add_bets([parlay()])[0]
        self.ledger.set_parlay_leg(saved['id'], 'leg-0', 'void')
        self.ledger.set_parlay_leg(saved['id'], 'leg-1', 'won')
        with self.assertRaises(TrackerError): self.ledger.settle_bet(saved['id'], 'won')
        won = self.ledger.settle_bet(saved['id'], 'won', returned='50')
        self.assertEqual(5000, won['returned_cents'])
        self.assertEqual(5000, self.ledger.update_bet(saved['id'], {'notes': 'One void leg'})['returned_cents'])

    def test_cross_book_and_duplicate_legs_are_rejected_atomically(self):
        for mutate in ('book', 'key'):
            item = parlay()
            if mutate == 'book': item['legs'][1]['book'] = 'draftkings'
            elif mutate == 'event': item['legs'][1]['event_id'] = item['legs'][0]['event_id']
            elif mutate == 'key': item['legs'][1]['key'] = item['legs'][0]['key']
            else: item['legs'][1]['matchup'] = item['legs'][0]['matchup']
            with self.assertRaises(TrackerError): self.ledger.add_bets([item])
        self.assertEqual([], self.ledger.state()['bets'])

    def test_same_game_uses_accepted_parent_quote_and_preserves_void_review(self):
        item=parlay()
        item['legs'][1]['event_id']=item['legs'][0]['event_id']
        item['legs'][1]['matchup']=item['legs'][0]['matchup']
        item['selection']='Same-game parlay';item['odds']='3.25'
        saved=self.ledger.add_bets([item])[0]
        self.assertEqual(saved['odds'],'3.25')
        self.assertEqual(self.ledger.add_bets([item])[0]['id'],saved['id'])
        self.ledger.set_parlay_leg(saved['id'],'leg-0','void')
        self.ledger.set_parlay_leg(saved['id'],'leg-1','won')
        with self.assertRaises(TrackerError):self.ledger.settle_bet(saved['id'],'won')
        self.assertEqual(self.ledger.settle_bet(saved['id'],'won',returned='40')['returned_cents'],4000)
        item['client_key']='sgp-won'
        second=self.ledger.add_bets([item])[0]
        self.assertEqual(self.ledger.settle_bet(second['id'],'won')['returned_cents'],8125)

    def test_conflicting_same_market_legs_rejected(self):
        item=parlay();item['legs'][1]={**item['legs'][0],'key':'opposite','selection':'Away'}
        with self.assertRaises(TrackerError):self.ledger.add_bets([item])

    def test_account_isolation_and_export_keep_child_legs(self):
        saved = self.ledger.add_bets([parlay()])[0]
        other = self.db.ledger(self.db.create_user('Other', 'other', 'hash')['id'])
        with self.assertRaises(TrackerError): other.set_parlay_leg(saved['id'], 'leg-0', 'won')
        self.assertEqual(saved['legs'], self.ledger.export()['bets'][0]['legs'])

    def test_pending_leg_reopen_and_cashout(self):
        saved = self.ledger.add_bets([parlay()])[0]
        cashed = self.ledger.settle_bet(saved['id'], 'cashout', returned='20')
        self.assertEqual(2000, cashed['returned_cents'])
        self.ledger.reopen_bet(saved['id'])
        self.assertEqual('won', self.ledger.set_parlay_leg(saved['id'], 'leg-1', 'won')['legs'][1]['status'])
