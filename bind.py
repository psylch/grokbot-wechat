#!/usr/bin/env python3
"""WeChat ClawBot binding via iLink (method from chihao.li/blog/en/wechat-clawbot-ilink-protocol).
Fetches QR -> renders qr.png (+ qr_url.txt) -> long-polls status -> saves credentials.json on confirm.
Scan qr.png with the WeChat account that has the ClawBot plugin enabled (iOS WeChat 8.0.70+ at the time).
Auto-refreshes QR (overwrites qr.png) on expiry. If phone shows a number (need_verifycode),
write it into verify_code.txt in this dir."""
import json, os, sys, time, urllib.request, urllib.parse, datetime
import qrcode

BASE = "https://ilinkai.weixin.qq.com"
from config import DATA_DIR as DIR   # credentials.json / qr.png land here
HDRS = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 9),
        "Content-Type": "application/json"}
MAX_REFRESH = int(os.environ.get("MAX_REFRESH", "10"))

def log(*a):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)

def req(url, data=None, timeout=40):
    r = urllib.request.Request(url, data=data, headers=HDRS, method="POST" if data else "GET")
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode())

def new_qr():
    j = req(f"{BASE}/ilink/bot/get_bot_qrcode?bot_type=3", json.dumps({"local_token_list": []}).encode())
    url = j["qrcode_img_content"]
    q = qrcode.QRCode(box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url); q.make(fit=True)
    tmp = os.path.join(DIR, "qr.tmp.png"); q.make_image().save(tmp); os.replace(tmp, os.path.join(DIR, "qr.png"))
    with open(os.path.join(DIR, "qr_url.txt"), "w") as f: f.write(url + "\n")
    log("NEW QR:", url, "(saved qr.png)")
    return j["qrcode"]

def main():
    qr = new_qr(); base = BASE; refreshes = 0; verify = None; last = None
    while True:
        ep = f"{base}/ilink/bot/get_qrcode_status?qrcode={urllib.parse.quote(qr)}"
        if verify: ep += f"&verify_code={urllib.parse.quote(verify)}"
        try:
            s = req(ep, timeout=40)
        except Exception as e:
            s = {"status": "wait", "_err": str(e)}
        st = s.get("status")
        if st != last: log("status:", st); last = st
        if st == "confirmed":
            path = os.path.join(DIR, "credentials.json")
            with open(path, "w") as f: json.dump(s, f, indent=2)
            os.chmod(path, 0o600)
            log("BOUND OK ilink_bot_id=", s.get("ilink_bot_id"), "saved", path); return 0
        if st == "binded_redirect":
            log("Already bound (binded_redirect)"); return 0
        if st == "scaned_but_redirect" and s.get("redirect_host"):
            base = "https://" + s["redirect_host"]; log("redirect ->", base)
        if st == "scaned": verify = None
        if st == "need_verifycode":
            vf = os.path.join(DIR, "verify_code.txt")
            log("Phone shows a number: write it to", vf)
            while not (os.path.exists(vf) and open(vf).read().strip()): time.sleep(2)
            verify = open(vf).read().strip(); os.remove(vf); continue
        if st in ("expired", "verify_code_blocked"):
            refreshes += 1
            if refreshes > MAX_REFRESH: log("too many refreshes, giving up"); return 1
            qr = new_qr(); base = BASE; verify = None
        time.sleep(1)

if __name__ == "__main__":
    sys.exit(main())
