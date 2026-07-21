"""Read recent Blogger posts and print content previews."""

import argparse
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


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


def html_to_preview(content: str, max_chars: int) -> str:
    parser = TextExtractor()
    parser.feed(content or "")
    text = unescape(parser.text())
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read recent Blogger posts.")
    parser.add_argument("--limit", type=int, default=5, help="Number of posts to read.")
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=280,
        help="Maximum characters to print from each post body.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.preview_chars < 20:
        raise SystemExit("--preview-chars must be at least 20")

    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    blog_name = blog.get("name", "(unnamed)")
    print(f"Using blog: {blog_name} ({blog_id})")

    response = (
        service.posts()
        .list(
            blogId=blog_id,
            fetchBodies=True,
            maxResults=args.limit,
            orderBy="published",
            status="LIVE",
        )
        .execute()
    )
    posts = response.get("items") or []
    if not posts:
        print("No live posts found.")
        return

    for index, post in enumerate(posts, start=1):
        print()
        print(f"{index}. {post.get('title', '(untitled)')}")
        print(f"   URL: {post.get('url', '(no url)')}")
        print(f"   Published: {post.get('published', '(unknown)')}")
        print(f"   Preview: {html_to_preview(post.get('content', ''), args.preview_chars)}")


if __name__ == "__main__":
    main()
