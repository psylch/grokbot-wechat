#!/usr/bin/env python3
"""Send a text to the bound WeChat user. This is what the agent calls to reply.
Usage: python3 send.py "text" [--to USER_ID] [--no-context] [--app] [--reply-to-ms MS]
--reply-to-ms: the trigger_ms of the WeChat batch this reply answers. If the user has sent a newer
  message since, nothing is sent and the exit code is 4 (SUPERSEDED): the newer run will answer.
--app: prefix APP_PREFIX (default "[grok bot] ") for pushes not triggered by the WeChat webhook
  (reminders, routine output), so the user can tell them apart from replies.
If WeChat refuses (the ~24h window since the user's last message has closed), the text is queued in
outbox.json (exit code 3) and forward.py sends it automatically the next time the user writes.
Exit codes: 0 sent, 3 queued, 4 superseded."""
import argparse, sys
import outbox
from config import APP_PREFIX, OWNER_NAME
p = argparse.ArgumentParser(); p.add_argument("text"); p.add_argument("--to"); p.add_argument("--no-context", action="store_true")
p.add_argument("--app", action="store_true", help="prefix APP_PREFIX for sends not triggered by the WeChat webhook")
p.add_argument("--reply-to-ms", type=int)
a = p.parse_args()
if a.reply_to_ms is not None:
    last = outbox.last_inbound_s()
    if last and last * 1000 > a.reply_to_ms + 500:
        print("SUPERSEDED: %s sent a newer message; not sending. Stop this run without filing anything." % OWNER_NAME)
        sys.exit(4)
text = (APP_PREFIX + a.text) if a.app else a.text
sent, resp = outbox.send_or_queue(text, to=a.to, context_token="" if a.no_context else None)
print("sent:" if sent else "QUEUED (will auto-send when the user next writes):", resp)
sys.exit(0 if sent else 3)
