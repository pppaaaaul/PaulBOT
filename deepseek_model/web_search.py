# Web search + page reading for the deepseek_model feature. Pure logic, no
# discord imports — DuckDuckGo's plain-HTML endpoint needs no API key, and page
# text is extracted with the stdlib html.parser (no new dependencies).
import asyncio
import os
import re
import ssl
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional, Tuple

import aiohttp

from deepseek_model.llm_client import LLMError

SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"

# DDG's HTML endpoint expects a normal browser; bare aiohttp UAs get blocked.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEARCH_TIMEOUT_SECONDS = 15
PAGE_TIMEOUT_SECONDS = 15

# Per-page context cap sent to the model (~3 pages * 3000 chars keeps the
# extra context comfortably under token limits).
PAGE_CHAR_LIMIT = 3000

# Pages larger than this are not worth parsing in full.
MAX_PAGE_BYTES = 1_000_000

# This venv (Anaconda-packaged Python) has a broken/expired default CA store,
# which makes many https sites fail verification ("certificate has expired").
# pip ships its own fresh CA bundle; use it when present. Override the path
# with DEEPSEEK_CA_BUNDLE if the venv layout ever changes.
_PIP_VENDORED_CA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", ".venv", "Lib", "site-packages", "pip", "_vendor", "certifi", "cacert.pem",
)


def build_ssl_context() -> Optional[ssl.SSLContext]:
    # Returns an SSL context backed by a known-good CA bundle, or None to use
    # the interpreter's (broken) default when no usable bundle is found.
    ca_file = os.getenv("DEEPSEEK_CA_BUNDLE") or _PIP_VENDORED_CA
    ca_file = os.path.normpath(ca_file)
    if os.path.exists(ca_file):
        return ssl.create_default_context(cafile=ca_file)
    return None


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def normalize_result_url(href: str) -> str:
    # DDG wraps real URLs in a redirect like
    # //duckduckgo.com/l/?uddg=<urlencoded>&rut=...; unwrap it. Also fix
    # scheme-relative links so everything is an absolute https URL.
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path == "/l/" or parsed.path.endswith("/l/"):
        real = urllib.parse.parse_qs(parsed.query).get("uddg", [])
        if real:
            return real[0]
    return href


class _ResultParser(HTMLParser):
    # Collects result links (a.result__a) and snippets (a.result__snippet)
    # from a DDG HTML search page.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: List[SearchResult] = []
        self._link: Optional[dict] = None
        self._snippet: Optional[SearchResult] = None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        d = dict(attrs)
        classes = (d.get("class") or "").split()
        if "result__a" in classes:
            self._link = {"title": "", "url": normalize_result_url(d.get("href", ""))}
        elif "result__snippet" in classes and self.results:
            # Snippet belongs to the most recently seen result link.
            self._snippet = self.results[-1]

    def handle_data(self, data):
        if self._link is not None:
            self._link["title"] += data
        elif self._snippet is not None:
            self._snippet.snippet += data

    def handle_endtag(self, tag):
        if tag != "a":
            return
        if self._link is not None:
            self.results.append(SearchResult(
                title=self._link["title"].strip(),
                url=self._link["url"],
                snippet="",
            ))
            self._link = None
        self._snippet = None


def parse_search_results(html: str) -> List[SearchResult]:
    parser = _ResultParser()
    parser.feed(html)
    # Drop entries that got no real URL.
    return [r for r in parser.results if r.url and r.url.startswith("http")]


_SKIP_TAGS = {"script", "style", "noscript", "svg", "form", "nav", "footer",
              "header", "iframe", "template", "aside"}
_BLOCK_TAGS = {"p", "li", "br", "tr", "div", "h1", "h2", "h3", "h4", "h5",
               "blockquote", "pre", "section", "article", "td", "th", "table"}


class _TextExtractor(HTMLParser):
    # Pulls the visible text out of an HTML page, skipping non-content tags
    # and inserting newlines at block boundaries so the model gets prose.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: List[str] = []
        self.title = ""
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0 and data.strip():
            self.chunks.append(data)


def extract_text(html: str) -> Tuple[str, str]:
    # Returns (page_title, cleaned_text) for an HTML document.
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(parser.chunks))
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return parser.title.strip(), "\n".join(lines)


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Reserve room for the trailing ellipsis so the result stays <= limit.
    return text[:max(limit - 3, 0)] + "..."


async def web_search(session: aiohttp.ClientSession, query: str) -> List[SearchResult]:
    # Returns DDG search results for the query; raises LLMError on failure.
    url = SEARCH_URL.format(query=urllib.parse.quote_plus(query))
    timeout = aiohttp.ClientTimeout(total=SEARCH_TIMEOUT_SECONDS)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT},
                               timeout=timeout, ssl=build_ssl_context()) as resp:
            body = await resp.text()
            status = resp.status
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        raise LLMError(f"web search request failed: {e}")
    if status != 200:
        raise LLMError(f"web search returned HTTP {status}", status=status)
    results = parse_search_results(body)
    if not results:
        raise LLMError("web search returned no results")
    return results


async def fetch_page_text(session: aiohttp.ClientSession, url: str, limit: int = PAGE_CHAR_LIMIT) -> str:
    # Fetches a page and returns its visible text capped at `limit` chars,
    # prefixed with the page title. Raises LLMError on failure.
    timeout = aiohttp.ClientTimeout(total=PAGE_TIMEOUT_SECONDS)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT},
                               timeout=timeout, ssl=build_ssl_context()) as resp:
            if resp.status != 200:
                raise LLMError(f"page fetch of {url} returned HTTP {resp.status}", status=resp.status)
            body = await resp.text()
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        raise LLMError(f"page fetch of {url} failed: {e}")
    title, text = extract_text(body[:MAX_PAGE_BYTES])
    if not text:
        raise LLMError(f"no readable text extracted from {url}")
    prefix = f"Title: {title}\n" if title else ""
    return truncate_text(prefix + text, limit)
