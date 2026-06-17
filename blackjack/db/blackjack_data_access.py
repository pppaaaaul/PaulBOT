import sqlite3
import os
from blackjack.db.card_data_access import *
from blackjack.db.blackjack_user import User

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'blackjack.db')

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

# TESTED
def create_user(user_id):
    cursor.execute('INSERT INTO blackjack (user_id) VALUES (?)', (user_id,))
    connection.commit()
    return

# TESTED
def user_in_database(user_id):
    users = cursor.execute('SELECT * FROM blackjack WHERE user_id=?',(user_id,)).fetchall()
    return len(users) > 0

# TESTED
# ASSUME : user is in database
def contains_enough_money(user_id, bet):
    # fetchall() returns a list of tuples, and we access the first value of the tuple with the 2nd [0]
    balance = cursor.execute('SELECT balance FROM blackjack WHERE user_id=?',(user_id,)).fetchall()[0][0]
    return not (balance < bet)

# TESTED
# ASSUME : user is in database
# Fails if user is not in game or the user is not even in database
def user_in_game(user_id):
    result = len(cursor.execute('SELECT * FROM blackjack WHERE user_id=? AND in_game=1', (user_id,)).fetchall())
    return result == 1

# TESTED
# ASSUME : user_cards/dealer_cards are an array of integers
def start_new_game(user_id, bet, user_cards, dealer_cards):
    if user_in_database(user_id) and contains_enough_money(user_id, bet):
        cursor.execute('''
            UPDATE blackjack
            SET in_game=1, current_bet=?
            WHERE user_id=?
        ''', (bet,user_id))
        connection.commit()

        for card in user_cards:
            add_card(user_id, CARD_HOLDER.USER.name, card)
        for card in dealer_cards:
            add_card(user_id, CARD_HOLDER.DEALER.name, card)
    else:
        raise ValueError('User does not exist, therefore cannot start new game with that user.')

def adjust_balance(user_id, new_balance):
    cursor.execute('''
            UPDATE blackjack
            SET balance=?
            WHERE user_id=?
        ''', (new_balance,user_id))
    connection.commit()
    return

# Returns all players as (user_id, balance), ranked by balance descending.
def get_moneyboard():
    return cursor.execute('SELECT user_id, balance FROM blackjack ORDER BY balance DESC').fetchall()

# TESTED
# returns a type db.blackjack_user.User object
def get_user(user_id):
    if user_in_database(user_id):
        user_tuple = cursor.execute('SELECT * FROM blackjack WHERE user_id=?', (user_id,)).fetchall()[0]
        return User(*user_tuple)
    else:
        raise ValueError('User does not exist, therefore cannot get that user.')

# ASSUME : there is actually an active game with the user
# TESTED
def end_game(user_id, new_balance, new_wins, new_losses):
    cursor.execute('''
        UPDATE blackjack
        SET in_game=0, current_bet=?, balance=?, wins=?, losses=?
        WHERE user_id=?
    ''', (None, new_balance, new_wins, new_losses, user_id))
    connection.commit()
    remove_cards(user_id)
    return