import sqlite3
from blackjack.db.blackjack_data_access import *
from blackjack.db.card_data_access import *

cursor = (connection).cursor()

user_id = 6969

def test_create_user_and_user_in_database():
    create_user(user_id)
    row = cursor.execute('SELECT * FROM blackjack WHERE user_id=?',(user_id,)).fetchall()

    if(len(row) != 1):
        raise ValueError('Error(test_create_user): error inserting new user')

    if(not user_in_database(user_id)):
        raise ValueError('Error(test_create_user): error checking if user exists')

    #delete the added tuple
    cursor.execute('DELETE FROM blackjack WHERE user_id=?',(user_id,))
    connection.commit()
    return

def test_contains_enough_money():
    bet = 100
    STARTING_AMOUNT = 100
    create_user(user_id)

    # Test when trying to bet all of our balance
    if(not contains_enough_money(user_id,bet)):
        raise ValueError(f'Error(test_contains_enough_money): says I do not have {bet} when I have {STARTING_AMOUNT}')
    # Test when trying to bet more than our balance
    if(contains_enough_money(user_id,2*bet)):
        raise ValueError(f'Error(test_contains_enough_money): says I have enough to bet {2*bet} when I have {STARTING_AMOUNT}')
    # Test when trying to bet less than our balance
    if(not contains_enough_money(user_id,bet/2)):
        raise ValueError(f'Error(test_contains_enough_money): says I do not have {bet} when I have {STARTING_AMOUNT}')

    #delete the added tuple
    cursor.execute('DELETE FROM blackjack WHERE user_id=?',(user_id,))
    connection.commit()

def test_start_new_game():
    bet = 100
    create_user(user_id)

    # start a new game by modifying in_game for user in blackjack table AND adds cards to cards table
    start_new_game(user_id,bet,[10,0],[3,2])

    # test if user in blackjack table has in_game set to 1
    row = cursor.execute('SELECT * FROM blackjack WHERE user_id=? AND in_game=1 AND current_bet=?',(user_id,bet)).fetchall()
    if(len(row) != 1):
        raise ValueError('Error(test_start_new_game): error creating new game')

    # test if cards are added to cards table
    expected_dealer_cards = [3,2]
    expected_user_cards = [10,0]
    result_dealer_cards = get_dealer_cards(user_id)
    result_user_cards = get_user_cards(user_id)

    if(expected_dealer_cards != result_dealer_cards or expected_user_cards != result_user_cards):
        print(result_dealer_cards)
        raise ValueError('Error(test_start_new_game): error adding cards to user/dealer')

    remove_cards(user_id)
    cursor.execute('DELETE FROM blackjack WHERE user_id=?',(user_id,))
    connection.commit()

def test_user_in_game():
    create_user(user_id)
    start_new_game(user_id, 100, [0,0], [0,0])
    if(not user_in_game(user_id)):
        raise ValueError('Error(test_user_in_game): says user is not in game when they should be in game')

    remove_cards(user_id)
    cursor.execute('DELETE FROM blackjack WHERE user_id=?',(user_id,))
    connection.commit()

def test_start_new_game_with_invalid_bet():
    create_user(user_id)
    try:
        start_new_game(user_id, 100, [0,0], [0,0])
        raise ValueError('Error(test_start_new_game_with_invalid_bet): created game with bet higher than balance')
    except ValueError:
        pass
    remove_cards(user_id)
    cursor.execute('DELETE FROM blackjack WHERE user_id=?', (user_id,))
    connection.commit()
    return

def test_get_user():
    in_game = 1
    current_bet = 1000
    balance = 10000
    wins = 60
    losses = 100
    cursor.execute('INSERT INTO blackjack (user_id, in_game, current_bet, balance, wins, losses) VALUES (?,?,?,?,?,?)',
                   (user_id,in_game,current_bet,balance,wins,losses))
    connection.commit()

    user = get_user(user_id)
    if(user.user_id != user_id
        or user.in_game != in_game
        or user.current_bet != current_bet
        or user.balance != balance
        or user.wins != wins
        or user.losses != losses):
        raise ValueError('Error(get_user): did not propertly retrieve all user info')

    cursor.execute('DELETE FROM blackjack WHERE user_id=?', (user_id,))
    connection.commit()
    return

def test_end_game():
    new_balance = 0
    new_wins = 0
    new_losses = 1

    create_user(user_id)
    start_new_game(user_id, 100, [0,0], [0,0])
    # user lost game
    end_game(user_id, new_balance, new_wins, new_losses)

    # check the blackjack table was modified correctly
    users = cursor.execute('''
        SELECT * FROM blackjack WHERE user_id=? AND in_game=0 AND balance=? AND wins=? AND losses=?
    ''',
    (user_id, new_balance, new_wins, new_losses)).fetchall()

    if(len(users) != 1):
        raise ValueError('Error(test_end_game): error ending blackjack game')

    # check that cards were removed
    if(( len(get_user_cards(user_id)) + len(get_dealer_cards(user_id)) ) != 0):
        raise ValueError('Error(test_end_game): error deleting all cards after game has ended')

    cursor.execute('DELETE FROM blackjack WHERE user_id=?', (user_id,))
    connection.commit()
    return

test_create_user_and_user_in_database()
test_contains_enough_money()
test_start_new_game()
test_user_in_game()
test_start_new_game_with_invalid_bet()
test_get_user()
test_end_game()
print("BLACKJACK/USERS DATA ACCESS TESTS FINISHED")