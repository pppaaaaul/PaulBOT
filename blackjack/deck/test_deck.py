from blackjack.deck import Deck

EXPECTED_DECK_LENGTH = 52

def test_create_deck():
    deck = Deck()
    if(deck.length() != EXPECTED_DECK_LENGTH):
        raise ValueError('Error(test_create_deck): deck is not expected length')
    return

def test_draw_card():
    deck = Deck()
    res = True

    card = deck.draw_card();
    if(card != 10 or deck.length() != EXPECTED_DECK_LENGTH - 1):
        raise ValueError('Error(test_draw_card): first drawn card is not 10 or deck is not expected length')

    # empty the deck, these cards should not be None
    for i in range(0,EXPECTED_DECK_LENGTH - 1):
        card = deck.draw_card()
        if (card == None):
            raise ValueError('Error(test_draw_card): card is None when it should not be')

    # should return None if deck is empty
    card = deck.draw_card();
    if(card != None):
        raise ValueError('Error(test_draw_card): card is not None when deck is empty')
    return

test_create_deck()
test_draw_card()
print("DECK TESTS FINISHED")