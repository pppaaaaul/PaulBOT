import sqlite3
import os
from enum import Enum

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'blackjack.db')

# will create db if not existing
connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

# for TESTING ONLY
# cursor.execute('DROP TABLE IF EXISTS cards')

class CARD_HOLDER(Enum):
    USER = 'USER',
    DEALER = 'DEALER'

cursor.execute('''
    CREATE TABLE IF NOT EXISTS cards (
        user_id INTEGER,
        holder VARCHAR(10),
        card INTEGER,
        
        CHECK(holder in ('USER','DEALER')),
        FOREIGN KEY (user_id) REFERENCES blackjack(id)
            ON DELETE CASCADE
    )
''')

connection.commit()
connection.close()

print("card database created!")