"""Timeline pictures of game events, laid out like Playtime's calendar.

One picture per game: each row has the event's banner and name on the left, a bar from its
start to its end across the next couple of weeks (the banner shows through the bar), and the
end time with the time left on the right. Rows ending within 3 days are red, within 7 amber.
Drawn locally with Pillow from Playtime's cached banners; times are Beijing (server) time.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from gamecal import GameEvent

SINGLE_IMAGE_ROWS = 10  # up to this many rows in all fit one picture
SEGMENT_ROWS = 8  # otherwise each section is its own picture, cut into parts of this many rows

TZ = ZoneInfo("Asia/Shanghai")
TZ_LABEL = "北京时间"
DAYS_BEFORE, DAYS_AFTER = 3, 14  # the timeline spans today -3 .. +14 days

WIDTH = 1000
PAD = 28
LEFT_W = 330  # banner + name
RIGHT_W = 200  # end time + time left
ROW_H = 84
THUMB = (112, 63)
HEADER_H = 128
SECTION_H = 44
AXIS_H = 34
FOOTER_H = 46

BG = (243, 244, 238)
CARD = (255, 255, 255)
LINE = (228, 230, 222)
GRID = (238, 240, 233)
TEXT = (34, 38, 33)
MUTED = (124, 130, 120)
TODAY = (106, 148, 72)
RED = (204, 68, 56)
AMBER = (214, 150, 30)
CATEGORY_COLORS = {
    "event": (196, 214, 178),
    "gacha": (205, 196, 232),
    "banner": (205, 196, 232),
    "exchange": (236, 214, 176),
    "update": (190, 214, 228),
    "maintenance": (220, 220, 220),
    "reward": (236, 200, 200),
}
GAME_ACCENTS = {"arknights-cn": (71, 126, 159), "endfield-cn": (217, 162, 27)}

FONT_DIR = Path("C:/Windows/Fonts")
# Chinese fonts outside Windows (macOS, then common Linux Noto CJK installs).
OTHER_FONTS = (
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ("msyhbd.ttc", "simhei.ttf") if bold else ("msyh.ttc", "simhei.ttf")
    for path in [str(FONT_DIR / n) for n in names] + list(OTHER_FONTS):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


F_TITLE = _font(34, bold=True)
F_SUB = _font(19)
F_NAME = _font(19, bold=True)
F_SMALL = _font(16)
F_TINY = _font(14)
F_END = _font(20, bold=True)


def _cover(path: Path | None, size: tuple[int, int]) -> Image.Image | None:
    """The banner scaled and cropped to fill size (like CSS object-fit: cover)."""
    if not path:
        return None
    try:
        img = Image.open(path).convert("RGB")
    except OSError:
        return None
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), mask)
    return out


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, lines: int) -> list[str]:
    """Break text into at most `lines` lines that fit width; the last one gets … if cut."""
    out: list[str] = []
    rest = text
    while rest and len(out) < lines:
        n = len(rest)
        while n > 1 and draw.textlength(rest[:n], font=font) > width:
            n -= 1
        out.append(rest[:n])
        rest = rest[n:]
    if rest:
        out[-1] = _fit(draw, out[-1] + rest, font, width)
    return out


def _left_text(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    days, hours = divmod(hours, 24)
    if days >= 1:
        return f"剩 {days} 天 {hours} 小时" if days < 3 else f"剩 {days} 天"
    minutes = int(delta.total_seconds() // 60) % 60
    return f"剩 {hours} 小时 {minutes} 分" if hours else f"剩 {minutes} 分钟"


def render(
    game_name: str, game: str, sections: list[tuple[str, list[GameEvent]]], now: datetime, subtitle: str = ""
) -> bytes:
    """A PNG of the events in each (heading, events) section, with a shared timeline."""
    sections = [(h, evs) for h, evs in sections if evs]
    rows = sum(len(evs) for _, evs in sections)
    height = HEADER_H + AXIS_H + len(sections) * SECTION_H + max(rows, 1) * ROW_H + FOOTER_H + PAD
    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)
    local_now = now.astimezone(TZ)
    accent = GAME_ACCENTS.get(game, TODAY)

    # Header
    draw.rounded_rectangle((PAD, 30, PAD + 8, 30 + 40), 4, fill=accent)
    draw.text((PAD + 22, 24), game_name, font=F_TITLE, fill=TEXT)
    if subtitle:
        width = draw.textlength(game_name, font=F_TITLE)
        draw.text((PAD + 22 + width + 14, 40), subtitle, font=F_SUB, fill=accent)
    draw.text((PAD + 22, 76), f"{local_now.month}月{local_now.day}日 · {TZ_LABEL} {local_now:%H:%M}", font=F_SUB, fill=MUTED)

    card_top = HEADER_H
    draw.rounded_rectangle((PAD - 10, card_top - 6, WIDTH - PAD + 10, height - FOOTER_H), 14, fill=CARD)

    # Timeline geometry
    tl_left = PAD + LEFT_W
    tl_right = WIDTH - PAD - RIGHT_W - 12
    day0 = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=TZ) - timedelta(days=DAYS_BEFORE)
    span = timedelta(days=DAYS_BEFORE + DAYS_AFTER + 1)

    def x_of(dt: datetime) -> float:
        frac = (dt - day0) / span
        return tl_left + max(0.0, min(1.0, frac)) * (tl_right - tl_left)

    body_top = card_top + AXIS_H
    body_bottom = height - FOOTER_H - 8
    # Day grid and axis labels
    for d in range(DAYS_BEFORE + DAYS_AFTER + 2):
        day = day0 + timedelta(days=d)
        x = x_of(day)
        draw.line((x, body_top, x, body_bottom), fill=GRID, width=1)
        if d % 2 == DAYS_BEFORE % 2 and d < DAYS_BEFORE + DAYS_AFTER:
            label = f"{day.month}/{day.day}"
            draw.text((x + 3, card_top + 6), label, font=F_TINY, fill=MUTED)
    draw.text((PAD, card_top + 6), "活动 · 开放状态", font=F_TINY, fill=MUTED)
    draw.text((WIDTH - PAD - RIGHT_W + 18, card_top + 6), f"结束（{TZ_LABEL}）", font=F_TINY, fill=MUTED)
    draw.line((PAD, body_top, WIDTH - PAD, body_top), fill=LINE, width=1)

    y = body_top
    for heading, events in sections:
        draw.text((PAD + 4, y + 11), f"■ {heading} · {len(events)}", font=F_SMALL, fill=MUTED)
        y += SECTION_H
        for e in events:
            _row(img, draw, e, y, local_now, x_of, tl_left, tl_right, accent)
            y += ROW_H
    if not rows:
        draw.text((PAD + 4, y + 26), "这段时间什么都没有。", font=F_SUB, fill=MUTED)

    # "Today" line, drawn last so it sits above the bars
    tx = x_of(local_now)
    for yy in range(int(body_top), int(body_bottom), 9):
        draw.line((tx, yy, tx, yy + 5), fill=TODAY, width=2)
    draw.rounded_rectangle((tx - 18, body_top - 12, tx + 18, body_top + 10), 5, fill=TODAY)
    draw.text((tx, body_top - 1), "今天", font=F_TINY, fill=(255, 255, 255), anchor="mm")

    draw.text(
        (PAD, height - FOOTER_H + 12),
        "数据：游时 Playtime（官方公告 · PRTS）· 具体以游戏内公告为准",
        font=F_TINY, fill=MUTED,
    )
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _row(img, draw, e: GameEvent, y: int, now: datetime, x_of, tl_left, tl_right, accent) -> None:
    mid = y + ROW_H // 2
    left_in = e.end and e.end > now
    urgency = None
    if e.end and left_in:
        left = e.end - now
        urgency = RED if left <= timedelta(days=3) else AMBER if left <= timedelta(days=7) else None
    draw.line((PAD, y + ROW_H, WIDTH - PAD, y + ROW_H), fill=GRID, width=1)
    draw.rectangle((PAD - 10, y + 6, PAD - 6, y + ROW_H - 6), fill=urgency or accent)

    # Banner thumbnail, or a coloured tile naming the category
    tw, th = THUMB
    thumb = _cover(e.artwork, THUMB)
    tx, ty = PAD + 6, mid - th // 2
    if thumb:
        img.paste(_rounded(thumb, 8), (tx, ty), _rounded(thumb, 8))
    else:
        draw.rounded_rectangle((tx, ty, tx + tw, ty + th), 8, fill=CATEGORY_COLORS.get(e.category, LINE))
        label = e.category_name
        draw.text((tx + tw / 2, ty + th / 2), label, font=F_SMALL, fill=TEXT, anchor="mm")

    name_x = tx + tw + 14
    name_w = PAD + LEFT_W - name_x - 10
    title = _wrap(draw, e.title, F_NAME, name_w, 2)
    top = mid - (len(title) * 24 + 20) // 2
    for i, part in enumerate(title):
        draw.text((name_x, top + i * 24), part, font=F_NAME, fill=TEXT)
    state = "进行中" if e.start and e.start <= now else "未开始"
    draw.text((name_x, top + len(title) * 24 + 2), f"{e.category_name} · {state}", font=F_TINY, fill=MUTED)

    # Bar from start to end (open-ended to the right edge when the end isn't known)
    x1 = x_of(e.start) if e.start else tl_left
    x2 = x_of(e.end) if e.end else tl_right
    if x2 - x1 < 6:
        x2 = x1 + 6
    bar_h = 40
    by = mid - bar_h // 2
    bw = int(x2 - x1)
    bar = _cover(e.artwork, (bw, bar_h)) if e.artwork and bw > 20 else None
    if bar:
        veil = Image.new("RGB", bar.size, CATEGORY_COLORS.get(e.category, LINE))
        bar = Image.blend(bar, veil, 0.35)
    else:
        bar = Image.new("RGB", (bw, bar_h), CATEGORY_COLORS.get(e.category, LINE))
    bar_r = _rounded(bar, 7)
    img.paste(bar_r, (int(x1), by), bar_r)
    if not e.end:
        tag = {"version": "版本末 →", "cycles": "随卡池 →"}.get(e.end_rule, "待定 →")
        tw = draw.textlength(tag, font=F_TINY)
        draw.rounded_rectangle((x2 - 18 - tw, mid - 11, x2 - 4, mid + 11), 5, fill=(255, 255, 255))
        draw.text((x2 - 11, mid), tag, font=F_TINY, fill=TEXT, anchor="rm")
    elif x_of(e.end) >= tl_right - 1:  # ends after the right edge of the timeline
        draw.rounded_rectangle((x2 - 26, mid - 11, x2 - 4, mid + 11), 5, fill=(255, 255, 255))
        draw.text((x2 - 15, mid), "›", font=F_SMALL, fill=TEXT, anchor="mm")
    if e.start and e.end and bw > 120:
        dates = f"{e.start.astimezone(TZ):%m/%d} → {e.end.astimezone(TZ):%m/%d}"
        tw2 = draw.textlength(dates, font=F_TINY)
        draw.rounded_rectangle((x1 + 6, mid - 11, x1 + 16 + tw2, mid + 11), 5, fill=(255, 255, 255))
        draw.text((x1 + 11, mid), dates, font=F_TINY, fill=TEXT, anchor="lm")

    # End time and what's left
    rx = WIDTH - PAD - RIGHT_W + 18
    if e.end:
        end = e.end.astimezone(TZ)
        draw.text((rx, mid - 26), f"{end:%m/%d %H:%M}" + ("" if e.end_exact else " 预计"), font=F_END, fill=urgency or TEXT)
        sub = _left_text(e.end - now) if left_in else "已结束"
        if e.start and e.start > now:
            sub = f"{e.start.astimezone(TZ):%m/%d %H:%M} 开始"
        draw.text((rx, mid + 6), sub, font=F_SMALL, fill=urgency or MUTED)
    else:
        draw.text((rx, mid - 26), e.end_note, font=F_END, fill=MUTED)
        if e.start and e.start > now:
            draw.text((rx, mid + 6), f"{e.start.astimezone(TZ):%m/%d %H:%M} 开始", font=F_SMALL, fill=MUTED)
        elif e.end_detail:
            draw.text((rx, mid + 6), e.end_detail, font=F_SMALL, fill=MUTED)


def pictures(
    game_name: str, game: str, sections: list[tuple[str, list[GameEvent]]], now: datetime
) -> list[tuple[str | None, bytes]]:
    """(heading, PNG) pictures for one game: one picture when everything fits, otherwise one
    per section (heading set), long sections cut into numbered parts."""
    sections = [(h, evs) for h, evs in sections if evs]
    if sum(len(evs) for _, evs in sections) <= SINGLE_IMAGE_ROWS:
        return [(None, render(game_name, game, sections, now))] if sections else []
    out: list[tuple[str | None, bytes]] = []
    for heading, events in sections:
        parts = [events[i : i + SEGMENT_ROWS] for i in range(0, len(events), SEGMENT_ROWS)]
        for n, part in enumerate(parts, 1):
            label = heading + (f"（{n}/{len(parts)}）" if len(parts) > 1 else "")
            out.append((heading, render(game_name, game, [(heading, part)], now, subtitle=label)))
    return out
