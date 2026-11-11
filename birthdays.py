"""Arknights operator birthdays, for the last line of the evening reminder posts.

Taken from the game's own operator files (the 【生日】 line of each handbook), via the public
ArknightsGameData mirror. A copy ships in assets/operator_birthdays.json; the calendar task
refreshes data/operator_birthdays.json once a week so new operators show up by themselves.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent
BUNDLED = ROOT / "assets" / "operator_birthdays.json"
FRESH = ROOT / "data" / "operator_birthdays.json"
SOURCE = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/{}.json"
REFRESH_EVERY = timedelta(days=7)
BIRTHDAY_RE = re.compile(r"【(?:生日|出生日|诞生日|出厂日|产品出厂日|出厂时间|制造日期)】\s*([^\n]+)")
DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")


def _load() -> dict:
    for path in (FRESH, BUNDLED):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def on(day: date) -> list[str]:
    """Operators whose birthday is on this day (month and day), in game order."""
    return _load().get("birthdays", {}).get(f"{day.month:02d}-{day.day:02d}", [])


def parse(handbook: dict, characters: dict) -> dict[str, list[str]]:
    """"MM-DD" -> operator names. Alternate versions (缄默德克萨斯) are folded into the original."""
    by_day: dict[str, list[str]] = {}
    for char_id, entry in handbook.get("handbookDict", {}).items():
        char = characters.get(char_id)
        if not char_id.startswith("char_") or not char or char.get("isNotObtainable"):
            continue
        text = "\n".join(
            s.get("storyText", "") for part in entry.get("storyTextAudio", []) for s in part.get("stories", [])
        )
        if (m := BIRTHDAY_RE.search(text)) and (d := DATE_RE.search(m.group(1))):
            by_day.setdefault(f"{int(d.group(1)):02d}-{int(d.group(2)):02d}", []).append(char["name"])
    for key, names in by_day.items():
        by_day[key] = [n for n in names if not any(o != n and o in n for o in names)]
    return dict(sorted(by_day.items()))


async def refresh_if_due() -> None:
    """Download the operator files again if the local copy is a week old. Errors are only logged."""
    try:
        updated = datetime.fromisoformat(json.loads(FRESH.read_text(encoding="utf-8"))["updated_at"])
        if datetime.now(timezone.utc) - updated < REFRESH_EVERY:
            return
    except (OSError, ValueError, KeyError):
        pass
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            tables = []
            for name in ("handbook_info_table", "character_table"):
                async with session.get(SOURCE.format(name)) as resp:
                    resp.raise_for_status()
                    tables.append(json.loads(await resp.read()))
        birthdays = parse(*tables)
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        log.warning("Couldn't refresh operator birthdays: %s", e)
        return
    if len(birthdays) < 100:  # the files changed shape: keep the old list
        log.warning("Operator birthday refresh found only %d days; keeping the old list", len(birthdays))
        return
    FRESH.parent.mkdir(exist_ok=True)
    FRESH.write_text(
        json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "birthdays": birthdays}, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Operator birthdays refreshed: %d operators", sum(map(len, birthdays.values())))
