"""Game event calendar from Playtime (游时), a friend's local calendar app.

Playtime normally runs in the background. Here it is started only for a sync: launch it
hidden on a free port, ask it to sync every game the same way its own web page does, export
the result to data/calendar.json, and shut it down. Everything else reads that file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

import config

log = logging.getLogger(__name__)

CACHE = Path(__file__).parent / "data" / "calendar.json"
STARTUP_TIMEOUT = 60
SYNC_TIMEOUT = 10 * 60
POLL_SECONDS = 5

GAME_NAMES = {
    "arknights-cn": "明日方舟",
    "endfield-cn": "明日方舟：终末地",
    "azurlane-cn": "碧蓝航线",
    "zzz-cn": "绝区零",
    "nikke-global": "NIKKE",
}
CATEGORY_NAMES = {
    "event": "活动",
    "exchange": "兑换商店",
    "gacha": "寻访",
    "banner": "寻访",
    "update": "更新",
    "maintenance": "维护",
    "reward": "奖励",
}


class CalendarError(Exception):
    pass


# ---- syncing -----------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def sync() -> dict[str, Any]:
    """Run Playtime once, sync all games, export to CACHE, stop it. Returns the export."""
    app_dir = Path(config.PLAYTIME_DIR)
    if not (app_dir / "app.py").is_file():
        raise CalendarError(f"找不到游时：{app_dir}")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(port), "--no-desktop"],
        cwd=app_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    started = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            await _wait_until_up(session, base, process)
            state = await _get(session, base + "/api/state")
            before = {g: (s or {}).get("last_attempt") for g, s in state["sync_by_game"].items()}

            # The same request Playtime's own "同步" button sends.
            async with session.post(
                base + "/api/sync",
                json={"game": "all"},
                headers={"X-Calendar-Token": state["csrf_token"]},
            ) as resp:
                if resp.status != 200:
                    raise CalendarError(f"游时拒绝了同步请求（HTTP {resp.status}）")

            sync_status = await _wait_for_sync(session, base, before)
            export = await _get(session, base + "/api/export?game=all")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    export["bot_meta"] = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "seconds": round(time.monotonic() - started),
        "sync_by_game": sync_status,
    }
    CACHE.parent.mkdir(exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)
    log.info("Playtime sync finished in %ss", export["bot_meta"]["seconds"])
    return export


async def _get(session: aiohttp.ClientSession, url: str) -> Any:
    async with session.get(url) as resp:
        if resp.status != 200:
            raise CalendarError(f"游时返回了 HTTP {resp.status}")
        return await resp.json(content_type=None)


async def _wait_until_up(session: aiohttp.ClientSession, base: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CalendarError("游时启动失败（进程已退出），请检查是否安装了 tzdata")
        try:
            await _get(session, base + "/api/health")
            return
        except (aiohttp.ClientError, CalendarError):
            await asyncio.sleep(1)
    raise CalendarError("游时启动超时")


async def _wait_for_sync(session: aiohttp.ClientSession, base: str, before: dict[str, Any]) -> dict[str, Any]:
    """Wait until every game has finished a sync attempt started after `before`."""
    deadline = time.monotonic() + SYNC_TIMEOUT
    while True:
        await asyncio.sleep(POLL_SECONDS)
        status = (await _get(session, base + "/api/state"))["sync_by_game"]
        pending = [
            game for game, s in status.items()
            if (s or {}).get("running") or (s or {}).get("last_attempt") == before.get(game)
            and (s or {}).get("mode") not in ("local-json",)  # local plugins have nothing to fetch
        ]
        if not pending:
            return status
        if time.monotonic() > deadline:
            log.warning("Playtime sync still running for %s; exporting what is there", pending)
            return status


# ---- reading -------------------------------------------------------------------


@dataclass
class GameEvent:
    id: str
    game: str
    title: str
    category: str
    version: str
    start: datetime | None
    start_exact: bool
    end: datetime | None
    end_exact: bool
    requirements: list[str]
    artwork: Path | None = None  # the official banner Playtime saved, if it found one
    # Why there's no end date yet, when the announcement does say what ends it:
    # "version" = when this version ends (the next version's date isn't announced yet),
    # "cycles" = after N special-recruitment banners (end_cycles); "" = really open-ended.
    end_rule: str = ""
    end_cycles: int = 0

    @property
    def end_note(self) -> str:
        """Short words for an end that isn't dated yet."""
        if self.end_rule == "version":
            return "本版本结束时"
        if self.end_rule == "cycles":
            return "随后续卡池结束"
        return "结束待定"

    @property
    def end_detail(self) -> str:
        if self.end_rule == "cycles" and self.end_cycles:
            return f"{self.end_cycles} 次特许寻访后"
        return "日期待公布" if self.end_rule else ""

    @property
    def game_name(self) -> str:
        return GAME_NAMES.get(self.game, self.game)

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES.get(self.category, self.category or "活动")


def _instant(point: dict[str, Any] | None) -> tuple[datetime | None, bool]:
    if not point or not point.get("at"):
        return None, False
    at = datetime.fromisoformat(point["at"].replace("Z", "+00:00"))
    return at, point.get("state") in ("exact", "confirmed", "manual")


VERSION_END_WORDS = ("版本更新维护前", "版本期间")
CYCLES_RE = re.compile(r"(\d+)\s*次「?特许寻访")


def _end_rule(point: dict[str, Any] | None) -> tuple[str, int]:
    """("version" | "cycles" | "", banner count) for an end Playtime couldn't date."""
    point = point or {}
    raw = point.get("raw") or ""
    m = CYCLES_RE.search(raw)
    if point.get("reference") == "recruitment_cycles" or m:
        return "cycles", int(m.group(1)) if m else 0
    if point.get("reference") == "next_maintenance_start" or any(w in raw for w in VERSION_END_WORDS):
        return "version", 0
    return "", 0


def _resolve_ends(events: list[GameEvent], next_maintenance: dict[tuple[str, str], datetime]) -> None:
    """Date what the other events make datable: a version-long event once the next version's
    maintenance is announced, and an "after N banners" one once the Nth banner is known."""
    for e in events:
        key = (e.game, e.version)
        if not e.end and e.end_rule == "version" and key in next_maintenance:
            e.end, e.end_exact, e.end_rule = next_maintenance[key], False, ""
    banners = sorted(
        (e for e in events if e.category == "gacha" and "特许寻访" in e.title and e.start),
        key=lambda e: e.start,  # type: ignore[arg-type, return-value]
    )
    for e in events:
        if e.end or e.end_rule != "cycles" or not e.end_cycles or not e.start:
            continue
        counted = [b for b in banners if b.game == e.game and b.start >= e.start - timedelta(hours=1)]  # type: ignore[operator]
        if len(counted) < e.end_cycles:
            continue
        last = counted[e.end_cycles - 1]
        if last.end:
            e.end, e.end_exact, e.end_rule = last.end, last.end_exact, ""
        elif last.end_rule == "version":
            e.end_rule = "version"  # the last banner it counts runs to the end of this version


def load() -> tuple[list[GameEvent], dict[str, Any]]:
    """Events from the last export, and its bot_meta (when it was synced)."""
    if not CACHE.is_file():
        raise CalendarError("还没有同步过活动日历")
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    artwork_dir = Path(config.PLAYTIME_DIR) / "data" / "artwork"
    events = []
    # When each version's next version starts (its maintenance), per game.
    starts_by_game: dict[str, list[tuple[datetime, str]]] = {}
    for version in data.get("versions") or []:
        at = (version.get("maintenance") or {}).get("start")
        if at and version.get("name"):
            starts_by_game.setdefault(version.get("game", ""), []).append(
                (datetime.fromisoformat(at.replace("Z", "+00:00")), version["name"]))
    next_maintenance: dict[tuple[str, str], datetime] = {}
    for game, starts in starts_by_game.items():
        starts.sort()
        for (_, name), (later, _) in zip(starts, starts[1:]):
            next_maintenance[(game, name)] = later
    for version in data.get("versions") or []:
        for e in version.get("events") or []:
            start, start_exact = _instant(e.get("start"))
            end, end_exact = _instant(e.get("end"))
            rule, cycles = _end_rule(e.get("end")) if not end else ("", 0)
            art = (e.get("artwork") or {}).get("key")
            art_path = artwork_dir / Path(art).name if art else None
            events.append(
                GameEvent(
                    id=e["id"],
                    game=version.get("game", ""),
                    title=e.get("title") or "?",
                    category=e.get("category") or "",
                    version=version.get("name") or "",
                    start=start,
                    start_exact=start_exact,
                    end=end,
                    end_exact=end_exact,
                    requirements=list(e.get("requirements") or []),
                    artwork=art_path if art_path and art_path.is_file() else None,
                    end_rule=rule,
                    end_cycles=cycles,
                )
            )
    _resolve_ends(events, next_maintenance)
    return events, data.get("bot_meta") or {}


def select(events: list[GameEvent], games: set[str] | None, view: str, now: datetime | None = None) -> list[GameEvent]:
    """view: ongoing | upcoming | ending (within 7 days)."""
    now = now or datetime.now(timezone.utc)
    chosen = [e for e in events if not games or e.game in games]
    if view == "upcoming":
        chosen = [e for e in chosen if e.start and now < e.start <= now + timedelta(days=14)]
        chosen.sort(key=lambda e: e.start)  # type: ignore[arg-type, return-value]
    elif view == "ending":
        chosen = [e for e in chosen if e.end and now < e.end <= now + timedelta(days=7)]
        chosen.sort(key=lambda e: e.end)  # type: ignore[arg-type, return-value]
    else:
        chosen = [e for e in chosen if e.start and e.start <= now and (not e.end or e.end > now)]
        chosen.sort(key=lambda e: (e.end is None, e.end or now))
    return chosen


def describe(events: list[GameEvent], meta: dict[str, Any], limit: int = 25) -> str:
    """Plain-text summary for the chat model, in the bot machine's local time."""
    def local(dt: datetime | None, exact: bool) -> str:
        if not dt:
            return "待定"
        return dt.astimezone().strftime("%m月%d日 %H:%M") + ("" if exact else "（预计）")

    def end_text(e: GameEvent) -> str:
        if e.end or not e.end_rule:
            return local(e.end, e.end_exact)
        return f"{e.end_note}（{e.end_detail}，不是长期活动）"

    lines = [
        f"- [{e.game_name}] {e.title}（{e.category_name}）：{local(e.start, e.start_exact)} → {end_text(e)}"
        for e in events[:limit]
    ]
    synced = meta.get("synced_at")
    footer = f"（数据同步于 {datetime.fromisoformat(synced).astimezone():%m月%d日 %H:%M}，时间为机器人所在地时间）" if synced else ""
    return ("\n".join(lines) or "没有符合条件的活动。") + ("\n" + footer if footer else "")
