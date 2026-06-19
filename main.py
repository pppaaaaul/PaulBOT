import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os

from blackjack.game.blackjack_utils import *



load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')) # loads the .env file (lives next to main.py at the project root)
token = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

COMMAND_PREFIX = '!'
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
bot.remove_command('help')

def hand_summary(user_id):
    return f"DEALER: {hand_display(get_dealer_cards(user_id))}  |  YOU: {hand_display(get_user_cards(user_id))}"

def active_display_name(ctx):
    """Resolve the active player's display name for the 'must wait' message."""
    active = get_active_player()
    if active is None:
        return None
    member = ctx.guild.get_member(active) if ctx.guild else None
    return member.display_name if member else f'user {active}'

# Guardrail 1: only the active player may act. If the caller is not in a game,
# tell them who they are waiting on (or that no game is running).
async def send_wait_message(ctx):
    name = active_display_name(ctx)
    if name is None:
        await ctx.send('You are not in a game. Start one with `!blackjack "bet"`.')
    else:
        await ctx.send(f'Must wait for {name} to finish their game.')

@bot.command()
async def blackjack(ctx, bet: float = 0):
    if not (bet > 0):
        # bet param was either not given or it was given as less than 0
        await ctx.send('Invalid bet for blackjack, must be greater than 0.')
        return

    # single-player guard: block if someone else is already playing
    active = get_active_player()
    if active is not None and active != ctx.author.id:
        await ctx.send(f'Must wait for {active_display_name(ctx)} to finish their game.')
        return
    
    bet = round(bet,2)
    try:
        result = start_game(ctx.author.id, bet)
    except Exception as e:
        await ctx.send(str(e))
        return

    if result is None:
        # no blackjack; game in progress, show the opening hands
        await ctx.send(f'Game started! {hand_summary(ctx.author.id)}')
    else:
        # user (and maybe dealer) got blackjack; game already ended
        await ctx.send(result)

# Shared handler for the in-game moves (hit=1, stand=2, double=3).
async def do_move(ctx, move):
    user_id = ctx.author.id
    if not user_in_game(user_id):
        await send_wait_message(ctx)
        return
    try:
        outcome = user_move(user_id, move)
    except Exception as e:
        await ctx.send(str(e))
        return
    if outcome is None:
        # a hit that did not bust: game continues, show the hand
        await ctx.send(f'You hit. {hand_summary(user_id)}')
    else:
        # game ended; the outcome string already describes the result
        await ctx.send(outcome)

@bot.command()
async def hit(ctx):
    await do_move(ctx, 1)

@bot.command()
async def stand(ctx):
    await do_move(ctx, 2)

@bot.command()
async def double(ctx):
    await do_move(ctx, 3)

@bot.command()
async def table(ctx):
    if not user_in_game(ctx.author.id):
        await send_wait_message(ctx)
        return
    await ctx.send(hand_summary(ctx.author.id))

@bot.command()
async def winrate(ctx):
    user_id = ctx.author.id
    if not user_in_database(user_id):
        await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
        return
    user = get_user(user_id)
    if user.wins + user.losses == 0:
        await ctx.send("You haven't won/lost a game yet.")
        return
    await ctx.send(f'Your winrate is {user.get_win_rate()}%.')
    return

@bot.command()
async def balance(ctx):
    user_id = ctx.author.id
    if not user_in_database(user_id):
        await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
        return
    user = get_user(user_id)
    await ctx.send(f'Your balance is {user.balance}.')
    return

@bot.command()
async def help(ctx):
    HELP_MESSAGE = '''
    Blackjack Commands (NOTE: 0 = ACE) :
    !blackjack "bet amount" - starts a new game of blackjack with the bet
    !table (during blackjack) - view the cards of dealer and your cards
    !hit (during blackjack) - adds another card to your hand
    !stand (during blackjack) - do not add another card to your hand
    !double (during blackjack) - doubles bet (if possible) and adds another card to your hand
    !balance - check your current balance
    !winrate - check your current winrate
    !moneyboard - check the top gamblers
    !getmoney
    '''
    await ctx.send(HELP_MESSAGE)    

@bot.command()
async def moneyboard(ctx):
    rows = get_moneyboard()   # [(user_id, balance), ...] ranked by balance
    if not rows:
        await ctx.send('No players yet. Start one with `!blackjack "bet"`.')
        return
    lines = []
    for user_id, balance in rows:
        member = ctx.guild.get_member(user_id) if ctx.guild else None
        name = member.display_name if member else f'Unknown ({user_id})'
        lines.append(f'{name} - {balance}')
    await ctx.send('**Moneyboard**\n' + '\n'.join(lines))

@bot.command()
async def getmoney(ctx):
    user_id = ctx.author.id
    if not user_in_database(user_id):
        await ctx.send('You are not registered. Play a game first with `!blackjack "bet"`.')
        return
    
    user = get_user(user_id)
    if user.balance > 0:
        await ctx.send('You are not broke, cannot ask for money.')
    else:
        adjust_balance(user.user_id,50)
        await ctx.send('LMAOO, bum ass gambled his way into a cardboard box. A nice man named walked by and dropped 50 bucks into the coffee cup.')

# any of the debug stuff will be logged in discord.log
bot.run(token, log_handler=handler, log_level=logging.DEBUG)







