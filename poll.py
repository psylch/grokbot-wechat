#!/usr/bin/env python3
"""Debug tool: fetch updates once (long-poll ~35s). Saves cursor + latest context_token per user to state.json.
WARNING: do NOT run this while forward.py is running. getupdates is cursor-based; whatever poll.py
consumes is gone for forward.py (the messages never reach the agent).
Usage: python3 poll.py [--loop]"""
import json, sys, socket
from ilink import post, load_state, save_state

def once():
    st = load_state()
    try:
        raw = post("ilink/bot/getupdates", {"get_updates_buf": st.get("get_updates_buf", "")}, timeout=40)
    except (socket.timeout, TimeoutError):
        print("(timeout, no messages)"); return []
    r = json.loads(raw)
    if r.get("ret", 0) != 0: print("ERROR:", raw); return []
    if r.get("get_updates_buf"): st["get_updates_buf"] = r["get_updates_buf"]
    msgs = r.get("msgs") or []
    for m in msgs:
        texts = [(i.get("text_item") or i.get("voice_item") or {}).get("text") for i in m.get("item_list") or []]
        print(json.dumps({"from_user_id": m.get("from_user_id"), "message_type": m.get("message_type"),
                          "texts": texts, "context_token": m.get("context_token"),
                          "create_time_ms": m.get("create_time_ms")}, ensure_ascii=False))
        if m.get("message_type") == 1 and m.get("from_user_id"):
            st["last_from_user_id"] = m["from_user_id"]
            if m.get("context_token"):
                st.setdefault("context_tokens", {})[m["from_user_id"]] = m["context_token"]
    st.setdefault("raw_log", []); st["raw_log"] = (st["raw_log"] + msgs)[-20:]
    save_state(st)
    if not msgs: print("(no messages)")
    return msgs

if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True: once()
    else: once()
