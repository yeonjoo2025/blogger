"""Generate a card-news thumbnail image and host it on Blogger photo storage.

Blogger's account-wide write restriction blocks posts.insert(), but
posts.patch() still works, and the resumable photo-upload endpoint used by
the Blogger web editor also accepts our existing OAuth token. That lets us:

  1. Paint a square (1080x1080) card-news style thumbnail locally with
     Pillow - bold centered keyword, category badge, short CTA - no
     external image API key required (works unattended in cron).
  2. Upload it to blogger.googleusercontent.com via the resumable upload
     protocol the web editor itself uses.
  3. Inject the <img> at the top of the post HTML.

Used both by publish_trend.py (new posts) and by the one-shot backfill of
existing LIVE posts that currently have no image.
"""

from __future__ import annotations

import json
import random
import re
import time
from html import escape
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials

IMAGE_CACHE_DIR = Path("generated_images")
UPLOAD_START_URL = "https://docs.google.com/upload/blogger/photos/resumable"

# Soft, category-specific palettes. Avoid the generic purple/cream AI look.
CATEGORY_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "금융": ((18, 52, 68), (46, 120, 110), (212, 180, 110)),       # deep teal → gold
    "투자": ((22, 32, 58), (50, 90, 150), (230, 140, 70)),         # navy → amber
    "건강": ((30, 60, 50), (70, 140, 110), (200, 210, 160)),       # forest → sage
    "생활안전": ((60, 40, 30), (160, 90, 50), (230, 190, 120)),    # umber → sand
    "법률": ((28, 34, 48), (80, 90, 120), (190, 170, 140)),        # slate → warm grey
}
_DEFAULT_PALETTE = ((30, 40, 55), (70, 100, 130), (180, 190, 200))

_TOKEN_CLEAN_RE = re.compile(r"[\[\]()（）]")


def _log(msg: str) -> None:
    print(f"[post_images] {msg}", flush=True)


def _pick_font(size: int) -> ImageFont.ImageFont:
    """Prefer a CJK-capable system font; fall back to default bitmap font."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 3,
) -> list[str]:
    # Character-wise wrap works better for mixed Korean/English titles.
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines[:max_lines]


def _fit_title_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int = 110, min_size: int = 52) -> tuple[ImageFont.ImageFont, list[str]]:
    """Pick the largest font size that fits the keyword in <= 3 centered lines."""
    for size in range(max_size, min_size - 1, -4):
        font = _pick_font(size)
        lines = _wrap_text(draw, text, font, max_width=max_width, max_lines=3)
        if len("".join(lines)) < len(text):
            continue  # truncated
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if widest <= max_width and len(lines) <= 3:
            return font, lines
    font = _pick_font(min_size)
    return font, _wrap_text(draw, text, font, max_width=max_width, max_lines=3)


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    cx: int,
    y: int,
    fill: tuple[int, int, int],
    shadow: tuple[int, int, int] | None = (0, 0, 0),
) -> int:
    width = draw.textlength(text, font=font)
    x = int(cx - width / 2)
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)
    ascent, descent = font.getmetrics()
    return y + ascent + descent + 8


def generate_header_image(keyword: str, category: str, out_path: Path, seed: str | None = None) -> Path:
    """Paint a 1080x1080 card-news thumbnail for the given topic.

    Layout (one composition, SNS/card-news style):
      - square canvas
      - category badge near the top
      - huge centered keyword
      - one short supporting line
      - bottom CTA strip ("지금 확인하기")
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed or f"{category}:{keyword}")

    top, mid, accent = CATEGORY_PALETTES.get(category, _DEFAULT_PALETTE)
    size = 1080
    img = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)

    # Diagonal gradient background (atmosphere, not flat).
    for y in range(size):
        t = y / (size - 1)
        # Slight horizontal bias so it doesn't look like a boring vertical wipe.
        r = int(top[0] * (1 - t) + mid[0] * t)
        g = int(top[1] * (1 - t) + mid[1] * t)
        b = int(top[2] * (1 - t) + mid[2] * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Soft radial glow behind the title area.
    for i, alpha in ((420, 50), (300, 70), (180, 40)):
        odraw.ellipse(
            [size // 2 - i, size // 2 - i - 40, size // 2 + i, size // 2 + i - 40],
            fill=(*mid, alpha),
        )
    # Corner accent shapes for card-news energy.
    odraw.polygon([(0, 0), (280, 0), (0, 220)], fill=(*accent, 55))
    odraw.polygon([(size, size), (size - 320, size), (size, size - 240)], fill=(*accent, 70))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Outer frame (card edge).
    inset = 36
    draw.rounded_rectangle(
        [inset, inset, size - inset, size - inset],
        radius=28,
        outline=accent,
        width=6,
    )

    # Category badge (pill-like, but not a content card - just a label).
    badge_font = _pick_font(34)
    badge_text = f"{category} 이슈"
    badge_pad_x, badge_pad_y = 28, 14
    badge_w = int(draw.textlength(badge_text, font=badge_font)) + badge_pad_x * 2
    badge_h = 34 + badge_pad_y * 2
    badge_x = (size - badge_w) // 2
    badge_y = 120
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=badge_h // 2,
        fill=accent,
    )
    draw.text(
        (badge_x + badge_pad_x, badge_y + badge_pad_y - 2),
        badge_text,
        font=badge_font,
        fill=(20, 20, 20),
    )

    # Main keyword - large, centered.
    clean_kw = _TOKEN_CLEAN_RE.sub("", keyword).strip() or keyword
    title_font, lines = _fit_title_font(draw, clean_kw, max_width=size - 160)
    line_height = title_font.getmetrics()[0] + title_font.getmetrics()[1] + 10
    block_h = line_height * len(lines)
    y = size // 2 - block_h // 2 - 20
    for line in lines:
        y = _center_text(draw, line, title_font, size // 2, y, fill=(250, 248, 240))

    # Supporting one-liner under the keyword.
    sub_font = _pick_font(36)
    y += 18
    _center_text(
        draw,
        "무슨 일이길래? 영향·대응 정리",
        sub_font,
        size // 2,
        y,
        fill=(230, 225, 210),
        shadow=None,
    )

    # Bottom CTA strip (card-news staple).
    strip_h = 110
    draw.rectangle([inset + 8, size - inset - strip_h, size - inset - 8, size - inset - 8], fill=accent)
    cta_font = _pick_font(40)
    cta = "지금 바로 확인하기 →"
    cta_w = draw.textlength(cta, font=cta_font)
    draw.text(
        ((size - cta_w) / 2, size - inset - strip_h + 30),
        cta,
        font=cta_font,
        fill=(20, 20, 20),
    )

    # Tiny decorative dots (kept sparse so they don't fight the title).
    for _ in range(10):
        x = rng.randint(80, size - 80)
        yy = rng.randint(220, size - 220)
        # Keep dots away from the center title band.
        if abs(yy - size // 2) < 140:
            continue
        r = rng.randint(3, 6)
        draw.ellipse([x - r, yy - r, x + r, yy + r], fill=accent)

    img.save(out_path, format="PNG", optimize=True)
    return out_path


def upload_image_to_blogger(creds: Credentials, image_path: Path) -> str:
    """Upload a local image via Blogger's resumable photo upload endpoint.

    Returns a direct blogger.googleusercontent.com URL suitable for <img src>.
    """
    if not creds.valid:
        from google.auth.transport.requests import Request

        creds.refresh(Request())

    raw = image_path.read_bytes()
    filename = image_path.name
    content_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    session = requests.Session()
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            if not creds.token:
                from google.auth.transport.requests import Request

                creds.refresh(Request())

            start_headers = {
                "authorization": f"Bearer {creds.token}",
                "content-type": "application/json; charset=UTF-8",
                "x-goog-upload-command": "start",
                "x-goog-upload-header-content-length": str(len(raw)),
                "x-goog-upload-header-content-type": content_type,
                "x-goog-upload-protocol": "resumable",
            }
            payload = {
                "protocolVersion": "0.8",
                "createSessionRequest": {
                    "fields": [
                        {
                            "external": {
                                "name": "file",
                                "filename": filename,
                                "put": {},
                                "size": len(raw),
                            }
                        },
                        {
                            "inlined": {
                                "name": "title",
                                "content": filename,
                                "contentType": "text/plain",
                            }
                        },
                        {
                            "inlined": {
                                "name": "addtime",
                                "content": str(int(time.time() * 1000)),
                                "contentType": "text/plain",
                            }
                        },
                        {
                            "inlined": {
                                "name": "onepick_version",
                                "content": "v2",
                                "contentType": "text/plain",
                            }
                        },
                        {
                            "inlined": {
                                "name": "album_mode",
                                "content": "permanent",
                                "contentType": "text/plain",
                            }
                        },
                        {
                            "inlined": {
                                "name": "silo_id",
                                "content": "3",
                                "contentType": "text/plain",
                            }
                        },
                    ]
                },
            }
            start_resp = session.post(
                UPLOAD_START_URL,
                headers=start_headers,
                data=json.dumps(payload),
                params={"authuser": "0"},
                timeout=30,
            )
            if not start_resp.ok or "x-goog-upload-url" not in start_resp.headers:
                raise RuntimeError(
                    f"upload session start failed: HTTP {start_resp.status_code} {start_resp.text[:300]}"
                )
            upload_url = start_resp.headers["x-goog-upload-url"]

            put_headers = {
                "content-type": content_type,
                "x-goog-upload-command": "upload, finalize",
                "x-goog-upload-offset": "0",
            }
            put_resp = session.post(upload_url, headers=put_headers, data=raw, timeout=60)
            if not put_resp.ok:
                raise RuntimeError(
                    f"upload finalize failed: HTTP {put_resp.status_code} {put_resp.text[:300]}"
                )
            body = put_resp.json()
            image_url = (
                body["sessionStatus"]["additionalInfo"]
                ["uploader_service.GoogleRupioAdditionalInfo"]
                ["completionInfo"]["customerSpecificInfo"]["url"]
            )
            # Prefer full-resolution variant (s0).
            parts = image_url.rstrip("/").split("/")
            if parts:
                return "/".join(parts[:-1]) + "/s0/" + parts[-1]
            return image_url
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _log(f"upload attempt {attempt + 1} failed: {exc}")
            try:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1 + attempt)
    raise RuntimeError(f"blogger image upload failed after retries: {last_error}")


def inject_hero_image(html: str, image_url: str, alt: str, replace_existing: bool = False) -> str:
    """Prepend (or replace) a card-news thumbnail <img> at the top of the HTML."""
    if replace_existing:
        html = re.sub(
            r'<div class="post-hero"[^>]*>.*?</div>\s*',
            "",
            html or "",
            count=1,
            flags=re.I | re.S,
        )
        # Also drop a lone leading <img> left over from older inserts.
        html = re.sub(r"^\s*<img\b[^>]*>\s*", "", html or "", count=1, flags=re.I)
    elif re.search(r"<img\b", html or "", flags=re.I):
        return html
    safe_alt = escape(alt)
    safe_url = escape(image_url, quote=True)
    hero = (
        f'<div class="post-hero" style="margin:0 auto 1.5em auto;max-width:720px;text-align:center;">'
        f'<img src="{safe_url}" alt="{safe_alt}" '
        f'style="width:100%;max-width:720px;aspect-ratio:1/1;height:auto;display:block;margin:0 auto;border:0;" />'
        f"</div>\n"
    )
    return hero + (html or "")


def build_and_host_hero(
    creds: Credentials,
    keyword: str,
    category: str,
    cache_dir: Path | None = None,
) -> str:
    """Generate + upload a hero image; return the hosted URL."""
    cache_dir = cache_dir or IMAGE_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", keyword).strip("-")[:40] or "topic"
    out_path = cache_dir / f"{slug}.png"
    generate_header_image(keyword, category, out_path, seed=f"{category}:{keyword}")
    url = upload_image_to_blogger(creds, out_path)
    _log(f"hosted hero for '{keyword}': {url}")
    return url


def content_has_image(html: str) -> bool:
    return bool(re.search(r"<img\b", html or "", flags=re.I))
