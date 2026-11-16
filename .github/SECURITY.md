# 安全政策

普瑞赛斯需要自己部署：每个人用自己的 Discord token 和 API 密钥运行自己的那一份。所以这里说的安全问题，通常是指别人能花掉部署者的钱、拿到部署者的密钥，或者让她在服务器里做不该做的事。

## 报告漏洞

**请不要开公开 issue。** 请用 GitHub 的私下报告：打开 <https://github.com/ffde007/Priestess-Bot/security/advisories/new>（也就是仓库 **Security** 页的 **Report a vulnerability**）。报告只有维护者能看到。

方便的话请写上：

- 怎么复现：发了什么消息、用了什么命令、`.env` 里相关的设置
- 会造成什么后果
- 用的是哪个版本，或哪次提交

## 支持的版本

只修最新的 release 和 `main` 分支。修复会发在新版本里，旧版本不单独打补丁。

## 算安全问题的

- 普通成员能用部署者专用的命令（`/余额`、`/聊天统计`、`/语音模块`、`/同步活动`、`/推送提醒`）
- 在 `ALLOWED_GUILD_IDS` 以外的服务器里，她仍然回复消息或调用 API
- 绕过聊天的每日额度、搜索次数或 SerpApi 的每月上限，让部署者多花钱
- 让她说出 `.env` 里的密钥、本机的文件内容或路径
- 让她把别的频道、别的服务器里的对话内容说出来
- 用提示词注入（直接说，或者藏在网页、歌名、搜索结果里）让她绕过上面这些限制，或者调用工具去做提问的人没要求的事
- 一条消息或一个链接就能让机器人崩溃或卡住，需要部署者手动重启

## 不算的

- 让她说出不符合人设的话，或聊到她本来不聊的话题，但没有上面这些后果。这类可以开普通 issue。
- 部署者自己的配置问题：没关 Public Bot、`ALLOWED_GUILD_IDS` 留空、自己把 token 或 `.env` 发了出去
- discord.py、yt-dlp、GPT-SoVITS 这些依赖本身的漏洞，请报告给对应的项目。如果是这个项目用错了它们，就算。
- 要先拿到部署者电脑的权限才能做到的事

## 处理方式

这是个人项目，会尽力处理，但不保证回复时间，也没有赏金。确认是问题后，修复会发在新版本里。修好之后，这条报告可以在 GitHub 上公开，你愿意的话会在里面致谢你。

## 部署者：密钥泄露了怎么办

- **Discord token**：Developer Portal → **Bot** → **Reset Token**，把新 token 填进 `.env`
- **DeepSeek、Claude、SerpApi 的密钥**：在对应的平台删掉旧密钥，新建一个填进 `.env`
- 改完从托盘「重新启动」，新的设置就会生效

## English

Please report vulnerabilities privately through GitHub at <https://github.com/ffde007/Priestess-Bot/security/advisories/new>, not in a public issue. Only the latest release and `main` are supported. This is a personal project: reports are handled on a best-effort basis, with no guaranteed response time and no bounty.
