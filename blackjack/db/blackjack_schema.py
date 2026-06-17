import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'blackjack.db')

# will create db if not existing
connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

# for TESTING ONLY
# cursor.execute('DROP TABLE IF EXISTS blackjack')

# in_game : a BOOLEAN value : 1-true 0-false
# dealer : if game is not finished (in_game should be 1) then store the cards of the dealer as csv
# player : if game is not finished (in_game should be 1) then store the cards of the player as csv
cursor.execute('''
    CREATE TABLE IF NOT EXISTS blackjack (
        user_id INTEGER PRIMARY KEY,
        in_game INTEGER NOT NULL DEFAULT(0) NOT NULL,
        current_bet numeric(50,2) DEFAULT(NULL),
        balance numeric(50,2) DEFAULT(100),
        wins INTEGER DEFAULT(0) NOT NULL,
        losses INTEGER DEFAULT(0) NOT NULL
    )
''')

connection.commit()
connection.close()

print("blackjack database created!")
