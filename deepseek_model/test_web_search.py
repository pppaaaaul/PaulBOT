# Tests for deepseek_model.web_search. House style (see blackjack/CLAUDE.md):
# plain test_xxx() functions that raise ValueError on failure, with explicit
# calls at the bottom so the file also runs standalone via
#   python -m deepseek_model.test_web_search
# It is also pytest-collectible: python -m pytest deepseek_model
# No network is used: the aiohttp layer is exercised with a duck-typed FakeSession.
import asyncio

from deepseek_model.llm_client import LLMError
from deepseek_model.web_search import (
    PAGE_CHAR_LIMIT,
    SearchResult,
    extract_text,
    fetch_page_text,
    normalize_result_url,
    parse_search_results,
    truncate_text,
    web_search,
)


# -- FakeSession for the async GET layer ---------------------------------------

class FakeResponse:
    # Duck-typed aiohttp response: .status and an async .text(); also an async
    # context manager like the object session.get(...) returns.
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
    # Duck-typed aiohttp.ClientSession for GET requests: returns canned
    # responses in order and records every url it was asked for.
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, headers=None, timeout=None, ssl=None):
        self.urls.append(url)
        return self.responses.pop(0)


# -- Small canned HTML fixtures ------------------------------------------------

SAMPLE_SEARCH_HTML = """
<html><body>
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=abc">Example Page</a>
  <a class="result__snippet" href="#">This is the snippet.</a>
  <a class="result__a" href="https://other.org/doc">Other Doc</a>
  <a class="result__snippet" href="#">Snippet two.</a>
</body></html>
"""

SAMPLE_PAGE_HTML = """
<html><head><title>  My Page Title  </title>
<script>var secret = "should not appear";</script>
<style>.x{color:red}</style></head>
<body>
<nav>menu items to skip</nav>
<div><p>First   paragraph with    extra   spaces.</p>
<h2>A Heading</h2>
<p>Second paragraph.</p></div>
<footer>footer to skip</footer>
</body></html>
"""


# -- Pure-function tests ------------------------------------------------------

def test_normalize_result_url():
    # DDG redirect is unwrapped to the real URL.
    redirect = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    if normalize_result_url(redirect) != "https://example.com/page":
        raise ValueError("Error(test_normalize_result_url), redirect not unwrapped")
    # Scheme-relative redirect prefix gets https.
    if not normalize_result_url(redirect).startswith("https://"):
        raise ValueError("Error(test_normalize_result_url), scheme-relative not fixed")
    # A plain https URL passes through unchanged.
    if normalize_result_url("https://other.org/doc") != "https://other.org/doc":
        raise ValueError("Error(test_normalize_result_url), plain url altered")
    # A scheme-relative non-redirect link gets https prefixed.
    if normalize_result_url("//cdn.example.com/x") != "https://cdn.example.com/x":
        raise ValueError("Error(test_normalize_result_url), scheme-relative link not prefixed")


def test_parse_search_results():
    results = parse_search_results(SAMPLE_SEARCH_HTML)
    if len(results) != 2:
        raise ValueError(f"Error(test_parse_search_results), expected 2 results, got {len(results)}")
    if results[0].title != "Example Page":
        raise ValueError(f"Error(test_parse_search_results), bad first title: {results[0].title}")
    if results[0].url != "https://example.com/page":
        raise ValueError(f"Error(test_parse_search_results), redirect not resolved: {results[0].url}")
    if results[0].snippet != "This is the snippet.":
        raise ValueError(f"Error(test_parse_search_results), bad snippet: {results[0].snippet}")
    if results[1].url != "https://other.org/doc":
        raise ValueError(f"Error(test_parse_search_results), bad second url: {results[1].url}")
    # Empty html -> no results.
    if parse_search_results("<html></html>") != []:
        raise ValueError("Error(test_parse_search_results), empty html should yield no results")
    # A result with no usable href is dropped.
    if parse_search_results('<a class="result__a" href="">No URL</a>') != []:
        raise ValueError("Error(test_parse_search_results), url-less result not dropped")


def test_extract_text():
    title, text = extract_text(SAMPLE_PAGE_HTML)
    if title != "My Page Title":
        raise ValueError(f"Error(test_extract_text), bad title: {title!r}")
    if "First paragraph with extra spaces." not in text:
        raise ValueError("Error(test_extract_text), paragraph text/spacing wrong")
    if "A Heading" not in text:
        raise ValueError("Error(test_extract_text), heading missing")
    if "secret" in text or "should not appear" in text:
        raise ValueError("Error(test_extract_text), script content leaked")
    if ".x{color:red}" in text:
        raise ValueError("Error(test_extract_text), style content leaked")
    if "menu items to skip" in text:
        raise ValueError("Error(test_extract_text), nav content leaked")
    if "footer to skip" in text:
        raise ValueError("Error(test_extract_text), footer content leaked")


def test_truncate_text():
    if truncate_text("abc", 10) != "abc":
        raise ValueError("Error(test_truncate_text), short text must be unchanged")
    # Result stays within the limit, with the ellipsis counted inside it.
    result = truncate_text("abcdefghij", 4)
    if result != "a...":
        raise ValueError(f"Error(test_truncate_text), expected 'a...', got {result!r}")
    if len(result) > 4:
        raise ValueError("Error(test_truncate_text), result must not exceed the limit")


def test_web_search_errors():
    # Non-200 -> LLMError with the status preserved.
    session = FakeSession([FakeResponse(500, "boom")])
    try:
        asyncio.run(web_search(session, "anything"))
    except LLMError as e:
        if e.status != 500:
            raise ValueError("Error(test_web_search_errors), status not preserved")
    else:
        raise ValueError("Error(test_web_search_errors), 500 must raise")
    # 200 but no parseable results -> LLMError.
    session = FakeSession([FakeResponse(200, "<html>nothing here</html>")])
    try:
        asyncio.run(web_search(session, "anything"))
    except LLMError:
        pass
    else:
        raise ValueError("Error(test_web_search_errors), empty results must raise")


def test_web_search_success():
    session = FakeSession([FakeResponse(200, SAMPLE_SEARCH_HTML)])
    results = asyncio.run(web_search(session, "example query"))
    if len(results) != 2:
        raise ValueError("Error(test_web_search_success), expected 2 results")
    # The query was url-encoded into the request url.
    if "q=example+query" not in session.urls[0] and "q=example%20query" not in session.urls[0]:
        raise ValueError(f"Error(test_web_search_success), query not encoded: {session.urls[0]}")


def test_fetch_page_text():
    session = FakeSession([FakeResponse(200, SAMPLE_PAGE_HTML)])
    text = asyncio.run(fetch_page_text(session, "https://example.com/page"))
    if "My Page Title" not in text:
        raise ValueError("Error(test_fetch_page_text), title prefix missing")
    if "First paragraph" not in text:
        raise ValueError("Error(test_fetch_page_text), body text missing")
    # Long page text is capped at PAGE_CHAR_LIMIT.
    huge = "<html><body><p>" + ("word " * 2000) + "</p></body></html>"
    session = FakeSession([FakeResponse(200, huge)])
    text = asyncio.run(fetch_page_text(session, "https://example.com/big"))
    if len(text) > PAGE_CHAR_LIMIT:
        raise ValueError(f"Error(test_fetch_page_text), text not capped: {len(text)} chars")
    if not text.endswith("..."):
        raise ValueError("Error(test_fetch_page_text), truncated text must end with ellipsis")
    # Non-200 page -> LLMError.
    session = FakeSession([FakeResponse(404, "not found")])
    try:
        asyncio.run(fetch_page_text(session, "https://example.com/missing"))
    except LLMError as e:
        if e.status != 404:
            raise ValueError("Error(test_fetch_page_text), page status not preserved")
    else:
        raise ValueError("Error(test_fetch_page_text), 404 page must raise")
    # A page with no readable text -> LLMError.
    session = FakeSession([FakeResponse(200, "<html><script>only code</script></html>")])
    try:
        asyncio.run(fetch_page_text(session, "https://example.com/empty"))
    except LLMError:
        pass
    else:
        raise ValueError("Error(test_fetch_page_text), empty page must raise")


test_normalize_result_url()
test_parse_search_results()
test_extract_text()
test_truncate_text()
test_web_search_errors()
test_web_search_success()
test_fetch_page_text()
print("WEB SEARCH TESTS FINISHED")
