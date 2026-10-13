"""Reference-count policy shared by main-line and player-prop EV."""
SOCCER_SINGLE_REFERENCES = frozenset({'pinnacle', 'betfair_ex_uk', 'betfair_ex_eu', 'betfair_ex_au'})

def sufficient_references(books, sport_key='', *, player_props=False):
    books = tuple(books)
    return len(books) >= 2 or (sport_key.startswith('soccer_') and len(books) == 1
                             and (books[0] in SOCCER_SINGLE_REFERENCES
                                  or (player_props and books[0] == 'fanduel')))
