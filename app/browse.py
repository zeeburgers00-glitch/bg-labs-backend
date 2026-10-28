"""
app/browse.py - server-side research/browsing for the agent skills.

Ports the useful half of the browsing-skill repos (Tencent/BrowserSkill,
browsing-skills, fullselfbrowsing/FSB) into something that runs on Vercel: no
headless Chrome, no Playwright - just careful HTTP plus a stdlib HTML parser.

What it gives the agents:
* ``snapshot(url)``      readable text, title, description, headings, links
* ``search(query)``      web results (DuckDuckGo HTML endpoint, no key)
* ``research(topic)``    a sourced brief: search -> fetch top pages -> extract facts
* ``youtube_id(url)``    pull a video id out of any YouTube URL form

Safety: outbound requests are restricted to http(s), public IPs only (no
loopback, link-local, private or cloud-metadata ranges), with redirect, size and
timeout caps. That matters because these endpoints take user-supplied URLs.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import json
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

logger = logging.getLogger("bglabs.browse")

USER_AGENT = ("Mozilla/5.0 (compatible; BGLabsResearchBot/1.0; +https://bg-labs-backend.vercel.app) "
              "Chrome/124.0 Safari/537.36")
MAX_BYTES = 4_000_000
DEFAULT_TIMEOUT = 25.0
MAX_RESULTS = 8

BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"), ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"), ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"), ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::1/128"), ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"), ipaddress.ip_network("::/128"),
]

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "head", "nav",
             "footer", "form", "button", "select", "option"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
              "blockquote", "pre", "td", "th", "header", "aside", "main", "figcaption"}


class BrowseError(Exception):
    def __init__(self, message: str, *, status_code: int = 502, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.hint = hint

    def as_dict(self) -> Dict[str, Any]:
        out = {"error": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


class _Extractor(HTMLParser):
    """Stdlib-only readable-text extraction (no bs4/lxml on Vercel)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.headings: List[Dict[str, str]] = []
        self.links: List[Dict[str, str]] = []
        self.paragraphs: List[str] = []
        self._skip_depth = 0
        self._buffer: List[str] = []
        self._in_title = False
        self._current_heading: Optional[str] = None
        self._heading_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = {k.lower(): (v or "") for k, v in attrs}
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            content = attributes.get("content", "")
            if name in ("description", "og:description", "twitter:description") and not self.description:
                self.description = content
        elif tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href", "")
        elif tag == "a":
            href = attributes.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.links.append({"href": href, "text": ""})
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._current_heading = tag
            self._heading_buffer = []
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._current_heading:
            text = " ".join("".join(self._heading_buffer).split())
            if text:
                self.headings.append({"level": self._current_heading, "text": text[:300]})
            self._current_heading = None
            self._heading_buffer = []
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        if self._current_heading is not None:
            self._heading_buffer.append(data)
        if self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = " ".join(data.split())[:160]
        self._buffer.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if len(text) >= 25:
            self.paragraphs.append(text)

    def close(self) -> None:  # pragma: no cover - parser API
        super().close()
        self._flush()


def parse_html(markup: str, base_url: str = "") -> Dict[str, Any]:
    parser = _Extractor()
    try:
        parser.feed(markup or "")
        parser.close()
    except Exception as exc:
        logger.debug("html parse issue: %s", exc)
    text = "\n\n".join(parser.paragraphs)
    if not text.strip():
        text = re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", markup or "")).strip()
    links: List[Dict[str, str]] = []
    seen = set()
    for link in parser.links:
        href = urljoin(base_url, link["href"]) if base_url else link["href"]
        if href in seen or not href.startswith(("http://", "https://")):
            continue
        seen.add(href)
        links.append({"href": href, "text": link["text"] or href})
        if len(links) >= 120:
            break
    return {
        "title": " ".join(parser.title.split())[:300],
        "description": " ".join(parser.description.split())[:600],
        "canonical": urljoin(base_url, parser.canonical) if parser.canonical else "",
        "headings": parser.headings[:60],
        "links": links,
        "text": text[:60000],
        "word_count": len(text.split()),
    }


def _assert_safe_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise BrowseError("Only http(s) URLs can be fetched.", status_code=400)
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host:
        raise BrowseError("That URL has no host.", status_code=400)
    if parsed.username or parsed.password:
        raise BrowseError("Credentials in URLs are not allowed.", status_code=400)
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BrowseError(f"Could not resolve '{host}'.", status_code=400, hint=str(exc))
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved \
                or address.is_multicast or any(address in net for net in BLOCKED_NETS):
            raise BrowseError(f"Refusing to fetch a non-public address ({address}).", status_code=400,
                              hint="Only public internet URLs are allowed - this blocks SSRF against "
                                   "internal services and cloud metadata endpoints.")
    return url


async def fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT, max_bytes: int = MAX_BYTES,
                accept: str = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5"
                ) -> Tuple[str, str, int]:
    """GET a public URL. Returns (body_text, content_type, status_code)."""
    _assert_safe_url(url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=12.0), follow_redirects=True,
                                 max_redirects=5, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                                          "Accept-Language": "en-US,en;q=0.9"}) as client:
        try:
            async with client.stream("GET", url) as response:
                ctype = (response.headers.get("content-type") or "").split(";")[0].strip()
                chunks: List[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= max_bytes:
                        break
                body = b"".join(chunks)
                status = response.status_code
        except httpx.HTTPError as exc:
            raise BrowseError(f"Fetch failed: {exc}", status_code=502,
                              hint="The site may block datacenter traffic or require JavaScript.")
    if status >= 400:
        raise BrowseError(f"{url} returned HTTP {status}.", status_code=502)
    if ctype and not ctype.startswith(("text/", "application/json", "application/xml", "application/xhtml")):
        raise BrowseError(f"{ctype} is not a readable document.", status_code=415,
                          hint="Use /api/media/download for binary files.")
    if "json" in ctype:
        return body.decode("utf-8", "replace"), ctype, status
    return body.decode("utf-8", "replace"), ctype or "text/html", status


async def snapshot(url: str, *, max_chars: int = 20000) -> Dict[str, Any]:
    """Readable snapshot of one page."""
    url = _assert_safe_url(url)
    body, ctype, status = await fetch(url)
    if "json" in ctype:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = None
        return {"url": url, "status": status, "kind": "json", "title": url, "description": "",
                "text": json.dumps(data, ensure_ascii=False)[:max_chars] if data else body[:max_chars],
                "json": data, "word_count": len(body.split()), "links": [], "headings": []}
    parsed = parse_html(body, base_url=url)
    parsed.update({"url": url, "status": status, "kind": "html"})
    parsed["text"] = parsed["text"][:max_chars]
    parsed["quotes"] = extract_facts(parsed["text"])
    return parsed


def extract_facts(text: str, limit: int = 12) -> List[str]:
    """Sentences that look like usable, attributable facts (numbers, dates, claims)."""
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text or ""))
    scored: List[Tuple[int, str]] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 40 or len(sentence) > 320:
            continue
        score = 0
        if re.search(r"\b\d[\d,\.]*\s?(%|percent|million|billion|k|x|times|days?|weeks?|months?|years?)\b",
                     sentence, re.I):
            score += 3
        if re.search(r"\b(20\d{2}|19\d{2})\b", sentence):
            score += 2
        if re.search(r"\b(found|founded|launched|released|published|reported|found that|shows|increased|"
                     r"decreased|compared|average|total|according to|study|research)\b", sentence, re.I):
            score += 2
        if re.search(r"\b(I|we|you)\b", sentence, re.I):
            score -= 1
        if score > 0:
            scored.append((score, sentence))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    out, seen = [], set()
    for _, sentence in scored:
        key = sentence[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sentence)
        if len(out) >= limit:
            break
    return out


def _ddg_result_url(href: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<encoded>; unwrap them."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/") or "duckduckgo.com/y.js" in parsed.netloc + parsed.path:
        query = parse_qs(parsed.query)
        if "uddg" in query:
            return unquote(query["uddg"][0])
    return href


async def search(query: str, *, max_results: int = MAX_RESULTS) -> List[Dict[str, str]]:
    """Keyless web search via the DuckDuckGo HTML endpoint."""
    query = (query or "").strip()
    if len(query) < 2:
        raise BrowseError("A search query is required.", status_code=400)
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=us-en"
    async with httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=12.0), follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise BrowseError(f"Search request failed: {exc}", status_code=502)
    if response.status_code >= 400:
        raise BrowseError(f"Search returned HTTP {response.status_code}.", status_code=502,
                          hint="DuckDuckGo rate limits datacenter IPs - retry shortly.")
    markup = response.text
    results: List[Dict[str, str]] = []
    # result links look like <a rel="nofollow" class="result__a" href="...">Title</a>
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', markup, re.S):
        href = _ddg_result_url(html_lib.unescape(match.group(1)))
        title = re.sub(r"<[^>]+>", "", match.group(2))
        title = " ".join(html_lib.unescape(title).split())
        if not href.startswith(("http://", "https://")):
            continue
        results.append({"title": title[:240], "url": href})
        if len(results) >= max_results:
            break
    if not results:  # fallback: any external link inside a result block
        for match in re.finditer(r'<a[^>]+class="[^"]*result__url[^"]*"[^>]*href="([^"]+)"', markup):
            href = _ddg_result_url(html_lib.unescape(match.group(1)))
            if href.startswith(("http://", "https://")):
                results.append({"title": href, "url": href})
            if len(results) >= max_results:
                break
    # snippets follow each result in class="result__snippet"
    snippets = [re.sub(r"<[^>]+>", "", s) for s in
                re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', markup, re.S)]
    for index, result in enumerate(results):
        if index < len(snippets):
            result["snippet"] = " ".join(html_lib.unescape(snippets[index]).split())[:400]
    return results


async def research(topic: str, *, urls: Optional[List[str]] = None, max_pages: int = 4,
                   angle: str = "") -> Dict[str, Any]:
    """Search -> fetch the best pages -> return a sourced brief the agents can use.

    This is what makes ``/yt-script`` able to say "never invent a number": the
    numbers come from here, with the page they came from.
    """
    topic = (topic or "").strip()
    if not topic:
        raise BrowseError("A topic is required.", status_code=400)
    query = f"{topic} {angle}".strip()
    sources: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    candidates: List[str] = [u.strip() for u in (urls or []) if u.strip()]
    if not candidates:
        try:
            found = await search(query, max_results=max_pages + 2)
            candidates = [item["url"] for item in found]
            search_results = found
        except BrowseError as exc:
            search_results = []
            errors.append({"stage": "search", "error": exc.message, "hint": exc.hint or ""})
    else:
        search_results = []

    async def one(url: str) -> Optional[Dict[str, Any]]:
        try:
            snap = await snapshot(url, max_chars=14000)
        except BrowseError as exc:
            errors.append({"url": url, "error": exc.message, "hint": exc.hint or ""})
            return None
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:200]})
            return None
        return {"url": url, "title": snap.get("title") or url, "description": snap.get("description", ""),
                "facts": snap.get("quotes") or extract_facts(snap.get("text", "")),
                "headings": [h["text"] for h in (snap.get("headings") or [])][:12],
                "word_count": snap.get("word_count", 0),
                "excerpt": (snap.get("text") or "")[:1200]}

    fetched = await asyncio.gather(*[one(url) for url in candidates[:max_pages]])
    sources = [item for item in fetched if item]

    facts: List[Dict[str, str]] = []
    for source in sources:
        for fact in source["facts"][:5]:
            facts.append({"fact": fact, "source": source["url"], "title": source["title"]})

    brief = {
        "topic": topic,
        "angle": angle,
        "query": query,
        "search_results": search_results,
        "sources": sources,
        "facts": facts[:40],
        "numbers": sorted({n for source in sources
                           for n in re.findall(r"\b\d[\d,\.]*\s?(?:%|percent|million|billion|k|hours?|days?|"
                                               r"weeks?|months?|years?)\b", source["excerpt"], re.I)})[:30],
        "errors": errors,
        "pages_read": len(sources),
        "guidance": "Every number in a script must be traceable to one of these sources. "
                    "If a claim has no source here, it stays out of the hook and the script.",
    }
    return brief


YT_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/|"
               r"youtube\.com/live/)([A-Za-z0-9_-]{11})"),
    re.compile(r"^([A-Za-z0-9_-]{11})$"),
]


def youtube_id(url_or_id: str) -> str:
    """Extract an 11-character video id from any common YouTube URL form."""
    value = (url_or_id or "").strip()
    if not value:
        return ""
    for pattern in YT_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return ""


def reading_time(word_count: int, wpm: int = 150) -> str:
    minutes = max(1, round((word_count or 0) / max(1, wpm)))
    return f"{minutes} min at {wpm} wpm"


__all__ = ["BrowseError", "snapshot", "fetch", "search", "research", "parse_html", "extract_facts",
           "youtube_id", "reading_time"]
