# Routine 模板 ①：微信消息入口（Webhook 触发）

> 在 Grok Bot 里建一个 **routine**，触发方式选 **Webhook**。复制它给出的 URL 和 Bearer key，填进 `.env`
> 的 `WECHAT_WEBHOOK_URL` / `WECHAT_WEBHOOK_KEY`。**这两个值都是秘密，别提交、别贴到 issue 里。**
> 下面是 routine 的指令模板（按需改名字、路径和你自己的整理规则）。
> 原作者实际用的 routine 指令保存在 Grok Bot 的 routine 配置里，不在本仓库；这里是按代码契约整理的等价版本。

---

**指令（贴进 routine）：**

你收到的是微信 ClawBot 转发来的一批消息（JSON，`source = "wechat-clawbot"`, `batch = true`）。

字段：
- `messages[]`：用户在一次停顿前连发的所有消息，按时间排序。每条有 `texts`（文字 / 语音转写）、
  `items[]`（每个元素的类型、文本或元数据，媒体会带 `file` 本地路径，失败带 `media_error`）、
  `files`（已下载并解密好的图片 / 文件 / 语音 / 视频的绝对路径）、`create_time_ms`。
- `history`：最近 40 行对话（`[时间] 用户：…` / `[时间] grok：…`）。你每次都是新开的一轮，靠它接上文。
- `trigger_ms`：这批里最新一条的时间戳。
- `reply_rule`：回复规则（见下）。
- `context_note`（可选）：比如"这是对续期提醒的回复"——照它说的简短回应。

规则：
1. 用 `python3 /path/to/grokbot-wechat-bridge/send.py "回复内容" --reply-to-ms <trigger_ms>` 回微信。
   可以发多条；每次都带 `--reply-to-ms`。
2. 退出码 **4 = SUPERSEDED**：用户在你处理期间又发了新消息。**立刻停止**，什么都不发、不归档，新的一轮会处理全部内容。
3. 退出码 **3 = QUEUED**：24 小时推送窗口已关，消息进了 outbox，用户下次说话时自动补发。不用重试。
4. 图片 / 文件：直接打开 `files` 里的路径看内容；需要的话归档到你的笔记 / 列表里。
5. 用户只回了 "1"、"续" 之类：这是在续 24h 推送窗口，回一句很短的"续上了"即可，别追问。
6. 回复要像微信聊天：短、口语、一条一个意思。
