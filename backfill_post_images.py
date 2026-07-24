"""One-shot / re-run: attach (or replace) 16:9 news thumbnails on LIVE posts.

Usage:
  python3 backfill_post_images.py              # only posts with no <img>
  python3 backfill_post_images.py --replace    # regenerate on posts that
                                               # already have post-thumb/post-hero
"""

from __future__ import annotations

import re
import sys
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials
from keyword_filter import classify
from post_images import (
    build_thumb_for_post,
    content_has_image,
    inject_thumb_html,
)
from trend_sources import NewsRef

REPLACE_EXISTING = "--replace" in sys.argv


def _guess_category(title: str) -> str:
    category, include_hits, _exclude = classify(title, [NewsRef(title=title)])
    if category and include_hits > 0:
        return category
    if any(k in title for k in ("주가", "증시", "코스닥", "코스피", "투자", "ETF", "근저당", "키미")):
        return "투자"
    if any(k in title for k in ("관세", "대출", "세금", "금융", "미소금융", "사이드카")):
        return "금융"
    if any(k in title for k in ("댐", "호우", "태풍", "화재", "대피")):
        return "생활안전"
    if any(k in title for k in ("판결", "구속", "소송", "법")):
        return "법률"
    return "금융"


def _keyword_from_title(title: str) -> str:
    head = title
    for sep in (", ", " - ", "…", "...", "？", "?"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
            break
    head = re.sub(r"\s*[\(（][^\)）]{0,24}[\)）]\s*$", "", head).strip()
    return head[:40] or title.strip()[:40]


def _needs_replace(content: str) -> bool:
    return bool(
        re.search(r'class="post-thumb"', content or "", flags=re.I)
        or re.search(r'class="post-hero"', content or "", flags=re.I)
    )


def main() -> None:
    creds = load_credentials()
    service = build("blogger", "v3", credentials=creds, cache_discovery=False)
    blogs = service.blogs().listByUser(userId="self").execute()
    blog_id = blogs["items"][0]["id"]

    request = service.posts().list(blogId=blog_id, maxResults=50, status="LIVE", fetchBodies=True)
    targets: list[dict] = []
    while request is not None:
        response = request.execute()
        for post in response.get("items") or []:
            content = post.get("content") or ""
            if REPLACE_EXISTING:
                if _needs_replace(content):
                    targets.append(post)
            elif not content_has_image(content):
                targets.append(post)
        request = service.posts().list_next(request, response)

    mode = "replace news thumbnails on" if REPLACE_EXISTING else "add news thumbnails to"
    print(f"[backfill_post_images] {mode} {len(targets)} LIVE post(s)", flush=True)

    updated = 0
    for idx, post in enumerate(targets, start=1):
        post_id = post["id"]
        title = post.get("title") or ""
        keyword = _keyword_from_title(title)
        category = _guess_category(title)
        print(
            f"[{idx}/{len(targets)}] {title!r} -> keyword={keyword!r} category={category}",
            flush=True,
        )
        try:
            url, main, sub = build_thumb_for_post(
                title=title,
                keyword=keyword,
                category=category,
                push=True,
                force=REPLACE_EXISTING,
            )
            print(f"  texts: main={main!r} sub={sub!r}", flush=True)
            new_content = inject_thumb_html(
                post.get("content") or "",
                url,
                main,
                replace_existing=REPLACE_EXISTING,
            )
            service.posts().patch(
                blogId=blog_id,
                postId=post_id,
                body={"content": new_content},
            ).execute()
            print(f"  updated: {post.get('url')}", flush=True)
            print(f"  thumb: {url}", flush=True)
            updated += 1
        except HttpError as exc:
            print(f"  patch failed HTTP {getattr(exc.resp, 'status', None)}: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}", flush=True)
        if idx < len(targets):
            time.sleep(1)

    print(f"[backfill_post_images] done - updated {updated}/{len(targets)}", flush=True)
    if updated == 0 and targets:
        sys.exit(1)


if __name__ == "__main__":
    main()
