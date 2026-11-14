<img src="docs/images/priestess.png" align="right" width="140" alt="普瑞赛斯">

# 普瑞赛斯 Priestess-Bot

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white) ![Windows](https://img.shields.io/badge/platform-Windows-0078D6) ![discord.py 2.7](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)

以《明日方舟》里的**普瑞赛斯**为人设的 Discord 机器人：在语音频道里放歌，@ 她就能聊天。

- **点歌**：塞壬唱片（明日方舟官方）、网易云音乐、Bilibili，YouTube 只能贴链接。用斜杠命令，或者直接跟她说「放一首晴天」。
- **聊天**：@ 她，她会用角色的口吻回复，还能查天气、上网搜索；配置好以后也能查机票、酒店和地图。需要 DeepSeek 或 Claude 的 API 密钥。
- **说话模式**：用你自己的 GPT-SoVITS 声音模型，在语音频道里把回复读出来。
- **游戏活动日历**：每晚提醒明日方舟、终末地等游戏快结束的活动，附一张时间轴图；有干员过生日也会提一句。
- **花钱有数**：常用指令、表情、敏感话题都用写好的台词回应，不调用 API；聊天和搜索每人每天有额度；她只待在你允许的服务器里。

<sub>A Discord music bot for a small private server, with Priestess from <i>Arknights</i> as its persona: plays songs from Monster Siren, NetEase Cloud Music, Bilibili and YouTube links, chats through DeepSeek or Claude, posts game event reminders, and can read replies aloud with a local GPT-SoVITS voice. Documentation is in Chinese. Built for Windows.</sub>

> [!NOTE]
> **非官方粉丝项目**，与鹰角网络（Hypergryph）无关。普瑞赛斯和《明日方舟》的角色、名字、图片版权归鹰角网络所有。代码以 MIT 许可证发布，见[许可证和致谢](#许可证和致谢)。

<p align="center"><img src="docs/images/chat-persona.png" width="750" alt="博士 @ 她问如何看待凯尔希，她用普瑞赛斯的口吻回答"></p>
<p align="center"><sub>README 里的截图按真实对话重建，提问的人显示为「博士」。</sub></p>

**目录**：[快速开始](#快速开始) · [命令](#命令) · [点歌](#点歌) · [聊天](#聊天) · [说话模式](#说话模式) · [游戏活动日历](#游戏活动日历) · [常见问题](#常见问题) · [隐私](#隐私) · [许可证和致谢](#许可证和致谢)

## 快速开始

需要 Windows 和 Python 3.10 以上（测试用的是 3.14）。点歌和聊天本身不依赖 Windows，但托盘、`PRTS.bat`、开机自启动和游戏活动日历只能在 Windows 上用。

### 1. 创建 Discord 机器人

1. 打开 <https://discord.com/developers/applications>，点 **New Application**
2. 左侧 **Bot** → **Reset Token**，复制 token
3. 左侧 **OAuth2** → **URL Generator**：
   - Scopes 勾选 `bot` 和 `applications.commands`
   - Bot Permissions 勾选 `View Channels`、`Send Messages`、`Embed Links`、`Connect`、`Speak`
4. 打开生成的链接，把机器人拉进你的服务器
5. **关掉 Public Bot**：回到左侧 **Bot** 页，把 **Public Bot** 关掉。这样只有你自己能邀请她，别人拿到邀请链接也加不了。这一步很重要：不管她在哪个服务器被 @，用的都是你电脑上的程序和你的 API 密钥，花的是你的钱。
6. **建议打开 Message Content Intent**（也在 **Bot** 页，私人服务器不需要审核，打开就能用）。原因见[聊天](#聊天)一节。其他 Privileged Gateway Intents 都不需要。

机器人的名字和头像在 **General Information** 和 **Bot** 页设置。

### 2. 配置

```bash
copy .env.example .env
```

用记事本打开 `.env`，每一项都有说明。先填下面几项就能用：

| 设置 | 说明 |
| --- | --- |
| `DISCORD_TOKEN` | 上一步复制的 token，**必填** |
| `ALLOWED_GUILD_IDS` | **强烈建议填**：她可以待的服务器 ID，几个用逗号隔开 |
| `DEV_GUILD_ID` | 你服务器的 ID。填了斜杠命令马上就能用；不填是全局同步，最多要等一小时才出现 |
| `DEEPSEEK_API_KEY` 或 `ANTHROPIC_API_KEY` | 开启聊天，见[聊天](#聊天)。不填也能点歌 |

服务器 ID 的拿法：Discord 设置里打开开发者模式，右键服务器 → 复制服务器 ID。

填了 `ALLOWED_GUILD_IDS` 后，万一她被拉进别的服务器，会马上退出，不回复任何消息、不调用 API。想让她去朋友的服务器，把那个服务器的 ID 加进来就行。留空时不限制服务器，日志里会提醒她在几个服务器里。

改了 `.env` 之后，从托盘「重新启动」就会读到新的设置。

### 3. 运行

双击 `PRTS.bat`。第一次会自动建好 `.venv`、装好依赖，并在这个文件夹里生成 `PRTS` 快捷方式。

- **平时启动**：双击 `PRTS` 快捷方式。机器人在后台运行，没有命令行窗口，右下角托盘（`^` 展开的隐藏图标里）会出现普瑞赛斯的头像。右键图标可以查看状态、打开日志（`logs/bot.log`）、打开文件夹、重新启动或退出；双击图标也会打开日志。移动了文件夹之后，运行 `.venv\Scripts\python tray.py --shortcut` 重新生成快捷方式。
- **调试**：双击 `PRTS.bat` 会带着命令行窗口运行，能直接看到输出。同一时间只能运行一个普瑞赛斯：托盘版在运行时，`PRTS.bat` 会提示后退出。
- **开机自启动**（可选，默认关闭）：右键托盘图标，勾选「开机自启动」。这会在 Windows 的「启动」文件夹里放一个普瑞赛斯的快捷方式（不需要管理员权限），取消勾选就删掉它。刚开机时网络还没连上的话，她每 30 秒重试一次，托盘状态显示「连不上 Discord，30 秒后重试」；Token 错误这类问题不会重试，状态显示「出错了」。想让图标一直显示在任务栏右下角，在 Windows 设置 → 个性化 → 任务栏 → 其他系统托盘图标里打开它。

不需要单独装 ffmpeg：系统 PATH 里有就用系统的，没有就用 `imageio-ffmpeg` 自带的。解析 YouTube 需要一个 JavaScript 运行时，装了 [Node.js](https://nodejs.org/) 就行。

<details>
<summary>不用 <code>PRTS.bat</code>，手动安装</summary>

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python bot.py
```

`requirements.lock` 里是最后一次测试通过时每个库的确切版本。以后重装时如果新版本出了问题，改用 `pip install -r requirements.lock` 就能装回一模一样的环境。yt-dlp 例外，YouTube 放不了时要更新它（见 [YouTube](#youtube)）。

</details>

## 命令

<p align="center"><img src="docs/images/commands.png" width="688" alt="在 Discord 里输入 / 时弹出的普瑞赛斯命令列表"></p>

在 Discord 里输入 `/` 就能看到她的命令，选中之后 Discord 会提示要填的内容。

**点歌**

| 命令 | 作用 |
| --- | --- |
| `/play` | 点歌：填歌名或链接，可以指定平台、插队。贴链接会自动识别平台并直接加入队列；输入歌名会弹出搜索结果列表让你挑（只有你自己看得到） |
| `/search` | 和 `/play` 输入歌名时一样，搜索后从下拉菜单里挑 |
| `/queue` | 查看队列，可以翻页 |
| `/nowplaying` | 正在放的歌 |
| `/skip` | 跳过这首 |
| `/pause` | 暂停 |
| `/resume` | 继续 |
| `/stop` | 停止并清空队列 |
| `/loop` | 循环模式：关闭 / 单曲 / 列表 |
| `/shuffle` | 打乱队列 |
| `/remove` | 按序号删除某首 |
| `/volume` | 音量，0–100 |
| `/leave` | 离开语音频道 |
| `/电台` | 打开或关闭塞壬电台：队列放完后从塞壬唱片随机接着放（不重复最近 60 首，跳过 Instrumental 版本），「正在播放」卡片会标「塞壬电台」。`/stop` 会把电台一起关掉。聊天里说「开电台」「关电台」，或者「一直放明日方舟的歌吧」也行 |

没有歌在放时，机器人会在 `IDLE_TIMEOUT` 秒后自动离开；频道里没人时 1 分钟后也会离开。

**其他**

| 命令 | 作用 |
| --- | --- |
| `/说话` | 打开或关闭说话模式：她进入你所在的语音频道，把聊天回复读出来，见[说话模式](#说话模式) |
| `/活动` | 查看游戏活动，可以指定游戏和范围，见[游戏活动日历](#游戏活动日历) |
| `/帮助` | 用她的口吻列出能做的事，只有你自己看得到 |

**只有[部署者](#人设)能用**

| 命令 | 作用 |
| --- | --- |
| `/余额` | DeepSeek 余额和花了多少钱，见[用量和花费](#用量和花费) |
| `/聊天统计` | 今天和最近 7 天每个人的聊天用量，见[用量和花费](#用量和花费) |
| `/语音模块` | 启动或关闭 GPT-SoVITS，见[说话模式](#说话模式) |
| `/同步活动` | 让游时马上重新同步一次活动日历 |
| `/推送提醒` | 把今天的频道提醒再发一次（比如改了样式想看看效果），不影响每晚的定时提醒 |

## 点歌

用 `/play` 输入歌名搜索，或者直接贴链接（单曲、视频、歌单、专辑、分P视频都行）；也可以 @ 她说「放一首晴天」，见[聊天](#聊天)。

**支持的链接**

| 平台 | 链接 |
| --- | --- |
| Bilibili | `bilibili.com/video/BV…`（含 `?p=` 分P）、`b23.tv` 短链、直接发 `BV…` 号 |
| 网易云 | `music.163.com` 的单曲、歌单、专辑链接，`163cn.tv` 短链 |
| 塞壬唱片 | 官网的歌曲链接 |
| YouTube | `youtube.com/watch?v=…`、`youtu.be/…`、`youtube.com/shorts/…`、`youtube.com/playlist?list=…` |

- 歌单一次最多添加 100 首（`config.py` 里的 `MAX_PLAYLIST_ITEMS`）。
- **YouTube 只能用链接**，不能按歌名搜索（它的搜索结果什么内容都有），`/play` `/search` 的平台里也没有它。机器人只取出视频或播放列表的 ID，重新拼成标准链接再交给 yt-dlp，其他形式的 YouTube 链接（跳转页、同意页等）不支持。

**按歌名搜索**

- 同时搜默认平台（`DEFAULT_SOURCE`，默认 Bilibili）和另一个平台（网易云；默认平台是网易云时换成 Bilibili）。指定了平台的话，只搜那个平台。
- 最多列 8 个结果，每个都标明平台、上传者和时长。60 秒内没有选择，列表会自动关闭。
- 少于 30 秒的片段和超过 20 分钟的视频（电影、合集、循环）会被去掉；翻唱、伴奏、教学、现场、乐器演奏这类版本排在后面（除非你搜的词里就带着这些字）。
- 某个平台搜索失败时（比如 B 站偶尔要求人机验证），另一个平台的结果会补上。

### 塞壬唱片和她的歌

<p align="center"><img src="docs/images/music-siren.png" width="632" alt="塞壬电台随机播放的「正在聆听」卡片，带她的一句话和官方专辑简介"></p>

- 塞壬唱片（monster-siren.hypergryph.com）是明日方舟的官方唱片公司，约 900 首歌，官方音源、音质最好、没有地区限制。`/play` 和 `/search` 的平台里可以选「塞壬唱片」。
- 不选平台按歌名搜时，也会顺带搜塞壬唱片：歌名完全一致（如 `Speed of Light`）时官方版本排在列表最前面；中文译名（如「飞驰如光」）或角色名（如「凯尔希」）搜到的排在最后。
- 塞壬唱片的歌还会显示专辑名和官方专辑简介（播放时从官网读取）。

**她的话**：放明日方舟的歌时，「正在播放」卡片里会多一句她的话，都是预先写好的，不调用 API。和她自己有关的歌是专门写的：

- **《Eclipse》**（Aimer，六周年印象曲，社区公认是她的歌）
- 巴别塔OST、慈悲灯塔OST、《离解复合》、孤星OST、众生行记OST
- 凯尔希的歌：Immutable、Innocence、Skeletal Wings、Before Summer
- WE、Reversed Time、Believing、From Ash to Fire

其他干员曲会说出 MV 角色和相关活动，活动原声会说出活动名。B站 / YouTube 链接里的明日方舟歌曲也能被认出来，前提是标题里带「明日方舟」「塞壬」「Arknights」之类的字样；Eclipse 只要标题里有「Eclipse」和「Aimer」就算。

这些对应关系来自 PRTS Wiki 的音乐列表，写在 `siren_lore.py` 里，她的专属台词也在那里，可以自己改或者加。

### 网易云音乐

<p align="center"><img src="docs/images/music-netease.png" width="632" alt="从网易云播放 Eclipse 的「正在聆听」卡片，带她为自己的歌写的一句话"></p>

> [!IMPORTANT]
> 网易云对**中国大陆以外的 IP** 有地区限制，但是按歌曲来的：一部分歌（比如周杰伦的）拿不到播放地址，很多歌（比如孤勇者、Lemon、Shape of You）海外也能正常播放。被限制的原唱还会从搜索结果里被藏起来，排在前面的往往是翻唱。

所以在海外时：

- `/play` 输入文字默认在 **Bilibili** 搜（`DEFAULT_SOURCE=bilibili`），不受网易云影响。
- 在 `/play` 里选了网易云时，只会选网易云标记为**原唱**、标题和你输入的一致、而且有一定热度的那首。找不到的话（原唱被藏起来了），会用你输入的原话去 Bilibili 搜，并提示「网易云上没有找到原唱版本，已改用 Bilibili」。
- 贴网易云的单曲、歌单、专辑链接照常可以用，放不了的歌会自动换源。

**自动换源**（默认开启）：网易云的歌放不了时，机器人会在 Bilibili 上搜同一首歌，挑一个最像原曲的来播，并在频道里提示「已换成 Bilibili 上的 …」。不想要换源的话，在 `.env` 里把 `NETEASE_FALLBACK=` 留空，放不了的歌就会直接跳过。

<details>
<summary>换源时怎么挑</summary>

输入文字点的歌用你输入的原话搜，链接里的歌用「歌名 + 歌手」搜（YouTube 只用链接，不参与换源）。

- 时长要和网易云的原曲接近（相差不超过 20 秒或 15%）；按输入文字搜时没有参考时长，只排除 1 分钟以下的片段和 15 分钟以上的循环、合集
- 标题要包含歌名（繁体和简体都算）；按输入文字搜时，输入的每个词都要出现在标题或上传者名字里
- 排除翻唱、伴奏、KTV、现场、Remix、乐器演奏、鼓谱之类的版本（除非原曲标题本身就是这种版本）
- 优先选歌手官方频道、Official、Hi-Res、无损、歌词版
- 条件差不多时优先 Bilibili（排在 `NETEASE_FALLBACK` 前面的平台）

</details>

**想播放网易云的原始音源**，需要让机器人用国内 IP 访问网易云：

- 在 `.env` 里把 `NETEASE_PROXY` 设成一个**位于中国大陆**的 HTTP 代理，例如 `http://127.0.0.1:7890`（需要你的代理软件把 `music.163.com` 和 `*.music.126.net` 分流到国内节点），或者
- 把机器人部署在国内的服务器上

**VIP 歌曲**：可以填 `NETEASE_MUSIC_U`，用**你自己账号**的登录 Cookie（浏览器登录 music.163.com 后，在开发者工具 → Application → Cookies 里找 `MUSIC_U`）。只能播放你的账号本来就有权限听的歌，只能试听片段的歌会被跳过。不要把 `MUSIC_U` 发给别人，它等于你的登录状态。

### Bilibili

<p align="center"><img src="docs/images/music-bilibili.png" width="632" alt="从 Bilibili 播放感谢庆典印象曲的「正在聆听」卡片"></p>

不登录也能用。偶尔某些关键词搜索会触发 B 站的人机验证，这时机器人会提示，可以：

- 换个关键词，或者直接贴 BV 链接（链接不受影响）
- 在 `.env` 里填 `BILIBILI_SESSDATA`（你自己账号的 `SESSDATA` Cookie），登录后基本不会触发，音质也更高

### YouTube

如果遇到 "Sign in to confirm you're not a bot"，导出 YouTube 的 cookies.txt（Netscape 格式，可以用浏览器扩展 "Get cookies.txt LOCALLY"），然后在 `.env` 里填 `YOUTUBE_COOKIES=cookies.txt` 的路径。建议用一个小号导出。

YouTube 经常改版，如果突然不能播放了，先更新 yt-dlp：

```bash
.venv\Scripts\python -m pip install -U "yt-dlp[default]"
```

## 聊天

需要 DeepSeek 或 Claude 的 API 密钥，二选一：

- **DeepSeek**：在 <https://platform.deepseek.com> 的 **API Keys** 页创建密钥，填进 `.env`：`DEEPSEEK_API_KEY=你的密钥`
- **Claude**：在 <https://platform.claude.com> 的 **API Keys** 页创建密钥，填进 `.env`：`ANTHROPIC_API_KEY=你的密钥`

两个都填时优先用 DeepSeek，也可以用 `CHAT_PROVIDER` 指定。填好后重启机器人。不要把密钥发给别人，也不要提交到 Git。两个都不填的话，聊天功能会自动关闭，点歌照常使用。

两个平台用的是同一套代码：DeepSeek 提供了和 Claude 相同格式的接口（`https://api.deepseek.com/anthropic`），所以对话、工具调用、人设都一样。

### 人设

- **台词**：机器人发出的所有消息都是普瑞赛斯的口吻（平静、从容、带一点调侃，喜欢用声音和寂静作比喻），每种情况有几条随机变体，都写在 `persona.py` 的 `LINES` 里，可以自己改。歌名、链接、序号这些信息照常显示。聊天的人设和规则写在同一个文件的 `CHAT_SYSTEM_PROMPT` 里。
- **称呼**：服务器的主人是她的「博士」，其他人按昵称称呼。
- **部署者和博士**：机器人有两种「主人」。
  - **部署者**是在开发者后台拥有这个机器人应用的人，也就是用自己的 token 和 API 密钥运行它的人。只有部署者能用管理整个机器人的指令（`/余额`、`/聊天统计`、`/语音模块`、`/同步活动`、`/推送提醒`），聊天条数和联网搜索次数也不受限制。
  - **博士**是每个服务器的主人：在自己的服务器里被称作博士，不受每人每天的条数限制，但全服务器的每日总量对博士也有效。
  - 只在你自己的服务器里用时，你同时是这两种人，没有区别。代码在 `access.py`。

### 能聊什么

<p align="center"><img src="docs/images/chat-homework.png" width="760" alt="博士让她证明哥德巴赫猜想，她说明这是未解难题，不会编一份假的证明"></p>

- 在任意频道 @普瑞赛斯 说话，她会以角色口吻回复。回复她的消息（默认会 @ 到她）也算。
- **控制音乐**：「放一首晴天」「跳过这首」「音量调小点」「现在在放什么」都行。点歌时你得在语音频道里。只说歌名时，她会在你的消息下面发一个搜索结果列表，你挑了才会播放（别人点不了你的列表）。
- **常用指令不花钱**：@ 她之后只说「放一首/来首/点一首 歌名」「我想听 歌名」「跳过/下一首/切歌」「暂停」「继续」「停止/别放了」「现在在放什么」「音量调到 50」时，直接用预先写好的台词处理，不调用 API，也更快。别的话（包括把点歌夹在长句子里）才交给模型。斜杠命令（`/play` `/skip` 等）本来就从不调用 API。
- **她记得聊过什么**：每个频道是一段共享的对话，她记得这个频道最近聊过的内容。聊得太久（40 条消息，`CHAT_MAX_MESSAGES`）或者 30 分钟没人说话，会重新开始。
- **不用 @ 也回复**：把频道 ID 填进 `.env` 的 `CHAT_CHANNEL_IDS`，她会回复那个频道里的每一条消息（需要打开 Message Content Intent）。
- **关于 Message Content Intent**：机器人有一个和她同名的身份组，在 @ 列表里容易选成它。不开这个开关的话，Discord 不会把 @ 身份组的那条消息的文字发给机器人，她只能回一句「后面的话没能传过来」。开了之后 @ 她本人和 @ 她的身份组都一样。没开也能正常启动，机器人会自动不申请这项权限。

**时间、天气和上网**

- 她知道现在的日期和时间（运行机器人那台电脑的时区）。
- 问天气时会查 [Open-Meteo](https://open-meteo.com)（免费，不需要密钥），能查任意城市的当前天气和最多 7 天预报。
- 问新闻、游戏更新这类她不知道的事时，会联网搜索；有人发来网页链接，她也能读正文。闲聊和角色设定不会去搜。
  - 用 DeepSeek 时，搜索和读网页由机器人自己调用 [DeepSeek 的 Search / Fetch API](https://api-docs.deepseek.com/guides/search/)（代码在 `websearch.py`），只把前 5 条结果的摘要交给她，每条消息最多 2 次（`CHAT_SEARCH_MAX_USES`）。结果里有 `blocked_words.txt`「回避」词的会被去掉，搜索词本身命中也不会搜。
  - 用 Claude 时用的是 Claude 自带的网页搜索（由 Anthropic 那边执行）。
- 价格、机票酒店、票务、汇率、比分、营业时间这类实时信息，就算没有专门的工具，她也会先搜；搜不到确切答案时，会说出最接近的信息，并给一个能直接打开的查询链接（比如填好机场和日期的 Google Flights 页面）。万一她没试就说「查不了」，机器人会让她先搜一次再回答（那句放弃的话不会发出来）。

**实时查询**（可选：机票、酒店、商品、地图、识图）：在 `.env` 填 `SERPAPI_KEY` 后开启（在 [serpapi.com](https://serpapi.com) 注册免费账号，每月 250 次）。数据来自 Google，代码在 `travel.py`、`lookup.py`、`serp.py`。没填密钥时这些工具不出现，问机票时她会给出填好条件的 Google Flights 链接。

<details>
<summary>能查什么、怎么算次数</summary>

- **机票**（Google Flights）：「5 月 1 号去 5 号回，上海到东京」列出几班航班的价格、航司、起降时间、经停和时长，附完整结果链接。纽约这类有几个机场的城市会一起查。
- **哪天飞最便宜**（价格日历）：「三月份哪几天飞大阪最便宜，玩五天」列出最便宜的日期。
- **特价机票**：「这周末从上海出发去哪玩便宜」列出目的地、价格、比平时便宜多少。
- **酒店**（Google Hotels）：每晚价格（含税）、总价、评分。
- **商品价格**（Google Shopping，美国）：「990 PRO 4TB 哪里最便宜」列出各家店的现价和链接。
- **地图**（Google Maps）：「新宿现在还开着的拉面店」列出评分、地址、此刻是否营业、电话；「从新宿开车去横滨要多久」按实时路况给出几条路线。
- **识图**（Google Lens）：她本来看不到图片。有人发图问「这是谁」「在哪买」，或者只发一张图给她（也可以回复别人的图片问她），她会用 Google Lens 查网上相似的图片来判断。只是顺手分享的图她不会去查。

每次查询算一次联网搜索（从每人每天的次数里扣）。机器人还会记录当月用量，到 `SERPAPI_MONTHLY_LIMIT`（默认 230）就停，记录在 `data/serpapi_usage.json`。每次查询在发出前就先记上，失败了也不退回，所以同时查也不会超过这个数；但同一个密钥在别处用掉的次数机器人不知道，以 SerpApi 后台的用量为准。记录文件损坏时，实时查询会停下来，直到你修好或删掉它。

</details>

**表情包**：只发「哈哈」「？」「好耶」「无语」「呜呜」「就这」「在吗」这类短反应，或者只 @ 她不说话、只发 emoji 时，她回一个自己的表情，不调用 API。同一个频道 5 秒内最多发一个（`STICKER_COOLDOWN`），这期间的短反应她改成在那条消息上点一个表情回应，不再另发消息。她自己聊天时也偶尔会在回复后面跟一个表情（模型写 `[表情:无奈]`，机器人换成表情图）。`CHAT_STICKERS=off` 可以关掉。

<details>
<summary>表情图怎么准备</summary>

- **表情图不在仓库里**，要自己准备图片，在开发者后台 **Emojis** 页上传成应用表情（不占服务器的表情位）。
- 机器人按名字里的编号认图（`_20261102031217_309_15` 认作 309），改名的话保留编号就行，比如 `laugh_309`。
- 在 `stickers.py` 的 `STICKERS` 里把每种心情对应到你的表情名里的编号；触发词和表情的对应也写在这个文件里。不想弄的话设 `CHAT_STICKERS=off`。

</details>

### 不聊的话题

下面这些都在调用 API 之前处理，不花钱。

- **敏感话题**：消息里有 `blocked_words.txt` 里的词（现实政治、战争冲突、歧视用语、色情、毒品、游戏圈引战），她会用预先写好的台词带过，不交给模型。歌名和上传者里有这些词的歌也不会放、不会出现在搜索列表里。
  - 仓库里只带一份很短的示例表 `blocked_words.example.txt`：复制一份改名为 `blocked_words.txt`，按你的服务器加上自己的词（`blocked_words.txt` 不会被提交到 Git；没有它时读示例表）。文件随时改，保存就生效；匹配不分大小写、空格和繁简体。
  - `[关心]` 一节的词（自杀、不想活……）换成认真、温柔的回应，提醒对方找身边的人或心理援助热线。
  - 被拦下的消息记在 `logs/blocked.log`，可以看看有没有误伤（比如「自杀小队」这种电影名也会被当成关心类）。默认只记时间、类别、命中的词和频道；想看是谁说的、说了什么，在 `.env` 设 `LOG_BLOCKED_TEXT=on`（会记下昵称和消息前 200 字，其中可能有很私人的内容）。文件超过 1 MB 会轮换，只留一份旧的。
- **人设里的规矩**：关键词没拦住的，靠人设里的「不聊的话题」：现实政治、宗教、民族、战争、现实人物八卦、游戏之间的拉踩，她都不评价、不站队，轻轻带过。DeepSeek 自己拒绝的内容（Content Exists Risk）也会换成她的台词，这条消息不会留在对话记录里。
- **她自己的回复也会检查**：回复会过一遍 `blocked_words.txt` 的「回避」一节（拐弯抹角的问题、搜索结果里带出来的敏感内容），命中就换成预写台词，记在 `logs/blocked.log`。「关心」一节不查她的回复，因为安慰人的话里本来就可能有这些词。

### 额度

**每日额度**按本机日期算，重启不清零。表情、快捷指令、被拦下的话题都不算额度。

| 额度 | 默认 | 部署者 | 博士 |
| --- | --- | --- | --- |
| 每人每天聊天条数（`CHAT_USER_DAILY`） | 40 | 不限 | 不限 |
| 全服务器每天聊天条数，所有服务器加在一起（`CHAT_SERVER_DAILY`） | 500 | 不限 | 受限 |
| 每人每天联网搜索次数，含读网页和实时查询（`CHAT_SEARCH_DAILY`） | 20 | 不限 | 受限 |
| 每人每天「长活」次数（`CHAT_TASKS_DAILY`） | 3 | 受限 | 受限 |
| SerpApi 每月查询次数（`SERPAPI_MONTHLY_LIMIT`） | 230 | 受限 | 受限 |

- 条数在排队之前就先记上，同时发很多条也不会超过额度。到了额度她说一次「今天累了」，之后当天只在这个人的消息上点一个「憔悴」的表情，点歌照常。
- 搜索次数用完后，她会告诉对方明天再查。

<details>
<summary>搜索次数为什么是硬性限制</summary>

- **用 DeepSeek 时**：每次搜索在发出前就先记上，用完后机器人直接不执行搜索。
- **用 Claude 时**：Claude 自带的搜索在 Anthropic 那边执行。每次请求发出前，机器人先占用这次最多能搜的次数（剩余次数不够时降到剩余次数），回复后把没用掉的退回，所以几个频道同时问也不会超；用完后把搜索工具撤掉。
- 如果这个频道的对话里已经有过 Claude 的搜索结果，工具撤不掉（撤掉的话请求可能被拒绝，暂停中的回复也必须带着它），这时机器人不会再发出能搜索的请求：新消息会让这个频道的对话重新开始（和聊满 40 条时一样）再回答；如果是回复到一半用完，她会停在那里：已经写出的部分照常发出，后面接一句今天的搜索次数用完了，这段回答以纯文字留在对话里。

</details>

**长消息和长活**

- 超过 1500 个字符（`CHAT_MAX_INPUT_CHARS`，英文按字母算）的消息不交给模型，她会让对方说短一点。
- 做作业、写作文或信件、写代码、翻译或总结长文、写长篇故事这类「长活」，她接活前会先登记，次数用完就婉拒、让对方明天再来。做完会在结尾加一两句她口吻的免责声明（只是参考，不能代替老师、律师、医生的意见；作业要自己读懂、别原样交上去）。闲聊、简单问答、一两句话的小忙不算长活。
- **这是软限制**：登记靠她自己调用工具，有人刻意绕的话可能绕过去。真正限制花费的是上面的每日额度和每条回复的长度上限。

**刷屏**：同一个人 2 分钟内把她已经回答过的话原样再发一遍，她第一次简短地说一句「这句话我已经听过了」，之后只在那条消息上点一个「盯」的表情。点歌指令（「跳过」连说两次、进了语音频道再说一次「放一首…」）和出错后重发的话不算刷屏。

### 费用

按用量计费，每百万 token：

| 模型 | 输入（缓存命中 / 未命中） | 输出 | 一次普通聊天大约 |
| --- | --- | --- | --- |
| `deepseek-v4-pro`（DeepSeek 默认） | $0.044 / $1.32 | $3.96 | 0.1–0.2 美分 |
| `deepseek-flash` | $0.006 / $0.30 | $1.20 | 0.05 美分以下 |
| `claude-opus-5-5`（Claude 默认） | $0.20 / $4 | $20 | 1 美分左右 |
| `claude-haiku-5-5` | — / $0.10 | $0.50 | 很便宜，但角色扮演没那么细腻 |

- DeepSeek 的价格是高峰时段的，其他时间（包括周末）半价。实测 `deepseek-v4-pro` 平均每条聊天约 $0.0008（高峰价），也就是每 1000 条聊天大约 0.5–1 美元。
- `deepseek-flash` + 高思考强度（`.env` 的 `CHAT_MODEL`、`CHAT_EFFORT`）实测每条聊天约 $0.0002，是 `deepseek-v4-pro` 的三分之一左右，回复也快一倍。
- 联网搜索每次约 $0.001–0.002（Search API 每次 $0.00075，加上交给她的约 2000 token 摘要）；不想要的话在 `.env` 里设 `CHAT_WEB_SEARCH=off`。查天气不走搜索，不额外花钱。
- 人设提示两边都会自动缓存。在 `.env` 的 `CHAT_MODEL` 里换模型。控制台日志里每次聊天都会打印实际用掉的 token 数。

### 用量和花费

- **`/聊天统计`**（只有部署者能用，只有你看得到）：今天每个人聊了几条、搜了几次、做了几次长活、用了多少 token，以及免费处理掉的表情、快捷指令和被拦的话题数，还有最近 7 天的合计。数据在 `data/chat_usage.json`（每个人的明细留 7 天，每天的合计一直保留）。
- **`/余额`**（只有部署者能用，只用 DeepSeek 时才有）：DeepSeek 账户余额（查询免费），以及今天、本周（从周一算）、本月、一直以来花了多少钱，旁边附上同一段时间的消息数、搜索次数和 token 数。
  - DeepSeek 只告诉我们当前余额，所以花费是这样算的：每 30 分钟（`BALANCE_CHECK_MINUTES`）读一次余额，减少的部分记为当天的花费，增加的部分当作充值、不算花费。从这个功能第一次运行时开始记，同一个密钥在别处用掉的钱也会算进来。
  - 余额低于 `BALANCE_WARN`（默认 10，按你账户的币种，比如 10 元）时，她会私信你一次，充值回去之后再低于才会再提醒。记录在 `data/balance.json`。
- **`/帮助`**：所有人都能用，只有自己看得到。用她的口吻列出能做的事；部署者还会看到只有自己能用的指令。

## 说话模式

可选。需要你自己装好 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，并准备自己的模型和一段参考音频。**仓库里不带任何声音模型或音频**。

**设置**：声音设置（GPT-SoVITS 文件夹、模型、参考音频、停顿、可选的后期滤镜 `post_filter`）写在一个 JSON 文件里：把 `voices/example.json` 复制成 `voices/voice.json`，改成你自己的路径（或者用 `.env` 的 `VOICE_CONFIG` 指向别的文件）。`voices/` 里除了示例之外的 JSON 都不会被提交到 Git。`VOICE_PROMPT=clip` 是 t1（带参考文本，语调也跟参考走），`none` 是 t4（只取音色），留空按 JSON 里写的。

模型和参考音频都只在本机，不上传。分句和有声书一样：破折号处停 0.8 秒、引号括号不念、太短的句子并进下一句，偶尔卡住或念太快的一句会换个随机种子重来。找不到这些文件时，这部分功能自动关闭。代码在 `speech.py` 和 `cogs/speech.py`。

- **`/语音模块 [开/关]`**（只有部署者能用）：在后台隐藏启动 GPT-SoVITS（用它自带的 Python，日志在 `logs/sovits.log`），加载模型后通知「我可以说话了」，大约半分钟。它占用显卡，**没人在说话模式里 5 分钟就自动关掉**（`SOVITS_IDLE_MINUTES`）；机器人退出或重新启动时也会关掉。如果 GPT-SoVITS 已经在别处开着（比如在做有声书），机器人直接用它，但不会去关它。
- **托盘菜单**：右键图标能看到「语音模块：已关闭 / 正在启动 / 运行中（说话模式：开/关）」，下面一项可以直接开启或关闭，和 `/语音模块` 一样；状态变化时托盘会弹通知。
- **`/说话 [开/关]`**（所有人）：她进入你所在的语音频道，开始说话模式。语音模块没开时，她会说「语音模块睡着了，等启用了再试试吧」。
- **说话模式下**：在开启说话模式的那个文字频道里 @ 她，她除了打字回复，还会在语音频道里读出来（只读前面大约 220 个字；链接、表情、格式符号不念，`$445` 读成「445 美元」）。她会把话说得更口语、更短。一句一句地合成：第一句好了就开始读，同时合成下一句，句与句之间按有声书的设置停顿。几个人同时 @ 她会排队一条条读。她听不见语音，大家还是打字跟她说。
- **和放歌互斥**（跟塞壬电台一样）：说话模式里有人点歌、开电台，会提示先 `/说话 关`；正在放歌或电台开着时用 `/说话`，会提示先停歌。频道里没人一分钟后，她会退出说话模式离开。
- **费用**：声音在本机生成，不调用付费 API。说话模式下每条消息多一句提示（约 20 个 token），但回复会变短。

> [!WARNING]
> 如果你的声音模型是用游戏配音或其他人的声音训练的，请只在私人服务器里自己用，不要公开发布模型或生成的音频。

## 游戏活动日历

<p align="center"><img src="docs/images/calendar.png" width="616" alt="每晚的活动提醒：她的开场白、接下来 3 天结束的活动，和明日方舟的活动时间轴图"></p>

活动数据来自 [游时 Playtime](https://github.com/ZhenyuFu039/acg-calendar)（官方公告、PRTS 等来源），支持明日方舟、终末地、碧蓝航线、绝区零、NIKKE。

**安装**：游时需要 `tzdata`（已写进 `requirements.txt`）。把游时放在这个文件夹的旁边（`../Playtime-v0.2.0-windows-x64`），或者在 `.env` 的 `PLAYTIME_DIR` 填它的位置。找不到游时文件夹时，这部分功能自动关闭，其他功能照常。

**同步**：游时不常驻后台。机器人启动时，在后台隐藏启动一次游时，让它同步全部游戏、导出数据到 `data/calendar.json`，然后马上关掉，之后的查询和提醒都读这个文件。机器人一直开着的话，每 `PLAYTIME_REFRESH_HOURS` 小时（默认 24）重复一次；3 小时内重启不会重复同步。首次同步要下载活动头图，大约 6 分钟；之后大约 1–2 分钟，都在后台进行，不影响点歌。部署者可以用 `/同步活动` 手动再同步一次。

**`/活动 [游戏] [范围]`**：查看进行中 / 7 天内截止 / 即将开始的活动、寻访和兑换商店，用和频道提醒一样的时间轴图，每个游戏一组。进行中的会分成「快结束了」「还在进行」两段，没有结束日期的长期项目列成一行字。

**频道提醒**：在 `.env` 填 `CALENDAR_CHANNEL_ID` 后开启。每天 `CALENDAR_DIGEST_TIME`（比如 20:00）每个游戏发一组：

1. **开场白**：她的一句话（第一组前面还有一句晚上好），按情况挑（有要结束的 / 有新开始的 / 很平静 / 没有活动）。没有结束日期的长期项目（常驻申领、玩法更新）列在开场白下面一行。
2. **小卡片**：列出「接下来 3 天结束」的活动，用 Discord 的时间格式，每个人看到的是自己当地的时间和倒计时。
3. **时间轴图**（仿游时）：左边是活动头图和名字，中间是从 3 天前到 14 天后的时间条（条里铺着头图，虚线是今天），右边是结束时间和剩余时间；3 天内结束标红，7 天内标黄。图里是北京时间。头图用的是游时同步时缓存的官方图，没有图的显示一个写着类型的色块。图在本地用 Pillow 画，不花钱，代码在 `calendar_image.py`。
   - 一个游戏不超过 10 行时只发一张图；超过的话按「快结束了（7 天内）」「明天开始」「还在进行」分开发，每张图前面有她的一句话，一张最多 8 行，再多就分成「（1/2）」「（2/2）」。没有内容的段落不发。

<details>
<summary>提醒的时间规则和设置</summary>

- 都从明天 0 点算起，所以晚上发的时候不会列出已经结束的活动。一项活动在结束前的 3 个晚上都会被提到（`CALENDAR_END_DAYS`），「明天开始」看几天由 `CALENDAR_START_DAYS` 决定。
- 活动和兑换商店在结束前 24 小时、1 小时各提醒一次（`CALENDAR_ALERTS=off` 可以关掉），只对公告写明的确切时间提醒。
- 发过的记在 `data/calendar_sent.json`，重启不会重发；机器人没开时错过的，6 小时内会补发。
- `CALENDAR_GAMES` 选哪些游戏；`CALENDAR_PING_ROLE_ID` 可以设一个身份组来 @（每批只 @ 一次，默认不 @）。
- 开场白的台词在 `persona.py` 的 `cal_game_*`；游戏的叫法（罗德岛、塔卫二）和卡片颜色在 `cogs/calendar.py` 的 `GAME_NICKNAMES`、`GAME_COLORS`。
- 部署者可以用 `/推送提醒` 把今天的提醒再发一次，不影响每晚的定时提醒。
- 这些提醒都是预先写好的台词，**不调用付费 API**。

</details>

**干员生日**：每晚的提醒发完后，如果当天有干员过生日，她最后再说一句，比如「对了——今天是战车、缪尔赛思、海霓的生日」；阿米娅生日那天有专门的一句。生日来自游戏里每位干员档案的【生日】一栏（通过公开的 ArknightsGameData 数据），约 375 位干员，没有公开生日的不算，异格干员和原干员算一个。仓库里带一份 `assets/operator_birthdays.json`，机器人每周自动重新下载一次（存到 `data/`），新干员会自己加进来。

**在聊天里问**：问她「明日方舟现在有什么活动」「兑换商店什么时候关」时，她会先查这份日历，不走网页搜索，不额外花钱。

## 常见问题

**斜杠命令不出现**：没填 `DEV_GUILD_ID` 时全局同步要等一会儿；或者邀请链接里没勾 `applications.commands`。

**机器人进了频道、头像变绿但没声音**：先检查 davey 的版本：`.venv\Scripts\python -m pip show davey`。必须是 0.1.x。davey 0.2 和 discord.py 2.7.1 不兼容，语音端到端加密（DAVE）会一直无法就绪，发出去的声音别人都听不到。`requirements.txt` 已经限制了版本，用它安装就不会出问题。也确认一下机器人有 `Speak` 权限。

**网易云全部提示地区限制**：见上面[网易云音乐](#网易云音乐)一节。

**@ 她没有反应**：看控制台有没有 `Priestess chat is disabled`（没填密钥）。如果只在 `CHAT_CHANNEL_IDS` 的频道里不 @ 没反应，检查开发者后台的 Message Content Intent 有没有打开。

## 隐私

部署这个机器人之前，最好让服务器里的人知道下面这些。

**会发给第三方的内容**

| 发给谁 | 什么时候 | 发送的内容 |
| --- | --- | --- |
| DeepSeek 或 Anthropic（聊天） | 有人 @ 她，或在 `CHAT_CHANNEL_IDS` 频道说话 | 这个频道最近和她的对话记录（不是频道里所有消息，只有和她有关的）、当前消息、说话人的昵称、所在语音频道名、正在放的歌、机器人电脑的时间和时区、人设提示词、工具结果。消息（或它回复的消息）里有图片时，只告诉她有几张、编号是多少，不发图片链接 |
| DeepSeek Search / Fetch | 她联网搜索或读网页时（用 DeepSeek） | 搜索词和原消息的前 128 字；或要读的完整网址。网页由 DeepSeek 的服务器去抓，不是从你的电脑抓 |
| Anthropic 网页搜索 | 她联网搜索时（用 Claude） | 由 Claude 在 Anthropic 那边决定搜什么 |
| SerpApi（Google） | 机票、酒店、商品、地图、识图 | 航线和日期、地点、商品名、地址；识图时还有图片链接和问题。只能是这条消息或它回复的那条消息里的图片，由机器人按编号取出链接，她不能指定别的链接（图片仍可能是别人发的，比如回复别人的图问她） |
| Open-Meteo | 问天气 | 地名 |
| 音乐平台 | 点歌 | 搜索词、歌曲或视频 ID；填了的话还有你自己账号的 Cookie |
| 本机 GPT-SoVITS | 说话模式 | 要读的句子（只在你自己的电脑上） |

**存在本机的内容**（都在 `data/` 和 `logs/` 里，不会被提交到 Git，但电脑上能打开这个文件夹的人都能看到）

- **对话记录**只在内存里，按频道分开；40 条或 30 分钟没人说话后，下一条消息到来时清空；机器人退出就没了。
- `data/chat_usage.json`：每个人（Discord 用户 ID 和最近的昵称）每天的条数、搜索次数、长活次数和 token 数。每个人的明细大约保留 7 天，之后合并成每天的总数，一直保留。
- `data/serpapi_usage.json`、`data/balance.json`、`data/calendar*.json`、`data/operator_birthdays.json`：每月查询次数、余额和花费记录、活动日历缓存、干员生日缓存，没有聊天内容。
- `logs/blocked.log`：被拦下的消息。默认只记时间、类别、命中的词和频道，`LOG_BLOCKED_TEXT=on` 时才记昵称和原文。超过 1 MB 轮换。
- `logs/bot.log`：运行日志，可能有出错信息、长活的一句话摘要、朗读重试的句子。2 MB 轮换，保留 3 份。
- `logs/output.log`、`logs/sovits.log`：程序输出和 GPT-SoVITS 输出，超过 5 MB 时在下次启动换新文件，保留 1 份旧的。
- 播放 YouTube 时会在系统临时文件夹里写一个视频信息的 `.info.json`，播放结束后删除；程序崩溃时可能留下。

**怎么删除**：退出机器人后，删掉 `data/chat_usage.json` 和 `logs/` 里的文件即可。删掉 `data/serpapi_usage.json` 会让每月查询次数从 0 重新算。

## 开发

<details>
<summary>项目结构</summary>

```
bot.py                     入口，加载命令并同步斜杠命令
tray.py                    托盘版入口（PRTS 快捷方式用的就是它）
assets/priestess.ico       托盘和快捷方式的图标
config.py                  读取 .env 配置
persona.py                 普瑞赛斯的台词（LINES）和聊天人设（CHAT_SYSTEM_PROMPT）
cogs/music.py              所有斜杠命令和语音频道事件
cogs/chat.py               @ 她聊天：DeepSeek / Claude、对话记录、控制音乐的工具
access.py                  部署者是谁、可以待在哪些服务器（ALLOWED_GUILD_IDS）
moderation.py              不聊的话题：读 blocked_words.txt（没有时读 blocked_words.example.txt），拦下的记在 logs/blocked.log
stickers.py                表情包：触发词、编号和心情的对应
usage.py                   每日聊天额度和 token 统计（data/chat_usage.json）
weather.py                 天气查询（Open-Meteo）
websearch.py               联网搜索和读网页（DeepSeek Search / Fetch API）
serp.py                    SerpApi 请求和每月额度
travel.py                  机票（含价格日历、特价）和酒店（Google Flights / Hotels）
lookup.py                  商品价格、识图、地图和路线（Google Shopping / Lens / Maps）
gamecal.py                 游时：启动一次、同步、导出、关闭，以及读取活动数据
cogs/calendar.py           /活动、/同步活动、/推送提醒、频道提醒和每日简报
calendar_image.py          活动时间轴图（Pillow，仿游时）
cogs/balance.py            /余额：DeepSeek 余额和花费记录（data/balance.json）
cogs/speech.py             /语音模块、/说话：说话模式（读出聊天回复）
speech.py                  GPT-SoVITS 的启动、关闭和合成（读 VOICE_CONFIG 指定的声音设置）
voices/example.json        说话模式的声音设置示例（只有路径和参数，不含模型和音频）
cogs/help.py               /帮助
birthdays.py               干员生日（assets/operator_birthdays.json，每周更新）
music/player.py            每个服务器的播放队列和播放循环
music/resolver.py          根据链接或平台选择对应的音源
music/track.py             Track / Stream 数据结构
music/sources/youtube.py   YouTube（yt-dlp）
music/sources/bilibili.py  Bilibili（Web API + WBI 签名）
music/sources/netease.py   网易云音乐（eapi 接口）
music/sources/siren.py     塞壬唱片（官方接口，本地搜索）
music/sources/links.py     展开 b23.tv、163cn.tv 短链接（每一跳都必须留在平台自己的网站上）
siren_lore.py              塞壬唱片歌曲对应的角色、活动，和她的专属台词
docs/images/               README 用的图
```

</details>

**添加新平台**：在 `music/sources/` 里写一个类，实现 `matches_url`、`search`、`from_url`、`resolve`、`close`，再在 `music/resolver.py` 和 `cogs/music.py` 的 `SOURCE_CHOICES` 里注册就行。

## 许可证和致谢

- **代码**：[MIT](LICENSE)。MIT 只管源代码；下面提到的角色、图片和第三方数据不在此列，各自沿用原有的版权或许可。
- **角色和图片**：普瑞赛斯和《明日方舟》的角色、名字、图片（包括 `assets/priestess*.png`、`assets/priestess.ico`，以及 `docs/images/` 里的立绘、头像和活动头图）版权归 [鹰角网络](https://www.hypergryph.com) 所有，不在 MIT 许可证范围内。截图里的专辑封面归各自的版权方所有。这是一个非官方粉丝项目，与鹰角网络无关。台词都是原创的，没有照搬游戏文本。
- **塞壬唱片**的歌曲和专辑简介由机器人在播放时从 [官网](https://monster-siren.hypergryph.com) 读取，仓库里不带音频。
- `siren_lore.py` 里歌曲和角色、活动的对应关系整理自 [PRTS Wiki](https://prts.wiki) 的音乐列表，PRTS Wiki 的内容使用 [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) 许可。
- 干员生日（`assets/operator_birthdays.json`）来自 [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)。
- 游戏活动日历来自 [游时 Playtime](https://github.com/ZhenyuFu039/acg-calendar)。
- 天气来自 [Open-Meteo](https://open-meteo.com)。说话模式用的是 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)。

请遵守各音乐平台的服务条款，只用你自己账号的 Cookie，只播放你有权收听的内容。
