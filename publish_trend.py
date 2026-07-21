"""Research a Korea trend topic and publish (or update) a Blogger post."""

from datetime import datetime, timezone
from html import escape

from googleapiclient.discovery import build

from auth_blogger import load_credentials

# Manual curation for this cron run (Google Trends KR, ~2026-07-21).
TREND_KEYWORD = "관광객"
TREND_LABEL = "여름 해외여행 L.I.T.E"
RELATED = ["일본 여행", "중국 여행", "시성비", "근거리 여행", "미야코지마", "다낭"]

# Stable id for updating today's article instead of duplicating.
POST_ID = "8398839996704702092"


def build_post(now: str) -> tuple[str, str, list[str]]:
    title = f"2026 여름 여행 트렌드 정리: 근거리·소도시·중국, 그리고 ‘가벼운’ 휴가"
    content = f"""
<p>고환율과 여행비 부담이 이어지면서 여름휴가의 기준도 바뀌고 있습니다.
멀리 떠나는 장기 여행보다 <strong>가까운 곳에서, 짧게, 그러나 분명한 경험</strong>을 챙기려는 수요가 커졌고,
최근 검색 데이터에서도 그 흐름이 뚜렷하게 드러납니다.</p>

<p>호텔스컴바인과 카약은 2026년 7월 1일부터 8월 31일까지 한국인 여행객의
해외 항공권·호텔 검색 데이터를 분석해 올여름 트렌드를 <strong>L.I.T.E</strong>로 정리했습니다.
동시에 Google 트렌드(한국)에서도 <strong>{escape(TREND_KEYWORD)}</strong> 관련 관심이 높게 나타나고 있어,
성수기 여행 수요를 한곳에 모아 정리해 봅니다.</p>

<h2>L.I.T.E란 무엇인가</h2>
<p>L.I.T.E는 네 가지 축의 앞 글자를 붙인 표현입니다.</p>
<ul>
  <li><strong>L · Lasting Favorites</strong> — 일본·베트남처럼 꾸준히 선택받는 근거리 여행지</li>
  <li><strong>I · Indie Picks</strong> — 대도시 대신 소도시·비명소로 눈을 돌리는 취향 여행</li>
  <li><strong>T · Trending China</strong> — 중국 항공권 검색 증가와 재관심</li>
  <li><strong>E · Efficient Escape</strong> — 1~2박 중심의 짧고 실속 있는 일정</li>
</ul>
<p>한 줄로 말하면 “멀리·오래·고급”보다 “가까이·짧게·효율”이 올해 여름의 중심축입니다.</p>

<h2>1. 항공권 검색 1위는 일본… 근거리 아시아 강세</h2>
<p>해외 항공권 검색량 상위 국가는 <strong>일본 → 베트남 → 중국 → 태국 → 미국</strong> 순이었습니다.
상위권이 대부분 아시아권에 몰려 있다는 점 자체가, 장거리 대륙 이동보다 접근성 좋은 목적지를
우선하는 분위기를 보여 줍니다.</p>
<p>특히 일본은 전체 해외 항공권 검색의 <strong>30% 이상</strong>을 차지하며 압도적 1위였습니다.
비행시간이 짧고 노선 선택지가 많은 데다, 엔화 약세와 가격 경쟁력이 겹치면서
“부담은 줄이고 빈도는 늘리는” 여행지로서의 지위가 굳어진 모습입니다.</p>
<p>베트남은 나트랑·다낭·푸꾸옥을 중심으로 안정적인 검색 수요를 유지했습니다.
휴양지 호텔·리조트 선택지가 다양하고 체류비 부담이 비교적 낮아,
짧은 휴가에도 바다·리조트 경험을 원하는 수요와 잘 맞습니다.</p>

<h2>2. 중국이 ‘증가율’ 1위인 이유</h2>
<p>검색 <em>증가율</em>에서는 중국이 눈에 띕니다. 중국 항공권 검색량은 전년 같은 기간보다
약 <strong>6.4%</strong> 늘었고, 조사 대상 국가 중 가장 큰 상승폭을 기록했습니다.
도시별로는 <strong>칭다오</strong>와 <strong>상하이</strong>의 상승이 상대적으로 컸습니다.</p>
<p>배경으로는 무비자 입국 정책, 비교적 합리적인 물가, 짧은 비행시간,
그리고 현지 체험형 콘텐츠에 대한 관심이 함께 거론됩니다.
단순히 “저렴해서”가 아니라, 입국 장벽과 체류 부담이 동시에 낮아지면서
재방문·첫방문 모두 문턱이 내려간 것으로 보는 편이 자연스럽습니다.</p>

<h2>3. 도쿄·오사카를 넘어 소도시로</h2>
<p>일본 여행이 반복될수록 익숙한 대도시만 도는 패턴도 조금씩 바뀌고 있습니다.
전년 대비 호텔 검색 증가율 상위 10곳 중 <strong>7곳이 일본 지역</strong>이었고,
미야코지마·고베·오키나와 온나손·모토부·기타큐슈 등이 이름을 올렸습니다.</p>
<p>그중 <strong>미야코지마</strong>는 호텔 검색량이 전년보다 약 <strong>27%</strong> 늘어
일본 지역 중 가장 가파른 상승세를 보였습니다.
에메랄드빛 바다로 알려진 휴양 이미지가 강한 데다,
대도시 일정에 지친 여행객이 “한 곳에서 천천히” 쉬고 싶은 욕구와 맞물린 결과로 읽힙니다.</p>
<p>고베나 기타큐슈처럼 접근성은 좋으면서도 과밀한 관광 동선에서 벗어난 도시도
대안지로 떠오르고 있습니다. 소도시 여행의 핵심은 명소 개수보다
<strong>호흡을 낮춘 일정과 지역 고유의 분위기</strong>에 있습니다.</p>

<h2>4. 국내도 ‘대표 도시’와 ‘조용한 휴식지’가 함께 움직인다</h2>
<p>국내 호텔 검색량은 제주·부산·서울 순으로 많았습니다.
다만 전년 대비 <em>증가율</em>에서는 동해·제천·경주·남해 등이 상위권에 올랐습니다.
대표 관광도시를 찾는 수요는 여전하지만, 동시에 해안·호수·문화유산·자연경관을 중심으로
조용히 쉬려는 선택지도 넓어지고 있다는 신호입니다.</p>

<h2>5. 일정은 짧게, 숙소는 실속으로</h2>
<p>해외 호텔 검색에서 <strong>1박·2박 일정이 전체의 46%</strong>를 차지했습니다.
장기 휴가를 한 번에 쓰기보다, 비행시간이 짧은 목적지를 골라
주말이나 짧은 연휴에 다녀오는 패턴이 커졌다는 뜻입니다.</p>
<p>짧은 여행에서는 여러 도시를 이동하기보다
한 도시에서 핵심 관광지·음식·쇼핑·휴식을 집중하는 편이 유리합니다.
“많이 돌아다니기”보다 “원하는 경험 하나를 제대로”가 시성비(시간 대비 만족도)에 가깝습니다.</p>
<p>숙소 등급에서도 변화가 보입니다. 4성급 검색 비중은 여전히 가장 높지만,
전년 대비로는 <strong>5성급 비중이 줄고 3성급 비중은 늘었습니다</strong>.
품질을 아예 포기하기보다 위치·청결·기본 편의시설을 지키면서
불필요한 비용을 줄이려는 실속형 선택으로 해석할 수 있습니다.</p>

<h2>이 트렌드가 말하는 것</h2>
<p>올해 여름의 여행객은 여행을 포기하기보다
<strong>목적지·숙소·기간을 조정해 여행을 이어가는</strong> 쪽에 가깝습니다.
가까운 국가와 도시를 고르고, 숙박 일수를 줄이는 대신
짧은 시간 안에 원하는 경험을 분명히 가져가려 합니다.</p>
<p>정리하면 2026년 여름 키워드는 네 가지입니다.</p>
<ol>
  <li>일본·베트남 중심의 근거리 선호</li>
  <li>대도시 다음 단계로서의 소도시·비명소</li>
  <li>중국 여행 관심의 재상승</li>
  <li>1~2박·3~4성급 중심의 효율적 휴가</li>
</ol>

<h2>여행 전에 체크하면 좋은 포인트</h2>
<ul>
  <li><strong>목적지를 하나로 고정하기</strong> — 짧은 일정일수록 이동 비용을 줄이는 것이 만족도를 올립니다.</li>
  <li><strong>소도시라면 교통편을 먼저 보기</strong> — 미야코지마·온나손처럼 매력적인 곳일수록 접근 동선이 핵심입니다.</li>
  <li><strong>숙소는 ‘등급’보다 ‘위치·리뷰·조식’을 보기</strong> — 3~4성급에서도 동선이 좋으면 일정이 훨씬 편해집니다.</li>
  <li><strong>중국은 입국·결제·앱 환경을 사전 확인</strong> — 무비자 혜택을 활용하려면 출발 전 최신 입국 요건을 확인하는 것이 안전합니다.</li>
  <li><strong>국내 대안지도 열어두기</strong> — 동해·제천·경주·남해처럼 휴식형 목적지는 비행 없이 시성비를 챙기기 좋습니다.</li>
</ul>

<h2>함께 보면 좋은 키워드</h2>
<ul>
{"".join(f"<li>{escape(item)}</li>" for item in RELATED)}
</ul>

<p>참고: 호텔스컴바인·카약 2026년 여름 여행 트렌드(L.I.T.E) 발표,
여행레저신문 보도, Google Trends KR. 작성일 {escape(now[:10])}.</p>
""".strip()
    labels = ["여행", "트렌드", TREND_KEYWORD, "일본여행", "중국여행", "시성비"]
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

    body = {
        "kind": "blogger#post",
        "id": POST_ID,
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
        "labels": labels,
    }

    # Prefer updating today's curated post when POST_ID is set.
    if POST_ID:
        post = (
            service.posts()
            .update(blogId=blog_id, postId=POST_ID, body=body)
            .execute()
        )
        print("Updated successfully.")
    else:
        # Avoid same-day duplicates by title.
        recent = service.posts().list(blogId=blog_id, maxResults=10, fetchBodies=False).execute()
        for existing in recent.get("items") or []:
            if existing.get("title") == title:
                print(f"Already published: {existing.get('url')}")
                return
        post = service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
        print("Published successfully.")

    print(f"Keyword: {TREND_KEYWORD}")
    print(f"Title: {post.get('title')}")
    print(f"URL: {post.get('url')}")
    print(f"Post ID: {post.get('id')}")


if __name__ == "__main__":
    main()
