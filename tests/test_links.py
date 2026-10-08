import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from corner import links

# Real shapes taken from a retained capture.
REAL = {
    'fanduel': ('https://sportsbook.fanduel.com/addToBetslip?marketId=42.613592434&selectionId=3050859',
                'https://sportsbook.fanduel.com/basketball/wnba/atlanta-dream-%40-new-york-liberty-36151344'),
    'draftkings': ('https://sportsbook.draftkings.com/?outcomes=0ML86597623_3', 'https://sportsbook.draftkings.com/event/34775717'),
    'espnbet': ('https://sportsbook.thescore.bet/?market_selection_id[0]=f417b86d-acaa-4ca1-b21c-eb048ca8f1ef&odds_numerator[0]=2&odds_denominator[0]=1',
                'https://sportsbook.thescore.bet/sport/basketball/organization/united-states/competition/wnba/event/79024896'),
    'betmgm': ('https://sports.{state}.betmgm.com/en/sports?options=19984576-1563634753-2310737301&type=Single',
               'https://sports.{state}.betmgm.com/en/sports/events/atlanta-dream-at-new-york-liberty-19984576'),
    'novig': ('https://novig.com/events/01a11976-8d33-7b20-b856-ea002e83cd48/oddsapi/{wager}', 'https://novig.com/event-markets/01a11976'),
    'prophetx': ('https://www.prophetx.co/?action=addtobetslip&lineID=8ae9364a&partner_id=theoddsapi&currency=cash',
                 'https://www.prophetx.co/basketball/wnba/atlanta-dream-vs-new-york-liberty-1700100021?currency=cash'),
    'betrivers': ('https://{state}.betrivers.com/?page=sportsbook#event/1029333399?coupon={pickType}|4366462176|{wagerAmount}',
                  'https://{state}.betrivers.com/?page=sportsbook#event/1029333399'),
}


class CleanUrl(unittest.TestCase):
    def test_real_provider_links_pass_unchanged(self):
        for book, urls in REAL.items():
            for url in urls:
                self.assertEqual(links.clean_url(url, book), url, (book, url))

    def test_rejects_unsafe_or_foreign_links(self):
        ok = 'https://sportsbook.fanduel.com/x'
        bad = [
            'http://sportsbook.fanduel.com/x', 'javascript:alert(1)', 'data:text/html,hi', '//sportsbook.fanduel.com/x',
            'https://evil.example/x', 'https://fanduel.com.evil.example/x', 'https://notfanduel.com/x',
            'https://user:pw@sportsbook.fanduel.com/x', 'https://sportsbook.fanduel.com:8443/x',
            'https://sportsbook.fanduel.com/x y', 'https://sportsbook.fanduel.com/x"onclick=1', 'https://sportsbook.fanduel.com/<x>',
            'https://sportsbook.fanduel.com/x\\y', 'https://{evil}.fanduel.com/x', 'https://sportsbook.fanduel.com/{evil}',
            'https://sportsbook.fanduel.com/{state', 'https://' + 'a' * 3000 + '.fanduel.com', '', None, 5, ['x'],
            'https://sportsbook.fanduel.com/\n', 'https://.fanduel.com/x', 'ftp://sportsbook.fanduel.com/x',
        ]
        self.assertEqual(links.clean_url(ok, 'fanduel'), ok)
        for url in bad:
            self.assertIsNone(links.clean_url(url, 'fanduel'), repr(url)[:70])

    def test_a_link_must_belong_to_its_own_sportsbook(self):
        self.assertIsNone(links.clean_url('https://sportsbook.draftkings.com/x', 'fanduel'))
        self.assertIsNone(links.clean_url('https://sportsbook.fanduel.com/x', 'unknown_book'))

    def test_placeholders_may_only_be_the_known_ones(self):
        self.assertEqual(links.clean_url('https://sports.{state}.betmgm.com/a?b={wager}&c={wagerAmount}&d={pickType}', 'betmgm'),
                         'https://sports.{state}.betmgm.com/a?b={wager}&c={wagerAmount}&d={pickType}')
        self.assertIsNone(links.clean_url('https://sports.{State}.betmgm.com/a', 'betmgm'))
        self.assertIsNone(links.clean_url('https://sports.{}.betmgm.com/a', 'betmgm'))


class CleanLinks(unittest.TestCase):
    def test_keeps_only_valid_levels(self):
        got = links.clean_links('fanduel', 'https://sportsbook.fanduel.com/e', 'https://evil.example/m', 'https://sportsbook.fanduel.com/o')
        self.assertEqual(got, {'event': 'https://sportsbook.fanduel.com/e', 'outcome': 'https://sportsbook.fanduel.com/o'})
        self.assertIsNone(links.clean_links('fanduel', None, 'http://x', 5))


class Rows(unittest.TestCase):
    def test_rows_pair_each_quote_with_its_bound_outcome_and_book(self):
        quote = lambda pointer, book, ev, mk, oc: NS(source_pointer=pointer, bookmaker_key=book, bookmaker_link=ev, market_link=mk, outcome_link=oc)
        snapshot = NS(quotes=[
            quote('/a', 'fanduel', REAL['fanduel'][1], None, REAL['fanduel'][0]),
            quote('/b', 'pinnacle', None, None, None),
            quote('/c', 'draftkings', 'https://evil.example/e', None, None),
            quote('/d', 'betmgm', REAL['betmgm'][1], None, REAL['betmgm'][0]),
        ])
        bindings = [NS(source_pointer=p, outcome_id=f'o{i}', sportsbook_id=f's{i}') for i, p in enumerate('/a /b /c /d'.split())]
        rows = links.link_rows(snapshot, bindings)
        self.assertEqual([r[:2] for r in rows], [('o0', 's0'), ('o3', 's3')])
        self.assertEqual(rows[0][2:], (REAL['fanduel'][1], None, REAL['fanduel'][0]))


if __name__ == '__main__':
    unittest.main()
