"""Native receiving-address validation. Checksums do not prove ownership/funding."""
import base64
import binascii
import hashlib
import re

XRP_ALPHABET = 'rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz'


def valid_address(asset, address):
    if not isinstance(address, str):
        return False
    if asset == 'XRP':
        if not 25 <= len(address) <= 35 or not address.startswith('r'):
            return False
        try:
            number = 0
            for char in address:
                number = number*58 + XRP_ALPHABET.index(char)
            data = number.to_bytes((number.bit_length()+7)//8, 'big')
            data = b'\0'*(len(address)-len(address.lstrip('r')))+data
            check = hashlib.sha256(hashlib.sha256(data[:-4]).digest()).digest()[:4]
            return len(data)==25 and data[0]==0 and data[-4:]==check
        except ValueError:
            return False
    if asset == 'XLM':
        if not re.fullmatch(r'G[A-Z2-7]{55}', address):
            return False
        try:
            data = base64.b32decode(address)
            return len(data)==35 and data[0]==48 and data[-2:]==binascii.crc_hqx(data[:-2],0).to_bytes(2,'little')
        except (ValueError, binascii.Error):
            return False
    if asset == 'HBAR':
        return bool(re.fullmatch(r'0\.0\.[1-9][0-9]{0,18}',address)) and int(address.split('.')[-1]) <= 2**63-1
    return False


def validate_receivers(config):
    """Strict configuration: three native coins, explicit memo review, off by default."""
    if not isinstance(config, dict) or type(config.get('payments_enabled')) is not bool:
        raise ValueError('Payment enablement must be explicit.')
    receivers = config.get('receiving')
    if not isinstance(receivers, dict) or set(receivers) != {'XRP','HBAR','XLM'}:
        raise ValueError('Configure exactly XRP, HBAR and XLM; ONDO is not accepted.')
    for asset, receiver in receivers.items():
        if not isinstance(receiver, dict) or set(receiver) != {'address','memo'} or not valid_address(asset,receiver['address']):
            raise ValueError(f'{asset} receiving address is invalid.')
        memo = receiver['memo']
        if memo is not None and (not isinstance(memo,str) or not 1<=len(memo)<=100):
            raise ValueError(f'{asset} memo/tag is invalid.')
        if asset=='XRP' and memo is not None and (not memo.isascii() or not memo.isdigit() or int(memo)>2**32-1):
            raise ValueError('XRP destination tag must be an unsigned 32-bit number.')
    if config['payments_enabled']:
        email = config.get('support_email')
        if not isinstance(email,str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
            raise ValueError('Configure a customer support email before enabling payments.')
        if config.get('memo_reviewed') is not True or config.get('receive_test_passed') is not True:
            raise ValueError('Memo review and supervised receive testing are still required.')
    return receivers
