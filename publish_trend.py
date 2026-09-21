#!/usr/bin/env python3
"""Trend → Blogger publish pipeline with quality/quota/CDN thumbnail gates.

Typical agent flow:
1) Write pending_posts/{slug}.md (frontmatter title/labels + markdown body)
2) python3 fetch_stats.py
3) python3 publish_trend.py --slug {slug}
4) If exit 2: GenerateImage → save plate → re-run publish_trend.py
5) Script converts plate→jpg, git commit/push thumb, patches Blogger with CDN URL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from blogger_http import build_blogger_service
from blogger_quality import (
    MIN_LABELS,
    TARGET_LABELS,
    is_hard_skip,
    sanitize_labels,
    validate_post,
)
from blogger_quota import can_publish, load_state, record_publish
from fetch_stats import category_boost, load_stats, save_stats
from publish_from_posts import md_to_blogger_html, parse_frontmatter, parse_labels

BLOG_ID = os.environ.get("BLOGGER_BLOG_ID", "4736025457821775813")
REPO = os.environ.get("BLOGGER_GITHUB_REPO", "yeonjoo2025/blogger")
PENDING_DIR = Path("pending_posts")
GEN_DIR = Path("generated_images")
IMG_DIR = Path("posts/images")
POSTS_DIR = Path("posts")
REQUIRE_AI_THUMB = os.environ.get("BLOGGER_REQUIRE_AI_THUMB", "1") != "0"
ALLOW_PILLOW = os.environ.get("BLOGGER_ALLOW_PILLOW_THUMB", "") == "1"
AUTO_GIT_PUSH = os.environ.get("BLOGGER_AUTO_GIT_PUSH", "1") != "0"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9가-힣]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or "post"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def git_head_sha() -> str:
    return run(["git", "rev-parse", "HEAD"]).stdout.strip()


def ensure_jpg_thumb(slug: str) -> Path | None:
    """Return posts/images/thumb-{slug}.jpg if AI plate exists or jpg already present."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    jpg = IMG_DIR / f"thumb-{slug}.jpg"
    if jpg.exists() and jpg.stat().st_size > 10_000:
        return jpg

    plate_candidates = [
        GEN_DIR / f"ai-thumb-{slug}.png",
        GEN_DIR / f"ai-thumb-{slug}.jpg",
        GEN_DIR / f"ai-thumb-{slug}.jpeg",
    ]
    plate = next((p for p in plate_candidates if p.exists()), None)
    if not plate:
        return None

    # Prefer sips on macOS; fall back to Pillow if available.
    try:
        run(["sips", "-s", "format", "jpeg", "-Z", "1600", str(plate), "--out", str(jpg)])
        if jpg.exists():
            return jpg
    except Exception:
        pass

    try:
        from PIL import Image

        img = Image.open(plate).convert("RGB")
        img.save(jpg, "JPEG", quality=88, optimize=True)
        return jpg
    except Exception as exc:
        print(f"THUMB_CONVERT_FAIL={exc}")
        return None


def cdn_url(sha: str, slug: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/posts/images/thumb-{slug}.jpg"


def push_thumb(slug: str, md_path: Path | None = None) -> str:
    jpg = IMG_DIR / f"thumb-{slug}.jpg"
    if not jpg.exists():
        raise SystemExit(f"Missing thumb jpg: {jpg}")
    paths = [str(jpg)]
    if md_path and md_path.exists():
        paths.append(str(md_path))
    run(["git", "add", *paths])
    # commit only if staged changes exist
    staged = run(["git", "diff", "--cached", "--name-only"], check=False)
    if staged.stdout.strip():
        msg = f"Add thumb for {slug}."
        run(["git", "commit", "-m", msg], check=False)
    if AUTO_GIT_PUSH:
        push = run(["git", "push", "origin", "HEAD"], check=False)
        if push.returncode != 0:
            print("GIT_PUSH_WARN=", push.stderr.strip()[:400])
    return git_head_sha()


def _list_posts(service, blog_id: str, status: str, *, fetch_bodies: bool, limit: int = 50) -> list[dict]:
    resp = (
        service.posts()
        .list(
            blogId=blog_id,
            status=status,
            maxResults=limit,
            fetchBodies=fetch_bodies,
            view="ADMIN",
        )
        .execute()
    )
    return list(resp.get("items") or [])


def find_empty_shell(service, blog_id: str) -> dict | None:
    for status in ("DRAFT", "LIVE"):
        for post in _list_posts(service, blog_id, status, fetch_bodies=True, limit=50):
            title = (post.get("title") or "").strip()
            content = post.get("content") or ""
            text = re.sub(r"<[^>]+>", "", content).strip()
            if title in {"", "신규", "빈 포스트", "Untitled", "새 게시물", "새 포스트"} or len(text) < 30:
                return post
    return None


def find_reusable_draft(service, blog_id: str) -> dict | None:
    """Prefer DRAFT slots that are safe to overwrite when insert is blocked.

    Priority:
    1) DRAFT whose title already exists as LIVE (duplicate leftover)
    2) DRAFT matching hard-skip sports/entertainment topics
    3) Oldest DRAFT as last resort
    """
    drafts = _list_posts(service, blog_id, "DRAFT", fetch_bodies=True, limit=50)
    if not drafts:
        return None
    live_titles = {
        (p.get("title") or "").strip()
        for p in _list_posts(service, blog_id, "LIVE", fetch_bodies=False, limit=50)
    }
    for post in drafts:
        title = (post.get("title") or "").strip()
        if title and title in live_titles:
            print(f"REUSE_DRAFT_REASON=duplicate_of_live title={title[:60]}")
            return post
    for post in drafts:
        title = (post.get("title") or "").strip()
        skip, why = is_hard_skip(title, title)
        if skip:
            print(f"REUSE_DRAFT_REASON=hard_skip_topic why={why[:80]}")
            return post
    oldest = sorted(drafts, key=lambda p: p.get("published") or p.get("updated") or "")[0]
    print(
        "REUSE_DRAFT_REASON=oldest_draft "
        f"title={(oldest.get('title') or '')[:60]}"
    )
    return oldest


def fit_labels_for_blogger(labels: list[str], *, minimum: int = MIN_LABELS) -> list[str]:
    """Blogger often rejects exactly 20 labels on patch/update; prefer 15~19."""
    cleaned = [x for x in labels if x][:TARGET_LABELS]
    if len(cleaned) > 19:
        cleaned = cleaned[:19]
    if len(cleaned) < minimum:
        return cleaned
    return cleaned


def now_published_rfc3339() -> str:
    """KST publish timestamp for draft→LIVE, e.g. 2026-07-26T22:40:33+09:00."""
    kst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    stamp = kst.strftime("%Y-%m-%dT%H:%M:%S%z")
    return stamp[:-2] + ":" + stamp[-2:]


def recent_titles(service, blog_id: str, limit: int = 20) -> list[str]:
    return [
        p.get("title") or ""
        for p in _list_posts(service, blog_id, "LIVE", fetch_bodies=False, limit=limit)
    ]


def emit_thumb_required(slug: str, title: str) -> None:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    save_path = GEN_DIR / f"ai-thumb-{slug}.png"
    headline = title.split(",")[0][:28]
    prompt = (
        f"Cinematic photorealistic 16:9 Korean tech/news blog thumbnail. "
        f"Scene matching topic '{title}'. Natural Korean headline text in-frame: '{headline}'. "
        f"Small watermark '@욘두두' bottom-right. No logos, no celebrity faces, no fake numbers, "
        f"no bottom banner overlay, no purple glow UI, no abstract charts."
    )
    print("AI_THUMB_REQUIRED")
    print(f"REQUIRED_SLUG={slug}")
    print(f"REQUIRED_SAVE_PATH={save_path}")
    print("REQUIRED_IMAGE_PROMPT_BEGIN")
    print(prompt)
    print("REQUIRED_IMAGE_PROMPT_END")
    raise SystemExit(2)


def load_pending(slug: str) -> tuple[Path, dict[str, str], str]:
    path = PENDING_DIR / f"{slug}.md"
    if not path.exists():
        # also allow posts/ draft path via --md
        raise SystemExit(f"Missing pending markdown: {path}")
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    if not meta.get("title"):
        raise SystemExit("pending markdown missing title frontmatter")
    return path, meta, body


def build_content(body: str, thumb: str) -> str:
    # Remove local/relative thumb markdown; inject CDN img at top.
    body = re.sub(r"!\[.*?\]\((?:images/)?thumb-[^)]+\)\s*", "", body)
    body = re.sub(r"!\[.*?\]\(https://cdn\.jsdelivr\.net/[^)]+thumb-[^)]+\)\s*", "", body)
    html = md_to_blogger_html(body)
    if "data:image" in html:
        raise SystemExit("data URI images forbidden")
    thumb_html = (
        f'<p><img class="post-thumb" src="{thumb}" '
        f'alt="post thumbnail" /></p>'
    )
    return thumb_html + html


def _apply_to_post(
    service,
    blog_id: str,
    post: dict,
    *,
    title: str,
    content: str,
    labels: list[str],
    set_published_now: bool,
) -> dict:
    """Update an existing post/draft; publish drafts with current publish time."""
    post_id = post["id"]
    status = (post.get("status") or "").upper()
    labels = fit_labels_for_blogger(labels)
    published_at = now_published_rfc3339() if set_published_now else None
    print(f"USING_SHELL={post_id} status={status}")
    if published_at:
        print(f"PUBLISH_AT={published_at}")

    # Prefer update with full resource; fall back to patch; shrink labels on 400.
    current = (
        service.posts()
        .get(blogId=blog_id, postId=post_id, view="ADMIN")
        .execute()
    )
    last_err: Exception | None = None
    for n in range(min(19, len(labels)), MIN_LABELS - 1, -1):
        trial = labels[:n]
        body = {
            **current,
            "kind": "blogger#post",
            "blog": {"id": blog_id},
            "title": title,
            "content": content,
            "labels": trial,
        }
        if published_at and status == "DRAFT":
            body["published"] = published_at
        try:
            service.posts().update(blogId=blog_id, postId=post_id, body=body).execute()
            labels = trial
            print(f"labels_count_applied={len(trial)}")
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001 - API probe
            last_err = exc
            continue
    if last_err is not None:
        # Final attempt: patch without published field.
        service.posts().patch(
            blogId=blog_id,
            postId=post_id,
            body={"title": title, "content": content, "labels": labels[:MIN_LABELS]},
        ).execute()
        print(f"labels_count_applied={MIN_LABELS}")

    if status == "DRAFT":
        return service.posts().publish(blogId=blog_id, postId=post_id).execute()
    return (
        service.posts()
        .patch(
            blogId=blog_id,
            postId=post_id,
            body={"title": title, "content": content, "labels": labels},
        )
        .execute()
    )


def publish_or_patch(service, blog_id: str, title: str, content: str, labels: list[str]) -> dict:
    labels = fit_labels_for_blogger(labels)
    shell = find_empty_shell(service, blog_id)
    if shell:
        return _apply_to_post(
            service,
            blog_id,
            shell,
            title=title,
            content=content,
            labels=labels,
            set_published_now=True,
        )

    body = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
        "labels": labels,
    }
    try:
        return service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
    except Exception as exc:
        print(f"INSERT_FAIL={exc}")
        reusable = find_reusable_draft(service, blog_id)
        if not reusable:
            print("생성/업데이트 없이 종료 (insert blocked and no reusable draft)")
            raise SystemExit(0) from exc
        print(f"FALLBACK_REUSE_DRAFT={reusable.get('id')}")
        return _apply_to_post(
            service,
            blog_id,
            reusable,
            title=title,
            content=content,
            labels=labels,
            set_published_now=True,
        )


def maybe_score_with_stats(category: str) -> None:
    stats = load_stats()
    boost = category_boost(category, stats)
    pv = (stats.get("pageviews") or {}).get("ALL_TIME")
    print(f"STATS_PAGEVIEWS_ALL={pv}")
    print(f"STATS_CATEGORY_BOOST={category}:{boost}")
    print(f"STATS_CATEGORY_COUNTS={(stats.get('content') or {}).get('category_counts')}")
    if boost <= -5:
        raise SystemExit(f"SKIP_LOW_STATS_CATEGORY: {category}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one trend post with gates")
    parser.add_argument("--slug", help="pending_posts/{slug}.md")
    parser.add_argument("--md", help="Explicit markdown path")
    parser.add_argument("--keyword", default="", help="Source keyword for logs")
    parser.add_argument("--refresh-stats", action="store_true", help="Refresh stats first")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.refresh_stats or not Path(".blogger_stats.json").exists():
        print("Refreshing stats...")
        save_stats()

    if args.md:
        md_path = Path(args.md)
        meta, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        slug = args.slug or slugify(meta.get("title") or md_path.stem)
    elif args.slug:
        md_path, meta, body = load_pending(args.slug)
        slug = args.slug
    else:
        # list pending and pick first
        PENDING_DIR.mkdir(exist_ok=True)
        pending = sorted(PENDING_DIR.glob("*.md"))
        if not pending:
            print("NO_PENDING_POST")
            print("Write pending_posts/{slug}.md then re-run.")
            raise SystemExit(0)
        md_path = pending[0]
        meta, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        slug = md_path.stem

    title = meta["title"]
    keyword = args.keyword or meta.get("keyword") or title
    labels_in = parse_labels(meta.get("labels", ""))

    skip, why = is_hard_skip(keyword, title)
    if skip:
        print(f"SKIP_HARD_FILTER: {why}")
        raise SystemExit(0)

    service = build_blogger_service()
    titles = recent_titles(service, BLOG_ID)
    result, labels, category = validate_post(
        title=title,
        body=body,
        labels=labels_in,
        recent_titles=titles,
        keyword=keyword,
    )
    for line in result.log_lines():
        print(line)
    print(f"PICK_KEYWORD={keyword}")
    print(f"PICK_CATEGORY={category}")
    print(f"LABELS_COUNT={len(labels)}")

    maybe_score_with_stats(category)

    ok_quota, quota_reason = can_publish(category)
    print(f"QUOTA_CHECK={quota_reason}")
    if not ok_quota:
        print(f"SKIP_QUOTA: {quota_reason}")
        raise SystemExit(0)

    if not result.ok:
        print(f"SKIP_LOW_USEFULNESS: {keyword} score={result.score}")
        raise SystemExit(0)

    if len(labels) < MIN_LABELS:
        labels = sanitize_labels(labels + labels_in, keyword=keyword, category=category)
    if len(labels) < MIN_LABELS:
        print(f"SKIP_LABELS: only {len(labels)} after sanitize (need {MIN_LABELS}+)")
        raise SystemExit(0)
    labels = fit_labels_for_blogger(labels)

    # Thumbnail gate
    if REQUIRE_AI_THUMB and not ALLOW_PILLOW:
        jpg = ensure_jpg_thumb(slug)
        if not jpg:
            emit_thumb_required(slug, title)

    # Archive markdown into posts/
    POSTS_DIR.mkdir(exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    archived = POSTS_DIR / f"{date}-{slug}.md"
    # Ensure archived md uses sanitized labels
    fm_labels = ", ".join(labels)
    archived.write_text(
        f"---\ntitle: {title}\nlabels: [{fm_labels}]\nkeyword: {keyword}\n---\n\n{body.strip()}\n",
        encoding="utf-8",
    )

    sha = push_thumb(slug, archived) if AUTO_GIT_PUSH else git_head_sha()
    thumb = cdn_url(sha, slug)
    print(f"THUMB_CDN={thumb}")
    content = build_content(body, thumb)

    if args.dry_run:
        print("DRY_RUN_OK")
        print(f"TITLE={title}")
        print(f"CATEGORY={category}")
        print(f"LABELS={labels}")
        raise SystemExit(0)

    post = publish_or_patch(service, BLOG_ID, title, content, labels)
    url = post.get("url")
    post_id = post.get("id")
    final_labels = post.get("labels") or []
    print(f"PUBLISHED_URL={url}")
    print(f"POST_ID={post_id}")
    print(f"labels_count={len(final_labels)}")
    if "post-thumb" not in (post.get("content") or "") or "jsdelivr.net" not in (
        post.get("content") or ""
    ):
        print("QUALITY_ERROR=missing CDN post-thumb in published content")
        raise SystemExit(1)
    if len(final_labels) < MIN_LABELS:
        print(f"QUALITY_ERROR=labels_count {len(final_labels)} < {MIN_LABELS}")
        raise SystemExit(1)

    record_publish(category=category, title=title, url=url or "", post_id=post_id or "")
    print("quality ok")
    # cleanup pending
    pending_path = PENDING_DIR / f"{slug}.md"
    if pending_path.exists():
        pending_path.unlink()
        print(f"PENDING_CLEARED={pending_path}")


if __name__ == "__main__":
    main()
