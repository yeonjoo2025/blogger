"""Pick a Korea trending topic and publish a Blogger post."""

from datetime import datetime, timezone
from html import escape

from googleapiclient.discovery import build

from auth_blogger import load_credentials

# Manual curation for this cron run (Google Trends KR, ~2026-07-21).
# Prefer evergreen / summary-style topics over rumor or sensitive personal news.
TREND_KEYWORD = "관광객"
TREND_LABEL = "여름 해외여행 L.I.T.E"
RELATED = ["일본 여행", "중국 여행", "시성비", "근거리 여행"]


def build_post(now: str) -> tuple[str, str, list[str]]:
    title = f"[트렌드] {TREND_KEYWORD} · {TREND_LABEL} ({now[:10]})"
    related_html = "".join(f"<li>{escape(item)}</li>" for item in RELATED)
    content = f"""
<p>Google 트렌드(한국) 기준으로 <strong>{escape(TREND_KEYWORD)}</strong> 관련 검색이 활발합니다.
오늘은 여름 성수기 해외여행 흐름을 짧게 정리합니다.</p>

<h2>올여름 여행 키워드: L.I.T.E</h2>
<p>호텔스컴바인·카약이 한국인 항공·호텔 검색을 분석해 제시한 2026 여름 트렌드는
<strong>L.I.T.E</strong>입니다.</p>
<ul>
  <li><strong>L · Lasting Favorites</strong> — 일본·베트남 등 근거리 인기 여행지 강세</li>
  <li><strong>I · Indie Picks</strong> — 미야코지마·고베 등 소도시 관심 확대</li>
  <li><strong>T · Trending China</strong> — 중국 항공권 검색 전년 대비 약 6.4% 증가</li>
  <li><strong>E · Efficient Escape</strong> — 1~2박 짧은 일정·실속형 숙소 선호</li>
</ul>

<h2>왜 지금 ‘관광객’ 검색이 늘까</h2>
<p>고물가·고환율 속에서 멀리 오래 떠나기보다, 가까운 곳으로 짧게 다녀오며
시간 대비 만족도(시성비)를 챙기는 선택이 늘고 있습니다.
중국은 무비자·합리적 물가·체험형 콘텐츠 수요가 검색 증가를 뒷받침하는 것으로 보입니다.</p>

<h2>관련 키워드</h2>
<ul>
{related_html}
</ul>

<p><em>작성 시각: {escape(now)} · 자동 트렌드 포스팅</em></p>
<p>참고: 호텔스컴바인·카약 2026 여름 여행 트렌드 발표, Google Trends KR</p>
""".strip()
    labels = ["트렌드", TREND_KEYWORD, "여행", "자동포스팅"]
    return title, content, labels


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
    title, content, labels = build_post(now)

    # Skip duplicate title if the same daily trend post already exists.
    recent = service.posts().list(blogId=blog_id, maxResults=10, fetchBodies=False).execute()
    for post in recent.get("items") or []:
        if post.get("title") == title:
            print(f"Already published today: {post.get('url')}")
            return

    body = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
        "labels": labels,
    }
    post = service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
    print("Published successfully.")
    print(f"Keyword: {TREND_KEYWORD}")
    print(f"Title: {post.get('title')}")
    print(f"URL: {post.get('url')}")
    print(f"Post ID: {post.get('id')}")


if __name__ == "__main__":
    main()
