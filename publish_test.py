"""Publish a one-off test post to Blogger."""

from datetime import datetime, timezone

from googleapiclient.discovery import build

from blogger_auth import load_credentials


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
