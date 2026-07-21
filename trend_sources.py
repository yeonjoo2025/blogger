"""Collect trending keyword candidates from multiple public sources.

Each collector is best-effort and defensive: network hiccups or markup
changes on any single source must never crash the whole pipeline. Every
collector returns a plain list of ``TrendItem`` so results from different
sources can be merged and compared across the 1h / 4h / 24h windows.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
HTTP_TIMEOUT = 12
KST = timezone(timedelta(hours=9))

GOOGLE_TRENDS_RSS = "https://trends.google.com/trending/rss?geo=KR"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
LOWORD_URL = "https://loword.co.kr/keywordTrend"
BLACKKIWI_URL = "https://blackkiwi.net/service/trend"

WINDOWS = ("1h", "4h", "24h")


@dataclass
class NewsRef:
    title: str
    url: str = ""
    source: str = ""
    published: str = ""


@dataclass
class TrendItem:
    keyword: str
    source: str
    rank: int | None = None
    traffic: int | None = None
    windows: tuple[str, ...] = field(default_factory=tuple)
    news: list[NewsRef] = field(default_factory=list)


def _log(msg: str) -> None:
    print(f"[trend_sources] {msg}", file=sys.stderr)


def _parse_traffic(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"[\d,]+", raw)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def fetch_google_trends_kr(now: datetime | None = None) -> list[TrendItem]:
    """Google Trends 'Daily Search Trends' RSS feed for South Korea.

    This is an official Google-hosted feed (no auth, no JS rendering
    required) and includes attached news items per trend, which we reuse
    later as grounding for the article body.
    """
    now = now or datetime.now(timezone.utc)
    items: list[TrendItem] = []
    try:
        resp = requests.get(GOOGLE_TRENDS_RSS, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001 - best effort source
        _log(f"google trends rss failed: {exc}")
        return items

    ns = {"ht": "https://trends.google.com/trending/rss"}
    for rank, item in enumerate(root.findall("./channel/item"), start=1):
        title_el = item.find("title")
        if title_el is None or not (title_el.text or "").strip():
            continue
        keyword = title_el.text.strip()

        pub_el = item.find("pubDate")
        age = None
        if pub_el is not None and pub_el.text:
            try:
                pub_dt = parsedate_to_datetime(pub_el.text)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                age = now - pub_dt
            except Exception:  # noqa: BLE001
                age = None

        windows = []
        if age is not None:
            if age <= timedelta(hours=1):
                windows = ["1h", "4h", "24h"]
            elif age <= timedelta(hours=4):
                windows = ["4h", "24h"]
            elif age <= timedelta(hours=24):
                windows = ["24h"]
            else:
                windows = []
        else:
            windows = ["24h"]

        traffic_el = item.find("ht:approx_traffic", ns)
        traffic = _parse_traffic(traffic_el.text if traffic_el is not None else None)

        news_refs = []
        for news_item in item.findall("ht:news_item", ns):
            t = news_item.find("ht:news_item_title", ns)
            u = news_item.find("ht:news_item_url", ns)
            s = news_item.find("ht:news_item_source", ns)
            if t is not None and (t.text or "").strip():
                news_refs.append(
                    NewsRef(
                        title=t.text.strip(),
                        url=(u.text or "").strip() if u is not None else "",
                        source=(s.text or "").strip() if s is not None else "",
                    )
                )

        items.append(
            TrendItem(
                keyword=keyword,
                source="google_trends_kr",
                rank=rank,
                traffic=traffic,
                windows=tuple(windows),
                news=news_refs,
            )
        )

    _log(f"google_trends_kr: {len(items)} items")
    return items


def _render_with_headless_chrome(url: str, wait_ms: int = 9000, hard_timeout: int = 35) -> str:
    """Render a JS-heavy page with headless Chrome and return its DOM HTML.

    Headless Chrome sometimes keeps running past --dump-dom (lingering
    network/service-worker tasks) even though the DOM was already flushed
    to stdout, so we always force-kill via the `timeout` command and treat
    the captured output as valid regardless of the process exit status.
    """
    has_timeout_cmd = shutil.which("timeout") is not None

    for binary in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(binary) is None:
            continue

        profile_dir = tempfile.mkdtemp(prefix="chrome-profile-")
        out_path = Path(tempfile.mkstemp(prefix="chrome-dump-", suffix=".html")[1])
        try:
            chrome_cmd = [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile_dir}",
                f"--virtual-time-budget={wait_ms}",
                "--dump-dom",
                url,
            ]
            cmd = ["timeout", "-k", "5", str(hard_timeout), *chrome_cmd] if has_timeout_cmd else chrome_cmd

            with open(out_path, "wb") as out_fh:
                subprocess.run(
                    cmd,
                    stdout=out_fh,
                    stderr=subprocess.DEVNULL,
                    timeout=hard_timeout + 10,
                    check=False,
                )

            html = out_path.read_text(encoding="utf-8", errors="ignore")
            if html.strip():
                return html
        except subprocess.TimeoutExpired:
            _log(f"headless render hard-timed-out for {binary}")
        except Exception as exc:  # noqa: BLE001
            _log(f"headless render failed for {binary}: {exc}")
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
            out_path.unlink(missing_ok=True)
    return ""


def _html_to_flat_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_between(text: str, start_marker: str, end_marker: str | None) -> str:
    i = text.find(start_marker)
    if i == -1:
        return ""
    i += len(start_marker)
    j = text.find(end_marker, i) if end_marker else -1
    if j == -1:
        j = len(text)
    return text[i:j]


_NAVER_ITEM_RE = re.compile(r"(\d{1,2})\s+(.+?)\s+(NEW|-|▲\s?\d*|▼\s?\d*)(?=\s*\d{1,2}\s|\s*$)")
_GOOGLE_ITEM_RE = re.compile(r"(\d{1,2})\s+(.+?)\s+검색량\s+([\d,]+)\+?\s*(NEW|-|▲\s?\d*|▼\s?\d*)?")


def fetch_loword_keyword_trend() -> list[TrendItem]:
    """loword.co.kr real-time search ranking (Naver + Google), current hour.

    The page is a client-rendered Next.js app, so we render it with headless
    Chrome and scrape the flattened text. The site itself labels this view
    as an hourly ("지난 1시간") snapshot, so results are tagged window="1h".
    """
    items: list[TrendItem] = []
    html = _render_with_headless_chrome(LOWORD_URL)
    if not html:
        _log("loword: headless render returned nothing")
        return items

    text = _html_to_flat_text(html)
    naver_block = _extract_between(text, "네이버에 검색할만한 실시간 검색어", "구글 실시간 검색어")
    google_block = _extract_between(text, "구글 실시간 검색어(구글 트렌드)", "네이버에 검색할만한 실시간 검색어")

    for m in _NAVER_ITEM_RE.finditer(naver_block):
        rank, keyword, _flag = m.groups()
        keyword = keyword.strip().rstrip(".")
        if not keyword:
            continue
        items.append(TrendItem(keyword=keyword, source="loword_naver", rank=int(rank), windows=("1h",)))

    for m in _GOOGLE_ITEM_RE.finditer(google_block):
        rank, keyword, traffic, _flag = m.groups()
        keyword = keyword.strip()
        if not keyword:
            continue
        items.append(
            TrendItem(
                keyword=keyword,
                source="loword_google",
                rank=int(rank),
                traffic=_parse_traffic(traffic),
                windows=("1h",),
            )
        )

    _log(f"loword_keyword_trend: {len(items)} items")
    return items


_BLACKKIWI_ITEM_RE = re.compile(r"(\d{1,2})\s+([가-힣A-Za-z0-9][^\d]{1,40}?)(?=\s+\d{1,2}\s|\s*$)")


def fetch_blackkiwi_trend() -> list[TrendItem]:
    """blackkiwi.net daily rising-keyword ranking (best effort).

    The ranking list appears to require a signed-in session / renders the
    top spots without plain text in anonymous mode, so this frequently
    returns an empty list. That is fine: it is one of three sources and the
    pipeline is designed to keep working with whichever sources succeed.
    """
    items: list[TrendItem] = []
    html = _render_with_headless_chrome(BLACKKIWI_URL, wait_ms=9000)
    if not html:
        _log("blackkiwi: headless render returned nothing")
        return items

    text = _html_to_flat_text(html)
    block = _extract_between(text, "인기 급상승 키워드 일간", "AI 트렌드 인사이트")
    for m in _BLACKKIWI_ITEM_RE.finditer(block):
        rank, keyword = m.groups()
        keyword = keyword.strip()
        if len(keyword) < 2:
            continue
        items.append(TrendItem(keyword=keyword, source="blackkiwi", rank=int(rank), windows=("24h",)))

    _log(f"blackkiwi_trend: {len(items)} items")
    return items


def collect_all_trends(now: datetime | None = None) -> list[TrendItem]:
    """Run every collector defensively and return the combined list."""
    collected: list[TrendItem] = []
    for fn in (fetch_google_trends_kr, fetch_loword_keyword_trend, fetch_blackkiwi_trend):
        try:
            if fn is fetch_google_trends_kr:
                collected.extend(fn(now))
            else:
                collected.extend(fn())
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the run
            _log(f"{fn.__name__} raised {exc!r}")
    return collected


def fetch_related_news(keyword: str, limit: int = 6) -> list[NewsRef]:
    """Query Google News RSS search for real, current articles about a topic."""
    url = GOOGLE_NEWS_RSS.format(q=quote(keyword))
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        _log(f"news search failed for {keyword!r}: {exc}")
        return []

    refs: list[NewsRef] = []
    for item in root.findall("./channel/item")[:limit]:
        title_el = item.find("title")
        if title_el is None or not (title_el.text or "").strip():
            continue
        raw_title = title_el.text.strip()
        source = ""
        title = raw_title
        if " - " in raw_title:
            title, source = raw_title.rsplit(" - ", 1)
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        refs.append(
            NewsRef(
                title=title.strip(),
                url=(link_el.text or "").strip() if link_el is not None else "",
                source=source.strip(),
                published=(pub_el.text or "").strip() if pub_el is not None else "",
            )
        )
    return refs
