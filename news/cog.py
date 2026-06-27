import os
import json

import discord
from discord.ext import commands, tasks
import feedparser
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

# Discord command/background-task layer for the news feature.
# All news logic + state lives in this folder; the only outside dependency is
# the bot itself, loaded from main.py via load_extension('news.cog').

# Stores ONLY (1)id of last post read AND (2)name of channel this bot sends news to.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state.json')


# All the URLs to try.
URLS = [
    "https://nitter.net/financialjuice/rss",
    "https://nitter.privacyredirect.com/financialjuice/rss",
    "https://nitter.poast.org/financialjuice/rss",
]


# Returns the persisted state dict, or a fresh default if missing/invalid.
def _load_state():
    default = {"last_read_feed_id": None, "channel": None}
    if not os.path.exists(STATE_FILE):
        return default
    try:
        with open(STATE_FILE) as f:
            return {**default, **json.load(f)}
    except (json.JSONDecodeError, OSError):
        return default


# Writes the state (id of last post and name of channel) to state.json file.
def _save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# Returns the posts from the first reachable feed, or None if all feeds fail.
def fetch_posts():
    for url in URLS:
        posts = feedparser.parse(url).entries
        if posts:
            return posts
    return None


# Converts RFC 2822 date string to PST.
def get_pst(time_str):
    dt = parsedate_to_datetime(time_str)
    pst_time = dt.astimezone(ZoneInfo("America/Vancouver"))
    return pst_time.strftime("%a, %d %b %Y %#I:%M:%S %p %Z")


# Formats a post into the multi-line message to be shown in Discord.
def post_to_string(post):
    author = post.author
    date = get_pst(post.published)
    title = post.title  # for FinancialJuice, all info is in the title.
    return f'''-
        \n\n🟥 {title}
        \n\n{author} - {date}
    '''

# A News instance is instantiated once when extension loads from setup().
# The single instance lives for the bot's while lifetime.
class News(commands.Cog):
    """Polls the FinancialJuice RSS feed and posts new items to a channel."""

    def __init__(self, bot):
        self.bot = bot
        state = _load_state()

        # Stores the channel name and last post id from persistent storage.
        self.last_read_feed_id = state.get('last_read_feed_id')
        self.channel = state.get('channel')


    # Saves current last-read id and channel name to state.json.
    def _persist(self):
        _save_state({'last_read_feed_id': self.last_read_feed_id, 'channel': self.channel})


    # NOT FULLY SURE WHAT THESE DO YET
    async def cog_load(self):
        # Starts the periodic RSS check when the cog is loaded.
        self.check_rss.start()

    async def cog_unload(self):
        # Stops the periodic RSS check when the cog is unloaded.
        self.check_rss.cancel()


    # Look for given text channel in server.
    def resolve_channel(self):
        if not self.channel:
            return None
        return discord.utils.get(self.bot.get_all_channels(), name=self.channel)


    # Posts the single most recent feed item to the channel and marks it read.
    async def send_latest(self, channel):
        posts = fetch_posts()
        if not posts:
            return
        await channel.send(post_to_string(posts[0]))
        self.last_read_feed_id = posts[0].id
        self._persist()

    # Sets the news channel by name (must exist in this server), then posts the latest item.
    @commands.command()
    async def set_news_channel(self, ctx, *, channel_name):
        if ctx.guild is None:
            await ctx.send('This command must be used in a server.')
            return
        channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
        if channel is None:
            await ctx.send(f'No text channel named "{channel_name}" found in this server.')
            return
        self.channel = channel_name
        self._persist()
        await ctx.send(f'News channel set to #{channel_name}. Here is the latest:')
        await self.send_latest(channel)


    # Every 5 min: Look for new posts to send to channel.
    @tasks.loop(minutes=5)
    async def check_rss(self):
        # get channel
        channel = self.resolve_channel()
        if channel is None:
            # Nowhere to send -> skip the fetch entirely (no channel to message).
            print(f'[news] channel "{self.channel}" not found; skipping fetch.')
            return

        # fetch posts
        posts = fetch_posts()
        # NOTE: "if not posts" for arrays which can be None or empty, checks BOTH 
        # if array is None or if it is empty, even though they are not the same thing.
        if not posts:
            return

        # First run, display the latest post, then mark it read.
        # If was not first run, News would be instantiated and id would be read from states.json.
        if self.last_read_feed_id is None:
            await channel.send(post_to_string(posts[0]))
            self.last_read_feed_id = posts[0].id
            self._persist()
            return

        # Collect new posts (feed is newest-first) up to the last-read one.
        new_posts = []
        for post in posts:
            if post.id == self.last_read_feed_id:
                break
            new_posts.append(post)
        self.last_read_feed_id = posts[0].id
        self._persist()
        if not new_posts:
            return
        # Send oldest-first so they read chronologically in Discord.
        for post in reversed(new_posts):
            await channel.send(post_to_string(post))

    @check_rss.before_loop
    async def before_check_rss(self):
        # Waits until the bot is ready (guilds/channels loaded) before the first run.
        await self.bot.wait_until_ready()


# Registers the News cog when this extension is loaded by the bot.
async def setup(bot):
    await bot.add_cog(News(bot))
