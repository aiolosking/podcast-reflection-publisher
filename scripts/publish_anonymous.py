#!/usr/bin/env python3
"""Publish a self-contained HTML to an anonymous temporary host (no account needed).

Default route: litterbox.catbox.moe — 72h (3 days) retention, serves the file with
Content-Type: text/html so the link renders as a web page for anyone, no login.
Prints LLM-friendly stdout (no tracebacks). Exit 0 on success, 1 on failure.

Usage:
    python publish_anonymous.py article.html [--expire 72h] [--name slug.html] [--retries 4]
"""
import argparse
import hashlib
import io
import os
import re
import sys
import time

import requests

API = "https://litterbox.catbox.moe/resources/internals/api.php"
UA = {"User-Agent": "curl/8.4.0"}
VALID_EXPIRE = ("1h", "12h", "24h", "72h")


def log(msg):
    print(msg, flush=True)


def ascii_name(path, override):
    if override:
        return override
    base = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1] or ".html"
    slug = re.sub(r"[^A-Za-z0-9-]+", "-", base).strip("-").lower() or "article"
    return slug + ext


def main():
    ap = argparse.ArgumentParser(description="Upload a standalone HTML to an anonymous 72h host.")
    ap.add_argument("file", help="path to the self-contained HTML to publish")
    ap.add_argument("--expire", default="72h", choices=VALID_EXPIRE, help="retention (default 72h = 3 days)")
    ap.add_argument("--name", default=None, help="ASCII upload filename (avoid non-ASCII in multipart)")
    ap.add_argument("--api", default=API, help="override upload endpoint")
    ap.add_argument("--retries", type=int, default=6)
    a = ap.parse_args()

    try:
        with open(a.file, "rb") as fh:
            payload = fh.read()
    except OSError as e:
        log("FAIL read: %s" % e)
        return 1
    md5 = hashlib.md5(payload).hexdigest()
    name = ascii_name(a.file, a.name)
    log("local bytes: %d" % len(payload))
    log("upload name: %s expire: %s" % (name, a.expire))

    url = None
    for i in range(1, a.retries + 1):
        try:
            # Fresh session + Connection: close each attempt: this network intermittently
            # aborts TLS mid-handshake (UNEXPECTED_EOF_WHILE_READING); never reuse a dead conn.
            sess = requests.Session()
            hdrs = dict(UA)
            hdrs["Connection"] = "close"
            r = sess.post(
                a.api,
                data={"reqtype": "fileupload", "time": a.expire},
                files={"fileToUpload": (name, io.BytesIO(payload), "text/html")},
                headers=hdrs,
                timeout=600,
            )
            t = r.text.strip()
            if r.status_code == 200 and t.startswith("http"):
                url = t
                log("upload ok (attempt %d)" % i)
                break
            log("attempt %d bad response: %d %s" % (i, r.status_code, t[:100]))
        except Exception as e:
            log("attempt %d error: %s" % (i, type(e).__name__))
        finally:
            try:
                sess.close()
            except Exception:
                pass
        time.sleep(min(2 ** i, 30))
    if not url:
        log("FAIL upload: all %d attempts failed" % a.retries)
        return 1
    log("URL: %s" % url)

    try:
        g = requests.get(url, headers=UA, timeout=180)
        ct = g.headers.get("Content-Type", "")
        ok_ct = "text/html" in ct
        ok_len = len(g.content) == len(payload)
        ok_md5 = hashlib.md5(g.content).hexdigest() == md5
        log("verify status: %d" % g.status_code)
        log("verify content-type: %s renders_html: %s" % (ct, ok_ct))
        log("verify bytes_match: %s md5_match: %s" % (ok_len, ok_md5))
        if g.status_code == 200 and ok_ct and ok_len and ok_md5:
            log("SUCCESS %s" % url)
            return 0
        log("FAIL verify: served copy mismatch or not rendered as html")
        return 1
    except Exception as e:
        log("FAIL verify: %s" % type(e).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
