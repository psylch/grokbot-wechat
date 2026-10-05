# Routine 模板 ②：转发器看门狗（每 15 分钟）

> 在 Grok Bot 里建一个 **routine**，触发方式选 **定时（every 15 minutes）**，在跑 forward.py 的那台机器（box）上执行。
> 也可以不用 routine，改用 cron：`*/15 * * * * /path/to/grokbot-wechat-bridge/watchdog.sh >> /path/to/data/watchdog.log 2>&1`

---

**指令（贴进 routine）：**

运行 `bash /path/to/grokbot-wechat-bridge/watchdog.sh`，它只输出一行：

- `OK pid=…`：一切正常。**什么都不用做，不要发任何消息，安静结束。**
- `RESTARTED (原因) pid=…`：转发器挂了已自动拉起（多半是机器重启过）。不用通知用户；如果一天内重启超过 3 次，
  再用 `send.py --app "微信转发器今天重启了 N 次，原因：…"` 提醒一次。
- `FAILED (原因)`：拉不起来。看 `forward.out` 和 `forward.log` 末尾 30 行找原因（常见：缺依赖、`credentials.json`
  丢了 / token 失效需重新 `bind.py`、`.env` 没配）。能修就修好后再跑一次 watchdog.sh；修不了就把原因简短告诉用户。

注意：
- 不要同时手动再启一个 `run_forward.sh`，两个轮询器共用一个 getupdates 游标会互相"偷"消息。
- 不要在转发器运行时跑 `poll.py`（同理）。
