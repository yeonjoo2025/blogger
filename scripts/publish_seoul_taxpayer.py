#!/usr/bin/env python3
"""Publish Seoul model-taxpayer post: insert, else patch empty LIVE/DRAFT."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blogger_http import build_blogger_service
from blogger_quality import MIN_LABELS, sanitize_labels, validate_post
from publish_from_posts import md_to_blogger_html, parse_frontmatter, parse_labels

BLOG_ID = "4736025457821775813"
POST_PATH = ROOT / "posts" / "2026-07-24-seoul-model-taxpayer-benefits.md"
EMPTY_TITLE_RE = re.compile(r"^(신규|임시|제목\s*없음|untitled)?$", re.I)


def is_nearly_empty(content: str | None) -> bool:
    text = re.sub(r"<[^>]+>", " ", content or "")
    text = re.sub(r"&nbsp;|\s+", "", text)
    return len(text) < 40


def list_posts(service, status: str, max_pages: int = 5):
    items = []
    token = None
    for _ in range(max_pages):
        kwargs = {
            "blogId": BLOG_ID,
            "status": status,
            "maxResults": 50,
            "fetchBodies": True,
            "orderBy": "PUBLISHED" if status == "LIVE" else "UPDATED",
        }
        if token:
            kwargs["pageToken"] = token
        if status == "DRAFT":
            kwargs["view"] = "ADMIN"
        resp = service.posts().list(**kwargs).execute()
        items.extend(resp.get("items") or [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def find_empty_post(service):
    for status in ("LIVE", "DRAFT"):
        try:
            posts = list_posts(service, status)
        except Exception as exc:
            print(f"list {status} failed: {exc}")
            continue
        for post in posts:
            title = (post.get("title") or "").strip()
            content = post.get("content") or ""
            if EMPTY_TITLE_RE.match(title) or is_nearly_empty(content):
                if is_nearly_empty(content) or EMPTY_TITLE_RE.match(title):
                    print(
                        f"candidate {status} id={post.get('id')} title={title!r} "
                        f"content_len={len(content)}"
                    )
                    if is_nearly_empty(content):
                        return post, status
    return None, None


def main() -> None:
    meta, body = parse_frontmatter(POST_PATH.read_text(encoding="utf-8"))
    title = meta["title"]
    labels = sanitize_labels(parse_labels(meta.get("labels", "")), keyword=title)
    result, labels, cat = validate_post(title=title, body=body, labels=labels, keyword=title)
    for line in result.log_lines():
        print(line)
    if not result.ok:
        raise SystemExit("quality gate failed")
    if len(labels) < MIN_LABELS:
        raise SystemExit(f"labels too few: {len(labels)}")

    # Prefer shorter label set for Blogger patch budget (~70 chars practical)
    short_labels = []
    total = 0
    for lab in labels:
        add = len(lab) + (1 if short_labels else 0)
        if total + add > 70:
            continue
        short_labels.append(lab)
        total += add
    if len(short_labels) < 8:
        short_labels = labels[:12]
    print("labels_for_api", short_labels, "chars", sum(len(x) for x in short_labels) + max(0, len(short_labels) - 1))

    content = md_to_blogger_html(body)
    # Ensure thumb has required style attrs
    content = content.replace(
        '<p><img class="post-thumb"',
        '<p><img class="post-thumb"',
    )
    content = re.sub(
        r'(<img class="post-thumb" src="[^"]+" alt="[^"]*")\s*/>',
        r'\1 style="display:block;width:100%;max-width:100%;height:auto;margin:0 0 1em 0;border:0;" />',
        content,
        count=1,
    )

    service = build_blogger_service()
    post_body = {
        "kind": "blogger#post",
        "blog": {"id": BLOG_ID},
        "title": title,
        "content": content,
        "labels": short_labels,
    }

    try:
        post = service.posts().insert(blogId=BLOG_ID, body=post_body, isDraft=False).execute()
        print("INSERT_OK")
        print("URL:", post.get("url"))
        print("ID:", post.get("id"))
        return
    except Exception as exc:
        print("INSERT_FAIL:", type(exc).__name__, str(exc)[:300])

    empty, status = find_empty_post(service)
    if not empty:
        print("NO_EMPTY_POST")
        raise SystemExit(2)

    post_id = empty["id"]
    print(f"PATCHING {status} {post_id}")

    # Patch title+content first, then labels
    try:
        patched = (
            service.posts()
            .patch(
                blogId=BLOG_ID,
                postId=post_id,
                body={"title": title, "content": content, "labels": short_labels},
            )
            .execute()
        )
    except Exception as exc:
        print("combined patch failed:", str(exc)[:300])
        patched = (
            service.posts()
            .patch(blogId=BLOG_ID, postId=post_id, body={"title": title, "content": content})
            .execute()
        )
        try:
            patched = (
                service.posts()
                .patch(blogId=BLOG_ID, postId=post_id, body={"labels": short_labels})
                .execute()
            )
        except Exception as lab_exc:
            print("labels patch failed:", str(lab_exc)[:300])

    if status == "DRAFT":
        patched = service.posts().publish(blogId=BLOG_ID, postId=post_id).execute()
        print("PUBLISHED_FROM_DRAFT")

    print("PATCH_OK")
    print("URL:", patched.get("url"))
    print("ID:", patched.get("id"))
    print("TITLE:", patched.get("title"))
    print("labels", patched.get("labels"))


if __name__ == "__main__":
    main()
