"""Reference-count policy shared by main-line and player-prop EV."""
SOCCER_SINGLE_REFERENCES = frozenset({'pinnacle', 'betfair_ex_uk', 'betfair_ex_eu', 'betfair_ex_au'})

def reference_source(book):
    # Regional views of the same Betfair exchange are not independent books.
    return 'betfair_exchange' if book in {'betfair_ex_uk','betfair_ex_eu','betfair_ex_au'} else book


def sufficient_references(books, sport_key='', *, player_props=False):
    books = tuple(books)
    sources={reference_source(b) for b in books}
    return len(sources) >= 2 or (not player_props and sport_key.startswith('soccer_')
                             and len(sources) == 1 and books and all(b in SOCCER_SINGLE_REFERENCES for b in books))
