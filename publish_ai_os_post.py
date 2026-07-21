"""Publish a casual post about using AI like a daily work OS."""

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

    title = "AI를 검색창 말고 작업 OS처럼 써보면 달라지는 것들"
    content = """
<p>요즘 AI 이야기를 보면 예전이랑 분위기가 꽤 달라졌어요. 전에는 “이거 검색해줘”, “요약해줘” 정도로 쓰는 느낌이 강했다면, 이제는 작은 작업들을 맡기는 <strong>작업 OS</strong>처럼 쓰는 흐름이 점점 커지는 것 같아요.</p>

<p>예를 들면 이런 식이에요. 글감이 떠오르면 AI에게 먼저 목차를 잡아달라고 하고, 마음에 드는 방향만 골라서 다시 다듬습니다. 자료가 길면 핵심만 추려달라고 하고, 애매한 문장은 더 자연스럽게 바꿔달라고 해요. 여기까지는 익숙한데, 요즘은 한 발 더 나아가서 “이 목표를 끝내려면 뭐부터 하면 좋을까?”라고 물어보는 사람들이 많아졌습니다.</p>

<h2>검색보다 “같이 일하는 느낌”에 가까워졌어요</h2>

<p>AI 에이전트라는 말도 자주 보이죠. 말만 들으면 조금 거창하지만, 쉽게 말하면 AI가 단순히 답만 던져주는 게 아니라 목표를 이해하고 중간 단계를 나눠서 도와주는 방식입니다. 일정 정리, 글 초안, 발표 자료 구성, 코드 점검처럼 손이 많이 가는 일을 잘게 쪼개서 함께 처리하는 거예요.</p>

<p>개인적으로는 이 변화가 꽤 현실적으로 느껴져요. 하루 중에 진짜 어려운 일보다 “시작하기 귀찮은 일”이 더 많잖아요. 빈 문서 열고 첫 문장 쓰기, 긴 자료에서 중요한 부분 찾기, 머릿속에 흩어진 생각을 순서대로 정리하기 같은 것들요. AI를 잘 쓰면 이 첫 진입 장벽이 확 낮아집니다.</p>

<h2>그렇다고 전부 맡기면 어색해져요</h2>

<p>물론 AI가 만들어준 결과를 그대로 쓰면 티가 납니다. 문장은 매끈한데 내 경험이 빠져 있거나, 모두에게 맞는 말만 해서 살짝 밍밍해질 때가 있어요. 그래서 저는 AI를 “대필 작가”보다는 “옆자리 편집자”처럼 쓰는 게 더 좋다고 봅니다.</p>

<p>초안은 빠르게 받고, 그다음에 내 말투와 내 경험을 넣는 식이죠. 예를 들어 “요즘 업무 정리할 때 이런 식으로 써보니 편했다”, “이 부분은 아직 불안해서 사람이 꼭 확인해야 한다” 같은 구체적인 감각은 결국 사람이 넣어야 글이 살아납니다.</p>

<h2>처음 써본다면 이렇게 가볍게 시작해보세요</h2>

<ul>
  <li><strong>하나의 목표만 던지기:</strong> “블로그 글 써줘”보다 “AI를 일상 생산성 도구로 쓰는 글의 목차를 잡아줘”가 훨씬 좋아요.</li>
  <li><strong>중간 결과를 고르기:</strong> 처음 나온 답을 바로 쓰기보다 마음에 드는 방향만 선택해서 다시 요청해보세요.</li>
  <li><strong>내 경험 한 스푼 넣기:</strong> AI가 정리한 문장에 내가 실제로 겪은 예시를 붙이면 글이 훨씬 자연스러워집니다.</li>
  <li><strong>마지막 검수는 직접 하기:</strong> 사실관계, 과장된 표현, 어색한 문장은 꼭 사람이 확인하는 게 안전합니다.</li>
</ul>

<p>결국 중요한 건 AI를 얼마나 화려하게 쓰느냐보다, 내 일상에서 반복되는 작은 막힘을 얼마나 부드럽게 풀어주느냐인 것 같아요. 검색창처럼 한 번 묻고 끝내는 도구에서, 생각을 정리하고 일을 시작하게 만드는 작업 파트너로 조금씩 바뀌는 중인 셈이죠.</p>

<p>오늘 할 일이 막막하다면 거창한 자동화부터 생각하지 않아도 됩니다. 그냥 “이 일을 시작하려면 첫 단계가 뭐야?”라고 물어보는 것부터 충분해요. 생각보다 그 한 문장이 꽤 많은 일을 움직이게 해주거든요.</p>
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
