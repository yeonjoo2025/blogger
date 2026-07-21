"""Publish a casual one-off blog post to Blogger."""

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


def build_post_content() -> tuple[str, str]:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y.%m.%d")
    title = f"오늘은 조금 가볍게, 다시 블로그를 켜봤다 ({today})"
    content = """
<p>요즘은 무언가를 길게 정리하기보다, 머릿속에 떠오른 생각을 가볍게 붙잡아두고 싶은 날이 더 많다.</p>

<p>그래서 오늘 글도 거창한 결론을 내리기보다는, 블로그를 다시 켜면서 든 생각들을 편하게 적어보려고 한다. 매번 완벽한 글을 써야 한다고 생각하면 시작부터 힘이 빠지는데, 사실 블로그는 조금 서툴고 느슨해도 괜찮은 공간이니까.</p>

<h3>작게 적어두는 것의 힘</h3>
<p>하루를 보내다 보면 별것 아닌 순간들이 은근히 오래 남는다. 산책하다가 본 하늘, 미뤄뒀던 일을 하나 끝냈을 때의 개운함, 아무 이유 없이 집중이 잘되던 오후 같은 것들. 이런 장면은 그냥 지나가면 금방 흐려지지만, 몇 줄이라도 적어두면 나중에 다시 꺼내볼 수 있는 작은 기록이 된다.</p>

<p>블로그 글도 꼭 대단한 정보나 멋진 문장으로만 채울 필요는 없는 것 같다. 지금의 기분, 요즘 자주 하는 생각, 다음에 해보고 싶은 일처럼 일상적인 내용도 충분히 글이 된다. 오히려 그런 글이 시간이 지나면 더 솔직하게 느껴지기도 한다.</p>

<h3>완벽하지 않아도 계속하기</h3>
<p>무언가를 꾸준히 하는 데 가장 큰 방해물은 의외로 완벽하게 하고 싶다는 마음일 때가 있다. 제목을 더 잘 지어야 할 것 같고, 문단을 더 매끄럽게 다듬어야 할 것 같고, 올리기 전에 한 번 더 고쳐야 할 것 같은 마음. 물론 다듬는 과정도 중요하지만, 가끔은 일단 올려보는 쪽이 더 도움이 된다.</p>

<p>오늘의 목표는 그 정도면 충분하다. 너무 무겁지 않게 쓰고, 너무 오래 붙잡지 않고, 지금의 생각을 지금의 온도로 남겨두기.</p>

<h3>다음 글을 위한 작은 메모</h3>
<p>다음에는 요즘 관심 있는 것들, 새로 시도해본 루틴, 혹은 하루를 조금 덜 바쁘게 보내는 방법에 대해서도 써보고 싶다. 특별한 사건이 없어도 기록할 만한 이야기는 늘 어딘가에 있으니까.</p>

<p>오늘은 여기까지. 가볍게 시작했으니, 다음 글도 너무 어렵게 생각하지 않고 이어가 봐야겠다.</p>
""".strip()
    return title, content


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

    title, content = build_post_content()
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
