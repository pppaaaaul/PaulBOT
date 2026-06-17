import csv
import random
import os

class Deck:
    DECK_DATA_FILE = os.path.join(os.path.dirname(__file__), 'cards_data.txt')

    def __init__(self):
        self.deck = self.create_deck()

    # TESTED
    # Can be recalled to recreate the deck with the same cards.
    def create_deck(self):
        deck = []
        with open(self.DECK_DATA_FILE) as csvfile:
            reader = csv.reader(csvfile)

            # each row is now an array of values
            for row in reader:
                for card in row:
                    # ASSUMES that deck values are integers
                    deck.append(int(card))
        return deck

    def shuffle(self):
        random.shuffle(self.deck)

    def length(self):
        return len(self.deck)

    # TESTED
    def draw_card(self):
        card = None
        if self.length() > 0:
            card = self.deck.pop()
        return card

    def print_deck(self):
        for card in self.deck:
            print(card)