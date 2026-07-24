"""Publish markdown files from posts/ to Blogger."""

from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path

from blogger_http import build_blogger_service
from blogger_quality import MIN_LABELS, sanitize_labels, validate_post

POSTS_DIR = Path("posts")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta_raw = text[4:end]
    body = text[end + 5 :].strip()
    meta: dict[str, str] = {}
    for line in meta_raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def parse_labels(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
    return [raw] if raw else []


def md_to_blogger_html(body: str) -> str:
    """Convert markdown-ish body to Blogger HTML (headings, lists, tables, images)."""
    lines = body.splitlines()
    blocks: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        text = " ".join(paragraph).strip()
        paragraph = []
        if text:
            blocks.append(f"<p>{inline_format(text)}</p>")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # pipe table
        if (
            "|" in stripped
            and i + 1 < len(lines)
            and TABLE_SEP_RE.match(lines[i + 1].strip())
        ):
            flush_paragraph()
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i]:
                if TABLE_SEP_RE.match(lines[i].strip()):
                    i += 1
                    continue
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            if rows:
                header = "".join(f"<th>{escape(c)}</th>" for c in rows[0])
                body_rows = []
                for row in rows[1:]:
                    body_rows.append(
                        "<tr>" + "".join(f"<td>{inline_format(c)}</td>" for c in row) + "</tr>"
                    )
                blocks.append(
                    '<table border="1" cellpadding="6" cellspacing="0">'
                    f"<thead><tr>{header}</tr></thead>"
                    f"<tbody>{''.join(body_rows)}</tbody></table>"
                )
            continue

        if not stripped:
            flush_paragraph()
            blocks.append("<p><br /></p>")
            i += 1
            continue

        img = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if img:
            flush_paragraph()
            alt = escape(img.group(1) or "")
            src = escape(img.group(2), quote=True)
            cls = ' class="post-thumb"' if "thumb-" in img.group(2) or "post-thumb" in alt else ""
            blocks.append(f'<p><img{cls} src="{src}" alt="{alt}" /></p>')
            i += 1
            continue

        if stripped.startswith("### "):
            flush_paragraph()
            blocks.append(f"<h3>{escape(stripped[4:].strip())}</h3>")
            i += 1
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            blocks.append(f"<h2>{escape(stripped[3:].strip())}</h2>")
            i += 1
            continue

        if stripped.startswith("> "):
            flush_paragraph()
            blocks.append(f"<blockquote><p>{inline_format(stripped[2:].strip())}</p></blockquote>")
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            flush_paragraph()
            items = []
            while i < len(lines) and (
                lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")
            ):
                item = lines[i].strip()[2:].strip()
                items.append(f"<li>{inline_format(item)}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    while blocks and blocks[-1] == "<p><br /></p>":
        blocks.pop()
    return "".join(blocks)


def inline_format(text: str) -> str:
    def repl_link(match: re.Match[str]) -> str:
        label = escape(match.group(1))
        url = escape(match.group(2), quote=True)
        return f'<a href="{url}">{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)
    parts: list[str] = []
    last = 0
    for match in re.finditer(r"\*\*([^*]+)\*\*", text):
        parts.append(escape_keep_anchors(text[last : match.start()]))
        parts.append(f"<strong>{escape(match.group(1))}</strong>")
        last = match.end()
    parts.append(escape_keep_anchors(text[last:]))
    return "".join(parts)


def escape_keep_anchors(text: str) -> str:
    pieces: list[str] = []
    pos = 0
    for match in re.finditer(r'<a href="[^"]+">.*?</a>', text):
        pieces.append(escape(text[pos : match.start()]))
        pieces.append(match.group(0))
        pos = match.end()
    pieces.append(escape(text[pos:]))
    return "".join(pieces)


def get_blog_id(service) -> str:
    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items") or []
    if not items:
        raise SystemExit("No Blogger blogs found for this Google account.")
    blog = items[0]
    print(f"Using blog: {blog.get('name')} ({blog['id']})")
    return blog["id"]


def publish_file(service, blog_id: str, path: Path, draft: bool) -> dict:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    title = meta.get("title")
    if not title:
        raise SystemExit(f"Missing title frontmatter: {path}")
    labels = sanitize_labels(parse_labels(meta.get("labels", "")), keyword=title)
    result, labels, _cat = validate_post(title=title, body=body, labels=labels, keyword=title)
    for line in result.log_lines():
        print(line)
    if not result.ok:
        raise SystemExit(f"Quality gate failed for {path}")
    if len(labels) < MIN_LABELS:
        raise SystemExit(f"Not enough labels after sanitize: {len(labels)}")

    content = md_to_blogger_html(body)
    if "data:image" in content:
        raise SystemExit("data URI images are forbidden; use jsDelivr CDN thumb URL")

    post_body = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
        "labels": labels,
    }
    post = (
        service.posts()
        .insert(blogId=blog_id, body=post_body, isDraft=draft)
        .execute()
    )
    return post


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish posts/*.md to Blogger.")
    parser.add_argument(
        "files",
        nargs="*",
        help="Markdown files to publish. Defaults to all posts/*.md",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create as draft instead of live publish.",
    )
    parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="Skip usefulness gate (not recommended).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(p) for p in args.files] if args.files else sorted(POSTS_DIR.glob("*.md"))
    if not paths:
        raise SystemExit("No markdown files to publish.")

    service = build_blogger_service()
    blog_id = get_blog_id(service)

    for path in paths:
        if not path.exists():
            raise SystemExit(f"File not found: {path}")
        if args.skip_quality:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            title = meta["title"]
            labels = sanitize_labels(parse_labels(meta.get("labels", "")), keyword=title)
            content = md_to_blogger_html(body)
            post = (
                service.posts()
                .insert(
                    blogId=blog_id,
                    body={
                        "kind": "blogger#post",
                        "blog": {"id": blog_id},
                        "title": title,
                        "content": content,
                        "labels": labels,
                    },
                    isDraft=args.draft,
                )
                .execute()
            )
        else:
            post = publish_file(service, blog_id, path, draft=args.draft)
        print(f"Published: {post.get('title')}")
        print(f"URL: {post.get('url')}")
        print(f"Post ID: {post.get('id')}")
        print(f"labels_count={len(post.get('labels') or [])}")
        print()


if __name__ == "__main__":
    main()
