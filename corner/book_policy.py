"""Books withdrawn from the product, including retained captures and overrides."""

REMOVED_BOOKS = frozenset({'betonlineag', 'betonline'})


def supported_book(book):
    return str(book).strip().lower() not in REMOVED_BOOKS


def supported_books(books):
    return tuple(book for book in books if supported_book(book))
