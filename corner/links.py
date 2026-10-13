"""Sportsbook links from The Odds API (event, market and betslip), validated before they are stored or shown.

The provider supplies these URLs, so none is trusted: each must be a plain https URL on a domain that belongs to
the sportsbook it is attached to. A few links contain placeholders the app fills in per user ({state}) or per bet
({wager}, {wagerAmount}, {pickType}); any other brace expression rejects the link.
"""
import re
from urllib.parse import urlsplit

PLACEHOLDERS = frozenset({'state', 'wager', 'wagerAmount', 'pickType'})
MAX_LENGTH = 2048
# Provider bookmaker key -> domains its links may use (the domain itself and any subdomain).
BOOK_DOMAINS = {
    'fanduel': ('fanduel.com',),
    'draftkings': ('draftkings.com',),
    'betmgm': ('betmgm.com',),
    'betrivers': ('betrivers.com',),
    'espnbet': ('thescore.bet', 'espnbet.com'),
    'novig': ('novig.com',),
    'prophetx': ('prophetx.co',),
    'kalshi': ('kalshi.com',),
    'pinnacle': ('pinnacle.com',),
    'betfair_ex_uk': ('betfair.com',),
    'betopenly': ('betopenly.com',),
    'polymarket': ('polymarket.com',),
    'prizepicks': ('prizepicks.com',),
    'underdog': ('underdogfantasy.com',),
}
_PLACEHOLDER = re.compile(r'\{([^{}]*)\}')
_HOST = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$')
_FORBIDDEN = re.compile(r'[\x00-\x20\x7f"\'<>\\^`]')
LEVELS = ('outcome', 'market', 'event')


def clean_url(value, book):
    """The URL unchanged if it is safe for this sportsbook, else None."""
    if not isinstance(value, str) or not value or len(value) > MAX_LENGTH or book not in BOOK_DOMAINS:
        return None
    names = _PLACEHOLDER.findall(value)
    if any(name not in PLACEHOLDERS for name in names):
        return None
    plain = _PLACEHOLDER.sub('x', value)
    if '{' in plain or '}' in plain or _FORBIDDEN.search(value.replace('{', '').replace('}', '')):
        return None
    try:
        parts = urlsplit(plain)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != 'https' or not host or port is not None or '@' in parts.netloc:
        return None
    if not _HOST.match(host) or not any(host == d or host.endswith('.' + d) for d in BOOK_DOMAINS[book]):
        return None
    return value


def clean_links(book, event=None, market=None, outcome=None):
    """{'event','market','outcome'} keeping only the valid links, or None when none survive."""
    cleaned = {name: clean_url(url, book) for name, url in (('event', event), ('market', market), ('outcome', outcome))}
    cleaned = {k: v for k, v in cleaned.items() if v}
    return cleaned or None


def link_rows(snapshot, bindings):
    """(outcome_id, sportsbook_id, event, market, outcome) for every quote that has at least one valid link.

    Several quotes can share an outcome and sportsbook only through a re-listing; the last one wins.
    """
    by_source = {b.source_pointer: b for b in bindings}
    rows = {}
    for quote in snapshot.quotes:
        links = clean_links(quote.bookmaker_key, quote.bookmaker_link, quote.market_link, quote.outcome_link)
        if not links:
            continue
        binding = by_source[quote.source_pointer]
        rows[(binding.outcome_id, binding.sportsbook_id)] = (
            binding.outcome_id, binding.sportsbook_id, links.get('event'), links.get('market'), links.get('outcome'))
    return list(rows.values())
