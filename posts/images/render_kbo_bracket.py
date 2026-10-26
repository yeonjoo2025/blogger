#!/usr/bin/env python3
"""Render 2026 KBO postseason bracket with @욘두두 watermark."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("kbo-2026-postseason-bracket.jpg")
W, H = 1600, 1900
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

BG = (246, 243, 235)
INK = (27, 42, 58)
MUTED = (107, 114, 128)
LINE = (168, 158, 140)
CARD = (255, 255, 255)
DONE = (232, 227, 216)
LIVE_BG = (255, 247, 237)
LIVE = (194, 65, 12)
NAVY = (27, 58, 75)
GOLD = (180, 132, 58)
WHITE = (255, 255, 255)
OK = (47, 93, 80)


def fnt(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size=size, index=1 if bold else 0)


def tw(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(draw.textbbox((0, 0), text, font=font)[2])


def box(draw, xy, fill, outline, width=2, radius=16):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def team_box(draw, x, y, w, h, name, sub, *, state="wait"):
    fills = {
        "done": DONE,
        "live": LIVE_BG,
        "wait": CARD,
        "bye": CARD,
    }
    outlines = {
        "done": LINE,
        "live": LIVE,
        "wait": LINE,
        "bye": NAVY,
    }
    box(draw, (x, y, x + w, y + h), fills[state], outlines[state], width=3 if state == "live" else 2)
    name_f = fnt(28, True)
    sub_f = fnt(20)
    name_c = MUTED if state == "done" else LIVE if state == "live" else INK
    draw.text((x + 18, y + 14), name, font=name_f, fill=name_c)
    draw.text((x + 18, y + 52), sub, font=sub_f, fill=MUTED)
    return x + w, y + h // 2


def connector(draw, x1, y1, x2, y2):
    mid = (x1 + x2) // 2
    draw.line([(x1, y1), (mid, y1), (mid, y2), (x2, y2)], fill=LINE, width=3)


def main() -> None:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.rectangle((0, 0, W, 150), fill=NAVY)
    d.text((56, 28), "2026  KBO  포스트시즌", font=fnt(48, True), fill=WHITE)
    d.text((56, 94), "대진표  ·  남은 일정     10월 26일 기준  ·  우천 순연 반영", font=fnt(24), fill=(214, 211, 203))

    # columns: WC / 준PO / PO / KS
    col_w = 300
    gap = 70
    left = 50
    xs = [left + i * (col_w + gap) for i in range(4)]
    labels = ["와일드카드", "준플레이오프", "플레이오프", "한국시리즈"]
    for i, (x, lab) in enumerate(zip(xs, labels)):
        d.text((x, 178), lab, font=fnt(22, True), fill=NAVY)

    bh = 84

    # WC: 두산 / LG
    _, y_doosan = team_box(d, xs[0], 230, col_w, bh, "두산 베어스", "정규시즌 5위  ·  탈락", state="done")
    _, y_lg_wc = team_box(d, xs[0], 430, col_w, bh, "LG 트윈스", "정규시즌 4위  ·  4-1 승", state="done")
    d.text((xs[0] + 18, 330), "10.14  잠실  1차전으로 종료", font=fnt(18), fill=MUTED)

    # 준PO: LG vs KIA
    _, y_lg_po = team_box(d, xs[1], 330, col_w, bh, "LG 트윈스", "와일드카드 승자  ·  0승", state="done")
    _, y_kia_semi = team_box(d, xs[1], 620, col_w, bh, "KIA 타이거즈", "정규시즌 3위  ·  3-0 승", state="done")
    d.text((xs[1] + 18, 430), "10.17–20  ·  KIA 3연승", font=fnt(18), fill=MUTED)

    # PO: KIA vs 삼성
    _, y_kia_po = team_box(d, xs[2], 470, col_w, bh, "KIA 타이거즈", "준PO 승자  ·  오늘 원정", state="live")
    _, y_sam = team_box(d, xs[2], 860, col_w, bh, "삼성 라이온즈", "정규시즌 2위  ·  홈 1·2차전", state="live")
    d.text((xs[2] + 18, 570), "5전 3선승  ·  진행 중", font=fnt(18), fill=LIVE)

    # KS: PO winner vs KT
    _, y_ks_po = team_box(d, xs[3], 660, col_w, bh, "플레이오프 승자", "아직 정해지지 않음", state="wait")
    _, y_kt = team_box(d, xs[3], 980, col_w, bh, "KT 위즈", "정규시즌 1위  ·  직행", state="bye")
    d.text((xs[3] + 18, 760), "7전 4선승  ·  2-3-2", font=fnt(18), fill=NAVY)

    # connectors
    connector(d, xs[0] + col_w, y_doosan, xs[1], y_lg_po)
    connector(d, xs[0] + col_w, y_lg_wc, xs[1], y_lg_po)
    connector(d, xs[1] + col_w, y_lg_po, xs[2], y_kia_po)
    connector(d, xs[1] + col_w, y_kia_semi, xs[2], y_kia_po)
    connector(d, xs[2] + col_w, y_kia_po, xs[3], y_ks_po)
    connector(d, xs[2] + col_w, y_sam, xs[3], y_ks_po)
    connector(d, xs[3] + col_w // 2, y_kt, xs[3] + col_w // 2, y_ks_po + 42)

    # schedule panel
    pan_y = 1140
    box(d, (50, pan_y, W - 50, 1760), CARD, LINE, width=2, radius=20)
    d.text((78, pan_y + 24), "남은 일정", font=fnt(28, True), fill=NAVY)

    rows = [
        ("오늘", "플레이오프 1차전", "10.26 (월)  18:30", "대구 삼성라이온즈파크"),
        ("화", "플레이오프 2차전", "10.27 (화)  18:30", "대구 삼성라이온즈파크"),
        ("목·금", "플레이오프 3·4차전", "10.29–30  18:30", "광주 기아챔피언스필드"),
        ("일", "플레이오프 5차전", "필요하면 11.1", "대구  ·  3승 선착 시 없음"),
        ("월~", "한국시리즈 1차전~", "안내상 11.2  수원", "PO가 길어지면 밀릴 수 있음"),
    ]
    yy = pan_y + 88
    label_f = fnt(22, True)
    main_f = fnt(26, True)
    date_f = fnt(24)
    for tag, what, when, where in rows:
        box(d, (78, yy, 168, yy + 48), LIVE_BG if tag == "오늘" else DONE, LIVE if tag == "오늘" else LINE, radius=10)
        tw_tag = tw(d, tag, label_f)
        d.text((78 + (90 - tw_tag) // 2, yy + 10), tag, font=label_f, fill=LIVE if tag == "오늘" else INK)
        d.text((188, yy + 8), what, font=main_f, fill=INK)
        d.text((700, yy + 8), when, font=date_f, fill=INK)
        d.text((1100, yy + 8), where, font=fnt(22), fill=MUTED)
        yy += 68

    d.text(
        (56, 1800),
        "출처  KBO 공식 일정 · 보도자료     비가 오면 날짜가 밀립니다     yeondodo.blogspot.com",
        font=fnt(20),
        fill=MUTED,
    )
    mark = "@욘두두"
    mf = fnt(28, True)
    d.text((W - 56 - tw(d, mark, mf), 1796), mark, font=mf, fill=GOLD)

    im.save(OUT, "JPEG", quality=90, optimize=True)
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
