"""Live status and grading tests on box-score shapes taken from real ESPN responses. No network."""
import unittest

from corner import tracker_live as live


def event(away, home, state='post', score=(0, 0), date='2026-10-07T23:00Z', detail='Final', completed=True, name='STATUS_FINAL'):
    return {'date': date, 'competitions': [{'competitors': [
        {'homeAway': 'home', 'team': {'displayName': home}, 'score': str(score[1])},
        {'homeAway': 'away', 'team': {'displayName': away}, 'score': str(score[0])}],
        'status': {'type': {'state': state, 'shortDetail': detail, 'completed': completed, 'name': name}}}]}


def group(name, keys, rows):
    return {'name': name, 'keys': keys, 'athletes': [{'athlete': {'displayName': n}, 'stats': s} for n, s in rows]}


BASKETBALL = {'boxscore': {'players': [{'team': {}, 'statistics': [group('', [
    'minutes', 'points', 'fieldGoalsMade-fieldGoalsAttempted', 'threePointFieldGoalsMade-threePointFieldGoalsAttempted',
    'freeThrowsMade-freeThrowsAttempted', 'rebounds', 'assists', 'turnovers', 'steals', 'blocks'],
    [('Jaden McDaniels', ['21', '16', '6-10', '4-6', '0-0', '3', '0', '1', '1', '1']),
     ('Luka Dončić', ['36', '31', '11-22', '5-12', '4-5', '9', '8', '3', '2', '0'])])]}]}}

HOCKEY = {'boxscore': {'players': [{'team': {}, 'statistics': [
    group('forwards', ['blockedShots', 'goals', 'assists', 'shotsTotal'], [('Egor Chinakhov', ['0', '1', '2', '4'])]),
    group('goalies', ['goalsAgainst', 'shotsAgainst', 'saves'], [('Arturs Silovs', ['5', '27', '22'])])]}]}}

FOOTBALL = {'boxscore': {'players': [{'team': {}, 'statistics': [
    group('passing', ['completions/passingAttempts', 'passingYards', 'passingTouchdowns', 'interceptions'], [('Daniel Jones', ['19/34', '143', '0', '1'])]),
    group('rushing', ['rushingAttempts', 'rushingYards', 'longRushing'], [('Jonathan Taylor', ['20', '95', '12'])]),
    group('receiving', ['receptions', 'receivingYards'], [('Daniel Jones', ['1', '4'])])]}]}}

BASEBALL = {'boxscore': {'players': [{'team': {}, 'statistics': [
    {'name': '', 'type': 'batting', 'keys': ['hits', 'runs', 'RBIs', 'homeRuns'], 'athletes': [
        {'athlete': {'displayName': 'Steven Kwan'}, 'stats': ['1', '1', '1', '0']}]},
    {'name': '', 'type': 'pitching', 'keys': ['fullInnings.partInnings', 'hits', 'strikeouts'], 'athletes': [
        {'athlete': {'displayName': 'Daniel Espino'}, 'stats': ['5.2', '4', '7']}]}]}]}}


class Matching(unittest.TestCase):
    def test_team_spellings(self):
        for ours, theirs in (('Sam Houston State Bearkats', 'Sam Houston Bearkats'), ('Los Angeles Clippers', 'LA Clippers'),
                             ('Brighton and Hove Albion', 'Brighton & Hove Albion')):
            self.assertTrue(live.same_team(ours, theirs), ours)
        self.assertFalse(live.same_team('Texas State Bobcats', 'Montana State Bobcats'))
        self.assertFalse(live.same_team('Chicago Bears', 'Chicago Bulls'))

    def test_find_event_uses_start_time_for_doubleheaders(self):
        first = event('Cleveland Guardians', 'Chicago White Sox', date='2026-10-07T17:00Z')
        second = event('Cleveland Guardians', 'Chicago White Sox', date='2026-10-07T23:00Z')
        other = event('Tampa Bay Rays', 'New York Yankees')
        self.assertIs(live.find_event([other, first], 'Cleveland Guardians', 'Chicago White Sox'), first)
        self.assertIs(live.find_event([first, second], 'Cleveland Guardians', 'Chicago White Sox', '2026-10-07T23:05:00Z'), second)
        self.assertIsNone(live.find_event([first, second], 'Cleveland Guardians', 'Chicago White Sox', '2026-10-09T00:00:00Z'))
        self.assertIsNone(live.find_event([other], 'Cleveland Guardians', 'Chicago White Sox'))

    def test_status(self):
        pre = live.status_view(event('A', 'B', state='pre', detail='10/8 - 7:00 PM EDT', completed=False))
        self.assertEqual(pre['state'], 'pre')
        inplay = live.status_view(event('A', 'B', state='in', score=(55, 58), detail='4:12 - 3rd Quarter', completed=False))
        self.assertEqual((inplay['state'], inplay['score']), ('in', {'away': 55, 'home': 58}))
        self.assertTrue(live.status_view(event('A', 'B', state='post', completed=False))['state'] == 'in')
        self.assertTrue(live.status_view(event('A', 'B', state='pre', name='STATUS_POSTPONED'))['postponed'])


class Grading(unittest.TestCase):
    def test_moneyline_spread_and_total(self):
        score = {'away': 112, 'home': 123}
        self.assertEqual(live.grade_main('h2h', 'home', None, score), 'won')
        self.assertEqual(live.grade_main('h2h', 'away', None, score), 'lost')
        self.assertEqual(live.grade_main('h2h', 'home', None, {'away': 3, 'home': 3}), 'push')
        self.assertEqual(live.grade_main('h2h', 'draw', None, {'away': 1, 'home': 1}), 'won')
        # Home won by 11: -10.5 covers, -11 pushes, -11.5 does not; the away side mirrors it.
        self.assertEqual(live.grade_main('spreads', 'home', -10.5, score), 'won')
        self.assertEqual(live.grade_main('spreads', 'home', -11, score), 'push')
        self.assertEqual(live.grade_main('spreads', 'home', -11.5, score), 'lost')
        self.assertEqual(live.grade_main('spreads', 'away', 11.5, score), 'won')
        self.assertEqual(live.grade_main('totals', 'over', 234.5, score), 'won')
        self.assertEqual(live.grade_main('totals', 'over', 235.5, score), 'lost')
        self.assertEqual(live.grade_main('totals', 'under', 235, score), 'push')
        self.assertIsNone(live.grade_main('spreads', 'home', None, score))
        self.assertIsNone(live.grade_main('h2h', 'home', None, {'away': None, 'home': 3}))

    def test_over_under_on_a_stat(self):
        self.assertEqual(live.result_vs_line(6, 5.5, 'over'), 'won')
        self.assertEqual(live.result_vs_line(5, 5.5, 'over'), 'lost')
        self.assertEqual(live.result_vs_line(5, 5.5, 'under'), 'won')
        self.assertEqual(live.result_vs_line(5, 5, 'under'), 'push')


class BoxScores(unittest.TestCase):
    def stat(self, summary, sport, player, prop):
        return live.player_stat(summary, player, sport, prop)

    def test_basketball_including_combos_and_threes(self):
        self.assertEqual(self.stat(BASKETBALL, 'basketball_nba', 'Jaden McDaniels', 'player_points')[0], 16)
        self.assertEqual(self.stat(BASKETBALL, 'basketball_nba', 'Jaden McDaniels', 'player_threes')[0], 4)
        self.assertEqual(self.stat(BASKETBALL, 'basketball_nba', 'Luka Doncic', 'player_points_rebounds_assists')[0], 48)
        self.assertIsNone(self.stat(BASKETBALL, 'basketball_nba', 'Nobody Here', 'player_points'))
        self.assertIsNone(self.stat(BASKETBALL, 'basketball_nba', 'Jaden McDaniels', 'player_points_q1'))

    def test_hockey_uses_keys_not_misaligned_labels(self):
        self.assertEqual(self.stat(HOCKEY, 'icehockey_nhl', 'Egor Chinakhov', 'player_shots_on_goal')[0], 4)
        self.assertEqual(self.stat(HOCKEY, 'icehockey_nhl', 'Egor Chinakhov', 'player_points')[0], 3)
        self.assertEqual(self.stat(HOCKEY, 'icehockey_nhl', 'Arturs Silovs', 'player_total_saves')[0], 22)
        self.assertIsNone(self.stat(HOCKEY, 'icehockey_nhl', 'Arturs Silovs', 'player_goals'))  # goalies are not skaters

    def test_football_reads_the_right_group(self):
        self.assertEqual(self.stat(FOOTBALL, 'americanfootball_nfl', 'Daniel Jones', 'player_pass_yds')[0], 143)
        self.assertEqual(self.stat(FOOTBALL, 'americanfootball_nfl', 'Daniel Jones', 'player_pass_completions')[0], 19)
        self.assertEqual(self.stat(FOOTBALL, 'americanfootball_nfl', 'Daniel Jones', 'player_pass_attempts')[0], 34)
        # The same player appears in two groups; the market picks the group.
        self.assertEqual(self.stat(FOOTBALL, 'americanfootball_nfl', 'Daniel Jones', 'player_reception_yds')[0], 4)
        self.assertEqual(self.stat(FOOTBALL, 'americanfootball_nfl', 'Jonathan Taylor', 'player_rush_yds')[0], 95)

    def test_baseball_batters_and_pitchers(self):
        self.assertEqual(self.stat(BASEBALL, 'baseball_mlb', 'Steven Kwan', 'batter_hits_runs_rbis')[0], 3)
        self.assertEqual(self.stat(BASEBALL, 'baseball_mlb', 'Daniel Espino', 'pitcher_strikeouts')[0], 7)
        self.assertEqual(self.stat(BASEBALL, 'baseball_mlb', 'Daniel Espino', 'pitcher_outs')[0], 17)  # 5.2 innings
        self.assertIsNone(self.stat(BASEBALL, 'baseball_mlb', 'Steven Kwan', 'pitcher_strikeouts'))

    def test_support_flags(self):
        self.assertTrue(live.supports_prop('basketball_nba', 'player_points'))
        self.assertFalse(live.supports_prop('basketball_nba', 'player_double_double'))
        self.assertTrue(live.can_grade('icehockey_nhl'))
        self.assertFalse(live.can_grade('soccer_epl'))
        self.assertIsNone(live.espn_path('tennis_atp'))


class ForBet(unittest.TestCase):
    def bet(self, **ref):
        return {'sport_key': 'basketball_nba', 'ref': ref}

    def test_final_prop_suggests_a_result_from_the_box_score(self):
        ev = event('Minnesota Timberwolves', 'Indiana Pacers', score=(112, 123))
        out = live.live_for_bet(self.bet(prop_market='player_points', player='Jaden McDaniels', side='over', point=14.5),
                                ev, BASKETBALL)
        self.assertEqual((out['state'], out['progress']['value'], out['suggest']['result']), ('post', 16, 'won'))

    def test_in_progress_shows_progress_but_never_a_result(self):
        ev = event('A', 'B', state='in', score=(40, 42), detail='5:00 - 2nd', completed=False)
        out = live.live_for_bet(self.bet(prop_market='player_points', player='Jaden McDaniels', side='over', point=14.5), ev, BASKETBALL)
        self.assertEqual(out['progress']['value'], 16)
        self.assertIsNone(out['suggest'])

    def test_missing_player_gives_no_suggestion(self):
        ev = event('A', 'B', score=(100, 90))
        out = live.live_for_bet(self.bet(prop_market='player_points', player='Did Not Play', side='over', point=9.5), ev, BASKETBALL)
        self.assertIsNone(out['progress'])
        self.assertIsNone(out['suggest'])

    def test_main_market_total_progress_and_final(self):
        bet = self.bet(market_key='totals', side='over', point=230.5)
        mid = live.live_for_bet(bet, event('A', 'B', state='in', score=(60, 58), detail='Half', completed=False))
        self.assertEqual((mid['progress']['value'], mid['suggest']), (118, None))
        done = live.live_for_bet(bet, event('A', 'B', score=(112, 123)))
        self.assertEqual(done['suggest']['result'], 'won')

    def test_soccer_and_postponed_are_never_graded(self):
        soccer = {'sport_key': 'soccer_epl', 'ref': {'market_key': 'h2h', 'side': 'home'}}
        self.assertIsNone(live.live_for_bet(soccer, event('A', 'B', score=(0, 2)))['suggest'])
        off = live.live_for_bet({'sport_key': 'basketball_nba', 'ref': {'market_key': 'h2h', 'side': 'home'}},
                                event('A', 'B', state='post', name='STATUS_POSTPONED'))
        self.assertIsNone(off['suggest'])


if __name__ == '__main__':
    unittest.main()
