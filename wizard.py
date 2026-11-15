"""The setup page: a small local website that fills in .env, so nobody has to edit it by hand.

The tray opens it on the first start (no DISCORD_TOKEN yet) and from its 设置 item. It covers
what the bot needs to work: the token, the servers she may stay in and, optionally, a chat key.
Everything else is still set in .env.

It listens on 127.0.0.1 only, on a random port, and every request must carry the one-time key
from the page's address. Secrets go one way: the page can send a token or a key, and is only
ever told whether one is set.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import threading
from pathlib import Path
from typing import Callable

import aiohttp
import discord
from aiohttp import web
from dotenv import dotenv_values

log = logging.getLogger("wizard")

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
PAGE_FILE = ROOT / "assets" / "wizard.html"
ICON_FILE = ROOT / "assets" / "priestess.png"

DEVELOPER_PORTAL = "https://discord.com/developers/applications"
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
# What the invite link asks for, the same boxes the README has you tick in the URL Generator.
INVITE_PERMISSIONS = discord.Permissions(
    view_channel=True, send_messages=True, embed_links=True, connect=True, speak=True
)
INVITE_SCOPES = ("bot", "applications.commands")
CHAT_KEYS = {"deepseek": "DEEPSEEK_API_KEY", "claude": "ANTHROPIC_API_KEY"}
SAVE_RESTART_DELAY = 1.0  # seconds, so the page gets its answer before the tray restarts


class WizardError(Exception):
    """Something the page should show as it is (the text is for the person setting up)."""


# ---- .env ----------------------------------------------------------------------


def read_env() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    return {key: (value or "").strip() for key, value in dotenv_values(ENV_FILE).items()}


def _clean(value: str, what: str) -> str:
    """A value that is safe to write after `KEY=`: one unquoted word."""
    value = value.strip()
    if re.search(r"[\s\"'#\\]", value):
        raise WizardError(f"{what}里有空格、引号或其他不该出现的字符，请重新复制一次。")
    return value


def write_env(changes: dict[str, str]) -> None:
    """Set these keys in .env, leaving every other line (and the comments) as it is.

    The first time, .env starts as a copy of .env.example, so it keeps the explanations.
    """
    source = ENV_FILE if ENV_FILE.is_file() else ENV_EXAMPLE
    text = ""
    if source.is_file():
        with open(source, encoding="utf-8", newline="") as f:  # newline="": keep CRLF or LF as found
            text = f.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    for key, value in changes.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[^\r\n]*", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda match: line, text)
        else:
            if text and not text.endswith("\n"):
                text += newline
            text += line + newline
    partial = ENV_FILE.with_name(".env.new")
    with open(partial, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(partial, ENV_FILE)


# ---- Discord -------------------------------------------------------------------


class Discord:
    """What the page needs from Discord, through a client that logs in but never connects.

    Logging in only checks the token over HTTP: she does not come online, and a copy of the bot
    that is already running is not disturbed.
    """

    def __init__(self) -> None:
        self.client: discord.Client | None = None
        self.token = ""
        self._tree: discord.app_commands.CommandTree | None = None

    async def login(self, token: str) -> None:
        client = discord.Client(intents=discord.Intents.none())
        try:
            await client.login(token)
        except discord.LoginFailure:
            await client.close()
            raise WizardError("Discord 不认识这个 Token。请在 Bot 页点 Reset Token，再复制一次。") from None
        except (aiohttp.ClientError, OSError, discord.HTTPException) as e:
            await client.close()
            raise WizardError(f"连不上 Discord：{e}") from None
        await self.close()
        self.client, self.token = client, token

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
        self.client, self.token, self._tree = None, "", None

    def _client(self) -> discord.Client:
        if self.client is None:
            raise WizardError("请先填好 Token。")
        return self.client

    async def info(self) -> dict:
        """The bot's name and picture, the two switches worth checking, and her invite link."""
        client = self._client()
        app = await client.application_info()
        user = client.user
        return {
            "name": user.name if user else app.name,
            "avatar": user.display_avatar.url if user else None,
            "public": app.bot_public,
            "message_content": app.flags.gateway_message_content or app.flags.gateway_message_content_limited,
            "invite_url": discord.utils.oauth_url(app.id, permissions=INVITE_PERMISSIONS, scopes=INVITE_SCOPES),
            "portal_url": f"{DEVELOPER_PORTAL}/{app.id}/bot",
        }

    async def guilds(self) -> list[dict]:
        """The servers she is in. IDs are strings: they are too long for a JavaScript number."""
        return [
            {"id": str(guild.id), "name": guild.name, "icon": guild.icon.url if guild.icon else None}
            async for guild in self._client().fetch_guilds(limit=200)
        ]

    async def enable_message_content(self) -> None:
        """Turn on Message Content Intent, the one portal switch a bot may change for itself."""
        app = await self._client().application_info()
        flags = app.flags
        flags.gateway_message_content_limited = True
        await app.edit(flags=flags)

    async def clear_guild_commands(self, guild_id: int) -> None:
        """Remove the slash commands synced to one server only (DEV_GUILD_ID).

        When the bot goes back to syncing globally, that server would otherwise show every
        command twice: its own copy and the global one.
        """
        if self._tree is None:  # an empty tree: syncing it to a server leaves that server with none
            self._tree = discord.app_commands.CommandTree(self._client())
        await self._tree.sync(guild=discord.Object(id=guild_id))


# ---- chat keys -----------------------------------------------------------------


async def check_deepseek(key: str) -> str:
    """Ask for the account balance (free). Returns a line to show, e.g. the balance."""
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(DEEPSEEK_BALANCE_URL, headers=headers) as response:
                if response.status == 401:
                    raise WizardError("DeepSeek 不认识这个密钥，请重新复制一次。")
                if response.status != 200:
                    raise WizardError(f"DeepSeek 返回了 {response.status}，请稍后再试。")
                data = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise WizardError(f"连不上 DeepSeek：{e or '超时'}") from None
    infos = data.get("balance_infos") or []
    if not infos:
        return "密钥有效。"
    info = max(infos, key=lambda i: float(i.get("total_balance") or 0))
    balance = f"余额 {info.get('total_balance')} {info.get('currency', '')}".strip()
    if not data.get("is_available", True):
        return f"密钥有效，但{balance}，不够调用：充值后才能聊天。"
    return f"密钥有效，{balance}。"


async def check_claude(key: str) -> str:
    """List one model (free): the request only succeeds with a working key."""
    import anthropic

    try:
        async with anthropic.AsyncAnthropic(api_key=key, max_retries=1, timeout=20.0) as client:
            await client.models.list(limit=1)
    except anthropic.AuthenticationError:
        raise WizardError("Claude 不认识这个密钥，请重新复制一次。") from None
    except anthropic.PermissionDeniedError:
        raise WizardError("这个密钥没有调用 API 的权限。") from None
    except anthropic.APIConnectionError as e:
        raise WizardError(f"连不上 Claude：{e}") from None
    except anthropic.APIStatusError as e:
        raise WizardError(f"Claude 返回了 {e.status_code}，请稍后再试。") from None
    return "密钥有效。"


CHAT_CHECKS = {"deepseek": check_deepseek, "claude": check_claude}


# ---- optional features ---------------------------------------------------------


def features() -> list[dict]:
    """Whether the optional parts are ready on this computer. Nothing here is needed to start."""
    import config
    from music.sources.youtube import JS_RUNTIMES

    js = next((name for name in JS_RUNTIMES if shutil.which(name)), None)
    return [
        {
            "name": "YouTube 链接",
            "ready": js is not None,
            "detail": f"找到了 {js}。" if js else "没有找到 Node.js，YouTube 可能放不了；其他来源不受影响。",
            "link": None if js else "https://nodejs.org/",
        },
        {
            "name": "游戏活动日历",
            "ready": Path(config.PLAYTIME_DIR).is_dir(),
            "detail": "找到了游时。" if Path(config.PLAYTIME_DIR).is_dir() else "没有找到游时 Playtime，/活动 和每晚提醒先关着。",
            "link": None,
        },
        {
            "name": "说话模式",
            "ready": Path(config.VOICE_CONFIG).is_file(),
            "detail": "找到了声音设置。" if Path(config.VOICE_CONFIG).is_file() else "没有声音设置（voices/voice.json），需要你自己的 GPT-SoVITS 模型。",
            "link": None,
        },
    ]  # fmt: skip


# ---- the page's server ---------------------------------------------------------


class Wizard:
    """The setup page, served from its own thread. `on_saved` runs after .env was written."""

    def __init__(self, on_saved: Callable[[], None], *, port: int = 0, key: str | None = None) -> None:
        self.on_saved = on_saved
        self.port = port
        self.key = key or secrets.token_urlsafe(24)
        self.url = ""
        self.discord = Discord()
        self.pending_chat: tuple[str, str] | None = None  # (provider, key), checked but not saved yet
        self.loop: asyncio.AbstractEventLoop | None = None
        self._error: BaseException | None = None

    # -- lifecycle --

    def start(self) -> str:
        """Start serving and return the page's address (with its key after the #)."""
        ready = threading.Event()

        def run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._serve())
            except BaseException as e:  # noqa: BLE001 - handed to start()
                self._error = e
                ready.set()
                return
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, name="setup-page", daemon=True).start()
        ready.wait(15)
        if self._error is not None:
            raise self._error
        if not self.url:
            raise RuntimeError("The setup page didn't start in time.")
        return self.url

    async def _serve(self) -> None:
        app = web.Application(middlewares=[self._guard])
        app.router.add_get("/", self.page)
        app.router.add_get("/icon.png", self.icon)
        app.router.add_get("/api/state", self.state)
        app.router.add_post("/api/token", self.set_token)
        app.router.add_post("/api/recheck", self.recheck)
        app.router.add_post("/api/intent", self.enable_intent)
        app.router.add_get("/api/guilds", self.list_guilds)
        app.router.add_post("/api/chat", self.set_chat)
        app.router.add_post("/api/save", self.save)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.port)
        await site.start()
        self.port = runner.addresses[0][1]
        # The key is after the #, which browsers keep to themselves (it is never sent or logged).
        self.url = f"http://127.0.0.1:{self.port}/#{self.key}"

    @web.middleware
    async def _guard(self, request: web.Request, handler):
        # Only this computer's own address: a web page elsewhere can't reach the API by pointing
        # a domain of its own at 127.0.0.1.
        if request.host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            raise web.HTTPForbidden()
        if request.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("X-Setup-Key", ""), self.key):
                raise web.HTTPForbidden()
            try:
                return await handler(request)
            except WizardError as e:
                return web.json_response({"error": str(e)}, status=400)
            except discord.HTTPException as e:
                log.warning("Discord refused a setup request: %s", e)
                return web.json_response({"error": f"Discord 没有同意：{e.text or e.status}"}, status=400)
        return await handler(request)

    # -- pages --

    async def page(self, request: web.Request) -> web.Response:
        headers = {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' https://cdn.discordapp.com; base-uri 'none'; form-action 'none'"
            ),
        }
        return web.Response(text=PAGE_FILE.read_text(encoding="utf-8"), content_type="text/html", headers=headers)

    async def icon(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(ICON_FILE)

    # -- API --

    async def state(self, request: web.Request) -> web.Response:
        env = read_env()
        token_error = None
        if self.discord.client is None and env.get("DISCORD_TOKEN"):
            try:  # show the bot that is already set up
                await self.discord.login(env["DISCORD_TOKEN"])
            except WizardError as e:
                token_error = str(e)
        return web.json_response(
            {
                "first_run": not env.get("DISCORD_TOKEN"),
                "bot": await self.discord.info() if self.discord.client else None,
                "token_error": token_error,
                "allowed": [g for g in env.get("ALLOWED_GUILD_IDS", "").replace(" ", "").split(",") if g],
                "chat": {
                    "saved": [name for name, key in CHAT_KEYS.items() if env.get(key)],
                    "pending": self.pending_chat[0] if self.pending_chat else None,
                },
                "features": features(),
                "portal": DEVELOPER_PORTAL,
            }
        )

    async def set_token(self, request: web.Request) -> web.Response:
        token = _clean(str((await request.json()).get("token", "")), "Token ")
        if not token:
            raise WizardError("请先粘贴 Token。")
        await self.discord.login(token)
        return web.json_response({"bot": await self.discord.info()})

    async def recheck(self, request: web.Request) -> web.Response:
        return web.json_response({"bot": await self.discord.info()})

    async def enable_intent(self, request: web.Request) -> web.Response:
        await self.discord.enable_message_content()
        return web.json_response({"bot": await self.discord.info()})

    async def list_guilds(self, request: web.Request) -> web.Response:
        return web.json_response({"guilds": await self.discord.guilds()})

    async def set_chat(self, request: web.Request) -> web.Response:
        data = await request.json()
        provider = str(data.get("provider", ""))
        if provider not in CHAT_KEYS:
            raise WizardError("请选择 DeepSeek 或 Claude。")
        key = _clean(str(data.get("key", "")), "密钥")
        if not key:
            raise WizardError("请先粘贴密钥。")
        detail = await CHAT_CHECKS[provider](key)
        self.pending_chat = (provider, key)
        return web.json_response({"detail": detail})

    async def save(self, request: web.Request) -> web.Response:
        if not self.discord.token:
            raise WizardError("请先填好 Token。")
        chosen = [str(g) for g in (await request.json()).get("guilds", [])]
        if not all(g.isdigit() for g in chosen):
            raise WizardError("服务器列表不对，请刷新页面再试。")
        env = read_env()
        changes = {"DISCORD_TOKEN": self.discord.token, "ALLOWED_GUILD_IDS": ",".join(chosen)}

        # One server: sync the slash commands to it, they appear at once. Several: sync globally,
        # so every server gets them (bot.py syncs to DEV_GUILD_ID only when it is set).
        old_dev = env.get("DEV_GUILD_ID", "")
        new_dev = chosen[0] if len(chosen) == 1 else ""
        changes["DEV_GUILD_ID"] = new_dev
        if old_dev.isdigit() and old_dev != new_dev:
            try:
                await self.discord.clear_guild_commands(int(old_dev))
            except discord.HTTPException as e:  # she may have left that server already
                log.info("Couldn't clear the commands of server %s: %s", old_dev, e)

        if self.pending_chat:
            provider, key = self.pending_chat
            changes[CHAT_KEYS[provider]] = key
            other = next(name for name in CHAT_KEYS if name != provider)
            current = env.get("CHAT_PROVIDER", "").lower() or (other if env.get(CHAT_KEYS[other]) else "")
            if current and current != provider:
                # The other provider would still win (or was chosen by hand), and its model name
                # means nothing to this one.
                changes["CHAT_PROVIDER"] = provider
                if env.get("CHAT_MODEL"):
                    changes["CHAT_MODEL"] = ""

        write_env(changes)
        log.info("Setup page saved %s", ", ".join(sorted(changes)))
        self.pending_chat = None
        if self.loop is not None:
            self.loop.call_later(SAVE_RESTART_DELAY, self.on_saved)
        return web.json_response({"ok": True})
