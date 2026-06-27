# Discord command layer for the blackjack feature.
# Depends on the pure game logic in blackjack.game.blackjack_utils; that module
# must never import discord, which is what keeps the game logic unit-testable.
import discord
from discord.ext import commands

from blackjack.game.blackjack_utils import *


class Blackjack(commands.Cog):
    """All blackjack-related commands and the helpers they share."""

    def __init__(self, bot):
        self.bot = bot


    # -- HELPERS --
    
    def hand_summary(self, user_id):
        # Returns a one-line string of the dealer's and user's current hands.
        return f"DEALER: {hand_display(get_dealer_cards(user_id))}  |  YOU: {hand_display(get_user_cards(user_id))}"

    def active_display_name(self, ctx):
        # Resolves the active player's display name for the "must wait" message.
        active = get_active_player()
        if active is None:
            return None
        member = ctx.guild.get_member(active) if ctx.guild else None
        return member.display_name if member else f'user {active}'

    async def send_wait_message(self, ctx):
        # Tells the caller they cannot act because someone else is playing (or no game is running).
        name = self.active_display_name(ctx)
        if name is None:
            await ctx.send('You are not in a game. Start one with `!blackjack "bet"`.')
        else:
            await ctx.send(f'Must wait for {name} to finish their game.')

    async def do_move(self, ctx, move):
        # Shared handler for hit/stand/double: checks in-game status, runs the move, and replies.
        user_id = ctx.author.id
        if not user_in_game(user_id):
            await self.send_wait_message(ctx)
            return
        try:
            outcome = user_move(user_id, move)
        except Exception as e:
            await ctx.send(str(e))
            return
        if outcome is None:
            await ctx.send(f'You hit. {self.hand_summary(user_id)}')
        else:
            await ctx.send(outcome)


    # -- COMMANDS --

    @commands.command()
    async def blackjack(self, ctx, bet: float = 0):
        # Starts a new blackjack game with the given bet (single-player guarded).
        if not (bet > 0):
            await ctx.send('Invalid bet for blackjack, must be greater than 0.')
            return
        active = get_active_player()
        if active is not None and active != ctx.author.id:
            await ctx.send(f'Must wait for {self.active_display_name(ctx)} to finish their game.')
            return
        try:
            result = start_game(ctx.author.id, bet)
        except Exception as e:
            await ctx.send(str(e))
            return
        if result is None:
            await ctx.send(f'Game started! {self.hand_summary(ctx.author.id)}')
        else:
            await ctx.send(result)

    @commands.command()
    async def hit(self, ctx):
        # Draws one card; ends the game on a bust, otherwise lets the player move again.
        await self.do_move(ctx, 1)

    @commands.command()
    async def stand(self, ctx):
        # Stops drawing and resolves the game against the dealer.
        await self.do_move(ctx, 2)

    @commands.command()
    async def double(self, ctx):
        # Doubles the bet, draws exactly one card, then resolves.
        await self.do_move(ctx, 3)

    @commands.command()
    async def table(self, ctx):
        # Shows the current dealer and user hands during a game.
        if not user_in_game(ctx.author.id):
            await self.send_wait_message(ctx)
            return
        await ctx.send(self.hand_summary(ctx.author.id))

    @commands.command()
    async def winrate(self, ctx):
        # Replies with the caller's win-rate percentage.
        user_id = ctx.author.id
        if not user_in_database(user_id):
            await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
            return
        user = get_user(user_id)
        if user.wins + user.losses == 0:
            await ctx.send("You haven't won/lost a game yet.")
            return
        await ctx.send(f'Your winrate is {user.get_win_rate()}%.')

    @commands.command()
    async def balance(self, ctx):
        # Replies with the caller's current balance.
        user_id = ctx.author.id
        if not user_in_database(user_id):
            await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
            return
        user = get_user(user_id)
        await ctx.send(f'Your balance is {user.balance}.')

    @commands.command()
    async def moneyboard(self, ctx):
        # Lists all players ranked by balance, using their server display names.
        rows = get_moneyboard()
        if not rows:
            await ctx.send('No players yet. Start one with `!blackjack "bet"`.')
            return
        lines = []
        for user_id, bal in rows:
            member = ctx.guild.get_member(user_id) if ctx.guild else None
            name = member.display_name if member else f'Unknown ({user_id})'
            lines.append(f'{name} - {bal}')
        await ctx.send('**Moneyboard**\n' + '\n'.join(lines))

    @commands.command()
    async def getmoney(self, ctx):
        # Gives a broke (zero-balance) player 50; refuses anyone with money left.
        user_id = ctx.author.id
        if not user_in_database(user_id):
            await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
            return
        user = get_user(user_id)
        if user.balance > 0:
            await ctx.send('You are not broke, cannot ask for money.')
        else:
            adjust_balance(user.user_id, 50)
            await ctx.send('LMAOO, bum ass gambled his way into a cardboard box. A nice man named walked by and dropped 50 bucks into the coffee cup.')

# Registers the Blackjack cog when this extension is loaded by the bot.
async def setup(bot):
    await bot.add_cog(Blackjack(bot))
