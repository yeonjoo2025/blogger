"""Korean news-style (16:9) thumbnail generation for Blogger posts.

## 썸네일 생성 (필수)

글마다 개성 있는 뉴스 썸네일 1장을 만든다. 목표는 "배경 사진/장면 안에 한글
헤드라인이 자연스럽게 들어간" 방송용 썸네일이다. 하단 반투명 배너를 따로
덮어씌우지 않는다 — 텍스트는 (가능하면) 이미지 생성 단계에서 배경과 함께
렌더링되거나, Pillow 폴백에서는 두꺼운 외곽선(stroke) 타이포로 장면 위에
직접 얹는다.

### 1) 텍스트 추출
- 메인 제목: 글 핵심 8~14자 (예: 메시 국가대표 은퇴)
- 서브 문구: 상황 한 줄 12~20자 (예: 월드컵 결승 패배 후 마지막 인사)
- 파일명: ASCII만 사용 (예: thumb-messi-argentina.jpg) — 한글 파일명 금지

### 2) 이미지 생성 프롬프트 템플릿 (`build_image_prompt`)

  Korean news thumbnail, 16:9, cinematic and unique to this topic.
  Background must visually match the article subject (not generic gradient).
  Compose large bold Korean headline INTO the scene itself (not a separate
  UI card): "{main}".
  Smaller Korean subheadline integrated in the composition: "{sub}".
  High contrast, dramatic lighting, broadcast sports/tech/politics news style.
  No logos, no brand marks, no realistic celebrity face likeness, no long
  paragraphs.
  Do NOT add a flat translucent bottom bar overlay after generation.

주제별 배경 힌트 예시 (`TOPIC_SCENES`):
  - 야구: 우천 야구장, 마운드, 야간 조명
  - 축구/은퇴: 경기장 밤 분위기, 유니폼/트로피 상징 (실존 얼굴 금지)
  - 국방/정치: 스마트 캠퍼스·훈련장 느낌의 상징 장면
  - AI/IT: 회로·네온·추상 테크 장면 (로고 금지)

### 3) 소스 우선순위 (자동화 파이프라인이 실제로 쓰는 순서)
  1. `generated_images/ai-thumb-{slug}.*` — 텍스트까지 완성된 AI 생성 이미지
     (에이전트가 GenerateImage로 위 프롬프트를 그대로 사용해 만든 결과).
     리사이즈 + 워터마크만 적용해 그대로 사용한다.
  2. `generated_images/bg-{slug}.*` — 텍스트 없는 배경판. Pillow로 헤드라인을
     장면 위에 직접(외곽선 타이포, 띠 없음) 합성한다.
  3. API 키/생성 이미지가 전혀 없을 때만 Pillow 폴백: `paint_topic_background`
     로 글마다 배경색·아이콘·구도를 다르게 그리고, 문구를 이미지 안에 크게
     직접 얹는다. 밋밋한 단색 + 배너 반복 금지.
  (`generated_images/` 는 git-ignore 대상 — 커밋되는 것은 최종 결과물인
  `posts/images/thumb-{slug}.jpg` 뿐이다.)

### 4) 후처리
  - 가로 1280px JPG 압축
  - 우측 하단에만 "@욘두두" 워터마크 추가 (작은 반투명 라벨만 허용)
  - 저장 경로: posts/images/thumb-{slug}.jpg (slug는 ASCII)
  - commit/push 후 URL:
    https://cdn.jsdelivr.net/gh/yeonjoo2025/blogger@{commitSHA}/posts/images/thumb-{slug}.jpg

### 5) 본문 삽입
  <p><img class="post-thumb" src="{URL}" alt="{메인제목}"
     style="display:block;width:100%;max-width:100%;height:auto;
     margin:0 0 1em 0;border:0;" /></p>

### 6) 금지 / 보호
  - `PROTECTED_SLUGS` 에 있는 슬러그의 썸네일 파일은 이미 존재하면 절대
    재생성/덮어쓰기하지 않는다 (force=True 여도 무시).
  - 이미 썸네일 파일이 있는 글은 기본적으로 새로 만들지 않고 그대로 유지한다
    (`build_thumb_for_post(..., force=True)` 를 명시해야만 재생성).
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import subprocess
import time
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

# Default ON: automation must supply GenerateImage output under generated_images/
# before a post can be published. Set BLOGGER_ALLOW_PILLOW_THUMB=1 only for local
# emergency fallbacks (flat Pillow scenes are NOT acceptable for production).
REQUIRE_AI_THUMB = os.environ.get("BLOGGER_REQUIRE_AI_THUMB", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
ALLOW_PILLOW_THUMB = os.environ.get("BLOGGER_ALLOW_PILLOW_THUMB", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


class MissingAIThumbError(RuntimeError):
    """Raised when a production-quality AI plate is required but missing."""

    def __init__(self, slug: str, prompt: str, dest: str, main: str, sub: str):
        self.slug = slug
        self.prompt = prompt
        self.dest = dest
        self.main = main
        self.sub = sub
        super().__init__(
            f"AI thumbnail missing for slug={slug}. "
            f"GenerateImage로 이미지를 만든 뒤 {dest} 에 저장하고 다시 실행하세요."
        )

IMAGE_DIR = Path("posts/images")
GENERATED_DIR = Path("generated_images")  # git-ignored AI source plates
REPO_SLUG = os.environ.get("BLOGGER_GITHUB_REPO", "yeonjoo2025/blogger")
JSDELIVR_TMPL = "https://cdn.jsdelivr.net/gh/{repo}@{sha}/posts/images/{filename}"

# Thumbnails that must never be regenerated/overwritten by automation once
# created, regardless of --replace / force flags.
PROTECTED_SLUGS: frozenset[str] = frozenset({
    "kt-doosan",
    "messi-argentina",
    "military-academy",
})

# Topic motif → (palette top/mid/accent, English scene for AI / Pillow)
# More specific / distinctive keys are listed first. Matching prefers the
# keyword field, then title; longer key wins when multiple hit.
# Title-template words that must not steal the visual motif/slug away from
# the real keyword (e.g. "구글 실적발표" + "...대출·세금에 영향..." → finance).
_TITLE_BOILERPLATE_KEYS = {
    "대출", "세금", "영향", "확인", "대응", "방법", "있나", "지갑", "정리",
    "전략", "수칙", "요령", "절차",
}

TOPIC_SCENES: list[tuple[tuple[str, ...], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], str, str]] = [
    (("키미", "kimi", "인공지능", " llm", "llm "), (8, 12, 40), (60, 40, 140), (120, 230, 255),
     "ai", "futuristic AI neural network glow, abstract chip circuits, magenta and cyan light, no people"),
    (("구글", "알파벳", "google", "alphabet", "실적발표", "실적", "어닝스", "earnings"),
     (10, 20, 48), (30, 70, 140), (120, 220, 255),
     "earnings", "tech earnings night: glowing blue revenue charts, abstract search-bar light streaks, city glass skyline bokeh, no logos, no people"),
    (("삼성전자", "반도체", "하이닉스", "웨이퍼"), (6, 24, 48), (20, 90, 130), (255, 214, 60),
     "chip", "semiconductor wafer fab, blue cleanroom light, abstract silicon circuit patterns, no people"),
    (("중동", "유가", "원유", "이란", "이스라엘"), (40, 20, 10), (140, 70, 30), (255, 180, 60),
     "desert", "middle east desert dusk over oil infrastructure, tense red sky reflected in distant glass skyline, no people"),
    (("사이드카",), (8, 16, 28), (20, 60, 50), (255, 80, 70),
     "candles", "Korean stock market circuit-breaker mood, red cascading candlesticks and volatility spike, trading screens bokeh, no people"),
    (("닛케이", "평균주가"), (8, 16, 28), (30, 50, 70), (255, 90, 70),
     "candles", "Tokyo Nikkei stock board glow, yen symbols and red-green candlesticks, rainy city skyline bokeh, no people"),
    (("관세", "무역", "수출", "항구", "컨테이너"), (20, 30, 50), (40, 70, 90), (255, 200, 60),
     "port", "cargo port at dusk, shipping containers and cranes silhouette, cinematic, no people"),
    (("댐", "호우", "침수", "태풍", "홍수", "방류", "황강"), (20, 30, 50), (40, 80, 100), (120, 220, 255),
     "water", "dramatic dam releasing water, stormy river, mist spray, cinematic weather, no people"),
    (("미소금융", "서민금융", "지원금", "보조금"), (20, 40, 50), (40, 110, 100), (255, 214, 60),
     "finance", "hopeful inclusive microfinance mood, warm neighborhood storefront bokeh and soft gold coin light, no people"),
    (("근저당", "부동산", "전세", "주택담보", "아파트"), (30, 28, 40), (80, 70, 90), (255, 214, 60),
     "house", "apartment complex silhouette at night, warm window light, mortgage document mood, no people"),
    (("육사", "사관학교", "통합 국군", "국군사관"), (20, 28, 24), (50, 70, 50), (220, 200, 120),
     "academy", "smart military academy campus at dawn, parade ground flagpoles silhouette, solemn, no people faces"),
    (("야구", "두산", "kt vs", "kt ", "홈런", "우천", "연장"), (10, 16, 40), (30, 50, 100), (255, 214, 60),
     "baseball", "baseball stadium at night under rain and floodlights, empty diamond, dramatic sports broadcast, no player faces"),
    (("메시", "축구", "월드컵", "국가대표", "은퇴"), (20, 30, 20), (40, 80, 40), (255, 214, 60),
     "football", "empty football stadium at sunset, spotlight on center circle, jersey and trophy silhouette, retirement farewell mood, no player faces"),
    (("증시", "주가", "코스피", "코스닥", "매수", "매도"), (8, 16, 28), (20, 60, 50), (255, 80, 70),
     "candles", "dramatic stock market candlestick charts glowing red and green, trading floor bokeh, no people"),
    (("대출", "세금"), (24, 36, 44), (50, 90, 100), (255, 214, 60),
     "finance", "personal finance paperwork and calculator mood, soft teal desk light, no people"),
    (("냉장고", "김치", "가전"), (30, 40, 50), (80, 100, 120), (180, 220, 255),
     "appliance", "modern kitchen appliance product mood, cool blue light, clean editorial, no people"),
]

_DEFAULT_SCENE = (
    (16, 22, 36), (50, 70, 110), (255, 214, 60),
    "abstract",
    "cinematic Korean newsroom abstract light leaks, high contrast broadcast graphics, no people",
)

# Text baked directly into the generated scene - no separate banner overlay.
_IMAGE_PROMPT_TMPL = (
    "Korean news thumbnail, 16:9, cinematic and unique to this topic. "
    "Background must visually match the article subject (not generic gradient): {scene}. "
    'Compose large bold Korean headline INTO the scene itself (not a separate UI card): "{main}". '
    'Smaller Korean subheadline integrated in the composition: "{sub}". '
    "High contrast, dramatic lighting, broadcast sports/tech/politics news style. "
    "No logos, no brand marks, no realistic celebrity face likeness, no long paragraphs. "
    "Do NOT add a flat translucent bottom bar overlay after generation."
)


def _log(msg: str) -> None:
    print(f"[post_images] {msg}", flush=True)


def resolve_scene(keyword: str, title: str = "", category: str = "") -> tuple[
    tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], str, str
]:
    """Return (top, mid, accent, motif_id, scene_en) matched to the topic.

    Prefer hits in the keyword, then longer keys, so distinctive topics
    (e.g. 중동, 미소금융) are not overridden by generic words in the title.
    """
    kw = (keyword or "").lower()
    title_l = (title or "").lower()
    cat = (category or "").lower()
    best_score: tuple[int, int, int] | None = None
    best_scene: tuple[
        tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], str, str
    ] | None = None

    for idx, (keys, top, mid, accent, motif, scene) in enumerate(TOPIC_SCENES):
        hit_key = ""
        in_kw = False
        for k in keys:
            kl = k.lower().strip()
            if not kl:
                continue
            if kl in kw:
                if len(kl) > len(hit_key) or not in_kw:
                    hit_key = kl
                    in_kw = True
            elif (
                not in_kw
                and kl not in _TITLE_BOILERPLATE_KEYS
                and (kl in title_l or kl in cat)
                and len(kl) > len(hit_key)
            ):
                hit_key = kl
        if not hit_key:
            continue
        score = (1 if in_kw else 0, len(hit_key), -idx)
        if best_score is None or score > best_score:
            best_score = score
            best_scene = (top, mid, accent, motif, scene)

    if best_scene is not None:
        return best_scene

    top, mid, accent, motif, scene = _DEFAULT_SCENE
    if category == "건강":
        return (14, 40, 36), (40, 110, 90), (120, 230, 220), "health", \
            "clean medical abstract soft green cyan light, no people"
    if category == "법률":
        return (20, 24, 36), (55, 70, 100), (120, 230, 220), "legal", \
            "courthouse pillars abstract solemn blue grey, no people"
    return top, mid, accent, motif, scene


def build_image_prompt(main: str, sub: str, category: str, keyword: str = "", title: str = "") -> str:
    """Full news-thumb prompt: text baked into the scene, no separate banner."""
    _t, _m, _a, _motif, scene = resolve_scene(keyword or main, title, category)
    return _IMAGE_PROMPT_TMPL.format(scene=scene, main=main, sub=sub)


def _pick_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _clamp_chars(text: str, target: int, hard_max: int | None = None) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    hard_max = hard_max or target + 4
    if len(text) <= hard_max:
        return text
    truncated = text[:target].rstrip()
    if " " in truncated:
        cut = truncated.rsplit(" ", 1)[0].strip(" '\"'“‘")
        if len(cut) >= max(4, target - 5):
            return cut
    return truncated


def make_thumb_texts(title: str, keyword: str = "", category: str = "") -> tuple[str, str]:
    """Main headline (8~14자) + sub headline (12~20자) for the image prompt."""
    title = (title or "").strip()
    keyword = (keyword or "").strip()
    head = title
    for sep in (", ", " - ", "…", "...", "？", "?"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
            break
    head = re.sub(r"\s*[\(（][^\)）]{0,24}[\)）]\s*$", "", head).strip()
    main_src = keyword or head or title
    main_src = re.sub(r"\s*[\(（][^\)）]{0,24}[\)）]\s*$", "", main_src).strip()
    main_src = re.sub(r"\s*무슨\s*일이길래\??\s*", " ", main_src).strip()

    stop = {
        "무슨", "일이길래", "정리", "확인", "대응법", "대응", "전략", "영향",
        "지갑에", "투자자", "방법", "있나", "개월", "결정", "후", "속", "3개월",
    }
    hangul_count = len(re.findall(r"[가-힣]", main_src))
    is_pipeline_title = "무슨 일이길래" in title
    if hangul_count <= 2 and not is_pipeline_title:
        preferred = ("국가대표", "은퇴", "구속", "급등", "급락", "판결", "리콜", "대피")
        clause = title.split(",", 1)[1] if "," in title else title
        clause = clause.split("…")[0].split("...")[0]
        extras = [t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", clause) if t not in stop]
        extras.sort(key=lambda t: (0 if t in preferred else 1))
        built = main_src
        for tok in extras:
            if tok in built:
                continue
            trial = f"{built} {tok}".strip()
            if len(trial) > 14:
                break
            built = trial
            if len(re.findall(r"[가-힣A-Za-z0-9]", built)) >= 11:
                break
        main_src = built
    main = _clamp_chars(main_src, target=11, hard_max=14)
    main = re.sub(r"\s*무슨(\s*일이길래)?\??\s*$", "", main).strip() or main_src[:11]

    remainder = title
    for token in (main_src, keyword, head):
        if token and token in remainder:
            remainder = remainder.replace(token, "", 1)
            break
    if "…" in remainder or "..." in remainder:
        tail = re.split(r"…|\.\.\.", remainder, maxsplit=1)[-1].strip()
        if len(re.findall(r"[가-힣]", tail)) >= 5:
            remainder = tail
    remainder = re.sub(r"[\(（][^\)）]{0,24}[\)）]", " ", remainder)
    remainder = re.sub(
        r"(무슨 일이길래\??|정리|확인·대응법|대응 전략|대응법|지갑에 영향|투자자 영향과)",
        " ",
        remainder,
    )
    remainder = re.sub(r"^[\s,，\-–—:：]+", "", remainder)
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", main):
        remainder = remainder.replace(tok, " ")
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,-·")
    if any(k in (keyword or "") or k in title for k in ("실적발표", "실적 발표", "어닝스")):
        fallback = "발표 일정과 실적 숫자 확인 포인트"
    else:
        fallback = {
            "금융": "지갑에 미치는 영향과 대응 포인트",
            "투자": "투자자 영향과 대응 전략 정리",
            "건강": "건강에 미치는 영향과 대응 수칙",
            "생활안전": "안전 영향과 대피 요령 정리",
            "법률": "법적 영향과 대응 절차 정리",
        }.get(category, "핵심 이슈와 대응 방법 정리")
    hangul_len = len(re.findall(r"[가-힣]", remainder))
    if hangul_len >= 6 and len(remainder) >= 8:
        sub = _clamp_chars(remainder, target=16, hard_max=20)
        # Avoid broken cutoffs like "...확인 방법과" / "...영향 있나?".
        if re.search(r"(과|와|은|는|이|가|을|를|의|에|로|으로|도|만|있나\??)$", sub):
            sub = _clamp_chars(fallback, target=16, hard_max=20)
    else:
        sub = _clamp_chars(fallback, target=16, hard_max=20)
    return main, sub


# ---- ASCII slug generation --------------------------------------------------

# Korean/ASCII entity → ascii slug token. Longer keys are tried first so
# compound phrases (e.g. "통합 국군") win over shorter overlapping ones.
ENTITY_SLUG_MAP: list[tuple[str, str]] = [
    ("삼성전자", "samsung-electronics"),
    ("반도체", "semiconductor"),
    ("하이닉스", "sk-hynix"),
    ("웨이퍼", "wafer"),
    ("키미", "kimi"),
    ("인공지능", "ai"),
    ("닛케이", "nikkei"),
    ("평균주가", "average-price"),
    ("증시", "stock-market"),
    ("주가", "stock-price"),
    ("코스피", "kospi"),
    ("코스닥", "kosdaq"),
    ("매수", "buy"),
    ("매도", "sell"),
    ("사이드카", "sidecar"),
    ("관세", "tariffs"),
    ("무역", "trade"),
    ("수출", "exports"),
    ("항구", "port"),
    ("컨테이너", "container"),
    ("중동", "middle-east"),
    ("유가", "oil-price"),
    ("원유", "crude-oil"),
    ("이란", "iran"),
    ("이스라엘", "israel"),
    ("댐", "dam"),
    ("호우", "heavy-rain"),
    ("침수", "flooding"),
    ("태풍", "typhoon"),
    ("홍수", "flood"),
    ("방류", "discharge"),
    ("황강", "hwanggang"),
    ("근저당", "mortgage-lien"),
    ("부동산", "real-estate"),
    ("전세", "jeonse"),
    ("주택담보", "mortgage"),
    ("주택", "housing"),
    ("아파트", "apartment"),
    ("미소금융", "microfinance"),
    ("서민금융", "microfinance"),
    ("지원금", "subsidy"),
    ("보조금", "grant"),
    ("통합 국군", "military-academy"),
    ("국군사관", "military-academy"),
    ("사관학교", "military-academy"),
    ("육사", "military-academy"),
    ("두산", "doosan"),
    ("홈런", "home-run"),
    ("연장", "extra-innings"),
    ("우천", "rain-delay"),
    ("야구", "baseball"),
    ("월드컵", "world-cup"),
    ("국가대표", "national-team"),
    ("아르헨티나", "argentina"),
    ("메시", "messi"),
    ("은퇴", "retirement"),
    ("축구", "football"),
    ("냉장고", "refrigerator"),
    ("김치", "kimchi"),
    ("가전", "appliance"),
    ("실적발표", "earnings"),
    ("어닝스", "earnings"),
    ("실적", "earnings"),
    ("알파벳", "alphabet"),
    ("구글", "google"),
    ("대출", "loan"),
    ("세금", "tax"),
    ("kt", "kt"),
]


def _find_entity_tokens(text: str, limit: int = 2) -> list[str]:
    text = text.lower()
    used_spans: list[tuple[int, int]] = []
    matches: list[tuple[int, str]] = []
    for key, token in sorted(ENTITY_SLUG_MAP, key=lambda kv: -len(kv[0])):
        start = 0
        while True:
            idx = text.find(key, start)
            if idx == -1:
                break
            span = (idx, idx + len(key))
            overlaps = any(idx < e and s < span[1] for s, e in used_spans)
            if not overlaps:
                matches.append((idx, token))
                used_spans.append(span)
            start = idx + len(key)
    matches.sort(key=lambda m: m[0])
    tokens: list[str] = []
    for _, tok in matches:
        if tok not in tokens:
            tokens.append(tok)
        if len(tokens) >= limit:
            break
    return tokens


def slugify(keyword: str, title: str = "") -> str:
    """ASCII-only slug for filenames/URLs (never Korean characters).

    Prefers known entity names translated/romanized to English
    (e.g. 메시+아르헨티나 -> messi-argentina, 육사 -> military-academy,
    두산 -> doosan). Keyword entities win over title-template words so a
    post about "구글 실적발표" does not become thumb-loan-tax.jpg just
    because the title asks about 대출·세금.
    """
    kw_tokens = _find_entity_tokens(keyword or "", limit=2)
    title_tokens = [
        t for t in _find_entity_tokens(title or "", limit=4)
        if t not in {"loan", "tax"} or not kw_tokens
    ]
    tokens = (kw_tokens + [t for t in title_tokens if t not in kw_tokens])[:2]
    if not tokens:
        latin = re.findall(r"[A-Za-z0-9]{2,}", keyword or "") or re.findall(r"[A-Za-z0-9]{2,}", title or "")
        tokens = [t.lower() for t in latin[:2]]
    if not tokens:
        combined = f"{keyword or ''} {title or ''}".strip()
        digest = hashlib.md5(combined.encode("utf-8")).hexdigest()[:8]
        tokens = [f"topic-{digest}"]
    slug = "-".join(tokens)
    slug = re.sub(r"[^0-9a-z-]+", "-", slug).strip("-")
    return (slug[:48] or "topic").lower()


# ---- content-matched Pillow motifs -------------------------------------------------

def _gradient_base(width: int, height: int, top: tuple[int, int, int], mid: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = (y / (height - 1)) ** 0.9
        r = int(top[0] * (1 - t) + mid[0] * t)
        g = int(top[1] * (1 - t) + mid[1] * t)
        b = int(top[2] * (1 - t) + mid[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _motif_candles(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    base_y = int(h * 0.55)
    x = 40
    while x < w - 40:
        bull = rng.random() > 0.45
        color = (80, 220, 120) if bull else (240, 70, 70)
        body_h = rng.randint(30, 140)
        wick = rng.randint(20, 60)
        cy = base_y - rng.randint(-40, 80)
        draw.line([(x + 6, cy - body_h - wick), (x + 6, cy + wick)], fill=color, width=2)
        draw.rectangle([x, cy - body_h, x + 12, cy], fill=color)
        x += rng.randint(22, 36)


def _motif_chip(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    cx, cy = int(w * 0.68), int(h * 0.38)
    for i in range(6):
        pad = 30 + i * 28
        draw.rounded_rectangle([cx - pad, cy - pad, cx + pad, cy + pad], radius=8, outline=accent, width=2)
    for _ in range(40):
        x1, y1 = rng.randint(cx - 120, cx + 120), rng.randint(cy - 120, cy + 120)
        x2, y2 = x1 + rng.choice([-1, 1]) * rng.randint(20, 80), y1 + rng.choice([-1, 0, 1]) * rng.randint(0, 40)
        draw.line([(x1, y1), (x2, y2)], fill=accent, width=1)


def _motif_ai(img: Image.Image, accent: tuple[int, int, int], rng: random.Random) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    nodes = [(rng.randint(w // 3, w - 40), rng.randint(40, int(h * 0.55))) for _ in range(14)]
    for i, (x1, y1) in enumerate(nodes):
        for x2, y2 in nodes[i + 1 :]:
            if rng.random() < 0.25:
                od.line([(x1, y1), (x2, y2)], fill=(*accent, 70), width=1)
    for x, y in nodes:
        r = rng.randint(4, 9)
        od.ellipse([x - r, y - r, x + r, y + r], fill=(*accent, 200))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _motif_port(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    for cx in (int(w * 0.55), int(w * 0.75), int(w * 0.9)):
        draw.line([(cx, 40), (cx, int(h * 0.55))], fill=accent, width=4)
        draw.line([(cx - 80, 80), (cx + 100, 80)], fill=accent, width=4)
        draw.line([(cx + 100, 80), (cx + 100, 140)], fill=accent, width=3)
    y = int(h * 0.42)
    x = int(w * 0.45)
    colors = [accent, (200, 80, 60), (60, 120, 180), (220, 160, 40)]
    for row in range(3):
        for col in range(6):
            c = colors[(row + col) % len(colors)]
            draw.rectangle([x + col * 55, y + row * 28, x + col * 55 + 50, y + row * 28 + 24], outline=c, width=2)


def _motif_water(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    draw.polygon([(int(w * 0.35), 60), (int(w * 0.7), 60), (int(w * 0.85), int(h * 0.55)), (int(w * 0.2), int(h * 0.55))], outline=accent, width=3)
    for i in range(8):
        x = int(w * 0.4) + i * 30
        draw.line([(x, int(h * 0.55)), (x + rng.randint(-10, 10), int(h * 0.75))], fill=accent, width=2)
    for y in range(int(h * 0.55), int(h * 0.75), 6):
        draw.arc([int(w * 0.2), y, int(w * 0.9), y + 20], 0, 180, fill=accent, width=1)


def _motif_desert(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    draw.ellipse([-100, int(h * 0.35), w + 100, h + 200], fill=(60, 35, 20))
    for i in range(5):
        x = int(w * 0.5) + i * 40
        draw.rectangle([x, int(h * 0.28), x + 18, int(h * 0.5)], fill=accent)
    draw.ellipse([int(w * 0.7), 50, int(w * 0.85), int(h * 0.2)], outline=accent, width=3)


def _motif_house(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    bx, by = int(w * 0.58), int(h * 0.28)
    draw.polygon([(bx, by + 40), (bx + 70, by), (bx + 140, by + 40)], fill=accent)
    draw.rectangle([bx + 20, by + 40, bx + 120, by + 130], outline=accent, width=3)
    draw.rectangle([bx + 55, by + 80, bx + 85, by + 130], fill=accent)
    draw.rectangle([bx + 35, by + 55, bx + 55, by + 75], outline=(255, 220, 120), width=2)


def _motif_stadium(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    cx, cy = int(w * 0.65), int(h * 0.38)
    draw.ellipse([cx - 200, cy - 90, cx + 200, cy + 90], outline=accent, width=4)
    draw.ellipse([cx - 120, cy - 50, cx + 120, cy + 50], outline=accent, width=2)
    for angle in range(0, 360, 20):
        rad = math.radians(angle)
        x = cx + int(220 * math.cos(rad))
        y = cy + int(100 * math.sin(rad))
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 255, 200))


def _motif_academy(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    base = int(h * 0.5)
    draw.rectangle([int(w * 0.45), 80, int(w * 0.9), base], outline=accent, width=3)
    for i in range(5):
        x = int(w * 0.5) + i * 50
        draw.rectangle([x, 110, x + 30, base - 10], outline=accent, width=2)
    draw.polygon([(int(w * 0.45), 80), (int(w * 0.675), 40), (int(w * 0.9), 80)], outline=accent, width=3)
    for x in (int(w * 0.5), int(w * 0.65), int(w * 0.8)):
        draw.line([(x, 40), (x, 100)], fill=accent, width=3)


def _motif_finance(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    for i, x in enumerate(range(int(w * 0.5), w - 40, 50)):
        r = 28 + (i % 3) * 6
        y = int(h * 0.35) + (i % 4) * 20
        draw.ellipse([x - r, y - r, x + r, y + r], outline=accent, width=3)


def _motif_earnings(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    """Rising bar chart + soft trend line for tech earnings posts."""
    base_y = int(h * 0.72)
    left = int(w * 0.52)
    bar_w = 38
    heights = [90, 140, 120, 190, 230, 210]
    for i, bh in enumerate(heights):
        x0 = left + i * (bar_w + 18)
        y0 = base_y - bh
        fill = tuple(min(255, c + (i % 2) * 25) for c in accent)
        draw.rounded_rectangle([x0, y0, x0 + bar_w, base_y], radius=6, fill=fill)
    pts = []
    for i, bh in enumerate(heights):
        x = left + i * (bar_w + 18) + bar_w // 2
        y = base_y - bh - 24 - rng.randint(0, 12)
        pts.append((x, y))
    if len(pts) >= 2:
        draw.line(pts, fill=(255, 255, 255), width=4)
        for x, y in pts:
            draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 255, 255))


def paint_topic_background(
    keyword: str,
    title: str,
    category: str,
    width: int = 1280,
    height: int = 720,
    seed: str | None = None,
) -> Image.Image:
    """Content-matched cinematic plate - different motifs per topic."""
    top, mid, accent, motif, _scene = resolve_scene(keyword, title, category)
    rng = random.Random(seed or f"{motif}:{keyword}:{title}")
    img = _gradient_base(width, height, top, mid)
    draw = ImageDraw.Draw(img)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(3):
        cx = rng.randint(width // 4, width * 3 // 4)
        cy = rng.randint(40, height // 2)
        rad = rng.randint(120, 260)
        od.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(*accent, rng.randint(25, 55)))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    if motif == "candles":
        _motif_candles(draw, width, height, accent, rng)
    elif motif == "chip":
        _motif_chip(draw, width, height, accent, rng)
    elif motif == "ai":
        img = _motif_ai(img, accent, rng)
        draw = ImageDraw.Draw(img)
    elif motif == "port":
        _motif_port(draw, width, height, accent, rng)
    elif motif == "water":
        _motif_water(draw, width, height, accent, rng)
    elif motif == "desert":
        _motif_desert(draw, width, height, accent, rng)
    elif motif == "house":
        _motif_house(draw, width, height, accent, rng)
    elif motif in {"baseball", "football"}:
        _motif_stadium(draw, width, height, accent, rng)
    elif motif == "academy":
        _motif_academy(draw, width, height, accent, rng)
    elif motif == "finance":
        _motif_finance(draw, width, height, accent, rng)
    elif motif == "earnings":
        _motif_earnings(draw, width, height, accent, rng)
    else:
        for i in range(5):
            x0 = rng.randint(-40, width // 2)
            od2 = ImageDraw.Draw(img)
            od2.polygon(
                [(x0, 0), (x0 + 70, 0), (x0 - 120, int(height * 0.6)), (x0 - 200, int(height * 0.6))],
                fill=tuple(min(255, c + 20) for c in mid),
            )

    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = ImageEnhance.Contrast(img).enhance(1.15)
    return img


def _find_source(directory: Path, stem: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = directory / f"{stem}{ext}"
        if path.exists():
            return path
    return None


def _draw_watermark(img: Image.Image) -> None:
    """Small translucent "@욘두두" label only - never a full-width banner."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = _pick_font(28)
    text = "@욘두두"
    pad_x, pad_y = 12, 6
    tw = int(draw.textlength(text, font=font))
    th = font.getmetrics()[0] + font.getmetrics()[1]
    w, h = img.size
    box = [w - tw - pad_x * 2 - 28, h - th - pad_y * 2 - 22, w - 20, h - 16]
    draw.rounded_rectangle(box, radius=8, fill=(0, 0, 0, 150))
    draw.text((box[0] + pad_x, box[1] + pad_y - 1), text, font=font, fill=(255, 255, 255, 235))


def render_headline_on_image(
    img: Image.Image,
    main: str,
    sub: str,
    accent: tuple[int, int, int],
) -> Image.Image:
    """Bake the Korean headline directly onto the scene using thick stroke
    outlines (no rectangle/banner underneath) so the background stays fully
    visible, matching a broadcast title-card look.
    """
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    main_size = int(h * 0.135)
    main_font = _pick_font(main_size)
    max_w = w - 88
    while draw.textlength(main, font=main_font) > max_w and main_size > 40:
        main_size -= 4
        main_font = _pick_font(main_size)
    main_stroke = max(4, main_size // 13)

    sub_size = max(26, int(main_size * 0.46))
    sub_font = _pick_font(sub_size)
    while draw.textlength(sub, font=sub_font) > max_w and sub_size > 24:
        sub_size -= 2
        sub_font = _pick_font(sub_size)
    sub_stroke = max(3, sub_size // 11)

    main_metrics = main_font.getmetrics()
    sub_metrics = sub_font.getmetrics()
    block_h = main_metrics[0] + main_metrics[1] + 12 + sub_metrics[0] + sub_metrics[1]
    main_x = 44
    main_y = h - block_h - 44
    sub_y = main_y + main_metrics[0] + main_metrics[1] + 12

    draw.text(
        (main_x, main_y), main, font=main_font,
        fill=(255, 255, 255, 255), stroke_width=main_stroke, stroke_fill=(0, 0, 0, 255),
    )
    draw.text(
        (main_x, sub_y), sub, font=sub_font,
        fill=(*accent, 255), stroke_width=sub_stroke, stroke_fill=(0, 0, 0, 255),
    )
    return img


def compose_pillow_headline(
    background: Image.Image,
    main: str,
    sub: str,
    accent: tuple[int, int, int],
    out_path: Path,
) -> Path:
    """Overlay baked-in Korean headline + required watermark onto a plate.
    No lower-third bar/gradient - the topic background stays fully visible.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = render_headline_on_image(background, main, sub, accent).convert("RGBA")
    _draw_watermark(img)
    img.convert("RGB").save(out_path, format="JPEG", quality=88, optimize=True)
    return out_path


def finalize_full_ai_thumbnail(src_path: Path, out_path: Path, width: int = 1280, height: int = 720) -> Path:
    """Take an AI-generated plate that already has the Korean headline baked
    in (per `build_image_prompt`) and just resize + add the watermark.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src_path).convert("RGB")
    im = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS)
    im = im.convert("RGBA")
    _draw_watermark(im)
    im.convert("RGB").save(out_path, format="JPEG", quality=90, optimize=True)
    return out_path


def has_ai_plate(slug: str) -> bool:
    return bool(
        _find_source(GENERATED_DIR, f"ai-thumb-{slug}")
        or _find_source(GENERATED_DIR, f"bg-{slug}")
    )


def generate_news_thumbnail(
    main: str,
    sub: str,
    category: str,
    out_path: Path,
    keyword: str = "",
    title: str = "",
    seed: str | None = None,
) -> Path:
    keyword = keyword or main
    title = title or main
    top, mid, accent, motif, scene = resolve_scene(keyword, title, category)
    slug = slugify(keyword, title)
    prompt = build_image_prompt(main, sub, category, keyword=keyword, title=title)
    _log(f"scene[{motif}]: {scene}")
    _log(f"prompt: {prompt}")

    full_ai = _find_source(GENERATED_DIR, f"ai-thumb-{slug}")
    if full_ai:
        _log(f"using full AI thumbnail ai-thumb-{slug}.* (headline baked in)")
        return finalize_full_ai_thumbnail(full_ai, out_path)

    bg_plate = _find_source(GENERATED_DIR, f"bg-{slug}")
    if bg_plate:
        _log(f"using AI background plate bg-{slug}.* + direct headline overlay")
        im = Image.open(bg_plate).convert("RGB")
        im = ImageOps.fit(im, (1280, 720), method=Image.Resampling.LANCZOS)
        return compose_pillow_headline(im, main, sub, accent, out_path)

    if REQUIRE_AI_THUMB and not ALLOW_PILLOW_THUMB:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        dest = str(GENERATED_DIR / f"ai-thumb-{slug}.png")
        _log("ERROR: production AI thumbnail plate missing - refusing Pillow fallback")
        _log(f"REQUIRED_SLUG={slug}")
        _log(f"REQUIRED_SAVE_PATH={dest}")
        _log(f"REQUIRED_MAIN={main}")
        _log(f"REQUIRED_SUB={sub}")
        _log("REQUIRED_IMAGE_PROMPT_BEGIN")
        _log(prompt)
        _log("REQUIRED_IMAGE_PROMPT_END")
        raise MissingAIThumbError(slug=slug, prompt=prompt, dest=dest, main=main, sub=sub)

    _log("no AI plate found - using varied Pillow fallback scene")
    im = paint_topic_background(keyword, title, category, seed=seed or f"{motif}:{slug}")
    return compose_pillow_headline(im, main, sub, accent, out_path)


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(Path.cwd()),
        check=check,
        text=True,
        capture_output=True,
    )


def _last_commit_sha_for(path: Path) -> str | None:
    res = _run_git(["log", "-n", "1", "--format=%H", "--", path.as_posix()], check=False)
    sha = res.stdout.strip()
    return sha or None


def commit_and_push_thumb(image_path: Path, main: str) -> str:
    rel = image_path.as_posix()
    _run_git(["add", "--", rel])
    status = _run_git(["status", "--porcelain", "--", "posts/images"], check=False)
    if not status.stdout.strip():
        return _run_git(["rev-parse", "HEAD"]).stdout.strip()

    _run_git(["commit", "-m", f"Add news thumbnail for {main}"])
    sha = _run_git(["rev-parse", "HEAD"]).stdout.strip()
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    push = _run_git(["push", "-u", "origin", branch], check=False)
    if push.returncode != 0:
        for delay in (4, 8, 16):
            time.sleep(delay)
            push = _run_git(["push", "-u", "origin", branch], check=False)
            if push.returncode == 0:
                break
        else:
            raise RuntimeError(f"git push failed: {push.stderr.strip()}")
    _log(f"pushed thumb {rel} @ {sha[:10]}")
    return sha


def jsdelivr_url(sha: str, filename: str) -> str:
    return JSDELIVR_TMPL.format(repo=REPO_SLUG, sha=sha, filename=filename)


def inject_thumb_html(html: str, image_url: str, main: str, replace_existing: bool = False) -> str:
    html = html or ""
    if replace_existing:
        html = re.sub(r'<p>\s*<img class="post-thumb"[^>]*>\s*</p>\s*', "", html, count=1, flags=re.I | re.S)
        html = re.sub(r'<div class="post-hero"[^>]*>.*?</div>\s*', "", html, count=1, flags=re.I | re.S)
        html = re.sub(r"^\s*<img\b[^>]*>\s*", "", html, count=1, flags=re.I)
    elif re.search(r'class="post-thumb"', html, flags=re.I):
        return html
    safe_alt = escape(main)
    safe_url = escape(image_url, quote=True)
    block = (
        f'<p><img class="post-thumb" src="{safe_url}" alt="{safe_alt}" '
        f'style="display:block;width:100%;max-width:100%;height:auto;'
        f'margin:0 0 1em 0;border:0;" /></p>\n'
    )
    return block + html


def content_has_image(html: str) -> bool:
    return bool(re.search(r"<img\b", html or "", flags=re.I))


def verify_watermark(image_path: Path) -> bool:
    if not image_path.exists() or image_path.stat().st_size < 8_000:
        return False
    with Image.open(image_path) as im:
        w, h = im.size
        sample = im.crop((w - 180, h - 70, w - 20, h - 16)).convert("L")
        extrema = sample.getextrema()
        return (extrema[1] - extrema[0]) > 20


def build_thumb_for_post(
    title: str,
    keyword: str,
    category: str,
    push: bool = True,
    force: bool = False,
) -> tuple[str, str, str]:
    """Build (or reuse) the ASCII-named thumbnail for a post.

    - If the thumbnail file already exists, it is kept as-is unless
      `force=True` is passed explicitly.
    - When AI thumbs are required, a previously saved Pillow-only JPG is
      NOT reused until `generated_images/ai-thumb-{slug}.*` exists.
    - Slugs in `PROTECTED_SLUGS` are never regenerated, even with
      `force=True`.
    """
    main, sub = make_thumb_texts(title, keyword=keyword, category=category)
    slug = slugify(keyword or main, title)
    filename = f"thumb-{slug}.jpg"
    out_path = IMAGE_DIR / filename
    ai_ready = has_ai_plate(slug)

    # Pillow-only leftovers must not block a proper AI upgrade.
    if (
        out_path.exists()
        and REQUIRE_AI_THUMB
        and not ALLOW_PILLOW_THUMB
        and not ai_ready
        and slug not in PROTECTED_SLUGS
    ):
        _log(f"existing {filename} has no AI plate - requiring GenerateImage upgrade")
        force = True

    if out_path.exists():
        if slug in PROTECTED_SLUGS:
            _log(f"protected thumbnail, keeping as-is: {filename}")
        elif not force:
            _log(f"thumbnail already exists, keeping current file: {filename}")
        else:
            out_path = None  # type: ignore[assignment]
        if out_path is not None:
            sha = _last_commit_sha_for(IMAGE_DIR / filename) or _run_git(["rev-parse", "HEAD"]).stdout.strip()
            return jsdelivr_url(sha, filename), main, sub
        out_path = IMAGE_DIR / filename

    generate_news_thumbnail(
        main, sub, category, out_path, keyword=keyword or main, title=title, seed=f"{category}:{slug}"
    )
    if not verify_watermark(out_path):
        raise RuntimeError("refusing to publish thumbnail without @욘두두 watermark")
    sha = commit_and_push_thumb(out_path, main) if push else _run_git(["rev-parse", "HEAD"]).stdout.strip()
    url = jsdelivr_url(sha, filename)
    _log(f"thumb ready: {url}")
    return url, main, sub
