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
    fit_labels_for_blogger,
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


def find_empty_shell(service, blog_id: str) -> dict | None:
    for status in ("DRAFT", "LIVE"):
        resp = (
            service.posts()
            .list(blogId=blog_id, status=status, maxResults=20, fetchBodies=True, view="ADMIN")
            .execute()
        )
        for post in resp.get("items") or []:
            title = (post.get("title") or "").strip()
            content = post.get("content") or ""
            text = re.sub(r"<[^>]+>", "", content).strip()
            if title in {"", "신규", "빈 포스트", "Untitled", "새 게시물", "새 포스트"} or len(text) < 30:
                return post
    return None


def _kst_now_rfc3339() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).isoformat()


def list_drafts(service, blog_id: str, max_results: int = 50) -> list[dict]:
    items: list[dict] = []
    req = service.posts().list(
        blogId=blog_id,
        status="DRAFT",
        maxResults=min(max_results, 50),
        fetchBodies=True,
        view="ADMIN",
    )
    while req is not None and len(items) < max_results:
        resp = req.execute()
        items.extend(resp.get("items") or [])
        req = service.posts().list_next(req, resp)
    return items[:max_results]


def find_reusable_draft(service, blog_id: str, title: str) -> dict | None:
    """Pick a DRAFT to overwrite when insert is blocked (403/429) and no empty shell.

    Priority:
      a) duplicate draft whose title already exists as LIVE
      b) hard-skip (sports/ent) themed draft
      c) oldest draft
    """
    drafts = list_drafts(service, blog_id)
    if not drafts:
        return None

    live_titles = {t.strip() for t in recent_titles(service, blog_id, limit=50) if t.strip()}

    dupes = []
    hard_skips = []
    for d in drafts:
        dt = (d.get("title") or "").strip()
        if dt and dt in live_titles:
            dupes.append(d)
            continue
        skip, _ = is_hard_skip(dt, dt)
        if skip:
            hard_skips.append(d)

    def oldest(posts: list[dict]) -> dict:
        return sorted(
            posts,
            key=lambda p: p.get("updated") or p.get("published") or p.get("id") or "",
        )[0]

    if dupes:
        chosen = oldest(dupes)
        print(f"FALLBACK_REUSE_DRAFT={chosen.get('id')} reason=duplicate_live_title")
        return chosen
    if hard_skips:
        chosen = oldest(hard_skips)
        print(f"FALLBACK_REUSE_DRAFT={chosen.get('id')} reason=hard_skip_topic")
        return chosen
    chosen = oldest(drafts)
    print(f"FALLBACK_REUSE_DRAFT={chosen.get('id')} reason=oldest_draft")
    return chosen


def recent_titles(service, blog_id: str, limit: int = 20) -> list[str]:
    resp = (
        service.posts()
        .list(blogId=blog_id, status="LIVE", maxResults=limit, fetchBodies=False, view="ADMIN")
        .execute()
    )
    return [p.get("title") or "" for p in (resp.get("items") or [])]


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


def _update_and_publish_draft(
    service, blog_id: str, post_id: str, body: dict, *, publish_at: str
) -> dict:
    body = dict(body)
    body["published"] = publish_at
    print(f"PUBLISH_AT={publish_at}")
    # Try full label set, then shrink 19→15 if Blogger rejects.
    labels = list(body.get("labels") or [])
    last_exc: Exception | None = None
    for count in (len(labels), 19, 18, 17, 16, 15):
        if count < MIN_LABELS:
            break
        trial = dict(body)
        trial["labels"] = fit_labels_for_blogger(labels, max_count=count)
        try:
            service.posts().update(blogId=blog_id, postId=post_id, body=trial).execute()
            print(f"DRAFT_UPDATE_LABELS={len(trial['labels'])}")
            return service.posts().publish(blogId=blog_id, postId=post_id).execute()
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "400" in msg or "label" in msg.lower():
                print(f"LABELS_RETRY count={count} err={msg[:160]}")
                continue
            raise
    raise SystemExit(f"DRAFT_UPDATE_FAIL={last_exc}")


def publish_or_patch(service, blog_id: str, title: str, content: str, labels: list[str]) -> dict:
    labels = fit_labels_for_blogger(labels, max_count=TARGET_LABELS)
    shell = find_empty_shell(service, blog_id)
    body = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
        "labels": labels,
    }
    if shell:
        post_id = shell["id"]
        status = (shell.get("status") or "").upper()
        print(f"USING_SHELL={post_id} status={status}")
        if status == "DRAFT":
            return _update_and_publish_draft(
                service, blog_id, post_id, body, publish_at=_kst_now_rfc3339()
            )
        # LIVE empty shell: patch in place
        for count in (len(labels), 19, 18, 17, 16, 15):
            if count < MIN_LABELS:
                break
            trial = dict(body)
            trial["labels"] = fit_labels_for_blogger(labels, max_count=count)
            try:
                return service.posts().patch(blogId=blog_id, postId=post_id, body=trial).execute()
            except Exception as exc:
                if "400" in str(exc):
                    print(f"LABELS_RETRY count={count} err={str(exc)[:160]}")
                    continue
                raise
        raise SystemExit("LIVE_SHELL_PATCH_FAIL")

    try:
        return service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
    except Exception as exc:
        print(f"INSERT_FAIL={exc}")
        err = str(exc)
        if "403" not in err and "429" not in err and "quota" not in err.lower():
            raise SystemExit(f"INSERT_FAIL_NON_QUOTA={exc}") from exc
        draft = find_reusable_draft(service, blog_id, title)
        if not draft:
            print("NO_REUSABLE_DRAFT")
            raise SystemExit(1) from exc
        return _update_and_publish_draft(
            service,
            blog_id,
            draft["id"],
            body,
            publish_at=_kst_now_rfc3339(),
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
    labels = labels[:TARGET_LABELS]

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
