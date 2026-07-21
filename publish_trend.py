"""Publish 1~3 issue-focused informational guides from trend keywords."""

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

MAX_POSTS = 3


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


def _issue_frame(keyword: str) -> dict[str, str]:
    """Return issue / impact / methods / solutions framing for a keyword."""
    k = keyword.strip()

    if re.search(r"근저당", k):
        return {
            "title": "근저당 설정되면 뭐가 문제일까? 영향과 말소·대응 방법",
            "issue": "근저당은 부동산에 채무 담보를 설정하는 권리입니다. 대출·보증과 함께 등기되면, 매매·추가 대출·상속 때 즉시 문제가 됩니다.",
            "impact": "집이 담보로 묶여 매도가 어려워지고, 채무 불이행 시 경매 위험이 커지며, 후순위 대출 한도에도 영향을 줍니다.",
            "methods": [
                "등기사항전부증명서에서 근저당권자·채권최고액·설정일을 확인한다",
                "대출 잔액과 채권최고액 차이를 계산해 실제 부담 규모를 파악한다",
                "매매·대환·상속 예정일이 있으면 말소 가능 시점을 미리 잡는다",
            ],
            "solutions": [
                "대출 상환 후 금융기관에 말소 서류 발급을 요청한다",
                "법무사·은행을 통해 말소 등기를 진행한다",
                "금액·기한이 복잡하면 계약 전 전문가 검토로 분쟁을 막는다",
            ],
        }

    if re.search(r"회생법원|개인회생|회생절차|즉시항고", k):
        return {
            "title": f"{k} 이슈 정리: 누구에게 영향이 있고 어떻게 대응할까",
            "issue": f"‘{k}’ 검색이 늘었다는 것은 채무 조정·회생 절차에 대한 실무 확인 수요가 커졌다는 신호입니다. 핵심은 ‘자격이 되는지’와 ‘지금 어떤 절차를 밟아야 하는지’입니다.",
            "impact": "소득·재산 처분, 채권자 추심, 신용도, 주거·사업 유지에 직접 영향을 줍니다. 기한을 놓치면 항고·이의 기회를 잃을 수 있습니다.",
            "methods": [
                "내 채무 목록·소득·필수생계비를 표로 정리한다",
                "법원·공식 안내에서 신청 요건과 제출 서류를 확인한다",
                "관련 결정문·공고문의 기한(항고·이의)을 달력에 표시한다",
            ],
            "solutions": [
                "요건이 맞으면 서류 보완 후 정식 신청/대응을 진행한다",
                "즉시항고·이의 기한이 있으면 늦지 않게 접수한다",
                "혼자 판단이 어려우면 신용회복·법률구조·변호사 상담을 우선한다",
            ],
        }

    if re.search(r"쿠팡|물류.*화재|화재.*물류|화재", k):
        return {
            "title": "쿠팡 물류센터 화재, 지금 이슈와 영향·대처 방법",
            "issue": "대형 물류센터 화재는 단순 사고가 아니라 인근 주민 안전, 배송 차질, 근로·보상 이슈가 한꺼번에 불거지는 사건입니다.",
            "impact": "대피·교통 통제, 배송 지연, 근로자 안전, 잔불/붕괴 위험, 추후 원인 조사와 보상 절차에 영향을 미칩니다.",
            "methods": [
                "소방·지자체·기업 공식 발표로 초진/잔불/대피 상태를 확인한다",
                "거주·근무지가 영향권인지 공지와 지도로 점검한다",
                "피해가 있으면 사진·영수증·공지 캡처 등 증빙을 남긴다",
            ],
            "solutions": [
                "위험 지역이면 대피·우회 지침을 따른다",
                "근로·배송 피해는 회사 공지와 상담 채널로 접수한다",
                "보상·산재 가능성이 있으면 관련 기관 상담을 진행한다",
            ],
        }

    if re.search(r"이관개방", k):
        return {
            "title": "이관개방증이란? 증상 영향과 대처 방법",
            "issue": "이관개방증은 귀와 코를 잇는 이관이 과도하게 열려 내 목소리가 울리거나 귀가 막힌 듯한 증상이 생기는 상태입니다.",
            "impact": "대화·업무 집중이 어렵고, 비행·다이어트·스트레스 상황에서 증상이 악화될 수 있습니다. 방치하면 생활 품질이 크게 떨어집니다.",
            "methods": [
                "증상(자가발성증, 이충만감)과 발생 상황을 기록한다",
                "체중 변화·비염·스트레스 등 유발 요인을 점검한다",
                "신뢰할 수 있는 이비인후과 정보로 유사 질환과 구분한다",
            ],
            "solutions": [
                "일상 지장이 있으면 이비인후과 진료를 받는다",
                "임의로 약·시술을 결정하지 말고 진료 후 치료 계획을 따른다",
                "악화 요인(급격한 체중 변화, 코 풀기 습관 등)을 조절한다",
            ],
        }

    if re.search(r"주가|주식|사이드카|코스피|주주", k):
        return {
            "title": f"{k} 이슈 해설: 시장 영향과 투자자 대응 방법",
            "issue": f"‘{k}’는 가격 급변, 거래 규정, 기업 이슈가 겹칠 때 검색이 몰립니다. 무엇을 사라는 신호가 아니라, ‘무슨 일이 생겼는지’를 확인해야 하는 키워드입니다.",
            "impact": "보유 종목 평가손익, 예약주문 체결, 신용/미수 위험, 변동성 확대에 영향을 줍니다.",
            "methods": [
                "공시·거래소·증권사 공식 설명으로 이슈 정의를 확인한다",
                "내 보유 종목·주문·레버리지 상태를 점검한다",
                "단기 커뮤니티 정보와 공식 데이터를 분리해서 본다",
            ],
            "solutions": [
                "근거 없는 추격 매수/패닉 매도를 피한다",
                "리스크가 크면 비중·주문 조건을 먼저 조정한다",
                "장기 판단은 공시와 실적 중심으로 재검토한다",
            ],
        }

    if re.search(r"은행|대출|금리|보험|세금", k):
        return {
            "title": f"{k} 이슈와 영향, 지금 확인할 방법·해결 포인트",
            "issue": f"‘{k}’ 검색 증가는 수수료·금리·한도·청구·정책 변화처럼 돈과 직결된 확인 수요가 커졌다는 뜻입니다.",
            "impact": "이자 부담, 승인 여부, 연체, 환급/청구 금액에 바로 영향을 줄 수 있습니다.",
            "methods": [
                "공식 앱·홈페이지 공지에서 변경 내용을 확인한다",
                "내 계약 조건(금리, 한도, 만기, 중도상환)을 다시 본다",
                "필요 서류와 신청/해지 경로를 정리한다",
            ],
            "solutions": [
                "불리한 조건이면 대환·조건 변경·상담을 검토한다",
                "오류 청구·연체 위험이 있으면 즉시 고객센터에 접수한다",
                "금액이 크면 실행 전 조건을 문서로 남긴다",
            ],
        }

    # Generic but still issue-structured
    return {
        "title": f"{k}, 무슨 이슈일까? 영향과 대응 방법 정리",
        "issue": f"‘{k}’는 현재 검색량이 늘어난 실무·생활 이슈 키워드입니다. 제목만 보지 말고, 무엇이 쟁점인지부터 정의해야 합니다.",
        "impact": "관련 비용, 일정, 자격, 안전, 계약 조건 중 하나 이상에 영향을 줄 수 있습니다.",
        "methods": [
            "공식 출처에서 이슈의 정의를 확인한다",
            "나에게 해당하는 조건(지역·금액·기한·자격)을 적는다",
            "필요한 서류·비용·연락 채널을 정리한다",
        ],
        "solutions": [
            "조건이 맞으면 신청·변경·상담 등 실행 절차로 넘어간다",
            "기한이 있으면 우선순위를 높여 처리한다",
            "판단이 어렵거나 금액이 크면 전문가·공식 상담을 이용한다",
        ],
    }


def _news_html(news: list[dict[str, str]]) -> str:
    if not news:
        return "<p>관련 최신 헤드라인이 제한적입니다. 공식 발표를 우선 확인하세요.</p>"
    lis = []
    for article in news[:4]:
        source = f" ({escape(article['source'])})" if article.get("source") else ""
        if article.get("link"):
            lis.append(
                f"<li><a href=\"{escape(article['link'])}\">{escape(article['title'])}</a>{source}</li>"
            )
        else:
            lis.append(f"<li>{escape(article['title'])}{source}</li>")
    return f"<ul>{''.join(lis)}</ul>"


def build_post(item: TrendItem, now: str) -> tuple[str, str, list[str]]:
    keyword = item.title
    frame = _issue_frame(keyword)
    news = fetch_news_headlines(keyword, limit=4)

    methods = "".join(f"<li>{escape(step)}</li>" for step in frame["methods"])
    solutions = "".join(f"<li>{escape(step)}</li>" for step in frame["solutions"])

    title = frame["title"]
    content = f"""
<p><strong>한 줄 요약:</strong> {escape(frame["issue"])}</p>

<h2>1. 이슈가 무엇인가</h2>
<p>{escape(frame["issue"])}</p>
<p>현재 수집 기준: {escape(item.source)} · {escape(item.window)} · {escape(item.volume_label)}</p>

<h2>2. 무엇이 영향받는가</h2>
<p>{escape(frame["impact"])}</p>

<h2>3. 관련해서 확인할 방법</h2>
<ol>
{methods}
</ol>

<h2>4. 해결·대응 방법</h2>
<ol>
{solutions}
</ol>

<h2>5. 관련 소식</h2>
{_news_html(news)}

<h2>참고 출처</h2>
<ul>
  <li><a href="{escape(SOURCE_URLS['google'])}">Google Trends KR</a></li>
  <li><a href="{escape(SOURCE_URLS['blackkiwi'])}">BlackKiwi 트렌드</a></li>
  <li><a href="{escape(SOURCE_URLS['loword'])}">Loword 키워드 트렌드</a></li>
</ul>
<p>작성 시각: {escape(now)}</p>
""".strip()

    labels = ["이슈정리", "정보성", "해결방법", keyword[:40]]
    return title, content, labels


def _upsert_post(
    service,
    blog_id: str,
    title: str,
    content: str,
    labels: list[str],
    *,
    recycle_ids: list[str] | None = None,
):
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

    try:
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
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status not in {403, 429} or not recycle_ids:
            raise
        post_id = recycle_ids.pop(0)
        post = _execute_with_retry(
            service.posts().update(
                blogId=blog_id,
                postId=post_id,
                body={
                    "kind": "blogger#post",
                    "id": post_id,
                    "blog": {"id": blog_id},
                    "title": title,
                    "content": content,
                    "labels": labels,
                },
            )
        )
        return post, "recycled"


def main() -> None:
    collected = collect_all_sources()
    keywords = select_guide_keywords(collected, limit=MAX_POSTS)
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
    print(f"Publishing up to {MAX_POSTS} issue guides.")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    recent = _execute_with_retry(
        service.posts().list(blogId=blog_id, maxResults=50, fetchBodies=False)
    )
    recycle_ids = []
    for post in recent.get("items") or []:
        title = post.get("title") or ""
        if title.startswith("[검색량 TOP5]") or "이슈 TOP" in title or "여행 트렌드" in title:
            recycle_ids.append(post["id"])
    print(f"Recycle candidates: {len(recycle_ids)}")

    results = []
    for item in keywords:
        title, content, labels = build_post(item, now)
        post, action = _upsert_post(
            service,
            blog_id,
            title,
            content,
            labels,
            recycle_ids=recycle_ids,
        )
        url = post.get("url")
        results.append((action, title, url))
        print(f"{action.upper()}: {title} -> {url}")
        time.sleep(2)

    print(f"Done. {len(results)} issue posts.")


if __name__ == "__main__":
    main()
