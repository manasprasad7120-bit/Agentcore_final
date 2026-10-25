import re
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from loguru import logger

from agentcore.custom import Node
from agentcore.io import IntInput, MessageTextInput, Output
from agentcore.schema import DataFrame

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
def _row_to_text(title: str, link: str, snippet: str, content: str) -> str:
    """Pick the richest textual representation for the row.

    Returns content if available, otherwise snippet. Title and link stay in their own
    columns — flows that need them can compose via the Parser component.
    """
    del title, link  # unused; columns stay separate so users compose via Parser
    return content or snippet


class WebSearch(Node):
    display_name = "Web Search"
    description = (
        "Searches the web via DuckDuckGo. Returns title, link, snippet, and page content "
        "for each result. Best for entity queries (people, places, defined topics)."
    )
    icon = "search"
    name = "WebSearchNoAPI"

    inputs = [
        MessageTextInput(
            name="query",
            display_name="Search Query",
            info="Keywords to search for.",
            tool_mode=True,
            required=True,
        ),
        IntInput(
            name="max_results",
            display_name="Max Results",
            info="Maximum number of search results to return.",
            value=5,
        ),
        IntInput(
            name="timeout",
            display_name="Timeout",
            info="Timeout for the web search request.",
            value=5,
            advanced=True,
        ),
    ]

    outputs = [Output(name="results", display_name="Search Results", method="perform_search")]

    def validate_url(self, string: str) -> bool:
        url_regex = re.compile(
            r"^(https?:\/\/)?" r"(www\.)?" r"([a-zA-Z0-9.-]+)" r"(\.[a-zA-Z]{2,})?" r"(:\d+)?" r"(\/[^\s]*)?$",
            re.IGNORECASE,
        )
        return bool(url_regex.match(string))

    def ensure_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if not self.validate_url(url):
            msg = f"Invalid URL: {url}"
            raise ValueError(msg)
        return url

    def _sanitize_query(self, query: str) -> str:
        return re.sub(r'[<>"\']', "", query.strip())

    def _scrape_duckduckgo_html(self, query: str) -> list[dict]:
        """Scrape DuckDuckGo's HTML endpoint. Returns [] when blocked / no results.

        DuckDuckGo serves a CAPTCHA challenge with HTTP 202 when it flags a request as
        bot traffic — the body parses fine but contains no `div.result` elements.
        """
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query, "kl": "us-en"}
        try:
            response = requests.get(url, params=params, headers=_BROWSER_HEADERS, timeout=self.timeout)
        except requests.RequestException as e:
            logger.warning(f"[WebSearch] DDG HTML request failed: {e}")
            return []

        if response.status_code != 200 or "text/html" not in response.headers.get("content-type", "").lower():
            logger.warning(
                f"[WebSearch] DDG HTML returned status={response.status_code} "
                f"ctype={response.headers.get('content-type', '')!r} — likely a bot challenge"
            )
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict] = []
        max_results = max(1, int(getattr(self, "max_results", 5) or 5))
        for result in soup.select("div.result"):
            if len(results) >= max_results:
                break
            title_tag = result.select_one("a.result__a")
            snippet_tag = result.select_one("a.result__snippet")
            if not title_tag:
                continue
            raw_link = title_tag.get("href", "")
            parsed = urlparse(raw_link)
            uddg = parse_qs(parsed.query).get("uddg", [""])[0]
            decoded_link = unquote(uddg) if uddg else raw_link

            try:
                final_url = self.ensure_url(decoded_link)
                page = requests.get(final_url, headers=_BROWSER_HEADERS, timeout=self.timeout)
                page.raise_for_status()
                content = BeautifulSoup(page.text, "lxml").get_text(separator=" ", strip=True)
            except requests.RequestException as e:
                final_url = decoded_link
                content = f"(Failed to fetch: {e!s})"

            title = title_tag.get_text(strip=True)
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            results.append(
                {
                    "title": title,
                    "link": final_url,
                    "snippet": snippet,
                    "content": content,
                    "text": _row_to_text(title, final_url, snippet, content),
                }
            )
        return results

    def _query_duckduckgo_api(self, query: str) -> list[dict]:
        """Fallback: DuckDuckGo Instant Answer JSON API.

        No API key, no CAPTCHA, but only returns useful data for named-entity queries
        (people, places, well-defined topics). Empty for general "how do I..." questions.
        """
        try:
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "no_redirect": 1},
                headers={"User-Agent": _BROWSER_UA},
                timeout=self.timeout,
            )
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"[WebSearch] DDG IA API request failed: {e}")
            return []

        results: list[dict] = []
        max_results = max(1, int(getattr(self, "max_results", 5) or 5))
        abstract = (j.get("AbstractText") or "").strip()
        if abstract:
            title = j.get("Heading") or query
            link = j.get("AbstractURL") or ""
            results.append(
                {
                    "title": title,
                    "link": link,
                    "snippet": abstract[:400],
                    "content": abstract,
                    "text": _row_to_text(title, link, abstract[:400], abstract),
                }
            )

        def _walk_topics(topics: list) -> None:
            for t in topics:
                if len(results) >= max_results:
                    return
                if "Topics" in t:
                    _walk_topics(t["Topics"])
                    continue
                snippet = (t.get("Text") or "").strip()
                first_url = t.get("FirstURL") or ""
                if snippet and first_url:
                    title = snippet.split(" - ", 1)[0][:120]
                    results.append(
                        {
                            "title": title,
                            "link": first_url,
                            "snippet": snippet,
                            "content": snippet,
                            "text": _row_to_text(title, first_url, snippet, snippet),
                        }
                    )

        _walk_topics(j.get("RelatedTopics") or [])
        return results

    def perform_search(self) -> DataFrame:
        query = self._sanitize_query(self.query)
        if not query:
            msg = "Empty search query"
            raise ValueError(msg)

        results = self._scrape_duckduckgo_html(query)
        if not results:
            results = self._query_duckduckgo_api(query)

        if not results:
            self.status = "No results — DuckDuckGo returned a bot challenge for this IP"
            no_results_msg = (
                "DuckDuckGo's search endpoints returned a bot challenge for this IP, and "
                "the Instant Answer API had no data for this query. Try again later, or "
                "use a search component that supports an API key (Tavily, Serper, Bing)."
            )
            return DataFrame(
                pd.DataFrame(
                    [
                        {
                            "title": "No results",
                            "link": "",
                            "snippet": no_results_msg,
                            "content": "",
                            "text": no_results_msg,
                        }
                    ]
                )
            )

        df_results = DataFrame(pd.DataFrame(results))
        self.status = df_results
        return df_results
