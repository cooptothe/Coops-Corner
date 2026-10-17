import json
from pathlib import Path
import unittest
from corner.beta_receiving import valid_address, validate_receivers

CONFIG = Path(__file__).resolve().parents[1]/'fixtures/billing/receiving-disabled.json'


class Receiving(unittest.TestCase):
    def test_supplied_native_addresses_pass_format_checks(self):
        config = json.loads(CONFIG.read_text())
        self.assertEqual(set(validate_receivers(config)), {'XRP','HBAR','XLM'})
        self.assertFalse(config['payments_enabled'])

    def test_corrupted_and_wrong_network_addresses_are_rejected(self):
        receivers = json.loads(CONFIG.read_text())['receiving']
        for asset in ('XRP','XLM'):
            address = receivers[asset]['address']
            self.assertFalse(valid_address(asset,address[:-1]+('1' if asset=='XRP' else 'A')))
        self.assertFalse(valid_address('HBAR','0.0.0'))
        self.assertFalse(valid_address('HBAR','0.0.9223372036854775808'))
        self.assertFalse(valid_address('ONDO',receivers['XRP']['address']))
        self.assertFalse(valid_address('XRP',receivers['XLM']['address']))

    def test_config_cannot_enable_without_receive_test_and_support(self):
        config = json.loads(CONFIG.read_text())
        config['payments_enabled'] = True
        config['support_email'] = ''
        with self.assertRaises(ValueError): validate_receivers(config)
        config['support_email'] = 'test@example.invalid'
        with self.assertRaises(ValueError): validate_receivers(config)
        config.update(memo_reviewed=True,receive_test_passed=True)
        self.assertEqual(len(validate_receivers(config)),3)

    def test_ondo_and_invalid_tag_are_not_silently_accepted(self):
        config = json.loads(CONFIG.read_text())
        config['receiving']['ONDO'] = config['receiving']['XRP']
        with self.assertRaises(ValueError): validate_receivers(config)
        del config['receiving']['ONDO']
        config['receiving']['XRP']['memo'] = 'not-a-number'
        with self.assertRaises(ValueError): validate_receivers(config)
