"""Turn a qualified trend keyword + real news into a structured post.

The required structure (issue / who is affected / how to check / how to
respond / related news) is always rendered, and every factual claim in the
"issue" and "related news" sections is grounded in real headlines pulled
from Google News RSS rather than invented.
"""

from __future__ import annotations

from html import escape

from trend_sources import NewsRef

CATEGORY_HOOK = {
    "금융": "지갑에 영향, 확인·대응법",
    "투자": "투자자 영향과 대응 전략",
    "건강": "건강 영향과 대응 수칙",
    "생활안전": "안전 영향과 대피·대응 방법",
    "법률": "법적 영향과 대응 방법",
}

CATEGORY_IMPACT_INTRO = {
    "금융": "이번 이슈는 대출, 세금, 연금, 물가 등 개인·가계의 지출과 자산 관리에 직접 영향을 줄 수 있는 사안입니다.",
    "투자": "이번 이슈는 국내외 증시·코인 시장에 노출된 투자자의 포트폴리오에 직접 영향을 줄 수 있는 사안입니다.",
    "건강": "이번 이슈는 감염, 부작용, 리콜 등 실제 건강과 진료·대처가 필요한 상황과 연결된 사안입니다.",
    "생활안전": "이번 이슈는 침수, 화재, 대피, 정전 등 실제 생활 안전과 직결되는 사안입니다.",
    "법률": "이번 이슈는 소송, 규제, 단속 등 개인·기업이 실제로 대응해야 하는 법적 절차와 관련된 사안입니다.",
}

CATEGORY_WHO_AFFECTED = {
    "금융": [
        "대출·전세·매매 등 부동산 관련 자금 계획이 있는 사람",
        "세금·연금·지원금 신청 일정이 있는 사람",
        "관련 산업 종사자 및 소비자",
    ],
    "투자": [
        "관련 종목·코인을 보유했거나 매수를 검토 중인 투자자",
        "국내 증시·환율 변동에 자산이 노출된 사람",
        "관련 산업(제조·수출 등) 종사자",
    ],
    "건강": [
        "관련 증상이 있거나 의심되는 사람",
        "리콜·부작용 대상 제품·의약품을 사용 중인 사람",
        "고위험군(어린이, 고령자, 기저질환자)",
    ],
    "생활안전": [
        "해당 지역 거주자 및 통근·통학하는 사람",
        "차량·물류 이동이 필요한 사람",
        "저지대·하천 인근 거주자",
    ],
    "법률": [
        "직접 당사자 또는 관련 계약·거래 당사자",
        "동일·유사 사안으로 분쟁 중인 사람",
        "관련 제도 변경으로 절차가 바뀌는 일반 이용자",
    ],
}

CATEGORY_CHECK = {
    "금융": [
        "한국은행 경제통계시스템(ECOS) 및 금융위원회·금융감독원 보도자료 확인",
        "거래 중인 은행·카드사 공식 홈페이지 및 앱 공지사항 확인",
        "국세청 홈택스에서 본인에게 적용되는 신고·납부 일정 확인",
    ],
    "투자": [
        "한국거래소(KRX) 공시 및 관련 종목 IR·공시자료 확인",
        "증권사 리서치센터 리포트, 나스닥·코스피 지수 변동 확인",
        "가상자산 거래소 공지사항 및 시세 변동 폭 확인",
    ],
    "건강": [
        "질병관리청·보건소 공식 발표 및 통계 확인",
        "식품의약품안전처 리콜·회수 정보 페이지 확인",
        "이용 중인 의료기관·약국에 증상 및 제품 관련 문의",
    ],
    "생활안전": [
        "기상청 특보(호우·태풍·대설 등) 및 행정안전부 안전디딤돌 앱 확인",
        "지자체·소방서·경찰서 공식 재난문자 및 공지사항 확인",
        "거주 지역 침수·정전·교통 상황을 실시간 뉴스로 재확인",
    ],
    "법률": [
        "국가법령정보센터에서 관련 법령·개정 여부 확인",
        "관할 법원·관계 기관 보도자료 및 공고문 확인",
        "대한법률구조공단 등 무료 법률 상담 채널 확인",
    ],
}

CATEGORY_RESPONSE = {
    "금융": [
        "대출 금리·만기, 세금 신고 기한을 캘린더에 등록해 놓기",
        "가계 지출 계획을 다시 점검하고 불필요한 지출 줄이기",
        "필요하면 은행·세무 전문가와 상담해 개인 상황에 맞는 대응 확인하기",
    ],
    "투자": [
        "단기 변동성에 즉흥적으로 매매하지 않고 원래 투자 원칙 유지하기",
        "보유 종목·코인의 리스크 비중을 다시 점검하기",
        "관련 공시·뉴스가 추가로 나오는지 며칠간 추적하기",
    ],
    "건강": [
        "의심 증상이 있으면 자가진단 대신 의료기관에서 진료받기",
        "리콜·회수 대상 제품이나 의약품은 즉시 사용을 중단하기",
        "예방접종, 손 씻기 등 기본 위생 수칙을 지키기",
    ],
    "생활안전": [
        "특보·경보 발효 지역은 외출을 자제하고 안전한 곳으로 대피하기",
        "침수 위험이 있는 지하공간·차량 이동을 피하기",
        "정전·단수에 대비해 비상용품과 연락 수단을 미리 점검하기",
    ],
    "법률": [
        "관련 계약서, 문자, 영수증 등 증거자료를 미리 보관하기",
        "이의신청·항소 등 대응 기한을 놓치지 않도록 일정 확인하기",
        "필요하면 변호사·법률구조공단 등에서 상담받기",
    ],
}


def _clean_headline(title: str) -> str:
    title = title.strip()
    return title[:120]


def build_title(keyword: str, category: str) -> str:
    hook = CATEGORY_HOOK.get(category, "핵심 요약과 대응법")
    return f"{keyword}, 무슨 일이길래? {hook} 정리"


def _p(text: str) -> str:
    return f"<p>{escape(text)}</p>"


def _h3(text: str) -> str:
    return f"<h3>{escape(text)}</h3>"


def _ul(items: list[str]) -> str:
    lis = "".join(f"<li>{escape(i)}</li>" for i in items)
    return f"<ul>{lis}</ul>"


def build_issue_section(keyword: str, news: list[NewsRef]) -> str:
    parts = [_h3("1. 이슈가 무엇인가")]
    headlines = [_clean_headline(n.title) for n in news[:4] if n.title.strip()]
    if headlines:
        parts.append(
            _p(
                f"최근 '{keyword}' 관련 검색과 보도가 동시에 늘고 있습니다. "
                f"주요 언론 보도를 종합하면 다음과 같은 내용이 확인됩니다."
            )
        )
        parts.append(_ul(headlines))
    else:
        parts.append(_p(f"최근 '{keyword}' 관련 검색이 눈에 띄게 늘어나며 이슈로 떠오르고 있습니다."))
    return "".join(parts)


def build_impact_section(keyword: str, category: str) -> str:
    intro = CATEGORY_IMPACT_INTRO.get(category, f"'{keyword}'는 실생활에 영향을 줄 수 있는 사안으로 분류됩니다.")
    who = CATEGORY_WHO_AFFECTED.get(category, [])
    parts = [_h3("2. 무엇이 영향받는가"), _p(intro)]
    if who:
        parts.append(_p("특히 아래에 해당한다면 더 눈여겨볼 필요가 있습니다."))
        parts.append(_ul(who))
    return "".join(parts)


def build_check_section(category: str) -> str:
    checks = CATEGORY_CHECK.get(category, ["관련 기관 공식 발표 및 언론 보도로 사실관계 재확인"])
    return "".join([_h3("3. 관련해서 확인할 방법"), _ul(checks)])


def build_response_section(category: str) -> str:
    actions = CATEGORY_RESPONSE.get(category, ["추가 공식 발표를 확인하며 상황에 맞게 대응하기"])
    return "".join([_h3("4. 해결·대응 방법"), _ul(actions)])


def build_related_news_section(news: list[NewsRef]) -> str:
    if not news:
        return ""
    parts = [_h3("5. 관련 소식")]
    lis = []
    for n in news[:5]:
        title = escape(_clean_headline(n.title))
        source = escape(n.source) if n.source else ""
        if n.url:
            link = f'<a href="{escape(n.url)}" rel="nofollow noopener" target="_blank">{title}</a>'
        else:
            link = title
        suffix = f" - {source}" if source else ""
        lis.append(f"<li>{link}{suffix}</li>")
    parts.append(f"<ul>{''.join(lis)}</ul>")
    return "".join(parts)


def build_body_html(keyword: str, category: str, news: list[NewsRef]) -> str:
    sections = [
        build_issue_section(keyword, news),
        build_impact_section(keyword, category),
        build_check_section(category),
        build_response_section(category),
        build_related_news_section(news),
        _p("본 글은 공개된 트렌드 지표와 언론 보도를 바탕으로 정리한 정보성 콘텐츠이며, 상황은 이후 달라질 수 있으니 최신 공식 발표를 함께 확인하시기 바랍니다."),
    ]
    return "\n".join(s for s in sections if s)
