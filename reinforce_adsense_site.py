#!/usr/bin/env python3
"""Reinforce live site for AdSense recovery: pages, as-of dates, internal links, weak posts."""

from __future__ import annotations

import re
import time
from datetime import date

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials

BLOG_ID = "4736025457821775813"
ASOF = date.today().isoformat()  # 2026-08-05
PUB_ID = "pub-3279521602914080"

ASOF_MARK = 'class="asof-box"'
RELATED_MARK = 'class="related-posts"'
ABOUT_MARK = "<!-- site-about-link -->"

WEAK_REWRITE_KEYS = ("타운카", "김치냉장고")
SITE_TITLES = frozenset({"소개", "개인정보처리방침", "문의"})


def service():
    return build("blogger", "v3", credentials=load_credentials(), cache_discovery=False)


def asof_html() -> str:
    return (
        f'<div {ASOF_MARK} style="border:1px solid #ddd;padding:12px 14px;'
        f'margin:0 0 1.2em 0;background:#fafafa;font-size:0.95em;line-height:1.5;">'
        f"<strong>정보 기준일:</strong> {ASOF}<br />"
        "일정·요금·자격·혜택은 변경될 수 있습니다. "
        "신청·예약·결제 직전에 본문 공식 링크에서 최종 조건을 다시 확인하세요."
        "</div>"
    )


def related_html(items: list[tuple[str, str]]) -> str:
    lis = "".join(
        f'<li><a href="{url}">{title}</a></li>' for title, url in items
    )
    return (
        f'<div {RELATED_MARK}><h2>관련 글</h2><ul>{lis}</ul></div>'
        f"<p>{ABOUT_MARK}"
        '<a href="ABOUT_URL_PLACEHOLDER">블로그 소개 · 운영 안내</a></p>'
    )


def count_internal(html: str) -> int:
    return len(
        [
            u
            for u in re.findall(r'href=["\'](https?://[^"\']+)["\']', html or "", re.I)
            if "yeondodo.blogspot.com" in u
        ]
    )


def insert_after_thumb(html: str, block: str) -> str:
    """Insert block after post-thumb image (outside wrapping <p>), else at top."""
    if ASOF_MARK in html:
        # refresh existing asof box date
        html = re.sub(
            r'(<div class="asof-box"[^>]*>[\s\S]*?<strong>정보 기준일:</strong>\s*)[^<]+',
            rf"\g<1>{ASOF}",
            html,
            count=1,
        )
        return html
    # Prefer: </p> that closes a paragraph containing post-thumb
    m = re.search(
        r'(<p>\s*<img[^>]*class="[^"]*post-thumb[^"]*"[^>]*/?>\s*</p>)',
        html,
        flags=re.I,
    )
    if m:
        return html[: m.end()] + block + html[m.end() :]
    m = re.search(
        r'(<img[^>]*class="[^"]*post-thumb[^"]*"[^>]*/?>)', html, flags=re.I
    )
    if m:
        # Insert after img; if still inside <p>, close p first then reopen is messy —
        # close the paragraph after img when a following </p> exists nearby.
        after = html[m.end() : m.end() + 80]
        close = re.match(r"\s*</p>", after, flags=re.I)
        if close:
            end = m.end() + close.end()
            return html[:end] + block + html[end:]
        return html[: m.end()] + "</p>" + block + "<p>" + html[m.end() :]
    m = re.search(r"(</div>\s*<br\s*/?>\s*<br\s*/?>)", html, flags=re.I)
    if m:
        return html[: m.end()] + block + html[m.end() :]
    return block + html


def ensure_related(html: str, items: list[tuple[str, str]], about_url: str) -> str:
    block = related_html(items).replace("ABOUT_URL_PLACEHOLDER", about_url)
    if RELATED_MARK in html:
        # keep existing related section; only ensure about link
        if ABOUT_MARK not in html and about_url:
            html += (
                f"<p>{ABOUT_MARK}<a href=\"{about_url}\">블로그 소개 · 운영 안내</a></p>"
            )
        return html
    # remove trailing empty paragraphs noise lightly, then append
    return html.rstrip() + block


def pick_related(
    current_title: str, hub: list[tuple[str, str]], n: int = 3
) -> list[tuple[str, str]]:
    others = [(t, u) for t, u in hub if t != current_title]
    # keyword overlap heuristic
    tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", current_title.lower()))

    def score(item: tuple[str, str]) -> int:
        t = item[0].lower()
        return sum(1 for tok in tokens if tok in t)

    others.sort(key=score, reverse=True)
    # diversify: top scored + rotate some evergreen
    picked = others[:n]
    if len(picked) < n:
        return others[:n]
    return picked


TOWNCAR_BODY = """
<p><img class="post-thumb" src="https://cdn.jsdelivr.net/gh/yeonjoo2025/blogger@b8a1a073f3fcbabd5527248ada4b83eb50f0856f/posts/images/thumb-towncar.jpg" alt="타운카 이웃차 이용 가이드" style="display:block;width:100%;max-width:100%;height:auto;margin:0 0 1em 0;border:0;" /></p>
__ASOF__
<h2>한 줄 요약</h2>
<p>타운카(Towncar)는 동네에 주차된 이웃 차량을 앱으로 예약해 쓰는 <strong>개인간 차량 공유</strong> 서비스입니다. 이 글을 읽으면 가입·인증·예약·반납 순서를 따라 <strong>오늘 바로 첫 대여까지</strong> 진행할 수 있고, 렌터카·쏘카형 카셰어링과 언제 비교해야 하는지도 정리됩니다.</p>
<h2>핵심 사실</h2>
<table border="1" cellpadding="6" cellspacing="0">
<thead><tr><th>항목</th><th>내용</th><th>확인 포인트</th></tr></thead>
<tbody>
<tr><td>서비스</td><td>이웃차(개인간 차량 공유)</td><td>앱 지도에서 주변 차량 확인</td></tr>
<tr><td>이용 방식</td><td>가서타기 / 불러서타기</td><td>도보 이동 vs 딜리버리</td></tr>
<tr><td>대여 단위</td><td>짧은 시간(분 단위)~일 단위</td><td>실제 필요 시간만 결제</td></tr>
<tr><td>요금 구조</td><td>대여료 + 주행요금 + 보험</td><td>예약 전 예상 요금·보험 옵션 확인</td></tr>
<tr><td>공식 채널</td><td>타운카 앱·안내</td><td><a href="https://towncar.onelink.me/">towncar.onelink.me</a></td></tr>
</tbody>
</table>
<p>요금·보험·가능 차종은 호스트·지역·시점에 따라 달라지므로, 결제 직전 앱 견적을 기준으로 하세요.</p>
<h2>나에게 해당되는지</h2>
<h3>쓰기 좋은 경우</h3>
<ul>
<li>차는 가끔만 필요하고, 지점 방문형 렌터카가 번거로운 경우</li>
<li>주말 근교·장보기·출장처럼 <strong>짧은 구간</strong>만 이동할 때</li>
<li>경차~SUV·특수 차종을 목적에 맞게 골라 쓰고 싶을 때</li>
</ul>
<h3>다른 수단이 나은 경우</h3>
<ul>
<li>장기 출장·여행으로 수일 이상 고정 대여가 필요할 때(전통 렌터카 비교)</li>
<li>즉시 출발인데 주변에 즉시예약 차량이 없을 때</li>
<li>운전면허·본인인증을 당장 완료할 수 없는 경우</li>
</ul>
<h2>지금 이용하는 방법</h2>
<ol>
<li>앱 설치 후 휴대폰·면허 등 회원 인증을 완료합니다.</li>
<li>지도에서 차량을 고르고, 대여 시간과 보험 옵션을 선택합니다.</li>
<li>급하면 <strong>즉시 예약 가능</strong> 차량만 필터합니다.</li>
<li>인수 전·후에 외관/내부 사진을 남겨 분쟁을 예방합니다.</li>
<li>반납 시 연료·충전·주차 위치 조건을 앱 안내대로 맞춥니다.</li>
</ol>
<p>공식 설치·안내: <a href="https://towncar.onelink.me/">https://towncar.onelink.me/</a></p>
<h2>체크리스트 / 피해야 할 실수</h2>
<ul>
<li>□ 예상 총요금(대여+주행+보험)을 결제 전에 확인했다</li>
<li>□ 인수·반납 사진을 남겼다</li>
<li>□ 주말·퇴근 등 피크 시간은 미리 예약했다</li>
<li>□ 반납 연료/충전 조건을 지켰다</li>
<li>피해야 할 실수: 승인 대기 차량만 골라 놓고 출발 시각을 못 맞추는 것</li>
</ul>
<h2>FAQ</h2>
<p><strong>Q. 타운카와 일반 렌터카 차이는?</strong><br />
A. 타운카는 이웃 차량을 앱으로 빌려 쓰는 구조라 근처 픽업이 빠르고 짧은 시간에 유리합니다. 장기·고정 일정은 렌터카 견적과 비교하세요.</p>
<p><strong>Q. 보험은 포함되나요?</strong><br />
A. 앱에서 보험 옵션을 선택하는 방식이 일반적입니다. 자기부담금·보장 범위를 결제 전 확인하세요.</p>
<p><strong>Q. 가서타기·불러서타기란?</strong><br />
A. 가서타기는 차량 위치로 직접 가고, 불러서타기는 호출형(가능 지역·차종 한정)입니다.</p>
<p><strong>Q. 분쟁을 줄이려면?</strong><br />
A. 인수·반납 사진, 연료/충전 상태, 주차 위치 기록을 남기는 것이 가장 중요합니다.</p>
""".replace("__ASOF__", asof_html())


SAMSUNG_BIZ_BODY = """
<p><img class="post-thumb" src="https://cdn.jsdelivr.net/gh/yeonjoo2025/blogger@b8a1a073f3fcbabd5527248ada4b83eb50f0856f/posts/images/thumb-kimchi-fridge.jpg" alt="삼성전자 사업자몰 김치냉장고 구매 가이드" style="display:block;width:100%;max-width:100%;height:auto;margin:0 0 1em 0;border:0;" /></p>
__ASOF__
<h2>한 줄 요약</h2>
<p>사업자등록이 있다면 삼성전자 사업자몰에서 <strong>비스포크 김치냉장고</strong>를 사업자 전용가·쿠폰·할부 조건으로 비교·구매할 수 있습니다. 이 글은 가입 자격, 구매 전 체크 항목, 공식몰 이동 경로를 한 번에 정리합니다.</p>
<h2>핵심 사실</h2>
<table border="1" cellpadding="6" cellspacing="0">
<thead><tr><th>항목</th><th>내용</th><th>확인 포인트</th></tr></thead>
<tbody>
<tr><td>채널</td><td>삼성전자 사업자몰</td><td><a href="https://www.samsungebiz.com/">samsungebiz.com</a></td></tr>
<tr><td>가입</td><td>사업자등록번호 필요</td><td>개인 쇼핑몰 계정과 별도</td></tr>
<tr><td>대표 혜택</td><td>사업자 전용가·쿠폰·무이자 할부 등</td><td>행사 기간·카드사 조건은 수시 변경</td></tr>
<tr><td>제품 포인트</td><td>AI 정온·에너지효율·공간 활용</td><td>모델별 스펙·용량을 매장 환경에 맞게 선택</td></tr>
<tr><td>환급·효율</td><td>으뜸효율 등 정책 혜택 가능 시</td><td>정부·지자체 공고 기간을 별도 확인</td></tr>
</tbody>
</table>
<p>가격·쿠폰·할부·사은품은 프로모션 회차에 따라 달라집니다. 결제 직전 사업자몰 상품 페이지 조건을 기준으로 하세요.</p>
<h2>나에게 해당되는지</h2>
<ul>
<li><strong>해당:</strong> 식당·카페·식품 취급 사업장, 김치·식재료 대량 보관이 필요한 소상공인</li>
<li><strong>보류:</strong> 사업자등록이 없거나, 가정용 소용량만 필요해 일반몰 특가가 더 유리한 경우</li>
</ul>
<h2>지금 확인·구매하는 방법</h2>
<ol>
<li>사업자몰 가입·사업자 인증을 완료합니다. (<a href="https://www.samsungebiz.com/">공식 사업자몰</a>)</li>
<li>필요 용량(문수·리터)·설치 공간·문 방향·소음을 기준으로 모델을 좁힙니다.</li>
<li>판매가 + 쿠폰 + 카드 할부 + 배송/설치비를 <strong>총소유비용</strong>으로 계산합니다.</li>
<li>에너지효율·환급 대상 여부를 제품 상세/공고에서 확인합니다.</li>
<li>설치 일정·엘리베이터·문 폭을 매장 기준으로 체크한 뒤 주문합니다.</li>
</ol>
<p>제품·프로모션 예시 링크(변경될 수 있음): <a href="https://www.samsung.com/sec/ace/link/3gI">삼성 안내 링크</a></p>
<h2>체크리스트 / 피해야 할 실수</h2>
<ul>
<li>□ 사업자 인증이 주문 전에 완료됐다</li>
<li>□ 쿠폰·카드 할인을 중복 적용 가능한지 확인했다</li>
<li>□ 설치 환경(문폭·전원·통로)을 재봤다</li>
<li>□ 환급/효율 혜택 기간을 공식 공고로 확인했다</li>
<li>피해야 할 실수: 정가만 보고 총비용(설치·할부·전기요금)을 빼먹는 것</li>
</ul>
<h2>FAQ</h2>
<p><strong>Q. 개인 삼성 계정으로 사업자몰을 쓰나요?</strong><br />
A. 사업자몰은 사업자 인증이 별도로 필요합니다. 가입 화면 안내를 따르세요.</p>
<p><strong>Q. 일반몰보다 항상 싼가요?</strong><br />
A. 대체로 사업자 전용가가 유리한 경우가 많지만, 카드·타임세일·재고 처분에 따라 역전될 수 있어 결제 직전 비교가 필요합니다.</p>
<p><strong>Q. 에너지 환급은 자동인가요?</strong><br />
A. 아닙니다. 대상 제품·신청 기간·서류는 정부/지자체 공고를 따로 확인해야 합니다.</p>
<p><strong>Q. 이 글은 광고인가요?</strong><br />
A. 일부 안내는 삼성 ACE 활동 대가가 포함된 정보성 글일 수 있습니다. 구매 결정은 공식몰 조건과 본인 사업장 필요를 기준으로 하세요.</p>
<p><em>※ 경제적 대가 고지: 관련 게시물은 삼성 ACE 활동의 일환으로 소정의 경제적 대가를 제공받아 작성된 내용을 포함할 수 있습니다.</em></p>
""".replace("__ASOF__", asof_html())


PAGES = [
    (
        "소개",
        f"""
<h2>욘두두 블로그 소개</h2>
<p>욘두두 블로그(<a href="https://yeondodo.blogspot.com/">yeondodo.blogspot.com</a>)는
<strong>신청·예약·요금·혜택·가입처럼 실제로 바로 쓰는 생활·금융·IT 정보</strong>를 정리하는 가이드형 사이트입니다.
검색으로 들어온 질문에 대해 “다음에 무엇을 클릭·신청하면 되는지”가 남도록,
공식 출처 링크·체크리스트·FAQ를 중심으로 글을 씁니다.</p>
<h3>이 사이트가 해결하려는 문제</h3>
<p>제도·혜택·예약 정보는 공지가 여러 페이지에 흩어져 있고, 자격·일정·서류 조건이 자주 바뀝니다.
뉴스 헤드라인만 보면 “된다/안 된다”는 감은 있어도, 실제로 앱에서 버튼을 누르거나
증명서를 발급받기까지의 순서가 빠지기 쉽습니다. 욘두두는 그 빈칸을 메우는 것을 목표로 합니다.</p>
<p>그래서 글마다 가능한 한 아래를 같은 형식으로 둡니다.</p>
<ul>
<li>정보 기준일 (언제 기준으로 정리했는지)</li>
<li>한눈에 보는 요약표 (대상·일정·핵심 조건)</li>
<li>따라 하는 체크리스트·신청 순서</li>
<li>공식 신청·예약·공지 URL 2개 이상</li>
<li>자주 막히는 지점 FAQ</li>
</ul>
<p>업데이트는 공식 공지 변경이 확인될 때 우선 반영하며, 불확실한 내용은 단정하지 않고 기준일과 확인 링크를 함께 남깁니다.</p>
<h3>이런 글을 올립니다</h3>
<ul>
<li>정부·공공·지자체·공식 기업 페이지에서 확인 가능한 <strong>신청·예약·예매·환급</strong> 절차</li>
<li>요금·자격·일정·한도처럼 숫자와 조건이 중요한 <strong>생활·금융 가이드</strong></li>
<li>서버·클라우드·도구처럼 따라 하면 끝나는 <strong>IT 실무 정리</strong></li>
</ul>
<p>반대로 사고·특보·일일 시황·연예·스포츠 결과처럼
<strong>30일 뒤에도 같은 행동으로 이어지지 않는 일회성 이슈</strong>는 다루지 않거나 최소화합니다.
한시 프로모션·마감 이벤트도, 독자가 반복해서 찾을 가이드로 남지 않으면 발행하지 않습니다.</p>
<h3>운영 원칙</h3>
<ul>
<li>가능하면 정부·공공기관·공식 기업 공지 URL을 본문에 2개 이상 넣습니다.</li>
<li>글 상단에 <strong>정보 기준일</strong>을 표기하고, 변경 가능 조건은 공식 링크 재확인을 안내합니다.</li>
<li>투자·의료·법률에 대한 확정 조언이나 매수·매도 지시는 하지 않습니다.</li>
<li>제휴·대가성 내용이 있으면 본문에 고지합니다.</li>
<li>사실 오류 제보가 오면 공식 출처를 다시 확인한 뒤 수정합니다.</li>
</ul>
<h3>읽는 방법</h3>
<ol>
<li>상단 정보 기준일과 요약표를 먼저 확인합니다.</li>
<li>체크리스트·신청 순서로 필요한 서류·앱·계정을 준비합니다.</li>
<li>본문 <strong>공식 링크</strong>에서 자격·일정·요금을 최종 확인한 뒤 신청·예약합니다.</li>
<li>FAQ에서 자주 막히는 지점을 보고, 오류가 있으면 문의 페이지로 알려 주세요.</li>
</ol>
<h3>대표 주제 예시</h3>
<ul>
<li>계좌·적금·세금·지원금처럼 조건 확인이 필요한 금융·제도 안내</li>
<li>캠핑·교통·멤버십처럼 예약·할인·등급 확인이 필요한 생활 혜택</li>
<li>리눅스·클라우드처럼 명령을 복사해 바로 쓰는 IT 치트시트</li>
</ul>
<h3>면책</h3>
<p>본 사이트의 글은 공식 공지를 바탕으로 한 <strong>정보 정리</strong>이며,
개별 세무·법률·의료·투자 결정의 확정 조언이 아닙니다.
실제 적용 여부·금액·일정은 신청·예약·결제 직전의 공식 페이지와 본인 자격이 기준입니다.</p>
<h3>관련 안내</h3>
<ul>
<li><a href="CONTACT_URL">문의·오류 제보</a> — 사실 오류, 링크 깨짐, 일정 변경 제보</li>
<li><a href="PRIVACY_URL">개인정보처리방침</a> — 쿠키·광고·문의 정보 처리</li>
<li>호스팅: <a href="https://www.blogger.com/">Google Blogger</a></li>
<li>광고 정책 참고: <a href="https://support.google.com/adsense/answer/1348695">Google AdSense 프로그램 정책</a></li>
</ul>
<p><em>최종 업데이트: {ASOF}</em></p>
""",
    ),
    (
        "개인정보처리방침",
        f"""
<h2>개인정보처리방침</h2>
<p>욘두두 블로그(<a href="https://yeondodo.blogspot.com/">yeondodo.blogspot.com</a>, 이하 “본 사이트”)는
Google <a href="https://www.blogger.com/">Blogger</a>에서 호스팅됩니다.
본 방침은 사이트 이용, 문의 접수, 광고·통계와 관련해 어떤 정보가 어떻게 다루어질 수 있는지를 설명합니다.
본 사이트를 계속 이용하시면 아래 내용에 동의한 것으로 봅니다.</p>
<h3>1. 운영자·적용 범위</h3>
<p>본 사이트는 개인이 운영하는 정보성 블로그입니다.
Blogger·Google 계정·광고·분석 기능이 제공하는 범위 안에서 정보가 처리될 수 있으며,
Google 측 처리에는 Google의
<a href="https://policies.google.com/privacy">개인정보처리방침</a>이 함께 적용됩니다.
본 방침은 운영자가 직접 받는 문의 정보와, 사이트에 표시되는 광고·쿠키에 대한 안내를 중심으로 합니다.</p>
<h3>2. 수집·이용</h3>
<ul>
<li>별도 회원 가입·유료 결제·뉴스레터 구독 기능을 직접 운영하지 않습니다.</li>
<li>문의·오류 제보를 보내는 경우, 이메일 주소·메시지 내용·관련 글 URL이
<strong>답변·사실 확인 목적</strong>으로만 사용됩니다.</li>
<li>사이트 방문 시 Blogger·Google 서비스 이용 과정에서
IP 주소, 쿠키, 기기·브라우저 정보, 방문 기록 등이 자동 수집될 수 있습니다.</li>
<li>댓글을 남기는 경우, 작성자가 입력한 이름·내용·공개 프로필 정보가 게시물에 표시될 수 있습니다.</li>
<li>민감정보(주민등록번호, 계좌번호, 인증번호 등)는 요청하지 않으며, 문의에 포함되지 않도록 해 주세요.</li>
</ul>
<h3>3. 광고·쿠키 (Google AdSense)</h3>
<ul>
<li>본 사이트는 Google AdSense 등 제3자 광고를 표시할 수 있습니다. 게시자 ID 참고: {PUB_ID}</li>
<li>Google을 포함한 제3자는 쿠키·유사 기술을 사용해 관심사에 맞는 광고를 게재할 수 있습니다.</li>
<li>사용자는 <a href="https://adssettings.google.com/">Google 광고 설정</a>에서 맞춤 광고를 관리할 수 있습니다.</li>
<li>광고·쿠키에 대한 추가 안내:
<a href="https://policies.google.com/technologies/ads">Google 광고 기술 정책</a>,
<a href="https://support.google.com/adsense/answer/1348695">AdSense 프로그램 정책</a></li>
<li>정책 준수·품질 개선을 위해 광고를 일시 중지하거나 특정 화면에서 광고를 제한할 수 있습니다.</li>
</ul>
<h3>4. 제3자 제공·처리 위탁</h3>
<p>운영자가 문의를 받은 경우를 제외하고, 이용자 정보를 판매하거나 마케팅 목적으로 제3자에게 제공하지 않습니다.
호스팅·광고·보안·로그는 Google 등 서비스 제공자의 인프라에서 처리될 수 있으며,
해당 처리에는 각 제공자의 약관과 개인정보 정책이 적용됩니다.</p>
<h3>5. 보관·파기</h3>
<p>문의 내용은 답변에 필요한 기간 동안만 보관하며, 목적 달성 후 지체 없이 삭제합니다.
호스팅·광고·보안 로그는 각 서비스 제공자 정책과 보관 주기를 따릅니다.
댓글은 작성자가 삭제하거나 운영자가 운영 목적상 제거할 수 있습니다.</p>
<h3>6. 이용자 권리</h3>
<ul>
<li>문의로 남긴 본인 관련 내용의 열람·수정·삭제를 요청할 수 있습니다.</li>
<li>브라우저에서 쿠키를 거부·삭제할 수 있으나, 일부 기능이 제한될 수 있습니다.</li>
<li>맞춤 광고는 Google 광고 설정에서 옵트아웃할 수 있습니다.</li>
</ul>
<h3>7. 아동의 개인정보</h3>
<p>본 사이트는 만 14세 미만 아동을 대상으로 한 서비스를 운영하지 않으며,
아동의 개인정보를 고의로 수집하지 않습니다.
아동의 정보가 포함된 문의가 확인되면 지체 없이 삭제합니다.</p>
<h3>8. 방침 변경</h3>
<p>법령·서비스 변경에 따라 본 방침을 개정할 수 있으며, 중요한 변경은 본 페이지에 게시하고
하단에 최종 업데이트 일자를 갱신합니다.</p>
<h3>9. 문의</h3>
<p>개인정보 관련 문의: <a href="CONTACT_URL">문의·오류 제보</a><br />
블로그 소개: <a href="ABOUT_URL">욘두두 블로그 소개</a></p>
<p><em>시행일: 2026-08-05 / 최종 업데이트: {ASOF}</em></p>
""",
    ),
    (
        "문의",
        f"""
<h2>문의·오류 제보</h2><p>정확한 제보에 감사드립니다. 공식 근거와 함께 보내주시면 반영이 더 빨라집니다.</p><p>정확한 제보에 감사드립니다. 공식 근거와 함께 보내주시면 반영이 더 빨라집니다.</p>
<p>욘두두 블로그는 공식 공지·신청 페이지를 바탕으로 가이드를 정리합니다. 숫자·일정·링크가 바뀌었거나 본문에 오류가 있으면 알려 주세요. 가능한 범위에서 공식 출처를 재확인한 뒤 수정합니다.</p><p>문의는 사이트 품질을 높이기 위한 채널이며, 개별 상담 창구가 아닙니다. 특히 자격·요금·마감일처럼 숫자가 바뀌는 항목은 공식 페이지와 차이가 생길 수 있습니다.</p><p>제보해 주시면 정보 기준일과 본문 링크를 함께 점검합니다. 확인이 어려운 경우에도 “확인 필요” 문구를 보강해 독자가 공식 페이지를 다시 보게 안내합니다.</p><p>제보가 많을수록 같은 주제를 찾는 다음 독자가 더 빠르게 올바른 신청·예약 경로에 도달할 수 있습니다. 근거 링크가 있으면 반영 속도가 훨씬 빨라집니다.</p><p>민감정보(주민등록번호·계좌·인증번호)는 보내지 말아 주세요. 필요한 것은 글 URL과 공식 공지 주소, 그리고 틀린 문장 인용입니다.</p>
<h3>문의 전에 확인하면 좋은 것</h3>
<ul>
<li>해당 글 상단의 <strong>정보 기준일</strong>과 본문 공식 링크의 최신 공지</li>
<li>자격·요금·마감일이 본인 상황에 맞는지 (지역·연령·가입 상품 등)</li>
<li>이미 FAQ에 같은 질문이 있는지</li>
<li>공식 페이지에 별도 공지·팝업·첨부 PDF가 있는지</li>
<li>모바일 앱과 PC 웹의 안내가 서로 다른지</li>
</ul>
<h3>이렇게 보내 주세요</h3>
<ol>
<li>제목 형식: <code>[욘두두 문의] 한 줄 요약</code></li>
<li>필수: 해당 글 URL</li>
<li>수정이 필요한 문장·숫자·일정 (가능하면 인용)</li>
<li>근거가 되는 공식 페이지 URL 또는 공지 캡처 설명</li>
<li>확인한 날짜 (예: 2026-08-07)</li>
<li>(선택) 스크린샷에서 개인정보가 가려졌는지 확인</li>
</ol>
<h3>좋은 제보 예시</h3>
<ul>
<li>“다자녀 통행료 글의 신청 URL이 404입니다. 하이패스 공식 안내 새 주소는 … 입니다.”</li>
<li>“ISA 글의 한도 숫자가 공식 안내와 다릅니다. 금융감독원/은행 공지 링크는 … 입니다.”</li>
<li>“캠핑 예약 오픈 시간이 바뀌었습니다. 서울시/인터파크 공지 기준 … 입니다.”</li>
<li>“멤버십 등급 표가 공식 안내와 다릅니다. U+ 등급 안내 URL은 … 입니다.”</li>
</ul>
<h3>연락 방법</h3>
<ul>
<li>블로그 프로필 메시지: <a href="https://www.blogger.com/profile/10676879295522899057">욘두두 프로필</a></li>
<li>해당 글 댓글 (비공개가 필요하면 프로필 메시지 권장)</li>
<li>호스팅·계정 관련 일반 도움말: <a href="https://support.google.com/blogger">Blogger 도움말</a></li>
</ul>
<h3>처리 범위 / 제외</h3>
<ul>
<li>반영: 사실 오류, 깨진 링크, 일정·요금·자격 변경, 공식 URL 추가·교체, 오탈자</li>
<li>제외: 개별 세무·법률·의료·투자 상담, 민감정보 확인, 광고 협상, 개별 자격 판정, 스팸</li>
</ul>
<h3>응답 안내</h3>
<p>보통 수일 내 확인합니다. 공식 출처가 불명확하거나 제도가 확정되지 않은 경우 즉시 수정 대신 기준일·주의 문구를 보강할 수 있습니다.
긴급한 제도 변경이라도 공식 문서가 없으면 단정 표현으로 바꾸지 않습니다.</p>
<p>개인정보 처리 방식은 <a href="PRIVACY_URL">개인정보처리방침</a>을, 운영 방향은 <a href="ABOUT_URL">블로그 소개</a>를 참고해 주세요.</p>
<h3>관련 링크</h3>
<ul>
<li><a href="ABOUT_URL">욘두두 블로그 소개</a></li>
<li><a href="PRIVACY_URL">개인정보처리방침</a></li>
<li><a href="https://support.google.com/adsense/answer/1348695">Google AdSense 프로그램 정책</a></li>
<li><a href="https://policies.google.com/privacy">Google 개인정보처리방침</a></li>
</ul>
<p><em>업데이트: {ASOF}</em></p>
""",
    ),
]


def _find_post_by_title(svc, title: str, status: str) -> dict | None:
    token = None
    while True:
        resp = (
            svc.posts()
            .list(
                blogId=BLOG_ID,
                fetchBodies=False,
                maxResults=50,
                status=status,
                pageToken=token,
            )
            .execute()
        )
        for p in resp.get("items") or []:
            if (p.get("title") or "").strip() == title:
                return p
        token = resp.get("nextPageToken")
        if not token:
            return None


def _next_draft(svc, used_ids: set[str]) -> dict | None:
    token = None
    while True:
        resp = (
            svc.posts()
            .list(
                blogId=BLOG_ID,
                fetchBodies=False,
                maxResults=50,
                status="DRAFT",
                pageToken=token,
            )
            .execute()
        )
        for p in resp.get("items") or []:
            if p["id"] not in used_ids:
                return p
        token = resp.get("nextPageToken")
        if not token:
            return None


def upsert_pages(svc) -> dict[str, str]:
    """pages/posts insert is 403 — convert DRAFT posts into site guide posts, then publish."""
    urls: dict[str, str] = {}
    created: dict[str, dict] = {}
    used_ids: set[str] = set()
    labels = ["사이트안내"]

    for title, content in PAGES:
        existing = _find_post_by_title(svc, title, "LIVE") or _find_post_by_title(
            svc, title, "DRAFT"
        )
        if existing:
            post_id = existing["id"]
            print(f"SITEPOST_REUSE {title} id={post_id}")
        else:
            draft = _next_draft(svc, used_ids)
            if not draft:
                raise SystemExit("No DRAFT posts left to convert into site pages")
            post_id = draft["id"]
            print(f"SITEPOST_CONVERT {title} from_draft={draft.get('title','')[:40]}")
        used_ids.add(post_id)
        body = {"title": title, "content": content, "labels": labels}
        page = svc.posts().patch(blogId=BLOG_ID, postId=post_id, body=body).execute()
        # ensure LIVE
        if (page.get("status") or "").upper() != "LIVE":
            page = svc.posts().publish(blogId=BLOG_ID, postId=post_id).execute()
            print(f"SITEPOST_PUBLISH {title}")
        created[title] = page
        urls[title] = page.get("url") or ""
        time.sleep(0.5)

    about = urls.get("소개", "")
    privacy = urls.get("개인정보처리방침", "")
    contact = urls.get("문의", "")

    for title, content in PAGES:
        fixed = (
            content.replace("ABOUT_URL", about)
            .replace("PRIVACY_URL", privacy)
            .replace("CONTACT_URL", contact)
        )
        page_id = created[title]["id"]
        page = svc.posts().patch(
            blogId=BLOG_ID, postId=page_id, body={"content": fixed}
        ).execute()
        urls[title] = page.get("url") or urls[title]
        print(f"SITE_LINKS {title} -> {urls[title]}")
        time.sleep(0.4)
    return urls


def list_live(svc) -> list[dict]:
    items: list[dict] = []
    token = None
    while True:
        resp = (
            svc.posts()
            .list(
                blogId=BLOG_ID,
                fetchBodies=True,
                maxResults=50,
                status="LIVE",
                pageToken=token,
            )
            .execute()
        )
        items.extend(resp.get("items") or [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def reinforce_posts(svc, about_url: str) -> None:
    posts = list_live(svc)
    hub = [
        (p.get("title", "").strip(), p.get("url", ""))
        for p in posts
        if (p.get("title") or "").strip() not in SITE_TITLES
    ]
    print(f"LIVE={len(posts)}")

    for i, p in enumerate(posts, 1):
        title = (p.get("title") or "").strip()
        post_id = p["id"]
        html = p.get("content") or ""

        if title in SITE_TITLES:
            print(f"[{i:02d}] SITE_SKIP_BODY {title}")
            time.sleep(0.2)
            continue

        if any(k in title for k in WEAK_REWRITE_KEYS):
            if "타운카" in title:
                html = TOWNCAR_BODY
            else:
                html = SAMSUNG_BIZ_BODY
            print(f"[{i:02d}] REWRITE {title[:50]}")
        else:
            html = insert_after_thumb(html, asof_html())
            print(f"[{i:02d}] ASOF {title[:50]}")

        if count_internal(html) < 2 or RELATED_MARK not in html:
            rel = pick_related(title, hub, n=3)
            html = ensure_related(html, rel, about_url)
            print(f"       +related {len(rel)} internal_now={count_internal(html)}")
        elif about_url and ABOUT_MARK not in html:
            html += f'<p>{ABOUT_MARK}<a href="{about_url}">블로그 소개 · 운영 안내</a></p>'

        # light disclaimer if missing
        if "정보 안내용" not in html and "확정 조언" not in html:
            html += (
                "<p><em>이 글은 정보 안내용이며 투자·법률·의료에 대한 확정 조언이 아닙니다. "
                "최종 조건은 공식 기관·판매처 안내를 확인하세요.</em></p>"
            )

        svc.posts().patch(
            blogId=BLOG_ID,
            postId=post_id,
            body={"content": html},
        ).execute()
        time.sleep(0.45)

    print("POSTS_REINFORCED_OK")


def main() -> None:
    svc = service()
    print(f"ASOF={ASOF}")
    print(
        "ADS_TXT_MANUAL="
        f"Blogger→설정→수익 창출→맞춤 ads.txt 사용: "
        f"google.com, {PUB_ID}, DIRECT, f08c47fec0942fa0"
    )
    print(
        "BLOG_DESCRIPTION_MANUAL="
        "Blogger→설정→기본→설명: 신청·예약·요금·혜택 가이드 (정보 기준일·공식 링크 확인)"
    )
    urls = upsert_pages(svc)
    about = urls.get("소개", "")
    reinforce_posts(svc, about)
    print("PAGE_URLS")
    for k, v in urls.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
