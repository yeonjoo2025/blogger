"""Every 4 hours: publish detailed posts for each category's search-volume TOP5."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from html import escape

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth_blogger import load_credentials
from fetch_trends import (
    TRENDS_URL,
    CategoryTrends,
    TrendItem,
    fetch_news_headlines,
    group_top_by_category,
)


def _hour_bucket(now: datetime) -> str:
    # Align titles to 4-hour automation windows: 0,4,8,12,16,20
    hour = (now.hour // 4) * 4
    return f"{now.strftime('%Y-%m-%d')} {hour:02d}시"


def _rank_table(items: list[TrendItem]) -> str:
    rows = []
    for item in items:
        state = "활성" if item.active else "소강"
        related = ", ".join(escape(r) for r in item.related[:4]) or "-"
        rows.append(
            "<tr>"
            f"<td>{item.rank}</td>"
            f"<td><strong>{escape(item.title)}</strong></td>"
            f"<td>{escape(item.volume_label)}</td>"
            f"<td>+{item.increase_percentage}%</td>"
            f"<td>{state}</td>"
            f"<td>{related}</td>"
            "</tr>"
        )
    return (
        '<table border="1" cellpadding="6" cellspacing="0">'
        "<thead><tr>"
        "<th>순위</th><th>검색어</th><th>검색량</th><th>증가율</th><th>상태</th><th>관련 검색어</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _keyword_section(item: TrendItem, category_name: str) -> str:
    news = fetch_news_headlines(item.title, limit=4)
    related = ", ".join(escape(r) for r in item.related[:6])
    state = "지금도 평소보다 많이 검색되는 활성 트렌드" if item.active else "한때가 지나 소강 상태인 트렌드"

    news_html = ""
    if news:
        lis = []
        for article in news:
            source = f" ({escape(article['source'])})" if article.get("source") else ""
            if article.get("link"):
                lis.append(
                    f"<li><a href=\"{escape(article['link'])}\">{escape(article['title'])}</a>{source}</li>"
                )
            else:
                lis.append(f"<li>{escape(article['title'])}{source}</li>")
        news_html = (
            "<p><strong>함께 보면 좋은 최근 보도·이슈</strong></p>"
            f"<ul>{''.join(lis)}</ul>"
        )
    else:
        news_html = (
            "<p>연관 뉴스 헤드라인이 바로 잡히지 않는 검색어입니다. "
            "인물명·생활정보·기관명처럼 실사용 검색이 몰릴 때도 상위에 오릅니다. "
            "단정적인 단일 사건으로 해석하기보다, 검색 의도와 관련어를 함께 보는 편이 안전합니다.</p>"
        )

    related_html = (
        f"<p><strong>관련 검색어:</strong> {related}</p>" if related else ""
    )

    return f"""
<h2>{item.rank}위. {escape(item.title)}</h2>
<p><strong>검색량</strong> {escape(item.volume_label)} ·
<strong>증가율</strong> +{item.increase_percentage}% ·
<strong>상태</strong> {state}</p>
<p>카테고리 <strong>{escape(category_name)}</strong>에서 지난 4시간 검색량
{item.rank}위를 기록한 키워드입니다.
사람들이 지금 무엇을 확인하려는지 보여주는 신호로, 단순 유행어가 아니라
정보 탐색·이슈 확인·실생활 필요 검색이 겹치며 순위가 움직입니다.</p>
{related_html}
<p><strong>정보성으로 읽어볼 포인트</strong></p>
<ul>
  <li>검색량이 높다는 것은 관심·궁금증·확인 수요가 한꺼번에 몰렸다는 뜻입니다.</li>
  <li>관련 검색어가 있다면 핵심 키워드 주변의 구체적 관심사(인물·일정·제도·상품 등)를 함께 체크하세요.</li>
  <li>활성 상태면 당분간 추가 소식·후속 검색이 이어질 가능성이 큽니다.</li>
  <li>공식 발표·1차 보도·공공기관 공지를 우선 확인하고, 확인되지 않은 추측성 정보는 구분해서 보세요.</li>
</ul>
{news_html}
""".strip()


def build_category_post(
    group: CategoryTrends,
    bucket: str,
    now: str,
) -> tuple[str, str, list[str]]:
    top_names = ", ".join(item.title for item in group.items[:3])
    title = (
        f"[검색량 TOP5] {group.category_name} "
        f"({bucket}, 지난 4시간)"
    )
    sections = "\n".join(
        _keyword_section(item, group.category_name) for item in group.items
    )
    content = f"""
<p>Google 트렌드 한국
<a href="{escape(group.trends_url)}">지난 4시간 · 검색량순 · {escape(group.category_name)}</a>
기준으로, 이 카테고리에서 검색량이 많은 상위 {len(group.items)}개 키워드를
정보성으로 정리했습니다.</p>

<p>이번 구간에서 눈에 띄는 검색어는
<strong>{escape(top_names)}</strong> 등입니다.
아래 순위표와 키워드별 해설에서 검색량·증가율·관련어·최근 이슈를 함께 확인할 수 있습니다.</p>

<h2>{escape(group.category_name)} 검색량 TOP{len(group.items)}</h2>
{_rank_table(group.items)}
<p>출처: Google Trends · geo=KR · hours=4 · sort=search-volume ·
category={group.category_id} ({escape(group.category_name)}) · {escape(now)}</p>

{sections}

<h2>이 글을 활용하는 방법</h2>
<ol>
  <li>카테고리 안에서도 <strong>검색량 순</strong>으로 먼저 보고, 관심 키워드만 깊게 읽으세요.</li>
  <li>같은 키워드가 여러 카테고리에 겹치면 이슈의 성격(스포츠·금융·연예 등)을 함께 판단하세요.</li>
  <li>4시간마다 순위가 바뀌므로, 제목의 시간 구간을 기준으로 흐름을 비교하면 좋습니다.</li>
</ol>

<p>데이터:
<a href="{escape(TRENDS_URL)}">Google Trends Trending Now · Korea · Past 4 hours · Search volume</a><br>
작성 시각: {escape(now)}</p>
""".strip()

    labels = [
        "트렌드",
        "검색량TOP5",
        group.category_name,
        "구글트렌드",
        "지난4시간",
    ]
    for item in group.items[:3]:
        if item.title not in labels and len(labels) < 8:
            labels.append(item.title)
    return title, content, labels


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
    groups = group_top_by_category(top_n=5)
    if not groups:
        raise SystemExit("No category trends found.")

    print(f"Categories with trends: {len(groups)}")
    for group in groups:
        titles = ", ".join(i.title for i in group.items)
        print(f"  - {group.category_name}: {titles}")

    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    print(f"Using blog: {blog.get('name')} ({blog_id})")

    now_dt = datetime.now(timezone.utc).astimezone()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    bucket = _hour_bucket(now_dt)

    results = []
    for group in groups:
        title, content, labels = build_category_post(group, bucket, now)
        post, action = _upsert_post(service, blog_id, title, content, labels)
        url = post.get("url")
        results.append((action, group.category_name, title, url))
        print(f"{action.upper()}: {group.category_name} -> {url}")
        time.sleep(2)

    print(f"Done. {len(results)} category posts.")


if __name__ == "__main__":
    main()
