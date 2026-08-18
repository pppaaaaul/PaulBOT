# Discord layer for the deepseek_model feature: answers questions when users
# @-mention the bot. All LLM/HTTP logic lives in deepseek_model.llm_client;
# this cog only does message handling (same layering rule as blackjack).
import asyncio
import logging

import aiohttp
import discord
from discord.ext import commands

from deepseek_model.llm_client import (
    LLMError,
    LLMConfig,
    ask_llm,
    build_chat_messages,
    build_search_messages,
    chunk_reply,
    parse_plan_search,
    plan_search_messages,
    strip_bot_mention,
)
from deepseek_model.web_search import fetch_page_text, web_search

log = logging.getLogger(__name__)

# How many recent channel messages to feed the model as conversation context.
HISTORY_LIMIT = 15

# How many top search-result pages to read for web-assisted answers.
SEARCH_PAGES_LIMIT = 3

# User-facing error replies are capped at this length.
ERROR_REPLY_LIMIT = 150


class DeepSeekModel(commands.Cog):
    """Answers questions asked via @-mention using the DeepSeek LLM."""

    def __init__(self, bot):
        self.bot = bot
        self.config = LLMConfig.from_env()
        # A missing API key disables the listener instead of crashing the bot.
        self.enabled = self.config is not None
        if not self.enabled:
            log.error("deepseek_model disabled: DEEPSEEK_API_KEY missing from .env")
        self.session = None
        # One LLM call at a time (free-tier rate limits); the typing indicator
        # covers the wait for queued questions.
        self._lock = asyncio.Lock()
        # Remembers the endpoint path that worked so later calls skip the probe.
        self._working_url = None

    async def cog_load(self):
        if self.enabled:
            self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session is not None:
            await self.session.close()

    # Collects recent channel history as (display_name, is_bot, content) tuples,
    # oldest first. history() yields newest-first, so the list is reversed.
    async def collect_history(self, message):
        try:
            items = [
                (m.author.display_name, m.author.bot, m.content)
                async for m in message.channel.history(limit=HISTORY_LIMIT, before=message)
            ]
        except (discord.Forbidden, discord.HTTPException):
            # No history access -> answer without context rather than failing.
            return []
        items.reverse()
        return items

    # Asks the model whether the question needs a live web search and, if so,
    # which query to use. Returns None (skip search) on ANY failure so the
    # question is still answered from model knowledge alone.
    async def decide_search(self, question):
        try:
            plan, url = await ask_llm(
                self.session, self.config, plan_search_messages(question),
                preferred_url=self._working_url,
            )
            self._working_url = url
        except Exception:
            log.warning("deepseek_model: search planning failed; answering without web", exc_info=True)
            return None
        return parse_plan_search(plan)

    # Runs the web search and reads the top result pages concurrently. Returns
    # the fetched page texts; any failure yields an empty list so the question
    # is still answered without web context.
    async def gather_pages(self, query):
        try:
            results = await web_search(self.session, query)
            log.info("deepseek_model: web search %r -> %d results", query, len(results))
            texts = await asyncio.gather(
                *(fetch_page_text(self.session, r.url) for r in results[:SEARCH_PAGES_LIMIT]),
                return_exceptions=True,
            )
        except Exception as e:
            log.warning("deepseek_model: web search failed (%s); answering without web", e)
            return []
        pages = [t for t in texts if isinstance(t, str) and t.strip()]
        if not pages:
            log.warning("deepseek_model: no readable pages for query %r", query)
        return pages

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.enabled:
            return
        if message.author.bot:
            return
        if self.bot.user not in message.mentions:
            return

        question = strip_bot_mention(message.content, self.bot.user.id)
        if not question:
            await message.reply('Please add a question after mentioning me.')
            return

        history_items = await self.collect_history(message)

        # Typing indicator wraps the whole pipeline: search planning, page
        # fetches, and the final answer.
        async with message.channel.typing():
            # Step 1: model decides whether the question needs a web search
            # (a model call, so it runs under the rate-limit lock).
            async with self._lock:
                query = await self.decide_search(question)

            # Step 2: if needed, search the web and read the top pages. These
            # are plain HTTP GETs (no model API), so no lock is held.
            pages = await self.gather_pages(query) if query else []

            # Step 3: build the final prompt, with web context when available.
            if pages:
                chat_messages = build_search_messages(history_items, question, pages)
            else:
                chat_messages = build_chat_messages(history_items, question)

            try:
                async with self._lock:
                    answer, url = await ask_llm(
                        self.session, self.config, chat_messages,
                        preferred_url=self._working_url,
                    )
                self._working_url = url
            except LLMError as e:
                log.warning("deepseek_model LLM call failed: %s", e)
                detail = str(e)[:ERROR_REPLY_LIMIT]
                await message.reply(
                    f"Sorry, I couldn't get an answer ({detail}).",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            except Exception:
                # Always reply on failure; otherwise the user sees a frozen
                # typing indicator with no explanation.
                log.exception("deepseek_model unexpected error")
                await message.reply(
                    "Sorry, something went wrong while answering.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return

        chunks = chunk_reply(answer)
        if not chunks:
            await message.reply(
                "Sorry, the model returned an empty answer.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        # First chunk: Discord reply + a single @-mention. allowed_mentions
        # blocks the LLM from pinging @everyone/roles, and mentioning via
        # content only (no mention_author) avoids a double ping.
        await message.reply(
            f"{message.author.mention}\n{chunks[0]}",
            allowed_mentions=discord.AllowedMentions(users=[message.author]),
        )
        # Remaining chunks: plain messages, no mention parsing at all.
        for chunk in chunks[1:]:
            await message.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())


# Registers the DeepSeekModel cog when this extension is loaded by the bot.
async def setup(bot):
    await bot.add_cog(DeepSeekModel(bot))
