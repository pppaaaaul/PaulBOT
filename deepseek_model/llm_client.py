# Pure logic for the deepseek_model feature: builds chat-completion messages from
# channel history, talks to the tokenrouter OpenAI-compatible API, and chunks the
# answer for Discord. MUST NEVER import discord — that keeps it unit-testable
# (same layering rule as blackjack.game.blackjack_utils).
import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

# tokenrouter defaults; overridable via .env.
DEFAULT_BASE_URL = "https://api.tokenrouter.com"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro-0813-free"

# tokenrouter was verified to serve /v1/chat/completions; the plain
# /chat/completions path returns an empty body there, so it is only a fallback.
ENDPOINT_PATHS = ("/v1/chat/completions", "/chat/completions")

SYSTEM_PROMPT = (
    "You are PaulBOT, a helpful assistant chatting in a Discord server. "
    "Keep answers friendly and reasonably concise, and format them as plain "
    "text that reads well in Discord."
)

# Each channel-history message is capped at this many chars before it is sent
# to the model (~15 messages * 300 chars keeps context well under token limits).
HISTORY_CHAR_LIMIT = 300

# Discord hard-limits messages at 2000 chars; leave headroom for the mention prefix.
CHUNK_LIMIT = 1900

REQUEST_TIMEOUT_SECONDS = 60

# How much of a failing HTTP response body to surface in the error message.
_ERROR_BODY_PREVIEW_LIMIT = 200

# Web-search planning: query length cap and how many results to consider.
MAX_SEARCH_QUERY_LENGTH = 200
SEARCH_RESULTS_LIMIT = 6

PLAN_SEARCH_PROMPT = (
    "You decide whether a user's question needs a live web search. Reply with "
    "ONLY a JSON object: {\"needs_search\": true/false, \"query\": \"...\"}. "
    "Set needs_search to true only for questions about current events, recent "
    "or latest information, real-time data, or facts you are not confident "
    "about; put the best short search query in \"query\". Set needs_search to "
    "false for greetings, math, coding help, opinions, or general knowledge, "
    "and leave \"query\" empty. Output nothing except the JSON."
)


class LLMError(ValueError):
    # Raised for any LLM call failure; subclasses ValueError to match the
    # project-wide ValueError-for-errors convention.
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass
class LLMConfig:
    api_key: str
    model: str
    base_url: str

    # Reads config from the environment (loaded from .env by main.py before the
    # cog is created). Returns None when the API key is missing so the feature
    # can disable itself instead of crashing the bot.
    @staticmethod
    def from_env() -> Optional["LLMConfig"]:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        return LLMConfig(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        )


def strip_bot_mention(content: str, bot_id: int) -> str:
    # Removes the bot's mention (<@id> and the nickname form <@!id>) so only the
    # user's actual question remains.
    for prefix in ("<@", "<@!"):
        content = content.replace(f"{prefix}{bot_id}>", "")
    return content.strip()


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def history_to_context(history_items: List[Tuple[str, bool, str]]) -> List[dict]:
    # Converts chronological (display_name, is_bot, content) tuples into chat
    # messages. Skips empty content (e.g. embed-only messages). Past bot answers
    # become assistant messages; everything else becomes a user message prefixed
    # with the author's name so the model can follow group conversations.
    messages = []
    for display_name, is_bot, content in history_items:
        content = truncate(content.strip(), HISTORY_CHAR_LIMIT)
        if not content:
            continue
        if is_bot:
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": "user", "content": f"{display_name}: {content}"})
    return messages


def build_chat_messages(history_items: List[Tuple[str, bool, str]], question: str) -> List[dict]:
    # System prompt first, then channel context, then the actual question last.
    return (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history_to_context(history_items)
        + [{"role": "user", "content": question}]
    )


def plan_search_messages(question: str) -> List[dict]:
    # Messages for the web-search planning call (decides search + query).
    return [
        {"role": "system", "content": PLAN_SEARCH_PROMPT},
        {"role": "user", "content": question},
    ]


def parse_plan_search(content: str) -> Optional[str]:
    # Parses the planning model's reply into a search query. Returns None when
    # the model decided no search is needed (or the reply is unusable) so the
    # caller falls back to answering without web context. Extracts the first
    # JSON object so replies wrapped in prose or code fences still parse.
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("needs_search"):
        return None
    query = data.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return query.strip()[:MAX_SEARCH_QUERY_LENGTH]


def build_search_messages(
    history_items: List[Tuple[str, bool, str]],
    question: str,
    pages: List[str],
) -> List[dict]:
    # Builds the final answer messages for a question that HAS web context:
    # system prompt, channel history, the fetched pages, then the question.
    # `pages` is a list of already-truncated page texts (title + body).
    # Without pages this is identical to build_chat_messages.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history_to_context(history_items)
    if pages:
        joined = "\n\n---\n\n".join(f"[Source {i + 1}]\n{p}" for i, p in enumerate(pages))
        messages.append({
            "role": "user",
            "content": (
                "Relevant web search results for the question (use these to "
                "answer; they may be noisy or partly off-topic):\n\n" + joined
            ),
        })
    messages.append({"role": "user", "content": question})
    return messages


def candidate_urls(base_url: str) -> List[str]:
    # Returns every plausible completions endpoint for the base URL, in order.
    base = base_url.rstrip("/")
    return [f"{base}{path}" for path in ENDPOINT_PATHS]


def chunk_reply(text: str, limit: int = CHUNK_LIMIT) -> List[str]:
    # Splits a long answer into Discord-safe chunks, preferring to break at the
    # last newline, then the last whitespace, and only hard-cutting as a last
    # resort. Concatenating the chunks reproduces the original text exactly
    # (the split character stays at the end of the chunk it split on).
    if not text:
        return []
    chunks = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    chunks.append(text)
    return chunks


def parse_llm_response(data: dict) -> str:
    # Extracts the answer text from a chat-completions response; any structural
    # problem (missing choices, empty content, wrong shape) raises LLMError.
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("LLM response was missing the answer content")
    if not content or not content.strip():
        raise LLMError("LLM returned an empty answer")
    return content.strip()


async def request_chat(session: aiohttp.ClientSession, config: LLMConfig, messages: List[dict], url: str) -> dict:
    # POSTs one chat-completions request and returns the parsed JSON body.
    # Reads the body as text first so proxies returning text/plain still work.
    headers = {"Authorization": f"Bearer {config.api_key}"}
    payload = {"model": config.model, "messages": messages}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    try:
        async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
            body = await resp.text()
    except asyncio.TimeoutError:
        raise LLMError(f"LLM request to {url} timed out after {REQUEST_TIMEOUT_SECONDS}s")
    except aiohttp.ClientError as e:
        raise LLMError(f"LLM request to {url} failed: {e}")
    if resp.status != 200:
        preview = truncate(body.strip(), _ERROR_BODY_PREVIEW_LIMIT)
        raise LLMError(f"LLM endpoint returned HTTP {resp.status}: {preview}", status=resp.status)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise LLMError("LLM endpoint returned malformed JSON")


async def ask_llm(
    session: aiohttp.ClientSession,
    config: LLMConfig,
    messages: List[dict],
    preferred_url: Optional[str] = None,
) -> Tuple[str, str]:
    # Asks the LLM and returns (answer, working_url). Tries the preferred URL
    # first if given, and only falls back to the next candidate on a 404 (a
    # wrong path); any other error is raised immediately without retrying.
    urls = candidate_urls(config.base_url)
    if preferred_url and preferred_url in urls:
        urls.remove(preferred_url)
        urls.insert(0, preferred_url)
    last_error: Optional[LLMError] = None
    for url in urls:
        try:
            data = await request_chat(session, config, messages, url)
        except LLMError as e:
            if e.status == 404:
                last_error = e
                continue
            raise
        return parse_llm_response(data), url
    raise last_error
