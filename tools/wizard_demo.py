"""Preview the setup page without a Discord token: Discord and the key checks are faked.

    python tools/wizard_demo.py [--port 8769] [--configured]

Then open http://127.0.0.1:8769/#demo. Any token or key is accepted unless it starts with "bad".
Saving writes to a throwaway .env in the temp folder, never to the real one. --configured starts
from a .env that already has a token and a server, as when the page is opened from the tray.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import wizard  # noqa: E402
from wizard import WizardError  # noqa: E402

GUILDS = [
    {"id": "1100000000000000001", "name": "罗德岛", "icon": None},
    {"id": "1100000000000000002", "name": "巴别塔 <b>旧址</b>", "icon": None},  # markup must show as text
]


class FakeDiscord:
    """Stands in for wizard.Discord. Each "重新检查" and "刷新列表" moves the story one step on."""

    def __init__(self) -> None:
        self.client = None
        self.token = ""
        self.public = True
        self.message_content = False
        self.refreshes = 0

    async def login(self, token: str) -> None:
        if token.startswith("bad"):
            raise WizardError("Discord 不认识这个 Token。请在 Bot 页点 Reset Token，再复制一次。")
        self.client, self.token = object(), token

    async def info(self) -> dict:
        return {
            "name": "普瑞赛斯",
            "avatar": None,
            "public": self.public,
            "message_content": self.message_content,
            "invite_url": "https://discord.com/oauth2/authorize?client_id=0",
            "portal_url": wizard.DEVELOPER_PORTAL,
        }

    async def guilds(self) -> list[dict]:
        self.refreshes += 1
        return GUILDS[: self.refreshes - 1] if self.token != "configured" else GUILDS

    async def enable_message_content(self) -> None:
        self.message_content = True

    async def clear_guild_commands(self, guild_id: int) -> None:
        print(f"(would clear the slash commands of server {guild_id})")


async def fake_check(key: str) -> str:
    if key.startswith("bad"):
        raise WizardError("不认识这个密钥，请重新复制一次。")
    return "密钥有效，余额 12.34 CNY。"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--configured", action="store_true", help="start from a .env that is already filled in")
    args = parser.parse_args()

    wizard.ENV_FILE = Path(tempfile.mkdtemp(prefix="priestess-wizard-")) / ".env"
    wizard.CHAT_CHECKS = {"deepseek": fake_check, "claude": fake_check}
    if args.configured:
        wizard.write_env({"DISCORD_TOKEN": "configured", "ALLOWED_GUILD_IDS": GUILDS[0]["id"], "DEV_GUILD_ID": GUILDS[0]["id"]})

    def saved() -> None:
        # What a save changed, with the secrets left out.
        lines = [line for line in wizard.ENV_FILE.read_text(encoding="utf-8").splitlines() if line and line[0] != "#"]
        for line in lines:
            key, _, value = line.partition("=")
            if key in ("DISCORD_TOKEN", "DEV_GUILD_ID", "ALLOWED_GUILD_IDS", "CHAT_PROVIDER", "CHAT_MODEL") or key.endswith("_API_KEY"):
                shown = value if "TOKEN" not in key and "KEY" not in key else f"({len(value)} characters)"
                print(f"saved  {key}={shown}", flush=True)

    page = wizard.Wizard(on_saved=saved, port=args.port, key="demo")
    page.discord = FakeDiscord()

    real_recheck = page.recheck

    async def recheck(request):  # in the demo, Public Bot has been turned off by the time of "重新检查"
        page.discord.public = False
        return await real_recheck(request)

    page.recheck = recheck
    print(page.start(), flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
