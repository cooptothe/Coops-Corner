import unittest
from decimal import Decimal
from corner.book_policy import supported_book
from corner.collection_policy import Job, PROP_STANDARD, STANDARD
from corner.links import clean_url
from corner.pricing import fee_policy, reference_eligible
from pipelines.props_ingestion import BOOKS


class CashPropBooks(unittest.TestCase):
    def test_local_and_scheduled_requests_replace_dfs_without_new_credit_tier(self):
        requested=BOOKS.split(',')
        for book in ('williamhill_us','fanatics','betonlineag','bovada'):
            self.assertIn(book,requested)
            self.assertIn(book,PROP_STANDARD)
            self.assertTrue(reference_eligible(book))
            self.assertEqual(fee_policy(book).commission,Decimal(0))
        self.assertEqual(len(set(requested)),16)
        self.assertEqual(len(PROP_STANDARD),10)
        self.assertEqual(len(STANDARD),10)
        for book in ('prizepicks','underdog','pick6','dabble_us_dfs'):
            self.assertNotIn(book,requested)
            self.assertNotIn(book,PROP_STANDARD)
            self.assertFalse(supported_book(book))
            self.assertFalse(reference_eligible(book))

    def test_links_use_verified_cash_book_domains(self):
        for url,book in [('https://sportsbook.caesars.com/us/az/bet','williamhill_us'),
                         ('https://www.williamhill.com/us','williamhill_us'),
                         ('https://sportsbook.fanatics.com/bet','fanatics')]:
            self.assertEqual(clean_url(url,book),url)
        self.assertIsNone(clean_url('https://sportsbook.fanatics.com.evil.example/bet','fanatics'))
        self.assertIsNone(clean_url('https://sportsbook.caesars.com/bet','fanatics'))
        self.assertIsNone(clean_url('https://prizepicks.com/bet','prizepicks'))

if __name__=='__main__':unittest.main()
