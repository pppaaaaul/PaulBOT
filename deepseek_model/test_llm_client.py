# Tests for deepseek_model.llm_client. House style (see blackjack/CLAUDE.md):
# plain test_xxx() functions that raise ValueError on failure, with explicit
# calls at the bottom so the file also runs standalone via
#   python -m deepseek_model.test_llm_client
# It is also pytest-collectible: python -m pytest deepseek_model
# No network is used: the aiohttp layer is exercised with a duck-typed FakeSession.
import asyncio
import json
import os

import deepseek_model.llm_client as lc
from deepseek_model.llm_client import (
    CHUNK_LIMIT,
    LLMConfig,
    LLMError,
    ask_llm,
    build_chat_messages,
    build_search_messages,
    candidate_urls,
    chunk_reply,
    history_to_context,
    parse_llm_response,
    parse_plan_search,
    plan_search_messages,
    strip_bot_mention,
    truncate,
)

BOT_ID = 12345


# -- Pure-function tests ------------------------------------------------------

def test_strip_bot_mention():
    # Both mention forms are removed, whitespace trimmed.
    result = strip_bot_mention("<@12345> hello there", BOT_ID)
    if result != "hello there":
        raise ValueError("Error(test_strip_bot_mention), failed on <@id> form")
    result = strip_bot_mention("  <@!12345>  hello  ", BOT_ID)
    if result != "hello":
        raise ValueError("Error(test_strip_bot_mention), failed on <@!id> form")
    # Mention only -> empty question.
    if strip_bot_mention("<@12345>", BOT_ID) != "":
        raise ValueError("Error(test_strip_bot_mention), mention-only input should be empty")
    # A different user id is untouched.
    if strip_bot_mention("<@999> hi", BOT_ID) != "<@999> hi":
        raise ValueError("Error(test_strip_bot_mention), must not strip other users' mentions")


def test_truncate():
    if truncate("abcde", 5) != "abcde":
        raise ValueError("Error(test_truncate), text at the limit must be unchanged")
    if truncate("abcdef", 3) != "abc":
        raise ValueError("Error(test_truncate), text over the limit must be cut")


def test_history_to_context():
    history = [
        ("Alice", False, "what is 2+2?"),
        ("PaulBOT", True, "4"),                       # bot -> assistant role
        ("Bob", False, ""),                            # empty content -> skipped
        ("Carol", False, "x" * 500),                   # over limit -> truncated to 300
    ]
    result = history_to_context(history)
    if len(result) != 3:
        raise ValueError("Error(test_history_to_context), empty-content message was not skipped")
    if result[0] != {"role": "user", "content": "Alice: what is 2+2?"}:
        raise ValueError("Error(test_history_to_context), user message must be prefixed with the display name")
    if result[1] != {"role": "assistant", "content": "4"}:
        raise ValueError("Error(test_history_to_context), bot message must become an assistant message")
    if result[2]["content"] != "Carol: " + "x" * 300:
        raise ValueError("Error(test_history_to_context), long messages must be truncated to 300 chars")


def test_build_chat_messages():
    history = [("Alice", False, "earlier question")]
    result = build_chat_messages(history, "new question")
    if result[0]["role"] != "system":
        raise ValueError("Error(test_build_chat_messages), system prompt must come first")
    if result[-1] != {"role": "user", "content": "new question"}:
        raise ValueError("Error(test_build_chat_messages), the question must be the last message")
    if len(result) != 3:
        raise ValueError("Error(test_build_chat_messages), expected system + 1 history + question")


def test_plan_search_messages():
    result = plan_search_messages("what is the latest news?")
    if len(result) != 2:
        raise ValueError("Error(test_plan_search_messages), expected system + question")
    if result[0]["role"] != "system" or result[1] != {"role": "user", "content": "what is the latest news?"}:
        raise ValueError("Error(test_plan_search_messages), wrong message structure")


def test_parse_plan_search():
    # Plain JSON object.
    if parse_plan_search('{"needs_search": true, "query": "latest python release"}') != "latest python release":
        raise ValueError("Error(test_parse_plan_search), plain JSON not parsed")
    # JSON wrapped in markdown fences and prose.
    wrapped = 'Sure!\n```json\n{"needs_search": true, "query": "today news"}\n```'
    if parse_plan_search(wrapped) != "today news":
        raise ValueError("Error(test_parse_plan_search), fenced JSON not parsed")
    # needs_search false -> None (no search).
    if parse_plan_search('{"needs_search": false, "query": ""}') is not None:
        raise ValueError("Error(test_parse_plan_search), false needs_search must yield None")
    # No JSON at all -> None.
    if parse_plan_search("no json here") is not None:
        raise ValueError("Error(test_parse_plan_search), non-JSON reply must yield None")
    # Malformed JSON -> None.
    if parse_plan_search('{"needs_search": true, "query": ') is not None:
        raise ValueError("Error(test_parse_plan_search), malformed JSON must yield None")
    # needs_search true but empty query -> None.
    if parse_plan_search('{"needs_search": true, "query": "   "}') is not None:
        raise ValueError("Error(test_parse_plan_search), empty query must yield None")
    # Overly long query is capped.
    long_query = "x" * 500
    result = parse_plan_search('{"needs_search": true, "query": "' + long_query + '"}')
    if result is None or len(result) > 200:
        raise ValueError("Error(test_parse_plan_search), query not capped at 200 chars")


def test_build_search_messages():
    history = [("Alice", False, "hi")]
    pages = ["Title A\nbody a", "Title B\nbody b"]
    result = build_search_messages(history, "what is new?", pages)
    if result[0]["role"] != "system":
        raise ValueError("Error(test_build_search_messages), system prompt must come first")
    if result[-1] != {"role": "user", "content": "what is new?"}:
        raise ValueError("Error(test_build_search_messages), question must be last")
    # history(1) + pages(1 combined) + question = 3, plus system = 4 total.
    if len(result) != 4:
        raise ValueError(f"Error(test_build_search_messages), expected 4 messages, got {len(result)}")
    if "Source 1" not in result[2]["content"] or "Source 2" not in result[2]["content"]:
        raise ValueError("Error(test_build_search_messages), pages not combined into one message")
    if "body a" not in result[2]["content"] or "body b" not in result[2]["content"]:
        raise ValueError("Error(test_build_search_messages), page bodies missing")
    # Without pages, identical to build_chat_messages.
    if build_search_messages(history, "q", []) != build_chat_messages(history, "q"):
        raise ValueError("Error(test_build_search_messages), empty pages must match build_chat_messages")


def test_candidate_urls():
    urls = candidate_urls("https://api.example.com/")
    if urls != ["https://api.example.com/v1/chat/completions", "https://api.example.com/chat/completions"]:
        raise ValueError(f"Error(test_candidate_urls), unexpected urls: {urls}")
    # No trailing slash -> same result.
    if candidate_urls("https://api.example.com") != urls:
        raise ValueError("Error(test_candidate_urls), trailing slash must be normalized")


def test_chunk_reply():
    # Empty -> no chunks.
    if chunk_reply("") != []:
        raise ValueError("Error(test_chunk_reply), empty text must return no chunks")
    # Short text -> one chunk, unchanged.
    if chunk_reply("short") != ["short"]:
        raise ValueError("Error(test_chunk_reply), short text must be a single chunk")
    # Long text with spaces -> all chunks within the limit, no content lost.
    text = ("word " * 1000).strip()  # 4999 chars
    chunks = chunk_reply(text)
    if any(len(c) > CHUNK_LIMIT for c in chunks):
        raise ValueError("Error(test_chunk_reply), a chunk exceeded CHUNK_LIMIT")
    if len(chunks) < 3:
        raise ValueError("Error(test_chunk_reply), 5000-char text should need multiple chunks")
    if "".join(chunks) != text:
        raise ValueError("Error(test_chunk_reply), chunks must concatenate back to the original")
    # Whitespace-free text -> hard cuts at the limit, still lossless.
    dense = "x" * 5000
    chunks = chunk_reply(dense)
    if chunks[:2] != ["x" * CHUNK_LIMIT, "x" * CHUNK_LIMIT] or "".join(chunks) != dense:
        raise ValueError("Error(test_chunk_reply), hard-cut chunking must not lose content")
    # Custom limit is respected.
    if chunk_reply("a" * 10, limit=4) != ["a" * 4, "a" * 4, "a" * 2]:
        raise ValueError("Error(test_chunk_reply), custom limit was not applied")


def test_parse_llm_response():
    valid = {"choices": [{"message": {"content": "  hello  "}}]}
    if parse_llm_response(valid) != "hello":
        raise ValueError("Error(test_parse_llm_response), content must be extracted and stripped")
    for bad in [{}, {"choices": []}, {"choices": [{"message": {}}]}, {"choices": [{"message": {"content": ""}}]}]:
        try:
            parse_llm_response(bad)
        except LLMError as e:
            if not isinstance(e, ValueError):
                raise ValueError("Error(test_parse_llm_response), LLMError must subclass ValueError")
        else:
            raise ValueError(f"Error(test_parse_llm_response), malformed payload not rejected: {bad}")


def test_config_from_env():
    env_keys = ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL")
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        if LLMConfig.from_env() is not None:
            raise ValueError("Error(test_config_from_env), missing key must yield None")
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        config = LLMConfig.from_env()
        if config is None or config.api_key != "sk-test":
            raise ValueError("Error(test_config_from_env), key was not read")
        if not config.model or not config.base_url:
            raise ValueError("Error(test_config_from_env), defaults must fill model/base_url")
        os.environ["DEEPSEEK_MODEL"] = "custom/model"
        os.environ["DEEPSEEK_BASE_URL"] = "https://custom.example.com"
        config = LLMConfig.from_env()
        if config.model != "custom/model" or config.base_url != "https://custom.example.com":
            raise ValueError("Error(test_config_from_env), env overrides were not applied")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# -- FakeSession for the async HTTP layer --------------------------------------

class FakeResponse:
    # Duck-typed aiohttp response: .status and an async .text(); also an async
    # context manager like the object session.post(...) returns.
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    # Duck-typed aiohttp.ClientSession: .post(url, json=..., headers=..., timeout=...)
    # returns canned responses in order and records every url + payload it saw.
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append((url, json, headers))
        return self.responses.pop(0)


def _ok_body(content):
    return json.dumps({"choices": [{"message": {"content": content}}]})


def test_ask_llm_fallback_and_errors():
    config = LLMConfig(api_key="sk-test", model="m", base_url="https://api.example.com")

    # 404 on first endpoint -> falls back to the plain /chat/completions path.
    session = FakeSession([FakeResponse(404, "not found"), FakeResponse(200, _ok_body("42"))])
    answer, url = asyncio.run(ask_llm(session, config, [{"role": "user", "content": "q"}]))
    if answer != "42" or url != "https://api.example.com/chat/completions":
        raise ValueError(f"Error(test_ask_llm_fallback_and_errors), unexpected fallback result: {answer} {url}")
    if len(session.requests) != 2:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), expected exactly two requests")
    # The bearer header was sent with the payload.
    _, payload, headers = session.requests[0]
    if headers != {"Authorization": "Bearer sk-test"} or payload["model"] != "m":
        raise ValueError("Error(test_ask_llm_fallback_and_errors), wrong headers/payload")

    # 401 -> raised immediately, no fallback attempt.
    session = FakeSession([FakeResponse(401, "bad key")])
    try:
        asyncio.run(ask_llm(session, config, []))
    except LLMError as e:
        if e.status != 401:
            raise ValueError("Error(test_ask_llm_fallback_and_errors), status not preserved")
        if "sk-test" in str(e):
            raise ValueError("Error(test_ask_llm_fallback_and_errors), api key leaked into error message")
    else:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), 401 must raise")
    if len(session.requests) != 1:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), 401 must not trigger a fallback request")

    # Malformed JSON body -> LLMError.
    session = FakeSession([FakeResponse(200, "not json")])
    try:
        asyncio.run(ask_llm(session, config, []))
    except LLMError:
        pass
    else:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), malformed JSON must raise")

    # 200 with an EMPTY body (tokenrouter's dead /chat/completions stub) must
    # fall back to the next endpoint instead of being parsed as a failure.
    session = FakeSession([FakeResponse(200, ""), FakeResponse(200, _ok_body("real"))])
    answer, url = asyncio.run(ask_llm(session, config, []))
    if answer != "real" or url != "https://api.example.com/chat/completions":
        raise ValueError(f"Error(test_ask_llm_fallback_and_errors), empty-body endpoint not skipped: {answer} {url}")
    if len(session.requests) != 2:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), empty body must trigger exactly one fallback")

    # Preferred URL is tried first and only once.
    session = FakeSession([FakeResponse(200, _ok_body("hi"))])
    answer, url = asyncio.run(ask_llm(
        session, config, [], preferred_url="https://api.example.com/v1/chat/completions"))
    if answer != "hi" or url != "https://api.example.com/v1/chat/completions":
        raise ValueError("Error(test_ask_llm_fallback_and_errors), preferred url not used")
    if session.requests[0][0] != "https://api.example.com/v1/chat/completions":
        raise ValueError("Error(test_ask_llm_fallback_and_errors), preferred url must be the first request")

    # Preferred URL 404 -> falls back to the other endpoint exactly once.
    session = FakeSession([FakeResponse(404, ""), FakeResponse(200, _ok_body("ok"))])
    answer, url = asyncio.run(ask_llm(
        session, config, [], preferred_url="https://api.example.com/v1/chat/completions"))
    if url != "https://api.example.com/chat/completions" or len(session.requests) != 2:
        raise ValueError("Error(test_ask_llm_fallback_and_errors), preferred-url fallback is broken")


def test_ask_llm_retry():
    config = LLMConfig(api_key="sk-test", model="m", base_url="https://api.example.com")
    original_delay = lc.RETRY_DELAY_SECONDS
    lc.RETRY_DELAY_SECONDS = 0  # keep the test instant
    try:
        # 502 -> single retry on the SAME url; second attempt succeeds.
        session = FakeSession([FakeResponse(502, json.dumps({"error": {"message": "backend connect failed"}})),
                               FakeResponse(200, _ok_body("recovered"))])
        answer, url = asyncio.run(ask_llm(session, config, []))
        if answer != "recovered" or len(session.requests) != 2:
            raise ValueError("Error(test_ask_llm_retry), 502 must be retried once on the same url")
        if session.requests[0][0] != session.requests[1][0]:
            raise ValueError("Error(test_ask_llm_retry), retry must reuse the same url")

        # 502 twice -> gives up after the single retry (no endless loop).
        session = FakeSession([FakeResponse(502, ""), FakeResponse(502, "")])
        try:
            asyncio.run(ask_llm(session, config, []))
        except LLMError as e:
            if e.status != 502 or len(session.requests) != 2:
                raise ValueError("Error(test_ask_llm_retry), two 502s must raise after exactly two tries")
        else:
            raise ValueError("Error(test_ask_llm_retry), persistent 502 must raise")

        # Empty answer (content: null -> retryable) is also retried once.
        session = FakeSession([FakeResponse(200, json.dumps({"choices": [{"message": {"content": None}}]})),
                               FakeResponse(200, _ok_body("second try"))])
        answer, _ = asyncio.run(ask_llm(session, config, []))
        if answer != "second try" or len(session.requests) != 2:
            raise ValueError("Error(test_ask_llm_retry), empty answers must be retried once")

        # 404 is NOT retried: falls straight back to the other candidate.
        session = FakeSession([FakeResponse(404, ""), FakeResponse(200, _ok_body("fallback"))])
        answer, url = asyncio.run(ask_llm(session, config, []))
        if answer != "fallback" or url != "https://api.example.com/chat/completions":
            raise ValueError("Error(test_ask_llm_retry), 404 must fall back, not retry same url")
        if session.requests[0][0] == session.requests[1][0]:
            raise ValueError("Error(test_ask_llm_retry), 404 fallback went to the same url")
    finally:
        lc.RETRY_DELAY_SECONDS = original_delay


test_strip_bot_mention()
test_truncate()
test_history_to_context()
test_build_chat_messages()
test_plan_search_messages()
test_parse_plan_search()
test_build_search_messages()
test_candidate_urls()
test_chunk_reply()
test_parse_llm_response()
test_config_from_env()
test_ask_llm_fallback_and_errors()
test_ask_llm_retry()
print("DEEPSEEK MODEL TESTS FINISHED")
