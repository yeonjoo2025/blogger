"""Publish a one-off test post to Blogger."""

from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")


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


def main() -> None:
    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    blog_name = blog.get("name", "(unnamed)")
    print(f"Using blog: {blog_name} ({blog_id})")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    title = f"[테스트] 자동 발행 확인 {now}"
    content = f"""
<p>이 글은 Blogger API 연동 테스트용 게시글입니다.</p>
<p>작성 시각: <strong>{now}</strong></p>
<p>정상이라면 자동화 파이프라인에서 같은 방식으로 본글을 발행할 수 있습니다.</p>
""".strip()

    body = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
    }
    post = service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
    print("Published successfully.")
    print(f"Title: {post.get('title')}")
    print(f"URL: {post.get('url')}")
    print(f"Post ID: {post.get('id')}")


if __name__ == "__main__":
    main()
