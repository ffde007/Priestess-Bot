"""Run Priestess from the system tray (the hidden-icons area), with no console window.

Start it with `pythonw.exe tray.py`; the PRTS shortcut does this. Output goes to logs/bot.log.
Right-click the icon to open the log, restart or quit. PRTS.bat still runs the bot with a
console window, which is handy for debugging.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "bot.log"
ICON_FILE = ROOT / "assets" / "priestess.png"
ICO_FILE = ROOT / "assets" / "priestess.ico"
STARTUP_LINK = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "普瑞赛斯.lnk"
)
NETWORK_RETRY_SECONDS = 30

log = logging.getLogger("tray")


def message_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "普瑞赛斯", 0x40)  # MB_ICONINFORMATION


# ---- start with Windows ------------------------------------------------------
# A shortcut in the user's Startup folder: no admin rights, and turning it off deletes it.


def autostart_enabled() -> bool:
    return STARTUP_LINK.is_file()


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def set_autostart(enabled: bool) -> None:
    if not enabled:
        STARTUP_LINK.unlink(missing_ok=True)
        return
    make_shortcut(STARTUP_LINK)


def make_shortcut(link: Path) -> None:
    """A shortcut that runs tray.py with this folder's pythonw.exe and her icon."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = "; ".join(
        [
            f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(link)})",
            f"$s.TargetPath = {_ps_quote(pythonw)}",
            f"$s.Arguments = {_ps_quote(chr(34) + str(ROOT / 'tray.py') + chr(34))}",
            f"$s.WorkingDirectory = {_ps_quote(ROOT)}",
            f"$s.IconLocation = {_ps_quote(f'{ICO_FILE},0')}",
            "$s.Description = '普瑞赛斯'",
            "$s.Save()",
        ]
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def setup_output() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    output = LOG_DIR / "output.log"
    if output.is_file() and output.stat().st_size > 5_000_000:  # one old copy, checked at each start
        output.replace(output.with_name("output.log.1"))
    # pythonw has no console, so sys.stdout/stderr are None and any print would crash.
    sys.stdout = sys.stderr = open(output, "a", encoding="utf-8", buffering=1)
    import discord

    handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    discord.utils.setup_logging(handler=handler, level=logging.INFO)


class BotRunner:
    """The Discord bot on its own thread and event loop, so the tray owns the main thread."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot = None
        self.error: BaseException | None = None
        self.waiting_for_network = False
        self._stop: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, name="discord-bot", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._lifecycle())
        except BaseException as e:  # noqa: BLE001 - shown in the tray instead of a console
            self.error = e
            log.exception("Bot stopped with an error")
        finally:
            # Let anything still pending (players, the calendar task) finish cancelling.
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    async def _lifecycle(self) -> None:
        import aiohttp
        import discord

        import config
        from bot import MusicBot

        self._stop = asyncio.Event()
        log.info("Using ffmpeg at %s", config.ffmpeg_path())
        while True:
            self.bot = MusicBot()
            running = asyncio.create_task(self.bot.start(config.DISCORD_TOKEN))
            stop = asyncio.create_task(self._stop.wait())
            await asyncio.wait({running, stop}, return_when=asyncio.FIRST_COMPLETED)
            # Closing on this loop (not from the tray thread) lets close() run to the end:
            # cogs unload, players leave voice, a running Playtime sync is stopped.
            if not self.bot.is_closed():
                await self.bot.close()
            stop.cancel()
            if self._stop.is_set():
                # start() returns once the bot is closed; don't let a stuck one hold up quitting.
                if not (await asyncio.wait({running}, timeout=10))[0]:
                    running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                return

            error = running.exception()
            if not isinstance(error, (aiohttp.ClientError, OSError, discord.GatewayNotFound)):
                await running  # re-raises anything else (a wrong token, say) for the tray to show
                return
            # Right after Windows starts, the network is often not up yet: wait and try again.
            log.warning("Can't reach Discord (%s); retrying in %ss", error, NETWORK_RETRY_SECONDS)
            self.waiting_for_network = True
            try:
                await asyncio.wait_for(self._stop.wait(), NETWORK_RETRY_SECONDS)
                return  # quit while waiting
            except asyncio.TimeoutError:
                pass
            finally:
                self.waiting_for_network = False

    def stop(self, timeout: float = 20) -> None:
        if self.loop and self._stop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._stop.set)
        self.thread.join(timeout)

    @property
    def speech(self):
        """The talk-mode cog (cogs/speech.py), when the bot is up and the voice is set up."""
        return self.bot.get_cog("Speech") if self.bot is not None and self.bot.is_ready() else None

    def voice_status(self) -> str:
        speech = self.speech
        return speech.status_text() if speech else "不可用"

    def toggle_voice(self, notify) -> None:
        """Start or stop GPT-SoVITS on the bot's loop (like /语音模块), telling the tray how it went."""
        speech = self.speech
        if speech is None or self.loop is None:
            return

        async def run() -> None:
            from speech import SpeechError

            if speech.engine.state == "off":
                notify("我去把声音找回来……要等一会儿。")
                try:
                    await speech.start_module()
                except SpeechError as e:
                    notify(f"声音没能找回来：{e}")
                    return
                notify("我可以说话了。")
            else:
                if not await speech.stop_module():  # the status watcher says "休息了" otherwise
                    notify("语音模块关了（GPT-SoVITS 是在别处打开的，没有去关它）。")

        asyncio.run_coroutine_threadsafe(run(), self.loop)

    @property
    def status(self) -> str:
        if self.error is not None:
            return "出错了，请查看日志"
        if self.waiting_for_network:
            return f"连不上 Discord，{NETWORK_RETRY_SECONDS} 秒后重试……"
        if self.bot is not None and self.bot.is_closed():
            return "已停止"
        if self.bot is not None and self.bot.is_ready():
            return f"在线 · {self.bot.user}"
        return "正在连接 Discord……"


def run_tray(runner: BotRunner, mutex: int) -> None:
    import pystray
    from PIL import Image

    from persona import line

    def open_log(icon, item) -> None:
        os.startfile(LOG_FILE)

    def open_folder(icon, item) -> None:
        os.startfile(ROOT)

    def quit_app(icon, item) -> None:
        icon.title = "普瑞赛斯 · 正在退出……"
        runner.stop()
        icon.stop()

    def restart(icon, item) -> None:
        quit_app(icon, item)
        # Let the new copy claim the single-instance mutex.
        ctypes.windll.kernel32.CloseHandle(mutex)
        subprocess.Popen(
            [sys.executable, str(ROOT / "tray.py")],
            cwd=ROOT,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def toggle_voice(icon, item) -> None:
        runner.toggle_voice(lambda text: icon.notify(text, "普瑞赛斯"))

    def toggle_autostart(icon, item) -> None:
        try:
            set_autostart(not autostart_enabled())
        except (OSError, subprocess.SubprocessError) as e:
            log.exception("Changing autostart failed")
            icon.notify(f"没能修改开机自启动：{e}", "普瑞赛斯")
            return
        icon.notify("以后开机时我会自己醒来。" if autostart_enabled() else "好，开机时我不会自己醒来了。", "普瑞赛斯")
        icon.update_menu()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"普瑞赛斯 · {runner.status}", None, enabled=False),
        pystray.MenuItem(lambda item: f"语音模块：{runner.voice_status()}", None, enabled=False),
        pystray.MenuItem(
            lambda item: "关闭语音模块" if runner.speech and runner.speech.engine.state != "off" else "开启语音模块",
            toggle_voice,
            enabled=lambda item: runner.speech is not None and runner.speech.engine.state != "starting",
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开日志", open_log, default=True),  # also on double-click
        pystray.MenuItem("打开文件夹", open_folder),
        pystray.MenuItem("开机自启动", toggle_autostart, checked=lambda item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("重新启动", restart),
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("priestess", Image.open(ICON_FILE), "普瑞赛斯 · 正在连接……", menu)

    def watch_status() -> None:
        announced = False
        last = None
        while icon.visible:
            status = (runner.status, runner.voice_status())
            if status != last:
                icon.title = f"普瑞赛斯 · {status[0]}"[:127]
                icon.update_menu()
                if last and last[1].startswith("运行中") and status[1] == "已关闭":
                    icon.notify("语音模块休息了。", "普瑞赛斯")  # stopped (after the idle minutes, or by command)
                last = status
            if not announced and runner.bot is not None and runner.bot.is_ready():
                icon.notify(line("tray_online"), "普瑞赛斯")
                announced = True
            if runner.error is not None and not announced:
                icon.notify("启动失败了，右键图标可以打开日志。", "普瑞赛斯")
                announced = True
            time.sleep(3)

    def setup(icon) -> None:
        icon.visible = True
        threading.Thread(target=watch_status, name="tray-status", daemon=True).start()

    icon.run(setup=setup)


def main() -> None:
    setup_output()
    from bot import claim_single_instance

    mutex = claim_single_instance()
    if mutex is None:
        message_box("普瑞赛斯已经在运行了。\n在右下角的托盘图标里（可能在 ^ 展开的隐藏图标中）。")
        return

    import config

    if not config.DISCORD_TOKEN:
        message_box("还没有设置 DISCORD_TOKEN。\n请在 .env 里填好后再启动。")
        return

    runner = BotRunner()
    runner.start()
    run_tray(runner, mutex)


if __name__ == "__main__":
    if "--shortcut" in sys.argv:  # PRTS.bat runs this once to make the PRTS shortcut
        make_shortcut(ROOT / "PRTS.lnk")
    else:
        main()
