"""Format the latest Blogger post as a casual Naver-style Slack message."""

import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")


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


def load_credentials() -> Credentials:
    if not TOKEN_PATH.exists():
        raise SystemExit("token.json not found. Run: python get_token.py")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise SystemExit("Token invalid. Re-run: python get_token.py")
    return creds


def html_to_text(content: str) -> str:
    parser = BlogTextExtractor()
    parser.feed(content or "")
    return parser.text()


def casualize_for_naver(title: str, body_text: str, url: str) -> str:
    intro = (
        "요즘 읽기 좋게 네이버 블로그 톤으로 살짝 풀어봤어요.\n"
        "너무 딱딱하지 않게, 편하게 쭉 읽히는 느낌으로 정리했습니다."
    )
    closing = (
        "정리하면, 핵심은 어렵게 접근하기보다 일상에서 바로 써먹을 수 있는 포인트를 "
        "가볍게 잡아보는 거예요. 필요하면 이 글을 바탕으로 더 짧은 카드뉴스 톤이나 "
        "검색 유입용 제목으로도 다시 다듬을 수 있습니다."
    )
    source = f"\n\n원문 확인: {url}" if url else ""
    return f"*{title}*\n\n{intro}\n\n{body_text}\n\n{closing}{source}".strip()


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
            orderBy="published",
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
