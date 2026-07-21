"""Publish practical guide posts from multi-source trend keywords."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html import escape

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth_blogger import load_credentials
from fetch_trends import (
    SOURCE_URLS,
    TrendItem,
    collect_all_sources,
    fetch_news_headlines,
    select_guide_keywords,
)


def _execute_with_retry(request, retries: int = 5):
    delay = 8
    for attempt in range(retries):
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status in {429, 500, 503} and attempt < retries - 1:
                print(f"API {status}, retry in {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue
            raise


def _guide_title(keyword: str) -> str:
    """SEO-style practical title focused on method / detailed guide."""
    k = keyword.strip()
    if re.search(r"근저당", k):
        return "근저당이란? 뜻·설정 방법·말소 절차 상세 안내"
    if re.search(r"회생법원", k):
        return f"{k} 개인회생 신청 전 확인사항·절차 상세 안내"
    if re.search(r"회생|파산|항고", k):
        return f"{k} 뜻과 대응 방법·절차 총정리"
    if re.search(r"사이드카|코스피|주가|주식|주주", k):
        return f"{k} 의미와 투자자가 확인할 점 상세 해설"
    if re.search(r"쿠팡|물류.*화재|화재.*물류", k):
        return "쿠팡 물류센터 화재 현황과 피해·안전 대응 방법 안내"
    if re.search(r"이관개방", k):
        return "이관개방증 증상·원인·대처 방법 상세 정리"
    if re.search(r"독사", k):
        return "독사 물렸을 때 증상 확인과 응급 대처 방법 상세 안내"
    if re.search(r"은행|대출|금리|보험|세금", k):
        return f"{k} 이용·확인 방법 상세 가이드"
    if re.search(r"항공|항공권|비자", k):
        return f"{k} 예약·이용 전 꼭 확인할 점 안내"
    if re.search(r"SQLD|자격|시험|취업", k, re.I):
        return f"{k} 준비 방법과 일정·합격 포인트 안내"
    if re.search(r"국토교통|법원|신청|절차", k):
        return f"{k} 업무 처리 방법 상세 안내"
    if len(k) <= 8:
        return f"{k} 핵심 의미와 실무 확인 방법 상세 안내"
    return f"{k} 핵심 정리와 실무 확인 방법"


def _topic_bucket(keyword: str) -> str:
    k = keyword.lower()
    if re.search(r"근저당|회생|파산|법원|압류|경매", k):
        return "법률·금융"
    if re.search(r"주가|주식|코스피|사이드카|주주|이더리움|비트코인|환율", k):
        return "투자·자산"
    if re.search(r"화재|물류|대피|산재|안전", k):
        return "생활·안전"
    if re.search(r"은행|대출|금리|보험|세금|카드", k):
        return "금융생활"
    if re.search(r"증상|질환|이관|치료|병원|검진", k):
        return "건강정보"
    if re.search(r"자격|시험|sqld|취업|이직", k):
        return "취업·자격"
    if re.search(r"항공|비자|여행|관광", k):
        return "여행·교통"
    return "실용정보"


def _build_guide_sections(keyword: str, news: list[dict[str, str]]) -> str:
    topic = _topic_bucket(keyword)
    k = escape(keyword)

    news_html = ""
    if news:
        lis = []
        for article in news[:5]:
            source = f" ({escape(article['source'])})" if article.get("source") else ""
            if article.get("link"):
                lis.append(
                    f"<li><a href=\"{escape(article['link'])}\">{escape(article['title'])}</a>{source}</li>"
                )
            else:
                lis.append(f"<li>{escape(article['title'])}{source}</li>")
        news_html = f"<ul>{''.join(lis)}</ul>"
    else:
        news_html = "<p>관련 최신 헤드라인이 제한적입니다. 공식 기관·1차 자료를 우선 확인하세요.</p>"

    # Topic-specific practical bodies
    if topic == "법률·금융":
        body = f"""
<h2>{k} 개념 한눈에 보기</h2>
<p><strong>{k}</strong>는 재산·채무·담보와 직접 연결되는 키워드입니다.
검색이 몰릴 때는 계약·대출·부동산 거래 과정에서 권리관계가 걸린 경우가 많습니다.
용어 뜻을 먼저 정확히 이해한 뒤, 본인 상황에 맞는 절차를 순서대로 확인하는 것이 중요합니다.</p>

<h2>왜 지금 검색이 늘어날까</h2>
<p>금리·부동산·개인 채무 이슈가 겹치면 관련 용어 검색이 급증합니다.
단순 호기심보다 ‘내 계약서에 불리한 조항이 있는지’, ‘신청 자격이 되는지’처럼
실무 확인 수요가 함께 붙는 편이 일반적입니다.</p>

<h2>확인·진행 방법</h2>
<ol>
  <li><strong>내 서류부터 확인</strong> — 등기사항전부증명서, 계약서, 대출약정서, 법원 문서를 모읍니다.</li>
  <li><strong>공식 기준 확인</strong> — 법원·정부24·금융기관 안내처럼 1차 출처의 정의와 요건을 봅니다.</li>
  <li><strong>일정·비용 체크</strong> — 신청 기한, 인지대/수수료, 필요 서류 목록을 표로 정리합니다.</li>
  <li><strong>전문가 상담 기준 정하기</strong> — 금액이 크거나 기한이 임박하면 변호사·법무사·신용상담과 상의합니다.</li>
</ol>

<h2>실무 체크리스트</h2>
<ul>
  <li>내 이름이 권리자/의무자로 어디에 기재돼 있는지</li>
  <li>담보·보증·연대입보 범위가 어디까지인지</li>
  <li>말소·변경·신청 가능 시점</li>
  <li>상담 전 질문 3가지를 미리 적을 것</li>
</ul>
"""
    elif topic == "투자·자산":
        body = f"""
<h2>{k}란 무엇인가</h2>
<p><strong>{k}</strong>는 시장 변동과 투자 판단에 쓰이는 키워드입니다.
검색량이 갑자기 커질 때는 지수 급변, 매매 규정 발동, 개별 종목 이슈가 겹친 경우가 많습니다.</p>

<h2>투자 전 꼭 볼 포인트</h2>
<ol>
  <li><strong>용어 정의</strong> — 뉴스 제목만 보지 말고, 거래소·증권사 가이드의 공식 설명을 확인합니다.</li>
  <li><strong>발동/발표 조건</strong> — 사이드카·서킷브레이커·공시처럼 조건과 해제 시점을 구분합니다.</li>
  <li><strong>내 포지션 영향</strong> — 보유 종목, 예약주문, 미수/신용 여부까지 함께 점검합니다.</li>
  <li><strong>검증된 정보만</strong> — 카톡발·단톡발 급등 정보보다 공시와 정규 시세 데이터를 우선합니다.</li>
</ol>

<h2>초보자가 실수하기 쉬운 점</h2>
<ul>
  <li>검색 상위 = 매수 신호로 오해하기</li>
  <li>단기 변동만 보고 레버리지 확대하기</li>
  <li>수수료·세금·스프레드를 무시하기</li>
</ul>
"""
    elif topic == "건강정보":
        body = f"""
<h2>{k} 기본 정보</h2>
<p><strong>{k}</strong>는 증상·질환 관련 검색어입니다.
갑자기 검색이 늘면 유명인 사례, 계절성 질환, 혹은 관련 콘텐츠 확산이 원인인 경우가 있습니다.
자가진단으로 단정하지 말고, 아래 순서로 정보를 정리해 보세요.</p>

<h2>증상 이해와 대처 순서</h2>
<ol>
  <li>주요 증상과 지속 시간을 메모합니다.</li>
  <li>악화 요인(자세, 비행, 감기, 스트레스 등)이 있었는지 기록합니다.</li>
  <li>신뢰할 수 있는 의학 정보(병원 공식 콘텐츠, 전문의 칼럼)로 개념을 확인합니다.</li>
  <li>일상생활 지장·통증·재발이 있으면 이비인후과 등 관련 진료과 상담을 고려합니다.</li>
</ol>

<h2>주의할 점</h2>
<ul>
  <li>검색 후기만으로 약 복용·시술을 결정하지 않기</li>
  <li>응급 증상(급격한 청력 저하, 심한 어지럼, 호흡곤란 등)은 즉시 진료</li>
  <li>광고성 ‘특효’ 콘텐츠와 의학 정보를 구분하기</li>
</ul>
"""
    elif topic == "취업·자격":
        body = f"""
<h2>{k} 준비 전에 확인할 것</h2>
<p><strong>{k}</strong>는 자격·채용·시험 관련 실무 키워드입니다.
검색이 몰릴 때는 접수 일정, 시험 개편, 채용 시즌이 겹치는 경우가 많습니다.</p>

<h2>합격·취업으로 이어가는 방법</h2>
<ol>
  <li><strong>공식 일정 확인</strong> — 주관처 공고의 원서 접수, 시험일, 합격 발표일을 캘린더에 고정합니다.</li>
  <li><strong>출제 범위 정리</strong> — 과목별 비중과 최근 개정 사항을 표로 만듭니다.</li>
  <li><strong>학습 루틴</strong> — 주 단위로 이론/문제풀이 비율을 나누고, 모의고사 오답노트를 남깁니다.</li>
  <li><strong>비용·교재 예산</strong> — 응시료, 강의, 교재 비용을 미리 책정합니다.</li>
</ol>
"""
    elif topic == "생활·안전":
        body = f"""
<h2>{k} 이슈 정리</h2>
<p><strong>{k}</strong>는 안전·재난·생활 리스크와 연결된 검색어입니다.
대형 사고나 화재 이슈가 있으면 원인, 피해 범위, 보상, 대피 요령을 한꺼번에 찾는 흐름이 나타납니다.</p>

<h2>상황별 확인 방법</h2>
<ol>
  <li>공식 발표(소방·지자체·기업 공지)로 현재 상태를 확인합니다.</li>
  <li>거주·근무 위치가 영향권인지 지도/공지로 점검합니다.</li>
  <li>대피·교통·출근 지침이 있는지 확인합니다.</li>
  <li>피해가 있다면 증빙(사진, 영수증, 공지 캡처)을 남겨 상담·보상 절차에 대비합니다.</li>
</ol>
"""
    else:
        body = f"""
<h2>{k}를 찾는 사람들이 궁금한 것</h2>
<p><strong>{k}</strong>는 현재 검색량이 늘어난 실용 키워드입니다.
단순 이슈 소비보다, 개념 이해 → 내 상황 대입 → 실행 체크 순서로 보면
실제 의사결정에 도움이 됩니다.</p>

<h2>상세 확인 방법</h2>
<ol>
  <li>키워드의 기본 정의를 공식 출처에서 확인합니다.</li>
  <li>나에게 해당하는 조건(자격, 지역, 금액, 일정)을 적습니다.</li>
  <li>필요한 서류·비용·소요 시간을 표로 정리합니다.</li>
  <li>마지막으로 최신 뉴스/공지와 교차 검증합니다.</li>
</ol>
"""

    return f"""
{body}
<h2>최근 관련 소식</h2>
{news_html}
<h2>자주 묻는 질문</h2>
<ul>
  <li><strong>검색이 많다는 건 지금 해야 한다는 뜻인가요?</strong> —
  관심 증가는 신호일 뿐입니다. 본인 조건과 공식 기준을 먼저 보세요.</li>
  <li><strong>어디에 나온 정보를 믿어야 하나요?</strong> —
  정부·법원·거래소·해당 기업 공지 등 1차 출처를 우선하세요.</li>
  <li><strong>혼자 해결이 어려우면?</strong> —
  금액·기한·법적 효과가 큰 사안은 전문가 상담이 비용 대비 안전합니다.</li>
</ul>
""".strip()


def build_post(item: TrendItem, now: str) -> tuple[str, str, list[str]]:
    keyword = item.title
    title = _guide_title(keyword)
    news = fetch_news_headlines(keyword, limit=5)
    sections = _build_guide_sections(keyword, news)
    sources = (
        f"<li><a href=\"{escape(SOURCE_URLS['google'])}\">Google Trends KR</a> ({escape(item.window)})</li>"
        f"<li><a href=\"{escape(SOURCE_URLS['blackkiwi'])}\">BlackKiwi 트렌드</a></li>"
        f"<li><a href=\"{escape(SOURCE_URLS['loword'])}\">Loword 키워드 트렌드</a></li>"
    )
    content = f"""
<p>지금 검색량이 늘어난 <strong>{escape(keyword)}</strong>에 대해
뜻과 확인 포인트, 실무에서 쓰는 방법을 중심으로 정리했습니다.
엔터테인먼트성 이슈가 아니라, 실제로 돈이 되거나 궁금해서 찾아볼 만한
정보성 관점으로 구성했습니다.</p>

<p><strong>수집 기준:</strong> {escape(item.source)} · {escape(item.window)} ·
{escape(item.volume_label)}
{" · 활성" if item.active else ""}</p>

{sections}

<h2>데이터 출처</h2>
<ul>
{sources}
</ul>
<p>작성 시각: {escape(now)}</p>
""".strip()
    labels = ["정보성", "상세안내", _topic_bucket(keyword), keyword[:40], "트렌드키워드"]
    return title, content, labels


def _upsert_post(service, blog_id: str, title: str, content: str, labels: list[str]):
    recent = _execute_with_retry(
        service.posts().list(blogId=blog_id, maxResults=50, fetchBodies=False)
    )
    for existing in recent.get("items") or []:
        if existing.get("title") == title:
            post = _execute_with_retry(
                service.posts().update(
                    blogId=blog_id,
                    postId=existing["id"],
                    body={
                        "kind": "blogger#post",
                        "id": existing["id"],
                        "blog": {"id": blog_id},
                        "title": title,
                        "content": content,
                        "labels": labels,
                    },
                )
            )
            return post, "updated"

    post = _execute_with_retry(
        service.posts().insert(
            blogId=blog_id,
            body={
                "kind": "blogger#post",
                "blog": {"id": blog_id},
                "title": title,
                "content": content,
                "labels": labels,
            },
            isDraft=False,
        )
    )
    return post, "published"


def main() -> None:
    collected = collect_all_sources()
    keywords = select_guide_keywords(collected, limit=8)
    if not keywords:
        raise SystemExit("No informational keywords selected.")

    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    print(f"Using blog: {blog.get('name')} ({blog_id})")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    results = []
    for item in keywords:
        title, content, labels = build_post(item, now)
        post, action = _upsert_post(service, blog_id, title, content, labels)
        url = post.get("url")
        results.append((action, title, url))
        print(f"{action.upper()}: {title} -> {url}")
        time.sleep(2)

    print(f"Done. {len(results)} guide posts.")


if __name__ == "__main__":
    main()
