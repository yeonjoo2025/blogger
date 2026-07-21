"""Publish a detailed informational post from KR Trends (search-volume order)."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from googleapiclient.discovery import build

from auth_blogger import load_credentials
from fetch_trends import TRENDS_URL, TrendItem, fetch_trends_by_search_volume


def _rank_table(trends: list[TrendItem]) -> str:
    rows = []
    for item in trends:
        state = "활성" if item.active else "소강"
        rows.append(
            "<tr>"
            f"<td>{item.rank}</td>"
            f"<td><strong>{escape(item.title)}</strong></td>"
            f"<td>{escape(item.volume_label)}</td>"
            f"<td>{state}</td>"
            "</tr>"
        )
    return (
        '<table border="1" cellpadding="6" cellspacing="0">'
        "<thead><tr><th>순위</th><th>검색어</th><th>검색량</th><th>상태</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def build_post(trends: list[TrendItem], now: str) -> tuple[str, str, list[str]]:
    top = trends[0]
    title = (
        f"지금 한국에서 검색량 많은 이슈 TOP "
        f"({now[:10]}, 지난 4시간)"
    )

    # Deep sections follow Google's search-volume order, with fuller writeups
    # for keywords that have clear, reportable public facts today.
    content = f"""
<p>Google 트렌드 한국(<a href="{escape(TRENDS_URL)}">지난 4시간 · 검색량순</a>) 기준으로
사람들이 지금 가장 많이 찾는 검색어를 정리했습니다.
순위는 인기도나 편집자 취향이 아니라 <strong>검색량</strong> 순서입니다.</p>

<p>집계 시각 기준 1위는 <strong>{escape(top.title)}</strong>
(약 {escape(top.volume_label)})였습니다. 아래는 상위 목록과, 배경을 확인할 수 있는
주요 키워드 해설입니다.</p>

<h2>지난 4시간 검색량 상위 키워드</h2>
{_rank_table(trends[:12])}
<p>출처: Google Trends · geo=KR · hours=4 · sort=search-volume · {escape(now)}</p>

<h2>1위 {escape(trends[0].title)} · 검색량 {escape(trends[0].volume_label)}</h2>
<p>이번 집계에서 가장 높은 검색량을 기록한 키워드입니다.
특정 사건명보다 일상·종교·지역 정보 탐색이 한꺼번에 모이면서
상위에 오르는 경우가 있어, 단정적인 단일 원인으로 해석하기보다
‘지금 관심이 몰린 검색어’로 보는 편이 안전합니다.
주변에서 예배·행사·지역 교회 정보를 찾는 수요와 함께
사회·문화 이슈가 겹칠 때 검색량이 크게 튀는 패턴이 관찰됩니다.</p>

<h2>중국 오픈 · 검색량 상위권</h2>
<p>배드민턴 BWF 월드투어 <strong>중국 오픈(슈퍼 1000)</strong> 관련 검색이
상위에 올라 있습니다. 세계 랭킹 1위 안세영은 일본 오픈 32강 도중
왼쪽 발 외측 통증을 호소한 뒤 16강전을 기권했고, 조기 귀국해 정밀검사를 받았습니다.
이후 중국 오픈 출전도 사실상 불참 쪽으로 정리되면서
대회 자체와 안세영의 재활·향후 일정(세계선수권, 아시안게임 준비)에 대한
관심이 함께 커진 상황입니다.</p>
<p>중국 오픈은 슈퍼 1000급 메이저 일정인 만큼, 우승 후보 공백이 대진과
배당·중계 관심에 미치는 영향도 함께 검색되는 흐름입니다.
팬 입장에서는 단기 성적보다 반복 통증 부위의 회복 여부가
더 중요한 포인트로 보입니다.</p>

<h2>화재 · 인천 쿠팡 물류센터</h2>
<p>‘화재’ 검색의 중심에는 인천 서해구 석남동
<strong>쿠팡 제32물류센터</strong> 대형 화재가 있습니다.
지난 18일 오전 6시 54분께 6층에서 시작된 불은 약 <strong>61시간 만인 20일 오후 8시</strong>
초진됐고, 민간인 인명피해는 보고되지 않았습니다.
불이 난 직후 직원 등 121명이 자력 대피했고,
진화 과정에서 소방대원 일부가 연기 흡입·탈진으로 치료를 받았습니다.</p>
<p>진화가 길어진 배경으로는 연면적 약 29만9000㎡의 대형 구조,
가연물 대량 적재, 3단 랙·메자닌(복층) 구조가 꼽힙니다.
소방 당국은 대응 단계와 국가소방동원령을 동원해 진화에 나섰고,
완전 진압 이후 소방청·국립소방연구원·한국전기안전공사 등이 참여하는
합동조사단이 발화 원인과 피해 규모를 조사할 예정입니다.
물류·유통업계에서는 안전관리와 복층 적재 구조 규제 논의가
다시 수면 위로 오른 상태입니다.</p>

<h2>카타고 · 신진서의 AI 대결 역전승</h2>
<p>관련 검색어 <strong>카타고</strong>·신진서가 상위에 함께 오르고 있습니다.
바둑 세계 랭킹 1위 <strong>신진서 9단</strong>이 21일
‘쎈수학·한경 기신전’ 최종 3국에서 바둑 AI <strong>카타고(KataGo)</strong>를
221수 만에 흑 11집 반으로 꺾었습니다.
1국 패배 뒤 2국·3국을 연속으로 잡아내 최종 전적 <strong>2승 1패</strong>로 시리즈를 마무리했습니다.</p>
<p>대국은 AI의 기력을 감안해 신진서가 흑 두 점을 먼저 두는
<strong>2점 접바둑</strong>으로 진행됐습니다.
동등 조건 승부는 아니지만, 카타고가 프로 상대 2점 접바둑에서도
강세를 보여 온 점을 고려하면 의미가 작지 않습니다.
2016년 이세돌 9단과 알파고 대결 이후 약 10년 만에 다시 주목받은
‘인간 대 AI’ 이벤트라는 점도 검색량을 끌어올린 배경입니다.</p>
<p>신진서는 대국료·승리 수당을 합쳐 상금 2억5000만원과
부상 제네시스 G90을 받게 됐습니다.
본인은 이세돌의 1승과 단순 비교하기보다,
“인간이 AI에 버틸 수 있다는 걸 보여준 대국”이라는 취지로 의미를 설명했습니다.</p>

<h2>이정후 · MLB 경기와 트레이드 관측</h2>
<p>샌프란시스코 자이언츠 <strong>이정후</strong>도 검색량 상위에 이름을 올렸습니다.
한국시간 21일 캔자스시티전에서는 6번 우익수로 나와 4타수 1안타 1득점을 기록했고,
9회 초 동점 발판이 된 안타를 때렸지만 팀은 끝내기 패배를 당했습니다.
시즌 타율은 3할대 초반권을 유지하는 흐름입니다.</p>
<p>현지에서는 트레이드 마감시한을 앞두고 자이언츠의 셀러 가능성과 함께
이정후 이적설이 다시 거론되고 있습니다.
일각에서는 계약상 옵트아웃 조항이 예전만큼 큰 걸림돌이 아닐 수 있다는
분석이 나와, 선수 개인 성적과 별개로 ‘이적 가능성’ 키워드가
검색을 키우는 요인으로 보입니다.</p>

<h2>윤이나 · LPGA 상승세</h2>
<p>여자골프 <strong>윤이나</strong>는 LPGA 무대에서의 상승세가 검색으로 이어진 케이스입니다.
올해 셰브론 챔피언십 공동 4위, KPMG 여자 PGA 챔피언십 준우승 등으로
메이저 경쟁력을 보여 줬고, 세계랭킹 개인 최고치(17위권)와
시즌 상금 상위권 진입이 화제가 됐습니다.
컷 통과율도 크게 높아져 “첫 승 시점”에 대한 관심과 함께
선수 이름이 실시간 검색에 자주 오르고 있습니다.</p>

<h2>그 밖에 눈여겨볼 상위 검색어</h2>
<ul>
  <li><strong>서울회생법원</strong> — 개인회생·파산 등 절차 정보 탐색이 한꺼번에 모이며 상위권에 등장하는 유형입니다.</li>
  <li><strong>신한은행</strong> — 금융 앱·영업점·이벤트·공지 관련 실사용 검색이 겹치면 검색량이 빠르게 올라갑니다.</li>
  <li><strong>대한항공</strong> — 항공권·스케줄·운항 정보 수요와 여행 시즌 관심이 맞물리는 키워드입니다.</li>
  <li><strong>이더리움</strong> — 가상자산 시세·관련 뉴스 흐름에 민감하게 반응하는 검색어입니다.</li>
</ul>

<h2>검색량 순으로 읽을 때 참고할 점</h2>
<ol>
  <li>같은 ‘2K+’ 구간이어도 Google 내부의 세부 검색량 차이가 있어, 화면 정렬 순서를 따릅니다.</li>
  <li>활성(Active) 키워드는 여전히 평소보다 많이 검색되는 상태이고, 소강(Lasted)은 한때가 지난 뒤입니다.</li>
  <li>인물·사건·생활 정보가 한 목록에 섞이므로, 순위만 보고 중요도를 단정하기보다 맥락을 함께 보는 것이 좋습니다.</li>
</ol>

<p>데이터: <a href="{escape(TRENDS_URL)}">Google Trends Trending Now · Korea · Past 4 hours · Search volume</a><br>
작성 시각: {escape(now)}</p>
""".strip()

    labels = ["트렌드", "검색량", top.title, "구글트렌드", "이슈정리"]
    # Keep labels short/unique.
    for item in trends[1:6]:
        if item.title not in labels and len(labels) < 8:
            labels.append(item.title)
    return title, content, labels


def main() -> None:
    trends = fetch_trends_by_search_volume(limit=15)
    print("Trends by search volume:")
    for item in trends:
        print(f"  {item.rank:2}. {item.volume_label:>5}  {item.title}")

    service = build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")

    blog = items[0]
    blog_id = blog["id"]
    print(f"Using blog: {blog.get('name')} ({blog_id})")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    title, content, labels = build_post(trends, now)

    # Avoid publishing an identical title twice in recent posts.
    recent = service.posts().list(blogId=blog_id, maxResults=8, fetchBodies=False).execute()
    for existing in recent.get("items") or []:
        if existing.get("title") == title:
            post = (
                service.posts()
                .update(
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
                .execute()
            )
            print("Updated existing post with the same title.")
            print(f"URL: {post.get('url')}")
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
    print(f"Title: {post.get('title')}")
    print(f"URL: {post.get('url')}")
    print(f"Post ID: {post.get('id')}")


if __name__ == "__main__":
    main()
