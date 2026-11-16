"""/帮助: what Priestess can do, in her voice. Lists only the features that are turned on."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import access
from persona import line

HELP_COLOR = 0x8E7CC3


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="帮助", description="普瑞赛斯能做什么")
    async def help(self, interaction: discord.Interaction):
        guild = interaction.guild
        owner = access.is_deployer(interaction.user.id)
        me = guild.me.mention if guild else "普瑞赛斯"
        embed = discord.Embed(title="普瑞赛斯 · 能为你做的事", description=line("help_intro"), color=HELP_COLOR)
        embed.add_field(
            name="点歌",
            value=(
                "`/play 歌名或链接` 输入歌名时会给你一个列表，挑一首我才放；贴链接会直接加入队列。\n"
                "能搜的：Bilibili、网易云、塞壬唱片（明日方舟官方）。YouTube 只认链接，不按歌名搜。\n"
                "`/search` 只搜不放，挑了才加入；两个都能选平台、选「插队」。"
            ),
            inline=False,
        )
        embed.add_field(
            name="播放",
            value=(
                "`/queue` 队列 · `/nowplaying` 正在放什么 · `/skip` `/pause` `/resume` `/stop`\n"
                "`/volume` 音量 · `/loop` 循环 · `/shuffle` 打乱 · `/remove` 删掉一首 · `/leave` 让我离开\n"
                "`/电台` 塞壬电台：队列放完后，我从塞壬唱片里随机接着放"
                + ("\n`/说话` 让我进你的语音频道，把聊天回复读出来（要先开语音模块；说话时不能放歌）"
                   if self.bot.get_cog("Speech") else "")
            ),
            inline=False,
        )
        if self.bot.get_cog("Chat"):
            embed.add_field(
                name="和我说话",
                value=(
                    f"{me} 加上你想说的话，或者直接回复我的消息。\n"
                    "「放一首 晴天」「跳过」「暂停」「音量调到 50」「开电台」这些我马上就办，不用等我想。\n"
                    "只说「哈哈」「？」「好耶」这样的短话，我回你一个表情。\n"
                    "现实里的纷争我不聊。作业、写信、写代码、翻译这类长活，每人每天可以找我几次。同样的话说一次就够了。"
                ),
                inline=False,
            )
        if self.bot.get_cog("Calendar"):
            embed.add_field(
                name="活动日历",
                value="`/活动` 用时间轴图看明日方舟、终末地等游戏正在进行、快结束、快开始的活动。也可以直接问我。",
                inline=False,
            )
        if owner:
            owner_lines = (
                ["`/同步活动` 让游时重新同步一次日历", "`/推送提醒` 现在把今天的活动提醒再发一次"]
                if self.bot.get_cog("Calendar") else []
            )
            if self.bot.get_cog("Speech"):
                owner_lines.append("`/语音模块` 开启或关闭我的声音（GPT-SoVITS，占显卡，空闲 5 分钟自动关；托盘菜单里也能开关）")
            if self.bot.get_cog("Chat"):
                owner_lines.append("`/聊天统计` 今天谁和我聊了多少、用了多少 token")
                if self.bot.get_cog("Balance"):
                    owner_lines.append("`/余额` DeepSeek 余额，以及今天 / 本周 / 本月 / 一直以来花了多少")
            if owner_lines:
                embed.add_field(name="只有部署者能用", value="\n".join(owner_lines), inline=False)
        embed.set_footer(text="这条说明只有你看得到。")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
