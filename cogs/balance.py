"""/余额: the DeepSeek account balance, and how much was spent today / this week / this month / ever.

DeepSeek reports only the current balance (free to ask), so spending is worked out from it:
the balance is read every BALANCE_CHECK_MINUTES and each drop is added to that day's spending
(a rise is a top-up and isn't counted). It starts counting when this feature first runs, and
counts everything on the key, including use outside the bot. Token counts come from usage.py.
When the balance falls below BALANCE_WARN, the deployer (access.py) gets one DM.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import access
import config
from persona import line

log = logging.getLogger(__name__)

BALANCE_URL = "https://api.deepseek.com/user/balance"
LEDGER_FILE = Path(__file__).parent.parent / "data" / "balance.json"
CURRENCY_SIGNS = {"CNY": "¥", "USD": "$"}
BALANCE_COLOR = 0x8E7CC3


class BalanceError(Exception):
    pass


def money(amount: float, currency: str) -> str:
    return f"{CURRENCY_SIGNS.get(currency, currency + ' ')}{amount:,.2f}"


class Balance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        try:
            self.ledger: dict[str, Any] = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.ledger = {}

    async def cog_load(self) -> None:
        self.task = asyncio.create_task(self._background())

    async def cog_unload(self) -> None:
        if self.task:
            self.task.cancel()

    # ---- reading and recording ---------------------------------------------

    async def fetch(self) -> dict[str, Any]:
        """{"available": bool, "currency": str, "total": float, "topped_up": float, "granted": float}."""
        headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(BALANCE_URL, headers=headers) as resp:
                    if resp.status != 200:
                        raise BalanceError(f"DeepSeek 返回了 {resp.status}")
                    data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise BalanceError(f"连不上 DeepSeek（{e.__class__.__name__}）") from e
        infos = data.get("balance_infos") or []
        if not infos:
            raise BalanceError("DeepSeek 没有返回余额")
        # The account's own currency is the one with money in it (CNY for accounts paid in yuan).
        info = max(infos, key=lambda i: float(i.get("total_balance") or 0))
        return {
            "available": bool(data.get("is_available")),
            "currency": info.get("currency", "CNY"),
            "total": float(info.get("total_balance") or 0),
            "topped_up": float(info.get("topped_up_balance") or 0),
            "granted": float(info.get("granted_balance") or 0),
        }

    async def check(self) -> dict[str, Any]:
        """Read the balance and add any drop since the last reading to today's spending."""
        async with self.lock:
            now = await self.fetch()
            last = self.ledger.get("last")
            today = date.today().isoformat()
            if last and last.get("currency") == now["currency"]:
                change = round(now["total"] - last["total"], 4)
                if change < 0:
                    spend = self.ledger.setdefault("spend", {})
                    spend[today] = round(spend.get(today, 0) + -change, 4)
                elif change > 0:
                    self.ledger.setdefault("topups", []).append({"date": today, "amount": change})
            else:
                self.ledger.setdefault("since", datetime.now(timezone.utc).isoformat())
            self.ledger["last"] = {
                "currency": now["currency"], "total": now["total"], "at": datetime.now(timezone.utc).isoformat()
            }
            self._save()
            return now

    def _save(self) -> None:
        LEDGER_FILE.parent.mkdir(exist_ok=True)
        LEDGER_FILE.write_text(json.dumps(self.ledger, ensure_ascii=False), encoding="utf-8")

    def spent(self, since: date | None) -> float:
        start = since.isoformat() if since else ""
        return sum(v for k, v in self.ledger.get("spend", {}).items() if k >= start)

    async def _background(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                now = await self.check()
                await self._warn_if_low(now)
            except BalanceError as e:
                log.warning("Balance check failed: %s", e)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Balance check failed")
            await asyncio.sleep(max(5, config.BALANCE_CHECK_MINUTES) * 60)

    async def _warn_if_low(self, now: dict[str, Any]) -> None:
        """One DM to the deployer each time the balance drops below BALANCE_WARN."""
        low = config.BALANCE_WARN > 0 and now["total"] < config.BALANCE_WARN
        if not low:
            if self.ledger.pop("warned", None):
                self._save()
            return
        if self.ledger.get("warned"):
            return
        if not access.deployer_ids():
            return
        try:
            owner = await self.bot.fetch_user(min(access.deployer_ids()))
            await owner.send(line("balance_low", balance=money(now["total"], now["currency"])))
        except discord.HTTPException as e:
            log.warning("Couldn't DM the owner about the low balance: %s", e)
            return
        self.ledger["warned"] = True
        self._save()

    # ---- command -----------------------------------------------------------

    @app_commands.command(name="余额", description="DeepSeek 余额，以及今天 / 本周 / 本月 / 一直以来的消耗（仅部署者）")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction):
        if not access.is_deployer(interaction.user.id):
            await interaction.response.send_message(line("deployer_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            now = await self.check()
        except BalanceError as e:
            await interaction.followup.send(f"查不到余额：{e}", ephemeral=True)
            return
        cur = now["currency"]
        embed = discord.Embed(title="DeepSeek 余额", color=BALANCE_COLOR)
        embed.description = f"**{money(now['total'], cur)}**" + (
            f"（充值 {money(now['topped_up'], cur)} · 赠送 {money(now['granted'], cur)}）" if now["granted"] else ""
        )
        if not now["available"]:
            embed.description += "\n余额不足，聊天已经用不了了。"
        elif config.BALANCE_WARN > 0 and now["total"] < config.BALANCE_WARN:
            embed.description += f"\n已经低于提醒线 {money(config.BALANCE_WARN, cur)}，该充值了。"

        today = date.today()
        periods = [
            ("今天", today),
            ("本周", today - timedelta(days=today.weekday())),
            ("本月", today.replace(day=1)),
            ("一直以来", None),
        ]
        chat = self.bot.get_cog("Chat")
        rows = []
        for name, since in periods:
            row = f"**{name}** {money(self.spent(since), cur)}"
            if chat is not None:
                t = chat.usage.totals(since)  # type: ignore[attr-defined]
                row += f" · 消息 {t['messages']} · 搜索 {t['searches']} · {(t['input'] + t['cache_read'] + t['output']) / 10000:.1f} 万 tokens"
            rows.append(row)
        embed.add_field(name="消耗", value="\n".join(rows), inline=False)

        since = self.ledger.get("since")
        started = datetime.fromisoformat(since).astimezone().strftime("%Y-%m-%d %H:%M") if since else "现在"
        first_chat = chat.usage.first_day() if chat is not None else None  # type: ignore[attr-defined]
        embed.set_footer(
            text=f"金额从 {started} 开始记录，按余额的变化算（同一个密钥在别处用也算在内）；"
            f"消息和 tokens 从 {first_chat or '今天'} 开始记录。"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    if config.CHAT_PROVIDER != "deepseek" or not config.DEEPSEEK_API_KEY:
        return  # only DeepSeek has a balance endpoint
    await bot.add_cog(Balance(bot))
