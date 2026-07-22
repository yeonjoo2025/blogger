"""Korean news-style (16:9) thumbnail generation for Blogger posts.

Pipeline (runs right before a post is published / patched):
  1. Derive short main (~8 chars) + sub (~14 chars) Korean lines.
  2. Pick a *topic-specific* visual scene from the keyword/title (not a
     fixed category template), then either:
       a) use a pre-rendered AI background at posts/images/bg-{slug}.jpg, or
       b) paint a content-matched cinematic scene with Pillow motifs.
  3. Composite a dark lower-third banner + white/yellow Korean type +
     required "@욘두두" watermark.
  4. Save JPG 1280px under posts/images/thumb-{slug}.jpg, git commit/push,
     build jsDelivr CDN URL, prepend <img class="post-thumb">.

Image-generation prompt brief (background plate, no on-image body copy):

  Cinematic Korean news broadcast B-roll, 16:9, {scene}, high contrast,
  darker lower third ready for caption overlay. No text, no letters,
  no logos, no watermarks, no realistic celebrity or recognizable person
  face, no long paragraphs.
"""

from __future__ import annotations

import math
import os
import random
import re
import subprocess
import time
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

IMAGE_DIR = Path("posts/images")
REPO_SLUG = os.environ.get("BLOGGER_GITHUB_REPO", "yeonjoo2025/blogger")
JSDELIVR_TMPL = "https://cdn.jsdelivr.net/gh/{repo}@{sha}/posts/images/{filename}"

# Topic motif → (palette top/mid/accent, English scene for AI / Pillow)
# More specific / distinctive keys are listed first. Matching prefers the
# keyword field, then title; longer key wins when multiple hit.
TOPIC_SCENES: list[tuple[tuple[str, ...], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], str, str]] = [
    (("키미", "kimi", "인공지능", " llm", "llm "), (8, 12, 40), (60, 40, 140), (120, 230, 255),
     "ai", "futuristic AI neural network glow, abstract chip circuits, magenta and cyan light, no people"),
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
     "academy", "military academy campus at dawn, parade ground flagpoles silhouette, solemn, no people faces"),
    (("야구", "두산", "kt vs", "kt ", "홈런", "우천"), (10, 16, 40), (30, 50, 100), (255, 214, 60),
     "baseball", "baseball stadium night under rain lights, empty diamond, dramatic sports broadcast, no player faces"),
    (("메시", "축구", "월드컵", "국가대표", "은퇴"), (20, 30, 20), (40, 80, 40), (255, 214, 60),
     "football", "empty football stadium at sunset, spotlight on center circle, retirement farewell mood, no player faces"),
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

_BG_PROMPT_TMPL = (
    "Cinematic Korean news broadcast B-roll background plate, 16:9 landscape, "
    "{scene}, high contrast, photogenic, darker empty lower third for caption overlay. "
    "No text, no letters, no captions, no logos, no watermarks, "
    "no realistic celebrity face, no recognizable person face, no long paragraphs."
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
            elif not in_kw and (kl in title_l or kl in cat) and len(kl) > len(hit_key):
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


def build_background_prompt(keyword: str, title: str = "", category: str = "") -> str:
    _t, _m, _a, _motif, scene = resolve_scene(keyword, title, category)
    return _BG_PROMPT_TMPL.format(scene=scene)


def build_image_prompt(main: str, sub: str, category: str, keyword: str = "", title: str = "") -> str:
    """Full news-thumb prompt (for logging / external AI). Korean lines included."""
    _t, _m, _a, _motif, scene = resolve_scene(keyword or main, title, category)
    return (
        f'Korean news thumbnail, 16:9, cinematic {scene}, high contrast, '
        f'dark translucent banner on lower third. '
        f'Large bold white Korean headline clearly readable: "{main}". '
        f'Smaller bold yellow Korean subheadline below it: "{sub}". '
        f'No logos, no watermarks, no realistic celebrity face, no long paragraphs.'
    )


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
    return text[:target].rstrip()


def make_thumb_texts(title: str, keyword: str = "", category: str = "") -> tuple[str, str]:
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
            if len(trial) > 12:
                break
            built = trial
            if len(re.findall(r"[가-힣A-Za-z0-9]", built)) >= 8:
                break
        main_src = built
    main = _clamp_chars(main_src, target=8, hard_max=12)
    main = re.sub(r"\s*무슨(\s*일이길래)?\??\s*$", "", main).strip() or main_src[:8]

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
    fallback = {
        "금융": "지갑 영향과 대응 포인트",
        "투자": "투자자 영향과 대응 전략",
        "건강": "건강 영향과 대응 수칙",
        "생활안전": "안전 영향과 대피 요령",
        "법률": "법적 영향과 대응 절차",
    }.get(category, "핵심 이슈와 대응 정리")
    hangul_len = len(re.findall(r"[가-힣]", remainder))
    if hangul_len >= 5 and len(remainder) >= 6:
        sub = _clamp_chars(remainder, target=14, hard_max=18)
    else:
        sub = _clamp_chars(fallback, target=14, hard_max=18)
    return main, sub


def slugify(keyword: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", (keyword or "").strip()).strip("-")
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
        draw.line([(x1, y1), (x2, y2)], fill=(*accent, 180) if False else accent, width=1)


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
    # Cranes
    for cx in (int(w * 0.55), int(w * 0.75), int(w * 0.9)):
        draw.line([(cx, 40), (cx, int(h * 0.55))], fill=accent, width=4)
        draw.line([(cx - 80, 80), (cx + 100, 80)], fill=accent, width=4)
        draw.line([(cx + 100, 80), (cx + 100, 140)], fill=accent, width=3)
    # Containers
    y = int(h * 0.42)
    x = int(w * 0.45)
    colors = [accent, (200, 80, 60), (60, 120, 180), (220, 160, 40)]
    for row in range(3):
        for col in range(6):
            c = colors[(row + col) % len(colors)]
            draw.rectangle([x + col * 55, y + row * 28, x + col * 55 + 50, y + row * 28 + 24], outline=c, width=2)


def _motif_water(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    # Dam wall
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
    # Flag poles
    for x in (int(w * 0.5), int(w * 0.65), int(w * 0.8)):
        draw.line([(x, 40), (x, 100)], fill=accent, width=3)


def _motif_finance(draw: ImageDraw.ImageDraw, w: int, h: int, accent: tuple[int, int, int], rng: random.Random) -> None:
    for i, x in enumerate(range(int(w * 0.5), w - 40, 50)):
        r = 28 + (i % 3) * 6
        y = int(h * 0.35) + (i % 4) * 20
        draw.ellipse([x - r, y - r, x + r, y + r], outline=accent, width=3)
        draw.text((x - 8, y - 12), "₩", fill=accent)  # may fallback if font missing - decorative


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

    # Soft vignette / light bloom unique per seed.
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
    else:
        # Abstract news bars unique per seed
        for i in range(5):
            x0 = rng.randint(-40, width // 2)
            od2 = ImageDraw.Draw(img)
            od2.polygon(
                [(x0, 0), (x0 + 70, 0), (x0 - 120, int(height * 0.6)), (x0 - 200, int(height * 0.6))],
                fill=tuple(min(255, c + 20) for c in mid),
            )

    # Slight blur + contrast for broadcast feel.
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = ImageEnhance.Contrast(img).enhance(1.15)
    return img


def load_ai_background(slug: str, width: int = 1280, height: int = 720) -> Image.Image | None:
    """Load a pre-generated AI plate from posts/images/bg-{slug}.* if present."""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = IMAGE_DIR / f"bg-{slug}{ext}"
        if path.exists():
            im = Image.open(path).convert("RGB")
            im = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS)
            # Darken lower third a bit so the banner type stays readable.
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rectangle([0, int(height * 0.55), width, height], fill=(0, 0, 0, 60))
            return Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    return None


def _draw_watermark(img: Image.Image) -> None:
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


def compose_news_thumbnail(
    background: Image.Image,
    main: str,
    sub: str,
    accent: tuple[int, int, int],
    out_path: Path,
) -> Path:
    """Overlay lower-third banner + Korean type + required watermark onto a plate."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = background.convert("RGBA")
    width, height = img.size
    draw = ImageDraw.Draw(img)

    banner_top = int(height * 0.62)
    draw.rectangle([0, banner_top, width, height], fill=(0, 0, 0, 185))
    draw.rectangle([0, banner_top, width, banner_top + 5], fill=(*accent, 230))

    main_size = 78
    main_font = _pick_font(main_size)
    while draw.textlength(main, font=main_font) > width - 80 and main_size > 44:
        main_size -= 4
        main_font = _pick_font(main_size)
    main_x, main_y = 40, banner_top + 28
    draw.text((main_x + 3, main_y + 3), main, font=main_font, fill=(0, 0, 0, 180))
    draw.text((main_x, main_y), main, font=main_font, fill=(255, 255, 255, 255))

    sub_size = 40
    sub_font = _pick_font(sub_size)
    while draw.textlength(sub, font=sub_font) > width - 80 and sub_size > 28:
        sub_size -= 2
        sub_font = _pick_font(sub_size)
    sub_y = main_y + main_font.getmetrics()[0] + main_font.getmetrics()[1] + 10
    draw.text((main_x + 2, sub_y + 2), sub, font=sub_font, fill=(0, 0, 0, 160))
    draw.text((main_x, sub_y), sub, font=sub_font, fill=(*accent, 255))

    _draw_watermark(img)
    rgb = img.convert("RGB")
    rgb.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_path


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
    slug = slugify(keyword)
    _log(f"scene[{motif}]: {scene}")
    _log(f"prompt: {build_image_prompt(main, sub, category, keyword=keyword, title=title)}")

    bg = load_ai_background(slug)
    if bg is None:
        bg = paint_topic_background(keyword, title, category, seed=seed or f"{motif}:{slug}")
    else:
        _log(f"using AI background plate bg-{slug}.*")

    return compose_news_thumbnail(bg, main, sub, accent, out_path)


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(Path.cwd()),
        check=check,
        text=True,
        capture_output=True,
    )


def commit_and_push_thumb(image_path: Path, main: str) -> str:
    rel = image_path.as_posix()
    _run_git(["add", "--", rel])
    # Also add paired AI background plate if present.
    slug = image_path.stem.replace("thumb-", "", 1)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        bg = IMAGE_DIR / f"bg-{slug}{ext}"
        if bg.exists():
            _run_git(["add", "--", bg.as_posix()])
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
) -> tuple[str, str, str]:
    main, sub = make_thumb_texts(title, keyword=keyword, category=category)
    slug = slugify(keyword or main)
    filename = f"thumb-{slug}.jpg"
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
