"""Central configuration. Everything personal/secret comes from environment variables or a local `.env`
file (see .env.example). Nothing secret is hard-coded in this repo."""
import json, os

CODE_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_dotenv(path):
    """Tiny .env loader (KEY=VALUE per line, # comments). Never overrides variables already in the env."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"": v = v[1:-1]
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass

_load_dotenv(os.path.join(CODE_DIR, ".env"))

def _env(name, default=""):
    return os.environ.get(name, default).strip()

# Where runtime files live: credentials.json, state.json, pending.json, outbox.json, history.log, logs.
DATA_DIR = os.path.abspath(os.path.expanduser(_env("BRIDGE_DATA_DIR") or CODE_DIR))
os.makedirs(DATA_DIR, exist_ok=True)

# --- inbound: WeChat -> Grok Bot webhook routine ---
WEBHOOK_URL = _env("WECHAT_WEBHOOK_URL")            # the URL of your Grok Bot routine's webhook trigger
SECRETS_FILE = _env("WECHAT_SECRETS_FILE")          # optional JSON file holding WECHAT_WEBHOOK_KEY (any nesting depth 1)

def webhook_key():
    """Bearer key for the webhook. Env WECHAT_WEBHOOK_KEY wins; else look it up in WECHAT_SECRETS_FILE."""
    k = _env("WECHAT_WEBHOOK_KEY")
    if k or not SECRETS_FILE: return k
    try:
        d = json.load(open(os.path.expanduser(SECRETS_FILE)))
        if isinstance(d, dict) and d.get("WECHAT_WEBHOOK_KEY"): return str(d["WECHAT_WEBHOOK_KEY"]).strip()
        for sect in (d.values() if isinstance(d, dict) else []):
            if isinstance(sect, dict) and sect.get("WECHAT_WEBHOOK_KEY"):
                return str(sect["WECHAT_WEBHOOK_KEY"]).strip()
    except Exception:
        pass
    return ""

# Downloaded images / files / voice / video land here; the path is passed to the agent in the webhook payload.
ATTACH_DIR = os.path.abspath(os.path.expanduser(_env("WECHAT_ATTACH_DIR") or os.path.join(DATA_DIR, "attachments")))

# --- batching (pending.json) ---
BATCH_QUIET_S = float(_env("BATCH_QUIET_S", "3"))    # flush when no new user message for this long
BATCH_CAP_S = float(_env("BATCH_CAP_S", "60"))       # ...or when the oldest pending message is this old

# --- persona / wording ---
OWNER_NAME = _env("OWNER_NAME", "User")              # how the agent prompts and history.log refer to the WeChat user
BOT_NAME = _env("BOT_NAME", "grok")                  # speaker label for bot lines in history.log
APP_PREFIX = _env("APP_PREFIX", "[grok bot] ")       # prefix for app-initiated (non-reply) pushes: send.py --app
NUDGE_TEXT = _env("NUDGE_TEXT", APP_PREFIX + "离你上次发消息快一天了，回个 1 续一下，免得之后的提醒发不过来。")

# --- time zones ---
QUIET_TZ = _env("QUIET_TZ", "Asia/Shanghai")         # quiet hours are evaluated in this zone (Beijing by default)
QUIET_START = int(_env("QUIET_START", "0"))          # no keep-alive nudge from QUIET_START:00 ...
QUIET_END = int(_env("QUIET_END", "8"))              # ... until QUIET_END:00 (exclusive)
HISTORY_TZ = _env("HISTORY_TZ", "Asia/Shanghai")     # timestamps written into history.log

def quiet_hours():
    if QUIET_START <= QUIET_END: return set(range(QUIET_START, QUIET_END))
    return set(range(QUIET_START, 24)) | set(range(0, QUIET_END))   # wraps midnight, e.g. 23 -> 7
