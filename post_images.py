"""Korean news-style (16:9) thumbnail generation for Blogger posts.

Pipeline (runs right before a post is published / patched):
  1. Derive short main (~8 chars) + sub (~14 chars) Korean lines from the
     post title / keyword.
  2. Build a 16:9 cinematic news/sports-broadcast thumbnail (Pillow), with
     a dark translucent lower-third banner, large white headline, smaller
     yellow/cyan subheadline, and a required "@욘두두" watermark.
  3. Save as JPG (1280px wide) under posts/images/thumb-{slug}.jpg.
  4. git add/commit/push that file and build a jsDelivr CDN URL pinned to
     the resulting commit SHA.
  5. Prepend the required <p><img class="post-thumb" ...></p> block.

The design brief (used both as the Pillow composition guide and as the
prompt seed if an external image model is later wired in) is:

  Korean news thumbnail, 16:9, cinematic {atmosphere}, high contrast,
  dark translucent banner on lower third.
  Large bold white Korean headline clearly readable: "{main}".
  Smaller bold yellow Korean subheadline below it: "{sub}".
  No logos, no watermarks (except the required @욘두두 credit),
  no realistic celebrity face, no long paragraphs.
"""

from __future__ import annotations

import os
import random
import re
import subprocess
import time
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMAGE_DIR = Path("posts/images")
REPO_SLUG = os.environ.get("BLOGGER_GITHUB_REPO", "yeonjoo2025/blogger")
JSDELIVR_TMPL = "https://cdn.jsdelivr.net/gh/{repo}@{sha}/posts/images/{filename}"

# Category → (top, mid, accent, atmosphere phrase for the prompt)
CATEGORY_LOOK: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], str]] = {
    "금융": ((12, 28, 48), (30, 90, 110), (255, 214, 60), "finance desk city night bokeh charts glow"),
    "투자": ((10, 18, 40), (40, 70, 140), (255, 214, 60), "stock market candlestick neon trading floor mood"),
    "건강": ((14, 40, 36), (40, 110, 90), (120, 230, 220), "clean medical light abstract soft green cyan"),
    "생활안전": ((40, 24, 18), (120, 70, 40), (255, 214, 60), "stormy sky emergency glow dramatic weather"),
    "법률": ((20, 24, 36), (55, 70, 100), (120, 230, 220), "courthouse pillars abstract solemn blue grey"),
}
_DEFAULT_LOOK = ((16, 22, 36), (50, 70, 110), (255, 214, 60), "cinematic newsroom abstract high contrast")

_PROMPT_TMPL = (
    'Korean news thumbnail, 16:9, cinematic {atmosphere}, high contrast, '
    'dark translucent banner on lower third. '
    'Large bold white Korean headline clearly readable: "{main}". '
    'Smaller bold yellow Korean subheadline below it: "{sub}". '
    'No logos, no watermarks, no realistic celebrity face, no long paragraphs.'
)


def _log(msg: str) -> None:
    print(f"[post_images] {msg}", flush=True)


def build_image_prompt(main: str, sub: str, category: str) -> str:
    _top, _mid, _accent, atmosphere = CATEGORY_LOOK.get(category, _DEFAULT_LOOK)
    return _PROMPT_TMPL.format(atmosphere=atmosphere, main=main, sub=sub)


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
    """Return (main ~8 chars, sub ~14 chars) for the lower-third banner."""
    title = (title or "").strip()
    keyword = (keyword or "").strip()

    # Prefer the head of our pipeline titles ("키워드, 무슨 일이길래? ...").
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
    # Expand only ultra-short proper names (e.g. "메시") when the title is a
    # real news headline - never pad with our pipeline boilerplate.
    hangul_count = len(re.findall(r"[가-힣]", main_src))
    is_pipeline_title = "무슨 일이길래" in title
    if hangul_count <= 2 and not is_pipeline_title:
        preferred = ("국가대표", "은퇴", "구속", "급등", "급락", "판결", "리콜", "대피")
        clause = title
        if "," in title:
            clause = title.split(",", 1)[1]
        clause = clause.split("…")[0].split("...")[0]
        extras = re.findall(r"[가-힣A-Za-z0-9]{2,}", clause)
        extras = [t for t in extras if t not in stop]
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

    # Sub: meaningful remainder of the title after the keyword, else a
    # category cue. Strip pipeline boilerplate and dangling parentheses.
    remainder = title
    for token in (main_src, keyword, head):
        if token and token in remainder:
            remainder = remainder.replace(token, "", 1)
            break
    remainder = re.sub(r"[\(（][^\)）]{0,24}[\)）]", " ", remainder)
    remainder = re.sub(
        r"(무슨 일이길래\??|정리|확인·대응법|대응 전략|대응법|지갑에 영향|투자자 영향과)",
        " ",
        remainder,
    )
    remainder = re.sub(r"^[\s,，\-–—:：]+", "", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,-·")
    fallback = {
        "금융": "지갑 영향과 대응 포인트",
        "투자": "투자자 영향과 대응 전략",
        "건강": "건강 영향과 대응 수칙",
        "생활안전": "안전 영향과 대피 요령",
        "법률": "법적 영향과 대응 절차",
    }.get(category, "핵심 이슈와 대응 정리")
    # Prefer remainder only when it still looks like a real Korean phrase.
    # Drop tokens already used in the main headline so sub doesn't repeat it.
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", main):
        remainder = remainder.replace(tok, " ")
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,-·")
    hangul_len = len(re.findall(r"[가-힣]", remainder))
    if hangul_len >= 5 and len(remainder) >= 6:
        sub = _clamp_chars(remainder, target=14, hard_max=18)
    else:
        sub = _clamp_chars(fallback, target=14, hard_max=18)
    return main, sub


def slugify(keyword: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", (keyword or "").strip()).strip("-")
    return (slug[:48] or "topic").lower()


def _draw_cinematic_background(
    width: int,
    height: int,
    top: tuple[int, int, int],
    mid: tuple[int, int, int],
    accent: tuple[int, int, int],
    seed: str,
) -> Image.Image:
    """Abstract cinematic news backdrop - no faces, no logos, no body text."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / (height - 1)
        # Bias mid color into the upper/center "subject atmosphere" zone.
        ease = t ** 0.85
        r = int(top[0] * (1 - ease) + mid[0] * ease)
        g = int(top[1] * (1 - ease) + mid[1] * ease)
        b = int(top[2] * (1 - ease) + mid[2] * ease)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    # Soft light blooms (broadcast LED wall feel).
    for _ in range(4):
        cx = rng.randint(width // 5, width * 4 // 5)
        cy = rng.randint(height // 10, height // 2)
        rad = rng.randint(140, 280)
        odraw.ellipse(
            [cx - rad, cy - rad, cx + rad, cy + rad],
            fill=(*accent, rng.randint(18, 40)),
        )

    # Diagonal speed lines / lens streaks.
    for i in range(6):
        x0 = rng.randint(-100, width // 2)
        odraw.polygon(
            [
                (x0, 0),
                (x0 + rng.randint(40, 90), 0),
                (x0 - rng.randint(80, 180), height * 2 // 3),
                (x0 - rng.randint(160, 260), height * 2 // 3),
            ],
            fill=(*mid, 28),
        )

    # Abstract geometric blocks suggesting news graphics (not a UI card).
    for _ in range(3):
        x1 = rng.randint(width // 2, width - 40)
        y1 = rng.randint(40, height // 3)
        x2 = x1 + rng.randint(60, 180)
        y2 = y1 + rng.randint(40, 120)
        odraw.rectangle([x1, y1, x2, y2], outline=(*accent, 70), width=3)

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _draw_watermark(img: Image.Image) -> None:
    """Required credit mark: translucent chip + white '@욘두두' at lower-right."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = _pick_font(28)
    text = "@욘두두"
    pad_x, pad_y = 12, 6
    tw = int(draw.textlength(text, font=font))
    th = font.getmetrics()[0] + font.getmetrics()[1]
    w, h = img.size
    box = [
        w - tw - pad_x * 2 - 28,
        h - th - pad_y * 2 - 22,
        w - 20,
        h - 16,
    ]
    draw.rounded_rectangle(box, radius=8, fill=(0, 0, 0, 140))
    draw.text((box[0] + pad_x, box[1] + pad_y - 1), text, font=font, fill=(255, 255, 255, 230))


def generate_news_thumbnail(
    main: str,
    sub: str,
    category: str,
    out_path: Path,
    seed: str | None = None,
) -> Path:
    """Render a 16:9 Korean news thumbnail JPG (1280x720) to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    top, mid, accent, _atmosphere = CATEGORY_LOOK.get(category, _DEFAULT_LOOK)
    width, height = 1280, 720
    seed = seed or f"{category}:{main}:{sub}"

    img = _draw_cinematic_background(width, height, top, mid, accent, seed)
    draw = ImageDraw.Draw(img, "RGBA")

    # Dark translucent lower-third banner.
    banner_top = int(height * 0.62)
    draw.rectangle([0, banner_top, width, height], fill=(0, 0, 0, 175))
    # Thin accent rule above the banner (broadcast lower-third cue).
    draw.rectangle([0, banner_top, width, banner_top + 5], fill=(*accent, 220))

    # Main headline (large bold white).
    main_size = 78
    main_font = _pick_font(main_size)
    while draw.textlength(main, font=main_font) > width - 80 and main_size > 44:
        main_size -= 4
        main_font = _pick_font(main_size)
    main_x = 40
    main_y = banner_top + 28
    draw.text((main_x + 3, main_y + 3), main, font=main_font, fill=(0, 0, 0, 180))
    draw.text((main_x, main_y), main, font=main_font, fill=(255, 255, 255, 255))

    # Subheadline (smaller bold yellow or cyan).
    sub_color = accent  # yellow or cyan depending on category palette
    sub_size = 40
    sub_font = _pick_font(sub_size)
    while draw.textlength(sub, font=sub_font) > width - 80 and sub_size > 28:
        sub_size -= 2
        sub_font = _pick_font(sub_size)
    sub_y = main_y + main_font.getmetrics()[0] + main_font.getmetrics()[1] + 10
    draw.text((main_x + 2, sub_y + 2), sub, font=sub_font, fill=(0, 0, 0, 160))
    draw.text((main_x, sub_y), sub, font=sub_font, fill=(*sub_color, 255))

    # Required watermark - never publish without this.
    _draw_watermark(img)

    # Flatten alpha and save JPG.
    rgb = img.convert("RGB")
    rgb.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_path


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(Path.cwd()),
        check=check,
        text=True,
        capture_output=True,
    )


def commit_and_push_thumb(image_path: Path, main: str) -> str:
    """git add/commit/push the thumbnail; return the commit SHA."""
    rel = image_path.as_posix()
    _run_git(["add", "--", rel])
    # If nothing changed (identical rebuild), reuse HEAD.
    status = _run_git(["status", "--porcelain", "--", rel], check=False)
    if not status.stdout.strip():
        sha = _run_git(["rev-parse", "HEAD"]).stdout.strip()
        _log(f"thumb unchanged, reusing HEAD {sha[:10]}")
        return sha

    msg = f"Add news thumbnail for {main}"
    _run_git(["commit", "-m", msg])
    sha = _run_git(["rev-parse", "HEAD"]).stdout.strip()

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    push = _run_git(["push", "-u", "origin", branch], check=False)
    if push.returncode != 0:
        # Retry with short backoff (network flakes).
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
    """Insert (or replace) the required post-thumb block at the top of the body."""
    html = html or ""
    if replace_existing:
        html = re.sub(
            r'<p>\s*<img class="post-thumb"[^>]*>\s*</p>\s*',
            "",
            html,
            count=1,
            flags=re.I | re.S,
        )
        html = re.sub(
            r'<div class="post-hero"[^>]*>.*?</div>\s*',
            "",
            html,
            count=1,
            flags=re.I | re.S,
        )
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
    """Cheap presence check: file exists, is JPG, and is non-trivial size.

    The watermark itself is drawn in generate_news_thumbnail; refusing to
    publish when generation somehow skipped that step is enforced by always
    calling _draw_watermark before save, and by refusing empty/tiny files.
    """
    if not image_path.exists():
        return False
    if image_path.stat().st_size < 8_000:
        return False
    # Re-open and confirm bottom-right region is not uniform (chip drawn).
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
    """Full pipeline: texts → JPG → (commit/push) → CDN URL.

    Returns (cdn_url, main, sub).
    """
    main, sub = make_thumb_texts(title, keyword=keyword, category=category)
    prompt = build_image_prompt(main, sub, category)
    _log(f"prompt: {prompt}")

    slug = slugify(keyword or main)
    filename = f"thumb-{slug}.jpg"
    out_path = IMAGE_DIR / filename
    generate_news_thumbnail(main, sub, category, out_path, seed=f"{category}:{slug}")

    if not verify_watermark(out_path):
        raise RuntimeError(f"refusing to publish thumbnail without @욘두두 watermark: {out_path}")

    if push:
        sha = commit_and_push_thumb(out_path, main)
    else:
        sha = _run_git(["rev-parse", "HEAD"]).stdout.strip()

    url = jsdelivr_url(sha, filename)
    _log(f"thumb ready: {url}")
    return url, main, sub
