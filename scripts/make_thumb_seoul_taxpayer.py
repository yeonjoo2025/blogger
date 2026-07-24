#!/usr/bin/env python3
"""Create 16:9 Korean info thumbnail with readable Hangul + watermark."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/workspace/posts/images/thumb-seoul-model-taxpayer.jpg")
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
BG = (15, 40, 64)


def main() -> None:
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    for i in range(0, h, 4):
        t = i / h
        r = int(15 + 20 * t)
        g = int(55 + 35 * t)
        b = int(95 + 45 * (1 - t))
        draw.rectangle([0, i, w, i + 4], fill=(r, g, b, 255))

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(0, 0), (760, 0), (620, h), (0, h)], fill=(8, 28, 48, 170))
    od.ellipse([820, -80, 1180, 280], fill=(45, 140, 170, 55))
    od.ellipse([980, 420, 1380, 820], fill=(210, 160, 70, 40))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    card = Image.new("RGBA", (320, 400), (245, 240, 230, 230))
    cd = ImageDraw.Draw(card)
    cd.rectangle([20, 30, 300, 70], fill=(30, 90, 130, 220))
    for y in range(100, 340, 28):
        cd.rectangle([30, y, 290, y + 12], fill=(180, 185, 190, 180))
    cd.rectangle([30, 350, 160, 370], fill=(200, 140, 50, 220))
    card = card.rotate(8, expand=True, fillcolor=(0, 0, 0, 0))
    img.paste(card, (850, 140), card)
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.truetype(FONT_BOLD, 86)
    sub_font = ImageFont.truetype(FONT_REG, 40)
    badge_font = ImageFont.truetype(FONT_BOLD, 28)
    mark_font = ImageFont.truetype(FONT_REG, 26)

    draw.rounded_rectangle([72, 120, 260, 168], radius=8, fill=(212, 160, 64))
    draw.text((92, 128), "서울시 2026", font=badge_font, fill=(30, 24, 12))
    draw.text((72, 210), "모범납세자 혜택", font=title_font, fill=(250, 248, 242))
    draw.text((74, 330), "은행·공연·의료 할인 한눈에", font=sub_font, fill=(210, 225, 235))
    draw.text((w - 160, h - 48), "@욘두두", font=mark_font, fill=(230, 230, 230))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, quality=92, optimize=True)
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
