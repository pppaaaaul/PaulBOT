import sqlite3
import os
from blackjack.db.card_schema import CARD_HOLDER

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'blackjack.db')

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

# ASSUME : user is in blackjack database
# ASSUME : holder is a value of card_schema.CARD_HOLDER
def add_card(user_id, holder, card):
    cursor.execute('INSERT INTO cards (user_id, holder, card) VALUES (?, ?, ?)', (user_id, holder, card))
    connection.commit()
    return

def get_cards(user_id, holder):
    cards = []
    # each card value is returned in a tuple like (2,), (1,), etc.
    result = cursor.execute('SELECT card FROM cards WHERE user_id=? AND holder=?', (user_id, holder)).fetchall()
    for tuple in result:
        cards.append(tuple[0])
    return cards

def get_user_cards(user_id):
    return get_cards(user_id, CARD_HOLDER.USER.name)

def get_dealer_cards(user_id):
    return get_cards(user_id, CARD_HOLDER.DEALER.name)

# used for when game is over
def remove_cards(id):
    cursor.execute('DELETE FROM cards WHERE user_id=?', (id,))
    connection.commit()
    return
