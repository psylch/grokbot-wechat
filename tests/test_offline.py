"""Offline tests: no WeChat, no webhook, no network. Run: python3 -m unittest discover -s tests -v"""
import json, os, sys, tempfile, unittest
from datetime import datetime
from zoneinfo import ZoneInfo

TMP = tempfile.mkdtemp(prefix="bridge-test-")
os.environ["BRIDGE_DATA_DIR"] = TMP
os.environ.setdefault("OWNER_NAME", "Tester")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forward, outbox, media, history, ilink  # noqa: E402

BJ = ZoneInfo("Asia/Shanghai")
def bj(*a): return datetime(*a, tzinfo=BJ).timestamp()

class FakeClock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t

class BatcherTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(TMP, "pending-test.json"); self.hist = os.path.join(TMP, "hist-test.log")
        for p in (self.path, self.hist):
            if os.path.exists(p): os.remove(p)
        self.sent, self.clock = [], FakeClock()
    def poster(self, body): self.sent.append(body); return (200, "ok")
    def mk(self, **kw): return forward.Batcher(self.path, quiet=3, cap=60, poster=self.poster, clock=self.clock,
                                               history_path=self.hist, **kw)
    def msg(self, text, ms):
        return {"items": [{"type": 1, "text": text}], "texts": [text], "create_time_ms": ms, "message_id": ms}

    def test_quiet_flush_batches_burst(self):
        b = self.mk()
        b.add(self.msg("a", 1)); self.clock.t += 1; b.add(self.msg("b", 2))
        self.assertFalse(b.maybe_flush())
        self.clock.t += 3
        self.assertTrue(b.maybe_flush())
        self.assertEqual(self.sent[0]["count"], 2)
        self.assertEqual(self.sent[0]["trigger_ms"], 2)
        self.assertIn("--reply-to-ms 2", self.sent[0]["reply_rule"])
        self.assertIn("Tester：a b", open(self.hist).read())

    def test_failed_flush_is_kept_and_survives_restart(self):
        b = forward.Batcher(self.path, quiet=3, cap=60, poster=lambda body: None, clock=self.clock, history_path=self.hist)
        b.add(self.msg("x", 5)); self.clock.t += 5
        self.assertFalse(b.maybe_flush())
        self.assertEqual(len(json.load(open(self.path))["messages"]), 1)
        b2 = self.mk(); self.assertEqual(len(b2.msgs), 1)       # restored from disk

    def test_bare_one_after_long_silence_gets_context_note(self):
        b = self.mk(); m = self.msg("1", 50 * 3600 * 1000); m["prev_inbound_ms"] = 10 * 3600 * 1000
        b.add(m); self.clock.t += 5; b.maybe_flush()
        self.assertIn("renewing", self.sent[0].get("context_note", ""))

class NudgeTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        outbox.send_text = lambda text, **kw: (self.calls.append(text) or ("{}", False))
    def state(self, last):
        ilink.save_state({"last_inbound_ms": int(last * 1000)})
    def test_normal_window_nudges_at_18h(self):
        last = bj(2026, 10, 1, 18, 0); self.state(last)           # 18h later = 12:00 Beijing
        self.assertFalse(outbox.maybe_nudge(last + 17 * 3600))
        self.assertTrue(outbox.maybe_nudge(last + 18 * 3600 + 60))
        self.assertFalse(outbox.maybe_nudge(last + 19 * 3600))   # one nudge per window
    def test_quiet_hours_block(self):
        last = bj(2026, 10, 1, 9, 0); self.state(last)           # 18h later = 03:00 Beijing
        self.assertFalse(outbox.maybe_nudge(last + 18 * 3600))
    def test_nudges_early_before_quiet_hours(self):
        # last msg 08:00; 18-23h slot = 02:00-07:00 next day (all quiet) -> nudge ~23:30 the evening before
        last = bj(2026, 10, 1, 8, 0); self.state(last)
        self.assertFalse(outbox.maybe_nudge(bj(2026, 10, 1, 21, 0)))
        self.assertTrue(outbox.maybe_nudge(bj(2026, 10, 1, 23, 35)))

class MediaTest(unittest.TestCase):
    def test_decrypt_roundtrip_and_keys(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        import base64, binascii
        key = bytes(range(16)); data = b"\x89PNG fake image"
        pad = 16 - len(data) % 16; e = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        enc = e.update(data + bytes([pad]) * pad) + e.finalize()
        self.assertEqual(media.decrypt(enc, key), data)
        self.assertEqual(media.sniff_ext(data), "png")
        self.assertEqual(media.parse_key({"aeskey": key.hex()}), key)
        self.assertEqual(media.parse_key({"media": {"aes_key": base64.b64encode(key).decode()}}), key)
        self.assertEqual(media.parse_key({"media": {"aes_key": base64.b64encode(key.hex().encode()).decode()}}), key)
    def test_summarize_voice_transcript(self):
        s = media.summarize({"type": 3, "voice_item": {"text": "你好", "media": {"aes_key": "x"}}})
        self.assertEqual(s["text"], "你好"); self.assertNotIn("media", s["meta"])

if __name__ == "__main__":
    unittest.main()
