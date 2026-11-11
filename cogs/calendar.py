"""Game event calendar: /活动, /同步活动, and posts in a reminder channel.

Data comes from Playtime (see gamecal.py), which is started only to sync and then closed.
Every day at CALENDAR_DIGEST_TIME each game gets: a short line from her with a small card of
what ends in the next few days (Discord timestamps, so everyone sees their own time), then
timeline pictures (calendar_image.py): one if it all fits, otherwise one each for "ending
soon", "starting tomorrow" and "still running". Long-running things with no end date are
named in one line instead; things that end with the current version (or after a few more
banners) but have no date yet are drawn, marked "本版本结束时". Last comes a word about operators whose birthday it is
(birthdays.py). There are also last-call alerts 24 hours and 1 hour before things end. All
text is pre-written and the pictures are drawn locally (no paid API calls). Sent posts are
recorded so restarts don't repeat them.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import birthdays
import calendar_image
import access
import config
import gamecal
from gamecal import CalendarError, GameEvent
from persona import line

log = logging.getLogger(__name__)

CHECK_EVERY = 10 * 60  # seconds between reminder checks
CATCH_UP = timedelta(hours=6)  # still send posts this late (the bot was off at the time)
RESYNC_GRACE = timedelta(hours=3)  # skip the startup sync if the data is this fresh
END_OFFSETS = (timedelta(hours=1), timedelta(hours=24))  # most urgent first
REMIND_CATEGORIES = {"event", "exchange", "gacha"}
SENT_FILE = Path(__file__).parent.parent / "data" / "calendar_sent.json"
CALENDAR_COLOR = 0x477E9F
CARD_BUDGET = 3500  # characters for the "ends soon" card (Discord allows 4096 in a description)
GAME_COLORS = {"arknights-cn": 0x477E9F, "endfield-cn": 0xD9A21B}
# What she calls each game in her opening line; other games use their full name.
GAME_NICKNAMES = {"arknights-cn": "罗德岛", "endfield-cn": "塔卫二"}
ENDING_SOON = timedelta(days=7)  # "快结束了" in the pictures (the red/amber rows)
SECTION_LINES = {"快结束了": "cal_seg_ending", "明天开始": "cal_seg_starting", "还在进行": "cal_seg_later"}

GAME_CHOICES = [
    app_commands.Choice(name="明日方舟", value="arknights-cn"),
    app_commands.Choice(name="明日方舟：终末地", value="endfield-cn"),
    app_commands.Choice(name="碧蓝航线", value="azurlane-cn"),
    app_commands.Choice(name="绝区零", value="zzz-cn"),
    app_commands.Choice(name="NIKKE", value="nikke-global"),
    app_commands.Choice(name="全部", value="all"),
]
VIEW_CHOICES = [
    app_commands.Choice(name="进行中", value="ongoing"),
    app_commands.Choice(name="7 天内截止", value="ending"),
    app_commands.Choice(name="即将开始", value="upcoming"),
]


def ts(dt: datetime, style: str) -> str:
    """Discord timestamp: every reader sees it in their own time zone."""
    return f"<t:{int(dt.timestamp())}:{style}>"


def quoted(title: str) -> str:
    """「title」, unless the title already starts with its own brackets."""
    return title if title.startswith("「") else f"「{title}」"


def times_valid(e: GameEvent) -> bool:
    return not (e.start and e.end and e.end < e.start)


def event_line(e: GameEvent, show: str) -> str:
    """Two lines: the title, then its start or end time ("show" is "start" or "end")."""
    label = f"**{discord.utils.escape_markdown(e.title)}**"
    if e.category != "event":
        label += f" · {e.category_name}"
    if not times_valid(e):
        return f"{label}\n　时间待核实"
    at, exact, verb = (e.start, e.start_exact, "开始") if show == "start" else (e.end, e.end_exact, "结束")
    if not at:
        return f"{label}\n　{verb}时间待定"
    return f"{label}\n　{verb} {ts(at, 'R')}（{ts(at, 'f')}）" + ("" if exact else "（预计）")


def _days_label(days: int) -> str:
    return "明天" if days == 1 else f"接下来 {days} 天"


def _date_range(first: datetime, days: int) -> str:
    last = first + timedelta(days=days - 1)
    if days == 1:
        return f"{first.month}月{first.day}日"
    if first.month == last.month:
        return f"{first.month}月{first.day}日–{last.day}日"
    return f"{first.month}月{first.day}日–{last.month}月{last.day}日"


def game_embed(game_name: str, title: str, events: list[GameEvent], show: str, color: int) -> discord.Embed:
    """One game's events as lines in the description, trimmed to fit."""
    lines, used = [], 0
    for i, e in enumerate(events):
        text = event_line(e, show)
        if used + len(text) + 40 > CARD_BUDGET:
            lines.append(f"……还有 {len(events) - i} 项，用 /活动 查看")
            break
        lines.append(text)
        used += len(text) + 1
    embed = discord.Embed(title=title, description="\n".join(lines), color=color)
    embed.set_author(name=game_name)
    return embed


def split_ongoing(ongoing: list[GameEvent], now: datetime) -> tuple[list[GameEvent], list[GameEvent], list[GameEvent]]:
    """(ending within a week, ending later, really open-ended), each in end order. Things whose
    end isn't dated yet but is known to come (with this version, after more banners) go last in
    "ending later": they're drawn in the pictures, not called long-running."""
    soon = [e for e in ongoing if e.end and e.end - now <= ENDING_SOON]
    later = [e for e in ongoing if e.end and e.end - now > ENDING_SOON]
    later += [e for e in ongoing if not e.end and e.end_rule == "version"]
    later += [e for e in ongoing if not e.end and e.end_rule == "cycles"]
    open_ended = [e for e in ongoing if not e.end and not e.end_rule]
    return soon, later, open_ended


def picture_post(content: str | None, pictures: list[tuple[str | None, bytes]], game: str) -> dict:
    return {
        "content": content,
        "images": [(f"{game}-{i}.png", png) for i, (_, png) in enumerate(pictures, 1)],
    }


def to_files(post: dict) -> dict:
    """Turn a post's PNG bytes into discord.Files (a File can only be sent once)."""
    images = post.pop("images", None)
    if images:
        post["files"] = [discord.File(io.BytesIO(png), filename=name) for name, png in images]
    return post


class Calendar(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sync_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self.task = asyncio.create_task(self._background())

    async def cog_unload(self) -> None:
        if self.task:
            self.task.cancel()

    # ---- syncing ---------------------------------------------------------

    def _synced_at(self) -> datetime | None:
        try:
            synced = gamecal.load()[1].get("synced_at")
        except CalendarError:
            return None
        return datetime.fromisoformat(synced) if synced else None

    async def sync(self) -> dict:
        async with self.sync_lock:
            return await gamecal.sync()

    async def _background(self) -> None:
        await self.bot.wait_until_ready()
        startup = True
        while True:
            try:
                await self._sync_if_due(startup)
                startup = False
                await birthdays.refresh_if_due()
                await self.check_reminders()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Calendar background check failed")
            await asyncio.sleep(CHECK_EVERY)

    async def _sync_if_due(self, startup: bool) -> None:
        synced = self._synced_at()
        age = datetime.now(timezone.utc) - synced if synced else None
        if startup:
            # Sync when the bot starts, unless it was restarted shortly after the last sync.
            due = age is None or age > RESYNC_GRACE
        else:
            hours = config.PLAYTIME_REFRESH_HOURS
            due = bool(hours) and (age is None or age > timedelta(hours=hours))
        if due and not self.sync_lock.locked():
            try:
                await self.sync()
            except CalendarError as e:
                log.warning("Playtime sync failed: %s", e)

    # ---- reminder channel ------------------------------------------------

    def _load_sent(self) -> dict[str, str]:
        try:
            return json.loads(SENT_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_sent(self, sent: dict[str, str]) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        sent = {k: v for k, v in sent.items() if v >= cutoff}
        SENT_FILE.parent.mkdir(exist_ok=True)
        SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")

    def due_alerts(self, events: list[GameEvent], sent: dict[str, str], now: datetime) -> list[tuple[str, str]]:
        """(key, line) for each last-call alert (24 h / 1 h before an exact end) not yet sent."""
        due: list[tuple[str, str]] = []
        for e in events:
            if e.game not in config.CALENDAR_GAMES or e.category not in REMIND_CATEGORIES or not times_valid(e):
                continue
            if not (e.end and e.end_exact and now < e.end):
                continue
            for offset in END_OFFSETS:
                key = f"{e.id}:end:{int(offset.total_seconds())}"
                if e.end - offset <= now and key not in sent and now - (e.end - offset) <= CATCH_UP:
                    kind = "cal_end_1h" if offset <= timedelta(hours=1) else (
                        "cal_exchange_24h" if e.category == "exchange" else "cal_end_24h"
                    )
                    due.append((key, f"[{e.game_name}] " + line(kind, title=quoted(e.title), when=ts(e.end, "R"))))
                    # Once the last-hour alert goes out, a late 24-hour one is pointless.
                    if offset == END_OFFSETS[0]:
                        for other in END_OFFSETS[1:]:
                            sent.setdefault(f"{e.id}:end:{int(other.total_seconds())}", now.isoformat())
                    break
        return due

    def daily_posts(self, events: list[GameEvent], now: datetime) -> list[dict]:
        """The evening posts, game by game: her opening line (plus the long-running things with no
        end date, and a small card of what ends in the next CALENDAR_END_DAYS days), then the
        timeline pictures, each section with a short line of its own when they're split.

        "Soon" starts at tomorrow 00:00, so an evening post never lists something that already
        ended earlier today, and each day is covered by the posts of the evenings before it.
        Something ending on day D shows up in the posts of the CALENDAR_END_DAYS days before D.
        Drawing the pictures takes a moment: call this in a thread from async code.
        """
        local = now.astimezone()
        tomorrow = datetime.combine(local.date() + timedelta(days=1), dtime(0, 0), tzinfo=local.tzinfo)
        start_days, end_days = max(1, config.CALENDAR_START_DAYS), max(1, config.CALENDAR_END_DAYS)
        start_label, end_label = _days_label(start_days), _days_label(end_days)

        posts: list[dict] = []
        for game in config.CALENDAR_GAMES:
            mine = [e for e in events if e.game == game]
            if not mine:
                continue
            name = mine[0].game_name
            ongoing = gamecal.select(mine, None, "ongoing", now)
            starts = sorted(
                (e for e in mine if e.start and tomorrow <= e.start < tomorrow + timedelta(days=start_days) and times_valid(e)),
                key=lambda e: e.start,  # type: ignore[arg-type, return-value]
            )
            ends = sorted(
                (e for e in mine if e.end and tomorrow <= e.end < tomorrow + timedelta(days=end_days) and times_valid(e)),
                key=lambda e: e.end,  # type: ignore[arg-type, return-value]
            )

            values = {"game": GAME_NICKNAMES.get(game, name), "start_days": start_label, "end_days": end_label,
                      "ends": len(ends), "starts": len(starts)}
            situation = (
                "ends_starts" if ends and starts else "ends" if ends else "starts" if starts
                else "quiet" if ongoing else "empty"
            )
            content = line(f"cal_game_{situation}", **values)
            if not posts:
                content = f"{line('cal_daily_greeting', date=f'{local.month}月{local.day}日')}\n\n{content}"
            soon, later, open_ended = split_ongoing(ongoing, now)
            if open_ended:
                content += "\n-# " + line("cal_longterm", names="、".join(e.title for e in open_ended))

            start_heading = "明天开始" if start_days == 1 else f"{start_label}开始"
            pictures = calendar_image.pictures(
                name, game, [("快结束了", soon), (start_heading, starts), ("还在进行", later)], now
            )
            first: dict = {"content": content}
            if ends:
                color = GAME_COLORS.get(game, CALENDAR_COLOR)
                first["embeds"] = [game_embed(name, f"{line('cal_daily_ends_title', days=end_label)} · "
                                                    f"{_date_range(tomorrow, end_days)}", ends, "end", color)]
            if pictures and pictures[0][0] is None:
                # Everything fits one picture: it goes with the opening line (below the card).
                if ends:
                    posts += [first, picture_post(None, pictures, game)]
                else:
                    posts.append({**first, **picture_post(content, pictures, game)})
                continue
            posts.append(first)
            for heading, png in pictures:
                caption = line(SECTION_LINES.get(heading or "", "cal_seg_starting"))
                posts.append(picture_post(caption, [(heading, png)], game))
        if names := birthdays.on(local.date()):
            # Her last word of the evening: today's operator birthdays.
            if "阿米娅" in names:
                others = [n for n in names if n != "阿米娅"]
                text = line("cal_birthday_amiya") + (line("cal_birthday_also", names="、".join(others)) if others else "")
            else:
                text = line("cal_birthday", names="、".join(names))
            posts.append({"content": text})
        return posts

    def _daily_due(self, sent: dict[str, str], now: datetime) -> str | None:
        """The daily key if today's post time has passed (within CATCH_UP) and it wasn't sent."""
        try:
            hour, minute = (int(x) for x in config.CALENDAR_DIGEST_TIME.split(":"))
        except ValueError:
            return None
        local = now.astimezone()
        at = datetime.combine(local.date(), dtime(hour, minute), tzinfo=local.tzinfo)
        key = f"daily:{local.date().isoformat()}"
        if at <= local <= at + CATCH_UP and key not in sent:
            return key
        return None

    def _reminder_channel(self):
        """CALENDAR_CHANNEL_ID's channel, only if it's in a server she may be in (ALLOWED_GUILD_IDS)."""
        channel = self.bot.get_channel(config.CALENDAR_CHANNEL_ID) if config.CALENDAR_CHANNEL_ID else None
        guild = getattr(channel, "guild", None)
        if channel is None or guild is None or not access.guild_allowed(guild.id):
            if channel is not None and not getattr(self, "_warned_channel", False):
                self._warned_channel = True  # once, not at every check
                log.warning("CALENDAR_CHANNEL_ID isn't in a server listed in ALLOWED_GUILD_IDS; no reminders sent")
            return None
        return channel

    async def check_reminders(self, now: datetime | None = None) -> None:
        channel = self._reminder_channel()
        if channel is None:
            return
        try:
            events, _ = gamecal.load()
        except CalendarError:
            return
        now = now or datetime.now(timezone.utc)
        sent = self._load_sent()
        posts: list[dict] = []

        if daily_key := self._daily_due(sent, now):
            posts += await asyncio.to_thread(self.daily_posts, events, now)
            sent[daily_key] = now.isoformat()

        if config.CALENDAR_ALERTS and (due := self.due_alerts(events, sent, now)):
            posts.append({"content": "\n".join([line("cal_reminder_intro"), *(f"- {text}" for _, text in due)])[:2000]})
            for key, _ in due:
                sent[key] = now.isoformat()

        await self.send_posts(channel, posts)
        self._save_sent(sent)

    @staticmethod
    async def send_posts(channel: discord.abc.Messageable, posts: list[dict]) -> None:
        role = config.CALENDAR_PING_ROLE_ID
        for i, post in enumerate(posts):
            if role and i == 0:  # @ the role once per batch, not on every post
                post["content"] = f"<@&{role}>\n{post.get('content') or ''}".strip()
                post["allowed_mentions"] = discord.AllowedMentions(roles=[discord.Object(role)])
            else:
                post["allowed_mentions"] = discord.AllowedMentions.none()
            await channel.send(**to_files(post))

    # ---- commands --------------------------------------------------------

    @app_commands.command(name="活动", description="查看游戏活动日历（数据来自游时）")
    @app_commands.describe(游戏="哪款游戏（默认：提醒设置里的游戏）", 范围="进行中 / 7 天内截止 / 即将开始")
    @app_commands.choices(游戏=GAME_CHOICES, 范围=VIEW_CHOICES)
    async def show(
        self,
        interaction: discord.Interaction,
        游戏: app_commands.Choice[str] | None = None,
        范围: app_commands.Choice[str] | None = None,
    ):
        view = 范围.value if 范围 else "ongoing"
        games = None if 游戏 and 游戏.value == "all" else {游戏.value} if 游戏 else set(config.CALENDAR_GAMES)
        try:
            events, meta = gamecal.load()
        except CalendarError as e:
            await interaction.response.send_message(line("cal_unavailable", error=e), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        now = datetime.now(timezone.utc)
        chosen = gamecal.select(events, games, view, now)
        posts = await asyncio.to_thread(self._view_posts, chosen, view, now)
        if not posts:
            await interaction.followup.send(line("cal_empty"))
            return
        if synced := meta.get("synced_at"):
            note = f"-# 数据由游时同步于 {ts(datetime.fromisoformat(synced), 'R')} · 图中是北京时间 · 具体以游戏内公告为准"
            posts[-1]["content"] = f"{posts[-1].get('content') or ''}\n{note}".strip()
        for post in posts:
            await interaction.followup.send(**to_files(post), allowed_mentions=discord.AllowedMentions.none())

    def _view_posts(self, chosen: list[GameEvent], view: str, now: datetime) -> list[dict]:
        """One post per game with its pictures (up to 10 per message) for /活动."""
        order = {g: i for i, g in enumerate(config.CALENDAR_GAMES)}
        by_game: dict[str, list[GameEvent]] = {}
        for e in chosen:
            by_game.setdefault(e.game, []).append(e)
        posts = []
        for game in sorted(by_game, key=lambda g: (order.get(g, len(order)), g)):
            items = by_game[game]
            name = items[0].game_name
            content = f"**{name}** · {line(f'cal_title_{view}')}"
            if view == "ongoing":
                soon, later, open_ended = split_ongoing(items, now)
                sections = [("快结束了", soon), ("还在进行", later)]
                if open_ended:
                    content += "\n-# " + line("cal_longterm", names="、".join(e.title for e in open_ended))
            else:
                sections = [("7 天内截止" if view == "ending" else "即将开始", items)]
            pictures = calendar_image.pictures(name, game, sections, now)
            for i in range(0, max(len(pictures), 1), 10):
                posts.append(picture_post(content if i == 0 else None, pictures[i : i + 10], game))
        return posts

    @app_commands.command(name="推送提醒", description="现在把今天的活动提醒再发一次到提醒频道（仅部署者）")
    @app_commands.guild_only()
    async def push(self, interaction: discord.Interaction):
        if not access.is_deployer(interaction.user.id):
            await interaction.response.send_message(line("deployer_only"), ephemeral=True)
            return
        channel = self._reminder_channel()
        if channel is None:
            await interaction.response.send_message("还没有设置提醒频道（CALENDAR_CHANNEL_ID）。", ephemeral=True)
            return
        try:
            events, _ = gamecal.load()
        except CalendarError as e:
            await interaction.response.send_message(line("cal_unavailable", error=e), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Doesn't touch the record of sent posts: tonight's scheduled post still goes out as usual.
        posts = await asyncio.to_thread(self.daily_posts, events, datetime.now(timezone.utc))
        await self.send_posts(channel, posts)
        await interaction.followup.send(line("cal_pushed", channel=channel.mention), ephemeral=True)  # type: ignore[union-attr]

    @app_commands.command(name="同步活动", description="让游时重新同步一次活动日历（仅部署者）")
    @app_commands.guild_only()
    async def refresh(self, interaction: discord.Interaction):
        if not access.is_deployer(interaction.user.id):
            await interaction.response.send_message(line("deployer_only"), ephemeral=True)
            return
        await interaction.response.send_message(line("cal_syncing"), ephemeral=True)
        try:
            export = await self.sync()
        except CalendarError as e:
            await interaction.edit_original_response(content=line("cal_sync_failed", error=e))
            return
        count = sum(len(v.get("events") or []) for v in export.get("versions") or [])
        await interaction.edit_original_response(
            content=line("cal_synced", count=count, seconds=export["bot_meta"]["seconds"])
        )


async def setup(bot: commands.Bot) -> None:
    if not Path(config.PLAYTIME_DIR, "app.py").is_file():
        log.warning("Playtime not found at %s; game calendar disabled.", config.PLAYTIME_DIR)
        return
    await bot.add_cog(Calendar(bot))
