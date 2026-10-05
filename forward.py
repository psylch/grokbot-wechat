#!/usr/bin/env python3
"""Forward WeChat ClawBot user messages (message_type==1) to a Grok Bot webhook routine.
Loops forever on ilink/bot/getupdates (same cursor/state handling as poll.py). Logs to forward.log.
Three threads:
  main     long-poll getupdates -> dedupe -> download media -> append to pending.json
  flusher  POST pending.json as one batch once the user pauses (BATCH_QUIET_S) or after BATCH_CAP_S
  outbox   flush queued sends right after the user writes; keep-alive nudge before the ~24h window closes
Usage: python3 forward.py [--selftest]"""
import json, os, socket, sys, threading, time, logging, urllib.request, urllib.error
from ilink import post, load_state, save_state, DIR
import config, media, history, outbox
from config import WEBHOOK_URL, webhook_key, OWNER_NAME

SEEN = os.path.join(DIR, "forward_seen.json")      # recent message_ids, for dedupe
HEARTBEAT = os.path.join(DIR, "forward.heartbeat") # touched after every long-poll; watchdog.sh checks its age
logging.basicConfig(filename=os.path.join(DIR, "forward.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("forward")

def post_webhook(payload, tries=5):
    key = webhook_key()
    if not WEBHOOK_URL:
        log.error("WECHAT_WEBHOOK_URL not set; cannot forward"); return None
    if not key:
        log.error("WECHAT_WEBHOOK_KEY unavailable; cannot forward"); return None
    data = json.dumps(payload, ensure_ascii=False).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=20) as f:
                body = f.read().decode(errors="replace")
                log.info("webhook OK status=%s body=%s", f.status, body[:300])
                return f.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            log.warning("webhook HTTP %s (try %d): %s", e.code, i + 1, body)
            if 400 <= e.code < 500 and e.code not in (408, 429):
                return e.code, body
        except Exception as e:
            log.warning("webhook error (try %d): %s", i + 1, e)
        time.sleep(min(2 ** i * 2, 60))
    log.error("webhook gave up after %d tries", tries)
    return None

def load_seen():
    try: return json.load(open(SEEN))
    except Exception: return []

def fetch():
    """One long-poll. Returns (ok, msgs). Mirrors poll.once() state updates."""
    st = load_state()
    try:
        raw = post("ilink/bot/getupdates", {"get_updates_buf": st.get("get_updates_buf", "")}, timeout=40)
    except (socket.timeout, TimeoutError):
        return True, []
    r = json.loads(raw)
    if r.get("ret", 0) != 0:
        log.warning("getupdates ret!=0: %s", raw[:300]); return False, []
    st = load_state()  # re-read to minimise clobbering concurrent writers
    if r.get("get_updates_buf"): st["get_updates_buf"] = r["get_updates_buf"]
    msgs = r.get("msgs") or []
    for m in msgs:
        if m.get("message_type") == 1 and m.get("from_user_id"):
            st["last_from_user_id"] = m["from_user_id"]
            if m.get("context_token"):
                st.setdefault("context_tokens", {})[m["from_user_id"]] = m["context_token"]
            m["_prev_inbound_ms"] = st.get("last_inbound_ms")
            st["last_inbound_ms"] = max(st.get("last_inbound_ms") or 0, m.get("create_time_ms") or int(time.time() * 1000))
    if msgs:
        st["raw_log"] = (st.get("raw_log", []) + msgs)[-20:]
    save_state(st)
    return True, msgs

ATTACH_DIR = config.ATTACH_DIR
MEDIA_TYPES = (2, 3, 4, 5)  # image, voice, file, video

def build_payload(m, attach_dir=ATTACH_DIR, fetch=True):
    items = m.get("item_list") or []
    payload = {"source": "wechat-clawbot", "from_user_id": m.get("from_user_id"),
               "texts": [t for t in (media.summarize(i).get("text") for i in items) if t],
               "item_types": [i.get("type") for i in items],
               "items": [media.summarize(i) for i in items],
               "create_time_ms": m.get("create_time_ms"), "message_id": m.get("message_id")}
    media_items = [i for i in items if i.get("type") in MEDIA_TYPES]
    if media_items:
        payload["has_media"] = True
        files, errors, raw = [], [], []
        ts = (m.get("create_time_ms") or 0) / 1000 or None
        for idx, i in enumerate(items):
            if i.get("type") not in MEDIA_TYPES or not fetch: continue
            try:
                path = media.fetch_item(i, attach_dir, ts)
                files.append(path); payload["items"][idx]["file"] = path
            except Exception as e:
                err = "%s: %s: %s" % (media.TYPE_NAMES.get(i.get("type")), type(e).__name__, e)
                errors.append(err); raw.append(i); payload["items"][idx]["media_error"] = err
        payload["files"] = files
        if errors:
            payload["media_error"] = "; ".join(errors)
            payload["raw_items"] = raw
            log.warning("media error message_id=%s: %s", m.get("message_id"), payload["media_error"])
    return payload

PENDING = os.path.join(DIR, "pending.json")
QUIET_S = config.BATCH_QUIET_S   # flush when no new user message for this long
CAP_S = config.BATCH_CAP_S       # ...or when oldest pending message is this old
RETRY_S = 60                     # wait after a failed flush before retrying
KEEPALIVE_TOKENS = {"1", "１", "续", "续一下", "+1", "11", "111"}   # bare "renew the window" replies

class Batcher:
    """Thread-safe, disk-persisted pending buffer, flushed by a background thread."""
    def __init__(self, path=PENDING, quiet=QUIET_S, cap=CAP_S, poster=None, clock=time.time, history_path=None):
        self.path, self.quiet, self.cap, self.clock = path, quiet, cap, clock
        self.history_path = history_path or history.HISTORY
        self.poster = poster or post_webhook
        self.lock = threading.Lock()
        self.next_try = 0
        d = {}
        try: d = json.load(open(path))
        except Exception: pass
        self.msgs = d.get("messages", [])
        self.oldest = d.get("oldest")
        # on restart, leftover buffer flushes after a fresh quiet window
        self.last = self.clock() if self.msgs else None
        if self.msgs: self.oldest = self.last   # reset cap too, so restart waits a full quiet window
        if self.msgs: log.info("restored %d pending message(s) from disk", len(self.msgs))

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"messages": self.msgs, "oldest": self.oldest, "last": self.last}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add(self, payload):
        with self.lock:
            now = self.clock()
            if not self.msgs: self.oldest = now
            self.msgs.append(payload); self.last = now
            self._save()
            log.info("buffered message_id=%s (pending=%d)", payload.get("message_id"), len(self.msgs))

    def due(self):
        now = self.clock()
        return bool(self.msgs) and now >= self.next_try and (
            now - self.last >= self.quiet or now - self.oldest >= self.cap)

    def maybe_flush(self):
        with self.lock:
            if not self.due(): return False
            batch = list(self.msgs)
            reason = "quiet" if self.clock() - self.last >= self.quiet else "cap"
        trigger_ms = max([m.get("create_time_ms") or 0 for m in batch] or [0])
        body = {"source": "wechat-clawbot", "batch": True, "messages": batch, "count": len(batch),
                "trigger_ms": trigger_ms,
                "reply_rule": "Pass --reply-to-ms %d to every send.py call. Exit code 4 (SUPERSEDED) means %s "
                              "sent something newer: stop immediately, send nothing, file nothing; the newer run "
                              "handles it." % (trigger_ms, OWNER_NAME),
                "history": history.tail(40, self.history_path)}
        hist_lines = [l for l in body["history"].splitlines() if l.strip()]
        after_nudge = bool(hist_lines) and outbox.NUDGE_TEXT in hist_lines[-1]
        first = batch[0]
        gap_h = ((first.get("create_time_ms") or 0) - (first.get("prev_inbound_ms") or 0)) / 3.6e6 if first.get("prev_inbound_ms") else 0
        bare_ping = all("".join(p.get("texts") or []).strip() in KEEPALIVE_TOKENS for p in batch)
        if not after_nudge and bare_ping and gap_h >= 12:
            body["context_note"] = ("%s sent a bare '%s' after %.0fh of silence. That's him renewing the ~24h WeChat push "
                                    "window (the keepalive nudge may have been skipped or missed). Reply with a very short "
                                    "natural ack like '续上了', and if any queued pushes went out, say so briefly. Don't ask "
                                    "what it means." % (OWNER_NAME, "".join(first.get("texts") or []).strip(), gap_h))
        if after_nudge:
            body["context_note"] = ("Your last WeChat message to %s was the keepalive nudge (see the end of history), "
                                    "so this batch is his reply to it. A bare '1' or similar just renews the window: reply "
                                    "with a very short natural ack (e.g. '续上了'), don't ask what's up. If he says more, "
                                    "answer that normally with the nudge as context." % OWNER_NAME)
        log.info("flushing %d message(s) (%s) ids=%s", len(batch), reason, [m.get("message_id") for m in batch])
        res = self.poster(body)
        ok = bool(res) and 200 <= res[0] < 300
        with self.lock:
            if ok:
                try: history.append(history.user_line(batch), self.history_path)
                except Exception as e: log.warning("history append failed: %s", e)
                self.msgs = self.msgs[len(batch):]   # keep anything that arrived during the POST
                self.oldest = self.clock() if self.msgs else None
                self.next_try = 0
            else:
                self.next_try = self.clock() + RETRY_S
                log.error("flush failed; keeping %d pending, retry in %ds", len(self.msgs), RETRY_S)
            self._save()
        return ok

    def run(self, interval=1.0):
        while True:
            try: self.maybe_flush()
            except Exception as e: log.warning("flusher error: %s: %s", type(e).__name__, e)
            time.sleep(interval)

def handle(msgs, batcher):
    seen = load_seen()
    for m in msgs:
        if m.get("message_type") != 1: continue
        mid = m.get("message_id")
        if mid is not None and mid in seen: continue
        payload = build_payload(m)
        payload["prev_inbound_ms"] = m.get("_prev_inbound_ms")
        log.info("received message_id=%s from=%s types=%s files=%s", mid, m.get("from_user_id"),
                 payload["item_types"], payload.get("files"))
        batcher.add(payload)
        if mid is not None:
            seen = (seen + [mid])[-500:]
            json.dump(seen, open(SEEN, "w"))

def outbox_loop():
    """Flush queued sends right after the user writes; nudge near window end."""
    seen_last = None
    while True:
        try:
            last = outbox.last_inbound_s()
            if last and last != seen_last:
                seen_last = last
                time.sleep(3)           # let the user's message register first
                outbox.flush()
            outbox.maybe_nudge()
        except Exception as e:
            log.warning("outbox loop error: %s: %s", type(e).__name__, e)
        time.sleep(15)

def main():
    log.info("forwarder start pid=%d url_set=%s key_present=%s quiet=%ds cap=%ds", os.getpid(), bool(WEBHOOK_URL),
             bool(webhook_key()), QUIET_S, CAP_S)
    batcher = Batcher()
    threading.Thread(target=batcher.run, daemon=True, name="flusher").start()
    threading.Thread(target=outbox_loop, daemon=True, name="outbox").start()
    fails = 0
    while True:
        try: open(HEARTBEAT, "w").write(str(int(time.time())))   # "loop is alive" (not "network is fine")
        except OSError: pass
        try:
            ok, msgs = fetch()
            if ok:
                fails = 0
                if msgs: handle(msgs, batcher)
            else:
                fails += 1
                time.sleep(60 if fails >= 3 else 10)
        except Exception as e:
            log.warning("poll error: %s: %s", type(e).__name__, e)
            time.sleep(10)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(post_webhook({"source": "wechat-clawbot", "test": True,
                            "texts": ["(forwarder self-test, ignore)"]}, tries=1))
    else:
        main()
