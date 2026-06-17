from blackjack.game.blackjack_utils import *
import blackjack.game.blackjack_utils as bu   # to rig the private _current_deck

user_id = 696969

def test_start_game():
    valid_bet = 100

    # Rig the deck so a natural blackjack can't be dealt. A real shuffle deals
    # ace+ten ~5-7% of the time, which ends the game immediately (in_game=0) and
    # made this test flaky. Restore the real Deck afterwards.
    original_deck = bu.Deck
    class FakeDeck:
        def __init__(self):
            self.cards = [2, 3, 5]   # user 2+3 (no ace, total 5); dealer 5
        def shuffle(self):
            pass
        def draw_card(self):
            return self.cards.pop(0)
    bu.Deck = FakeDeck
    try:
        start_game(user_id, valid_bet)

        expected = 1
        result = len(cursor.execute('SELECT * FROM blackjack WHERE user_id=? AND in_game=1 AND current_bet=? AND balance=100 AND wins=0 AND losses=0',(user_id, valid_bet)).fetchall())
        if expected != result:
            raise ValueError('Error(test_start_game), error starting creating the user and/or putting them in a game')

        # test that 3 cards (2 for user, 1 for dealer) were added to cards table
        expected = 3
        result = len(cursor.execute('SELECT * FROM cards WHERE user_id=?',(user_id,)).fetchall())
        if result != expected :
            raise ValueError('Error(test_start_game), error adding cards at start of game')

        end_game(user_id,100,0,0)
    finally:
        bu.Deck = original_deck
    return

def test_handle_blackjack():
    user = [0,10]

    # set the balance to 100 and current bet to 100
    cursor.execute('''
        UPDATE blackjack
        SET in_game=1, balance=100, current_bet=100
        WHERE user_id=?
    ''', (user_id,))
    connection.commit()
    # user and dealer bj, balance does not change
    dealer = [10,0]
    handle_user_blackjack(user_id, user, dealer)
    expected_balance = 100
    expected = 1
    result = len(cursor.execute('SELECT * FROM blackjack WHERE user_id=? AND balance=?',(user_id,expected_balance)).fetchall())
    if expected != result:
        raise ValueError('Error(test_handle_blackjack), error in handling case where both user and dealer have bj.')

    # set the balance to 100 and current bet to 100
    cursor.execute('''
        UPDATE blackjack
        SET in_game=1, balance=100, current_bet=100
        WHERE user_id=?
    ''', (user_id,))
    connection.commit()
    # user has bj but not dealer
    dealer = [10,1]
    handle_user_blackjack(user_id, user, dealer)
    expected_balance = 200 # +100 from win
    expected = 1
    result = len(cursor.execute('SELECT * FROM blackjack WHERE user_id=? AND balance=?',(user_id,expected_balance)).fetchall())
    if expected != result:
        raise ValueError('Error(test_handle_blackjack), error in handling case where user has bj but dealer does not.')

    return


test_start_game()
test_handle_blackjack()


# --- user_move tests -------------------------------------------------------
# These rig the private module-level deck (_current_deck) with a FakeDeck that
# draws a fixed sequence, so each hit/double/dealer draw is deterministic.

class FakeDeck:
    """Stand-in for Deck with a fixed draw order, for deterministic tests."""
    def __init__(self, cards):
        self.cards = list(cards)
    def draw_card(self):
        return self.cards.pop(0)

def setup_game(user_cards, dealer_cards, deck_cards, bet=10):
    # clean slate: fresh user with default balance 100
    cursor.execute('DELETE FROM blackjack WHERE user_id=?', (user_id,))
    cursor.execute('DELETE FROM cards WHERE user_id=?', (user_id,))
    connection.commit()
    create_user(user_id)
    start_new_game(user_id, bet, user_cards, dealer_cards)
    bu._current_deck = FakeDeck(deck_cards)

def teardown_game():
    cursor.execute('DELETE FROM blackjack WHERE user_id=?', (user_id,))
    cursor.execute('DELETE FROM cards WHERE user_id=?', (user_id,))
    connection.commit()
    bu._current_deck = None

def test_hit_bust():
    # user 10+9 = 19, hit draws 5 -> 24, bust loses the bet
    setup_game([10, 9], [10], [5])
    user_before = get_user(user_id)
    outcome = user_move(user_id, 1)        # hit
    user_after = get_user(user_id)
    # ended in a loss: game over, balance down by bet, losses +1, wins unchanged
    if outcome is None:
        raise ValueError('Error(test_hit_bust): game should have ended on a bust')
    if user_after.in_game != 0:
        raise ValueError('Error(test_hit_bust): in_game should be 0 after a bust')
    if user_after.balance != user_before.balance - 10:
        raise ValueError('Error(test_hit_bust): balance should drop by the bet on a bust')
    if user_after.losses != user_before.losses + 1 or user_after.wins != user_before.wins:
        raise ValueError('Error(test_hit_bust): losses should increment, wins unchanged')
    if bu._current_deck is not None:
        raise ValueError('Error(test_hit_bust): deck should be cleared after game ends')
    teardown_game()

def test_hit_continue():
    # user 5+4 = 9, hit draws 3 -> 12, no bust -> game continues
    setup_game([5, 4], [10], [3])
    balance_before = get_user(user_id).balance
    outcome = user_move(user_id, 1)
    if outcome is not None:
        raise ValueError(f'Error(test_hit_continue): expected game to continue, got {outcome}')
    user = get_user(user_id)
    if user.in_game != 1 or user.balance != balance_before:
        raise ValueError('Error(test_hit_continue): game/balance should be unchanged on a safe hit')
    if len(get_user_cards(user_id)) != 3:
        raise ValueError('Error(test_hit_continue): hit should add exactly one card')
    if bu._current_deck is None:
        raise ValueError('Error(test_hit_continue): deck must stay active while game continues')
    teardown_game()

def test_hit_ace_no_bust():
    # ace(0)+5 -> soft 16; hit draws 10, ace drops to 1 -> 16, no bust
    setup_game([0, 5], [10], [10])
    outcome = user_move(user_id, 1)
    if outcome is not None:
        raise ValueError(f'Error(test_hit_ace_no_bust): soft ace should not bust, got {outcome}')
    if get_user(user_id).in_game != 1:
        raise ValueError('Error(test_hit_ace_no_bust): game should continue with a soft hand')
    teardown_game()

def test_stand_win():
    # user 19; dealer [10] draws 6 -> 16, then 2 -> 18; user wins +bet
    setup_game([10, 9], [10], [6, 2])
    user_before = get_user(user_id)
    user_move(user_id, 2)                   # stand
    user_after = get_user(user_id)
    if user_after.in_game != 0:
        raise ValueError('Error(test_stand_win): in_game should be 0 after stand resolves')
    if user_after.balance != user_before.balance + 10:
        raise ValueError('Error(test_stand_win): balance should rise by the bet on a win')
    if user_after.wins != user_before.wins + 1 or user_after.losses != user_before.losses:
        raise ValueError('Error(test_stand_win): wins should increment, losses unchanged')
    teardown_game()

def test_stand_loss():
    # user 12; dealer [10] draws 7 -> 17 and stands; user loses -bet
    setup_game([5, 7], [10], [7])
    user_before = get_user(user_id)
    user_move(user_id, 2)                   # stand
    user_after = get_user(user_id)
    if user_after.in_game != 0:
        raise ValueError('Error(test_stand_loss): in_game should be 0 after stand resolves')
    if user_after.balance != user_before.balance - 10:
        raise ValueError('Error(test_stand_loss): balance should drop by the bet on a loss')
    if user_after.losses != user_before.losses + 1 or user_after.wins != user_before.wins:
        raise ValueError('Error(test_stand_loss): losses should increment, wins unchanged')
    teardown_game()

def test_double_win():
    # user 15, double draws 5 -> 20; dealer [10] draws 6 -> 16, 2 -> 18; win +doubled bet (20)
    setup_game([10, 5], [10], [5, 6, 2])
    user_before = get_user(user_id)
    user_move(user_id, 3)                   # double
    user_after = get_user(user_id)
    if user_after.in_game != 0:
        raise ValueError('Error(test_double_win): in_game should be 0 after double resolves')
    if user_after.balance != user_before.balance + 20:
        raise ValueError('Error(test_double_win): balance should rise by the doubled bet on a win')
    if user_after.wins != user_before.wins + 1 or user_after.losses != user_before.losses:
        raise ValueError('Error(test_double_win): wins should increment, losses unchanged')
    teardown_game()

test_hit_bust()
test_hit_continue()
test_hit_ace_no_bust()
test_stand_win()
test_stand_loss()
test_double_win()


# --- crash recovery tests --------------------------------------------------

def test_handle_crash():
    # user [10,9], dealer [10]: three cards dealt (two 10s, one 9)
    setup_game([10, 9], [10], [])
    bu._current_deck = None            # simulate a bot restart
    handle_crash(user_id)

    deck = bu._current_deck
    if deck is None:
        raise ValueError('Error(test_handle_crash): deck was not rebuilt')
    if len(deck.deck) != 52 - 3:
        raise ValueError('Error(test_handle_crash): rebuilt deck has wrong size')
    # two 10s and one 9 removed from a full deck
    if deck.deck.count(10) != 16 - 2 or deck.deck.count(9) != 4 - 1:
        raise ValueError('Error(test_handle_crash): dealt cards not removed correctly')
    teardown_game()

def test_user_move_recovers_from_crash():
    # deck is missing; a stand should trigger handle_crash internally and still end the game
    setup_game([10, 9], [10], [])
    bu._current_deck = None            # simulate a bot restart
    outcome = user_move(user_id, 2)    # stand
    if not isinstance(outcome, str):
        raise ValueError('Error(test_user_move_recovers_from_crash): stand should return an outcome after recovery')
    if get_user(user_id).in_game != 0:
        raise ValueError('Error(test_user_move_recovers_from_crash): game should end after stand')
    teardown_game()

test_handle_crash()
test_user_move_recovers_from_crash()

print("BLACKJACK TESTS FINISHED")