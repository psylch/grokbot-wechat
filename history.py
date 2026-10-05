"""Rolling stitched conversation history (history.log, one line per turn).
Each webhook run is a fresh agent run, so the forwarder ships the last 40 lines with every batch."""
import fcntl, os, time
from datetime import datetime
from zoneinfo import ZoneInfo
from config import DATA_DIR, HISTORY_TZ, OWNER_NAME, BOT_NAME
HISTORY = os.path.join(DATA_DIR, "history.log")   # contains real conversation text; NEVER commit
MAX_LINES, KEEP_LINES = 2000, 1000

def clean(s):
    return " / ".join(p.strip() for p in str(s or "").replace("\r\n", "\n").split("\n") if p.strip())

def stamp(ts=None):
    return datetime.fromtimestamp(ts or time.time(), ZoneInfo(HISTORY_TZ)).strftime("%Y-%m-%d %H:%M")

def item_text(it):
    """it: summarized item from build_payload (type, text, meta, file, media_error)."""
    t = it.get("type")
    if t == 1: return clean(it.get("text"))
    f = it.get("file")
    if t == 2: return "[图片 %s]" % f if f else "[图片 下载失败]"
    if t == 4:
        name = clean((it.get("meta") or {}).get("file_name") or "")
        return "[文件 %s %s]" % (name, f) if f else "[文件 %s 下载失败]" % name
    if t == 3: return "[语音: %s]" % clean(it.get("text")) if it.get("text") else ("[语音 %s]" % f if f else "[语音 下载失败]")
    if t == 5: return "[视频 %s]" % f if f else "[视频 下载失败]"
    return "[未知类型 %s]" % t

def user_line(payloads):
    parts = [item_text(it) for p in payloads for it in p.get("items", [])]
    ts = (payloads[0].get("create_time_ms") or 0) / 1000 or None
    return "[%s] %s：%s" % (stamp(ts), OWNER_NAME, " ".join(x for x in parts if x))

def grok_line(text, ts=None):
    return "[%s] %s：%s" % (stamp(ts), BOT_NAME, clean(text))

def append(line, path=None):
    path = path or HISTORY
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.replace("\n", " / ") + "\n"); f.flush()
        f.seek(0); lines = f.readlines()
        if len(lines) > MAX_LINES:
            f.seek(0); f.truncate(); f.writelines(lines[-KEEP_LINES:])

def tail(n=40, path=None):
    path = path or HISTORY
    try:
        with open(path, encoding="utf-8") as f: return "".join(f.readlines()[-n:])
    except FileNotFoundError:
        return ""
