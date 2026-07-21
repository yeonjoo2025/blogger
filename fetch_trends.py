"""Fetch Google Trends KR list sorted by search volume (past 4 hours)."""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from html import unescape

TRENDS_URL = (
    "https://trends.google.com/trending?geo=KR&hours=4&sort=search-volume"
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class TrendItem:
    rank: int
    title: str
    volume_label: str
    volume: int
    active: bool


def _parse_volume(label: str) -> int:
    """Parse labels like '5K+', '검색 5천+회', '검색 500+회'."""
    text = unescape(label).replace(",", "").strip()
    korean = re.search(r"(\d+(?:\.\d+)?)\s*(천|만)?\+?", text)
    if korean and ("검색" in text or "회" in text or "천" in text or "만" in text):
        value = float(korean.group(1))
        unit = korean.group(2) or ""
        if unit == "천":
            value *= 1_000
        elif unit == "만":
            value *= 10_000
        return int(value)

    english = re.search(r"(\d+(?:\.\d+)?)([KkMm]?)\+?", text)
    if not english:
        return 0
    value = float(english.group(1))
    unit = english.group(2).lower()
    if unit == "k":
        value *= 1_000
    elif unit == "m":
        value *= 1_000_000
    return int(value)


def fetch_trends_by_search_volume(limit: int = 15) -> list[TrendItem]:
    """Return trends in Google's search-volume sort order (page order)."""
    request = urllib.request.Request(
        TRENDS_URL,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    chunks = re.split(r'<div class="mZ3RIc">', html)[1:]
    items: list[TrendItem] = []
    for index, chunk in enumerate(chunks, start=1):
        title_match = re.match(r"([^<]+)", chunk)
        volume_match = re.search(r'<div class="qNpYPd">([^<]+)</div>', chunk)
        if not title_match or not volume_match:
            continue
        title = unescape(title_match.group(1)).strip()
        volume_label = unescape(volume_match.group(1)).strip()
        volume_label = volume_label.replace(" searches", "").replace("searches", "").strip()
        preview = chunk[:2500]
        if "활성" in preview or "Active" in preview:
            active = True
        elif "지속됨" in preview or "Lasted" in preview:
            active = False
        else:
            active = "trending_up" in preview
        items.append(
            TrendItem(
                rank=index,
                title=title,
                volume_label=volume_label,
                volume=_parse_volume(volume_label),
                active=active,
            )
        )
        if len(items) >= limit:
            break

    if not items:
        raise RuntimeError(f"Failed to parse trends from {TRENDS_URL}")
    return items


if __name__ == "__main__":
    for item in fetch_trends_by_search_volume():
        state = "active" if item.active else "lasted"
        print(f"{item.rank:2}. {item.volume_label:>5}  {state:6}  {item.title}")
