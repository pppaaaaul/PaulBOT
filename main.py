import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Bot entry point: creates the Discord client, loads feature cogs, and runs.

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))  # token lives next to main.py
token = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    # Fires once the bot has connected to Discord.
    print(f'Hello, I am {bot.user.name}')


async def load_features():
    # Loads every feature cog; register new features here.

    # Importants ./blackjack/cog and then runs setup() in the cog file.
    await bot.load_extension('blackjack.cog')


bot.setup_hook = load_features

# Runs the bot; debug output is written to discord.log.
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
