"""Format the latest Blogger post as a casual Naver-style Slack message."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from googleapiclient.discovery import build

from blogger_auth import load_credentials

# Blank paragraphs: Hangul Filler so empty gaps don't vanish in some editors.
HANGUL_FILLER = "\u3164"


class BlogTextExtractor(HTMLParser):
    """Convert simple Blogger HTML into readable plain text blocks."""

    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "li", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._in_li = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3"}:
            self.parts.append("\n\n")
        elif tag == "li":
            self._in_li = True
            self.parts.append("\n- ")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "li":
            self._in_li = False
            self.parts.append("\n")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        text = unescape(" ".join(self.parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(content: str) -> str:
    parser = BlogTextExtractor()
    parser.feed(content or "")
    return parser.text()


def for_naver_paste(plain: str) -> str:
    """Normalize plain text for Slack delivery (no mrkdwn / code fences).

    Important: Slack drag-select copy puts text/html on the clipboard, and
    Naver SmartEditor prefers that HTML — which often collapses line breaks.
    Users should copy via Slack's "Copy text" / "텍스트 복사", or paste into
    Naver with Ctrl+Shift+V (paste without formatting).

    We still keep real newlines + Hangul-filler blank lines so plain-text
    copy paths preserve paragraph structure.
    """
    lines: list[str] = []
    for line in plain.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() == "":
            lines.append(HANGUL_FILLER)
        else:
            lines.append(line.rstrip())
    # Paragraph spacing: blank filler line between blocks already in source;
    # collapse runs of fillers to a single filler.
    out: list[str] = []
    prev_filler = False
    for line in lines:
        is_filler = line == HANGUL_FILLER
        if is_filler and prev_filler:
            continue
        out.append(line)
        prev_filler = is_filler
    return "\n".join(out).strip()


def write_naver_ready_file(plain: str, path: Path) -> Path:
    """Write UTF-8 plain text for optional raw-file fallback."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # File fallback should use real empty lines, not Hangul filler.
    cleaned = "\n".join(
        "" if line == HANGUL_FILLER else line for line in plain.split("\n")
    )
    # If caller passed already-plain text without fillers, write as-is.
    if HANGUL_FILLER not in plain:
        cleaned = plain
    path.write_text(cleaned.strip() + "\n", encoding="utf-8")
    return path


def casualize_for_naver(title: str, body_text: str, url: str) -> str:
    """Return Slack body text (title + body + source). No code fences."""
    intro = (
        "요즘 읽기 좋게 네이버 블로그 톤으로 살짝 풀어봤어요.\n"
        "너무 딱딱하지 않게, 편하게 쭉 읽히는 느낌으로 정리했습니다."
    )
    closing = (
        "정리하면, 핵심은 어렵게 접근하기보다 일상에서 바로 써먹을 수 있는 포인트를 "
        "가볍게 잡아보는 거예요. 필요하면 이 글을 바탕으로 더 짧은 카드뉴스 톤이나 "
        "검색 유입용 제목으로도 다시 다듬을 수 있습니다."
    )
    source = f"\n\n참고 링크: {url}" if url else ""
    plain = f"{title}\n\n{intro}\n\n{body_text}\n\n{closing}{source}".strip()
    return for_naver_paste(plain)


def latest_post(service) -> dict:
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    response = (
        service.posts()
        .list(
            blogId=blog_id,
            fetchBodies=True,
            maxResults=1,
            orderBy="PUBLISHED",
            status="LIVE",
        )
        .execute()
    )
    posts = response.get("items") or []
    if not posts:
        raise SystemExit("No live posts found.")
    return posts[0]


def main() -> None:
    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    post = latest_post(service)
    title = post.get("title", "(untitled)")
    content = html_to_text(post.get("content", ""))
    url = post.get("url", "")

    print(casualize_for_naver(title, content, url))


if __name__ == "__main__":
    main()
