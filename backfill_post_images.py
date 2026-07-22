"""One-shot: add a generated hero image to every LIVE post that has none.

Uses the same generate → Blogger resumable upload → posts.patch() path as
the publish_trend automation, so the result matches what future runs produce.
"""

from __future__ import annotations

import re
import sys
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials
from keyword_filter import classify
from post_images import build_and_host_hero, content_has_image, inject_hero_image
from trend_sources import NewsRef

# Re-run mode: replace existing heroes (used when regenerating thumbnail style).
REPLACE_EXISTING = "--replace" in sys.argv


def _guess_category(title: str) -> str:
    category, include_hits, _exclude = classify(title, [NewsRef(title=title)])
    if category and include_hits > 0:
        return category
    # Lightweight fallbacks for titles our filter lexicon doesn't cover.
    lowered = title.lower()
    if any(k in title for k in ("주가", "증시", "코스닥", "코스피", "투자", "ETF", "근저당")):
        return "투자"
    if any(k in title for k in ("관세", "대출", "세금", "금융", "미소금융")):
        return "금융"
    if any(k in title for k in ("댐", "호우", "태풍", "화재", "대피")):
        return "생활안전"
    if any(k in title for k in ("판결", "구속", "소송", "법")):
        return "법률"
    if any(k in lowered for k in ("messi", "kt", "두산", "월드컵", "야구", "축구")):
        return "생활안전"
    return "금융"


def _keyword_from_title(title: str) -> str:
    # Prefer the phrase before the first topical separator used by our
    # pipeline titles. Use ", " (comma+space) rather than bare "," so that
    # amounts like "(2,000억원)" are not truncated mid-parenthesis.
    head = title
    for sep in (", ", " - ", "…", "...", "？", "?"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
            break
    # Drop trailing parenthetical angle crumbs like "(3개월)" / "(2,000억원)"
    # so the card-news title stays punchy.
    head = re.sub(r"\s*[\(（][^\)）]{0,24}[\)）]\s*$", "", head).strip()
    return head[:40] or title.strip()[:40]


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
                # Only touch posts that already carry our generated hero, so we
                # don't overwrite manually curated images on older posts.
                if 'class="post-hero"' in content or "post-hero" in content:
                    targets.append(post)
            elif not content_has_image(content):
                targets.append(post)
        request = service.posts().list_next(request, response)

    mode = "replace card-news thumbnails on" if REPLACE_EXISTING else "add images to"
    print(f"[backfill_post_images] {mode} {len(targets)} LIVE post(s)", flush=True)
    updated = 0
    for idx, post in enumerate(targets, start=1):
        post_id = post["id"]
        title = post.get("title") or ""
        keyword = _keyword_from_title(title)
        category = _guess_category(title)
        print(f"[{idx}/{len(targets)}] {title!r} -> keyword={keyword!r} category={category}", flush=True)
        try:
            url = build_and_host_hero(creds, keyword, category)
            new_content = inject_hero_image(
                post.get("content") or "",
                url,
                alt=keyword,
                replace_existing=REPLACE_EXISTING,
            )
            service.posts().patch(
                blogId=blog_id,
                postId=post_id,
                body={"content": new_content},
            ).execute()
            print(f"  updated: {post.get('url')}", flush=True)
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
