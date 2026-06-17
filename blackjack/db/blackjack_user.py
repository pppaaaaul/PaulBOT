
class User:
    def __init__(self, user_id, in_game, current_bet, balance, wins, losses):
        self.user_id = user_id
        self.in_game = in_game
        self.current_bet = current_bet
        self.balance = balance
        self.wins = wins
        self.losses = losses

    def get_win_rate(self):
        return round(self.wins / (self.wins + self.losses) * 100)

