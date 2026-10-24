"""Books withdrawn from the product, including retained captures and overrides."""

DFS_BOOKS = frozenset({'prizepicks', 'underdog', 'pick6', 'dabble_us_dfs'})
REMOVED_BOOKS = frozenset({'betonline'}) | DFS_BOOKS


def supported_book(book):
    return str(book).strip().lower() not in REMOVED_BOOKS


def supported_books(books):
    return tuple(book for book in books if supported_book(book))


def props_book_eligible(book):
    """Betfair stays in main markets but is withdrawn from all player-prop paths."""
    return supported_book(book) and not str(book).strip().lower().startswith('betfair_ex_')
