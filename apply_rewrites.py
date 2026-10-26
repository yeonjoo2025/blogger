#!/usr/bin/env python3
"""Patch all rewritten LIVE guides. Needs token.json in this directory."""
from __future__ import annotations

import re
import time
import urllib.request

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials
from rewrite_five import FACTORY, POSTS as FIVE, WANT_TITLE as FIVE_TITLES, factory_hits, plain
from rewrite_rest import POSTS as REST, TITLES, WANT_TITLE as REST_TITLES

BLOG_ID = "4736025457821775813"
POSTS = {**FIVE, **REST}
WANT_TITLE = {**FIVE_TITLES, **REST_TITLES}

LIVE_URL = {
    "952254718860090808": "https://yeondodo.blogspot.com/2026/08/ssg-839-60.html",
    "1443812505491527673": "https://yeondodo.blogspot.com/2026/08/opec-9-188.html",
    "2463554141315791031": "https://yeondodo.blogspot.com/2026/08/isa-2026.html",
    "2909365048267358341": "https://yeondodo.blogspot.com/2026/07/blog-post_2724.html",
    "4956430608006738565": "https://yeondodo.blogspot.com/2026/07/blog-post_21.html",
    "4863046033605649972": "https://yeondodo.blogspot.com/2026/08/1-8.html",
    "4093607406080187356": "https://yeondodo.blogspot.com/2026/07/blog-post_368.html",
    "9052985159577674175": "https://yeondodo.blogspot.com/2026/08/5.html",
    "8601843476871187862": "https://yeondodo.blogspot.com/2026/08/blog-post.html",
    "7242409839703786821": "https://yeondodo.blogspot.com/2026/07/hug.html",
    "8811987628887877688": "https://yeondodo.blogspot.com/2026/07/2026.html",
    "3883915663945913866": "https://yeondodo.blogspot.com/2026/07/2026_02108530232.html",
    "3161488937629526277": "https://yeondodo.blogspot.com/2026/07/blog-post_23.html",
    "7319862352980141793": "https://yeondodo.blogspot.com/2026/07/blog-post_389.html",
}


def fetch_thumb(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<img[^>]+class="[^"]*post-thumb[^"]*"[^>]+src="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'<div class=\'post-body[^>]*>.*?<img[^>]+src="([^"]+)"', html, flags=re.S)
    return m.group(1) if m else ""


def with_thumb(html: str, src: str) -> str:
    if not src:
        return html
    if re.search(r'<img[^>]+src="https?://', html):
        return html
    return re.sub(
        r"<img class=\"post-thumb\"([^>]*)/>",
        f'<img class="post-thumb" src="{src}"\\1/>',
        html,
        count=1,
    )


def main() -> None:
    thumbs = {}
    for pid, url in LIVE_URL.items():
        try:
            thumbs[pid] = fetch_thumb(url)
            print(f"THUMB {pid} {'ok' if thumbs[pid] else 'none'}")
        except Exception as e:
            print(f"THUMB fail {pid} {e}")
            thumbs[pid] = ""

    for pid, html in POSTS.items():
        html = with_thumb(html, thumbs.get(pid, ""))
        POSTS[pid] = html
        text = plain(html)
        hits = factory_hits(html)
        print(f"LOCAL {pid} chars={len(text)} factory={hits or 'none'}")
        if len(text) < 1500:
            raise SystemExit(f"too short {pid} {len(text)}")
        if hits:
            raise SystemExit(f"factory left {pid} {hits}")

    creds = load_credentials()
    svc = build("blogger", "v3", credentials=creds, cache_discovery=False)

    for pid, html in POSTS.items():
        try:
            cur = svc.posts().get(blogId=BLOG_ID, postId=pid).execute()
        except HttpError as e:
            print(f"SKIP {pid} get-fail {e.resp.status}")
            continue
        status = (cur.get("status") or "").upper()
        title = cur.get("title") or ""
        if status != "LIVE":
            print(f"SKIP {pid} status={status} | {title[:40]}")
            continue
        if not any(k in title for k in (WANT_TITLE[pid],)):
            print(f"SKIP {pid} title-mismatch | {title[:50]}")
            continue
        body = {"content": html}
        if pid in TITLES:
            body["title"] = TITLES[pid]
        r = svc.posts().patch(blogId=BLOG_ID, postId=pid, body=body).execute()
        saved = r.get("content") or ""
        hits = factory_hits(saved)
        print(
            f"PATCH {r.get('id')} | {r.get('title')} | "
            f"chars={len(plain(saved))} | factory_gone={not hits} {hits or ''}"
        )
        time.sleep(0.4)


if __name__ == "__main__":
    main()
