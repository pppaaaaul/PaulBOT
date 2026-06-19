from blackjack.db.blackjack_data_access import *
from blackjack.deck.deck import Deck

ACE = 0

# The deck for the single active game. Only one user plays at a time, so a
# single module-level deck is safe (it is cleared whenever a game ends).
_current_deck = None

def start_game(user_id, valid_bet):
    if not user_in_database(user_id):
        create_user(user_id)
    
    if user_in_game(user_id):
        raise Exception('You are already in a game.')

    if not contains_enough_money(user_id,valid_bet):
        raise Exception(f'Error, you cannot bet more than your balance.')

    global _current_deck
    _current_deck = Deck()
    _current_deck.shuffle()

    dealer = []
    user = []

    # give dealer and user cards
    user.append(_current_deck.draw_card())
    user.append(_current_deck.draw_card())
    dealer.append(_current_deck.draw_card())

    start_new_game(user_id, valid_bet, user, dealer)

    # handle blackjack and end game
    if 0 in user and sum(user) == 10:
        # reveal second card for dealer
        dealer_draw = _current_deck.draw_card()
        dealer.append(dealer_draw)
        add_card(user_id, CARD_HOLDER.DEALER.name, dealer_draw)
        end_msg = handle_user_blackjack(user_id, user, dealer)
        return end_msg

    return None

# Blackjack is only possible at the very start of game before any hits and stands.
def handle_user_blackjack(user_id, user, dealer):
    user = get_user(user_id)

    if 0 in dealer and sum(dealer) == 10:
        # dealer has blackjack
        resulting_hand = _finish(user_id, user.balance, user.wins, user.losses)
        return f"User and dealer has blackjack, game tied...🎀\n{resulting_hand}"
    else:
        # dealer does not have blackjack
        resulting_hand = _finish(user_id, user.balance + user.current_bet, user.wins + 1, user.losses)
        return f"User has blackjack, game won!✅\n{resulting_hand}"

# Sums a hand. Aces (ACE) count as 11, dropping to 1 while the total is over 21.
def hand_value(cards):
    total = 0
    aces = 0
    for card in cards:
        if card == ACE:
            aces += 1
            total += 11
        else:
            total += card
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

# Formats a hand for display: "1, 0, 5 (7 or 17)" when an ace can count as 11,
# "10, 6 (16)" otherwise. The two totals are shown only when an ace fits without
# busting; otherwise a single value is shown.
def hand_display(cards):
    cards_str = ', '.join(map(str, cards))
    high = hand_value(cards)                                       # best total (ace as 11 where it fits)
    low = sum(1 if card == ACE else card for card in cards)        # every ace counted as 1
    total = f'{low} or {high}' if low != high else f'{high}'
    return f'{cards_str} ({total})'

# Dealer draws until its hand value is 17 or higher.
def _dealer_play(user_id):
    while hand_value(get_dealer_cards(user_id)) < 17:
        add_card(user_id, CARD_HOLDER.DEALER.name, _current_deck.draw_card())
    return

# Compares player vs dealer totals and ends the game. bet is the amount wagered.
def _resolve(user_id, bet):
    user = get_user(user_id)
    user_total = hand_value(get_user_cards(user_id))
    dealer_total = hand_value(get_dealer_cards(user_id))

    if dealer_total > 21:
        resulting_hand = _finish(user_id, user.balance + bet, user.wins + 1, user.losses)
        return f'dealer busts! you win.✅\n{resulting_hand}'
    elif user_total > dealer_total:
        resulting_hand = _finish(user_id, user.balance + bet, user.wins + 1, user.losses)
        return f'you win.✅\n{resulting_hand}'
    elif user_total < dealer_total:
        resulting_hand = _finish(user_id, user.balance - bet, user.wins, user.losses + 1)
        return f'you lose.❌\n{resulting_hand}'
    else:
        resulting_hand = _finish(user_id, user.balance, user.wins, user.losses)
        return f'Game tied.🎀\n{resulting_hand}'

# Ends the game (updates blackjack row, clears cards) and releases the deck.
def _finish(user_id, new_balance, new_wins, new_losses):
    global _current_deck
    resulting_hands = (
        f'DEALER: {hand_display(get_dealer_cards(user_id))}\n'
        f'USER: {hand_display(get_user_cards(user_id))}\n'
        f'Your balance is now: {new_balance}.'
    )
    end_game(user_id, new_balance, new_wins, new_losses)
    _current_deck = None
    # returns a string of the hands
    return resulting_hands

# Rebuilds the in-memory deck after a bot restart. The full deck minus the cards
# already held by the user and dealer is reshuffled; this is probability-
# equivalent to the original deck for every future draw.
def handle_crash(user_id):
    global _current_deck
    deck = Deck()
    for card in get_user_cards(user_id) + get_dealer_cards(user_id):
        deck.deck.remove(card)
    deck.shuffle()
    _current_deck = deck
    return

# Returns the user_id of the one player currently in a game, or None if nobody is.
def get_active_player():
    row = cursor.execute('SELECT user_id FROM blackjack WHERE in_game = 1').fetchall()
    return row[0][0] if row else None

# moves - 1(hit), 2(stand), 3(double)
def user_move(user_id, move):
    # ASSUMES user is in game / in_game = 1
    global _current_deck
    if _current_deck is None:
        # The in-memory deck was lost (e.g. bot restarted mid-game); rebuild it.
        handle_crash(user_id)

    user = get_user(user_id)
    bet = user.current_bet

    if move == 1:        # hit
        add_card(user_id, CARD_HOLDER.USER.name, _current_deck.draw_card())

        if hand_value(get_user_cards(user_id)) > 21:
            resulting_hand = _finish(user_id, user.balance - bet, user.wins, user.losses + 1)
            return f'bust! you lose.❌\n{resulting_hand}'
        # not bust -> game continues, player may move again
        return

    elif move == 2:      # stand
        _dealer_play(user_id)
        return _resolve(user_id, bet)

    elif move == 3:      # double
        bet = user.current_bet * 2
        if not contains_enough_money(user_id, bet):
            raise Exception('Error, you do not have enough money to double.')
        add_card(user_id, CARD_HOLDER.USER.name, _current_deck.draw_card())

        if hand_value(get_user_cards(user_id)) > 21:
            resulting_hand =_finish(user_id, user.balance - bet, user.wins, user.losses + 1)
            return f'bust after double! you lose.❌\n{resulting_hand}'
        _dealer_play(user_id)
        return _resolve(user_id, bet)

    else:
        raise Exception('Error, an invalid move was made in blackjack.')
