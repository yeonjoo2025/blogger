"""Generate a topical header image and host it on Blogger photo storage.

Blogger's account-wide write restriction blocks posts.insert(), but
posts.patch() still works, and the resumable photo-upload endpoint used by
the Blogger web editor also accepts our existing OAuth token. That lets us:

  1. Paint a category-themed header image locally with Pillow (no external
     image API key required - works unattended in the cron automation).
  2. Upload it to blogger.googleusercontent.com via the resumable upload
     protocol the web editor itself uses.
  3. Inject a full-bleed <img> at the top of the post HTML.

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


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = list(text)
    # Character-wise wrap works better for mixed Korean/English titles.
    lines: list[str] = []
    current = ""
    for ch in words:
        trial = current + ch
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines[:3]  # at most 3 lines in the hero


def generate_header_image(keyword: str, category: str, out_path: Path, seed: str | None = None) -> Path:
    """Paint a 1200x630 editorial header image for the given topic."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed or f"{category}:{keyword}")

    top, mid, accent = CATEGORY_PALETTES.get(category, _DEFAULT_PALETTE)
    width, height = 1200, 630
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)

    # Vertical gradient background.
    for y in range(height):
        t = y / (height - 1)
        # Ease toward mid color in the lower half.
        r = int(top[0] * (1 - t) + mid[0] * t)
        g = int(top[1] * (1 - t) + mid[1] * t)
        b = int(top[2] * (1 - t) + mid[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Soft diagonal accent bands for atmosphere (not flat single color).
    for i in range(5):
        offset = rng.randint(-80, 80) + i * 90
        alpha_band = tuple(min(255, c + 30) for c in mid)
        points = [
            (offset, 0),
            (offset + 220, 0),
            (offset - 80, height),
            (offset - 300, height),
        ]
        # Pillow can't draw translucent polygons on RGB easily without RGBA overlay.
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.polygon(points, fill=(*alpha_band, 35))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    # Accent arc / circle motif (real visual anchor, not a card).
    cx, cy = width - 220, height // 2
    for radius, width_px in ((260, 18), (180, 10), (110, 6)):
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.arc(bbox, start=rng.randint(20, 60), end=rng.randint(200, 320), fill=accent, width=width_px)

    # Small dotted constellation near the arc.
    for _ in range(18):
        x = cx + rng.randint(-200, 200)
        y = cy + rng.randint(-180, 180)
        r = rng.randint(2, 5)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=accent)

    # Category eyebrow + keyword title.
    eyebrow_font = _pick_font(28)
    title_font = _pick_font(64)
    sub_font = _pick_font(26)

    margin_x = 72
    y = 120
    eyebrow = f"{category} 이슈"
    draw.text((margin_x, y), eyebrow, font=eyebrow_font, fill=accent)
    y += 56

    clean_kw = _TOKEN_CLEAN_RE.sub("", keyword).strip()
    lines = _wrap_text(draw, clean_kw, title_font, max_width=width - margin_x - 280)
    for line in lines:
        # Soft shadow for readability on the gradient.
        draw.text((margin_x + 2, y + 2), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin_x, y), line, font=title_font, fill=(245, 245, 240))
        y += 72

    y += 12
    draw.text(
        (margin_x, y),
        "영향 · 확인 방법 · 대응 정리",
        font=sub_font,
        fill=(220, 220, 210),
    )

    # Thin bottom accent rule.
    draw.rectangle([0, height - 10, width, height], fill=accent)

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


def inject_hero_image(html: str, image_url: str, alt: str) -> str:
    """Prepend a full-bleed hero <img> if the HTML doesn't already have one."""
    if re.search(r"<img\b", html, flags=re.I):
        return html
    safe_alt = escape(alt)
    safe_url = escape(image_url, quote=True)
    hero = (
        f'<div class="post-hero" style="margin:0 0 1.5em 0;">'
        f'<img src="{safe_url}" alt="{safe_alt}" '
        f'style="width:100%;max-width:100%;height:auto;display:block;border:0;" />'
        f"</div>\n"
    )
    return hero + html


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
