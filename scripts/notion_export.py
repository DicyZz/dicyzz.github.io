#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Notion 知识库导出为本地 Markdown，方便用 AI（Codex / ask_kb.py）检索与总结。

导出结果：
    knowledge_base/notion/
        _index.json       每篇文章的元数据索引（供 ask_kb.py 检索）
        index.md          按「系列 / 分类」组织的目录树
        <系列|分类>/       每篇文章一个 .md（含完整正文与图片外链）

用法：
    export NOTION_API_SECRET=ntn_...
    python scripts/notion_export.py --database-id <id> [--out knowledge_base/notion]

说明：
    - 只导出未删除（非 trash）的页面。
    - 每次导出会清空并重建 --out 目录，保证与 Notion 完全同步。
    - 不提交任何 token；导出的 .md 中只保留原文链接，不含凭证。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wechat_notion import _notion_headers  # noqa: E402

BASE = "https://api.notion.com/v1"
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge_base", "notion",
)
SLEEP = 0.22


# ---------------------------------------------------------------------------
# Notion 读取
# ---------------------------------------------------------------------------
def _with_retry(fn, attempts: int = 4):
    last = None
    for i in range(attempts):
        try:
            r = fn()
            if r.status_code != 200:
                last = RuntimeError(f"HTTP {r.status_code}")
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (i + 1))
                    continue
                return None
            return r.json()
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    if isinstance(last, Exception) and last is not None:
        print(f"   ⚠️ 请求失败（重试后放弃）：{last}")
    return None


def api_get(url: str, token: str, params: dict | None = None) -> dict | None:
    return _with_retry(lambda: requests.get(url, headers=_notion_headers(token),
                                             params=params, timeout=60))


def api_post(url: str, token: str, body: dict | None = None) -> dict | None:
    return _with_retry(lambda: requests.post(url, headers=_notion_headers(token),
                                              json=body or {}, timeout=60))


def query_all_pages(database_id: str, token: str) -> list[dict]:
    pages: list[dict] = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        j = api_post(f"{BASE}/databases/{database_id}/query", token, body)
        if not j:
            break
        pages.extend(j.get("results", []))
        if not j.get("has_more"):
            break
        cursor = j.get("next_cursor")
        time.sleep(SLEEP)
    return pages


def list_blocks(block_id: str, token: str) -> list[dict]:
    blocks: list[dict] = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        j = api_get(f"{BASE}/blocks/{block_id}/children", token, params)
        if not j:
            break
        blocks.extend(j.get("results", []))
        if not j.get("has_more"):
            break
        cursor = j.get("next_cursor")
        time.sleep(SLEEP)
    return blocks


# ---------------------------------------------------------------------------
# 属性提取
# ---------------------------------------------------------------------------
def _rt_text(rich_text: list | None) -> str:
    if not rich_text:
        return ""
    return "".join(t.get("plain_text", "") for t in rich_text if t.get("type") == "text")


def extract_props(page: dict) -> dict:
    props = page.get("properties", {})
    out = {"title": "", "series": "", "seq": None, "category": "",
           "author": "", "published": "", "url": "", "summary": "", "tags": []}
    for name, p in props.items():
        ptype = p.get("type")
        if ptype == "title":
            out["title"] = _rt_text(p.get("title"))
        elif ptype == "select":
            key = {"分类": "category", "系列": "series", "公众号": "author"}.get(name, name)
            out[key] = (p.get("select") or {}).get("name", "")
        elif ptype == "number":
            out["seq"] = p.get("number")
        elif ptype == "multi_select":
            out["tags"] = [m.get("name", "") for m in (p.get("multi_select") or [])]
        elif ptype == "url":
            out["url"] = p.get("url") or ""
        elif ptype == "date":
            out["published"] = ((p.get("date") or {}).get("start") or "")[:10]
        elif ptype == "rich_text":
            out["summary"] = _rt_text(p.get("rich_text"))
    out["series"] = out.get("series", "")
    out["category"] = out.get("category", "")
    out["author"] = out.get("author", "")
    return out


# ---------------------------------------------------------------------------
# Notion block → Markdown
# ---------------------------------------------------------------------------
def _inline(rich_text: list | None) -> str:
    if not rich_text:
        return ""
    parts = []
    for t in rich_text:
        if t.get("type") != "text":
            continue
        txt = t.get("plain_text", "")
        ann = t.get("annotations", {})
        link = t.get("href") or ((t.get("text") or {}).get("link") or {}).get("url")
        if ann.get("code"):
            txt = f"`{txt}`"
        if ann.get("bold"):
            txt = f"**{txt}**"
        if ann.get("italic"):
            txt = f"*{txt}*"
        if ann.get("strikethrough"):
            txt = f"~~{txt}~~"
        if link:
            txt = f"[{txt}]({link})"
        parts.append(txt)
    return "".join(parts)


def _image_url(block: dict) -> str:
    img = block.get("image") or {}
    if img.get("type") == "file":
        return (img.get("file") or {}).get("url", "")
    return (img.get("external") or {}).get("url", "")


def _table_rows(token: str, table_id: str) -> list[list[str]]:
    rows = list_blocks(table_id, token)
    out: list[list[str]] = []
    for r in rows:
        if r.get("type") != "table_row":
            continue
        cells = (r.get("table_row") or {}).get("cells", [])
        out.append([_inline(c) for c in cells])
    return out


def render_block(block: dict, token: str, depth: int = 0) -> list[str]:
    """把单个 Notion block 渲染成若干行 Markdown（不含子块，子块由调用方递归）。"""
    btype = block.get("type")
    body = block.get(btype, {}) if btype else {}
    prefix = "  " * depth
    text = _inline(body.get("rich_text"))

    if btype == "paragraph":
        return [prefix + text] if text else []
    if btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype[-1])
        return [prefix + "#" * level + " " + text] if text else []
    if btype == "bulleted_list_item":
        return [prefix + "- " + text]
    if btype == "numbered_list_item":
        return [prefix + "1. " + text]
    if btype == "to_do":
        mark = "x" if body.get("checked") else " "
        return [prefix + f"- [{mark}] " + text]
    if btype == "toggle":
        return [prefix + "> " + text] if text else []
    if btype == "quote":
        lines = [prefix + "> " + ln for ln in text.split("\n")]
        return lines or [prefix + "> "]
    if btype == "callout":
        lines = [prefix + "> [!note] " + ln for ln in text.split("\n")]
        return lines or [prefix + "> [!note]"]
    if btype == "code":
        lang = body.get("language") or ""
        return [prefix + f"```{lang}", text, prefix + "```"]
    if btype == "image":
        url = _image_url(block)
        if url:
            alt = text or "图片"
            return [prefix + f"![{alt}]({url})"]
        return []
    if btype == "divider":
        return [prefix + "---"]
    if btype == "equation":
        expr = body.get("expression") or ""
        return [prefix + f"${expr}$"] if expr else []
    if btype == "bookmark":
        url = body.get("url") or ""
        return [prefix + f"[{text or url}]({url})"] if url else []
    if btype in ("file", "video", "pdf"):
        file = body.get(btype) or {}
        url = (file.get("file") or {}).get("url") or (file.get("external") or {}).get("url")
        if url:
            return [prefix + f"[{text or btype}]({url})"]
        return []
    if btype == "table":
        rows = _table_rows(token, block.get("id", ""))
        out = []
        if rows:
            header = rows[0]
            out.append(prefix + "| " + " | ".join(header) + " |")
            out.append(prefix + "| " + " | ".join(["---"] * len(header)) + " |")
            for row in rows[1:]:
                cells = [c.replace("\n", " ") for c in row]
                while len(cells) < len(header):
                    cells.append("")
                out.append(prefix + "| " + " | ".join(cells[:len(header)]) + " |")
        return out
    if btype == "column_list":
        return []
    if btype == "column":
        return []
    if btype == "child_page":
        return [prefix + f"→ 子页面：{body.get('title', '')}"]
    if btype == "child_database":
        return [prefix + f"→ 子数据库：{body.get('title', '')}"]
    if btype == "link_to_page":
        return []
    if btype == "synced_block":
        return []
    return [prefix + text] if text else []


def render_blocks(blocks: list[dict], token: str, depth: int = 0) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type")
        lines.extend(render_block(block, token, depth))
        if block.get("has_children"):
            children = list_blocks(block.get("id", ""), token)
            lines.extend(render_blocks(children, token, depth + 1))
        # column_list / column 的子块平铺
        if btype in ("column_list", "column") and block.get("has_children"):
            children = list_blocks(block.get("id", ""), token)
            lines.extend(render_blocks(children, token, depth))
        if btype == "synced_block" and not block.get("has_children"):
            synced = block.get("synced_block") or {}
            origin = (synced.get("synced_from") or {}).get("block_id")
            if origin:
                lines.extend(render_blocks(list_blocks(origin, token), token, depth))
    return lines


# ---------------------------------------------------------------------------
# 文件写出
# ---------------------------------------------------------------------------
def _slug(s: str, n: int = 60) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", s or "").strip("_")
    s = re.sub(r"[^\w\u4e00-\u9fff·.-]+", "", s)
    return s[:n] or "untitled"


def _header(meta: dict) -> str:
    lines = [f"# {meta['title']}", ""]
    if meta["series"]:
        lines.append(f"- 系列：{meta['series']}（第 {meta['seq']} 讲）" if meta["seq"] is not None
                    else f"- 系列：{meta['series']}")
    if meta["seq"] is not None:
        lines.append(f"- 序号：{meta['seq']}")
    lines.append(f"- 分类：{meta['category'] or '未分类'}")
    lines.append(f"- 公众号：{meta['author'] or '未知'}")
    if meta["published"]:
        lines.append(f"- 发布日期：{meta['published']}")
    if meta["tags"]:
        lines.append("- 标签：" + "、".join(meta["tags"]))
    if meta["summary"]:
        lines.append(f"- 摘要：{meta['summary']}")
    if meta["url"]:
        lines.append(f"- 原文链接：{meta['url']}")
    lines += ["", "---", ""]
    return "\n".join(lines)


def export(database_id: str, token: str, out_dir: str) -> dict:
    pages = query_all_pages(database_id, token)
    if not pages:
        print("⚠️ 未查询到任何页面，请确认数据库 id / token / 集成权限。")
        return {"pages": 0, "failed": 0}

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    index: list[dict] = []
    failed = 0
    for page in pages:
        meta = extract_props(page)
        page_id = page.get("id", "")
        blocks = list_blocks(page_id, token)
        content = render_blocks(blocks, token)
        md = _header(meta) + "\n".join(content).rstrip() + "\n"

        folder = meta["series"] or meta["category"] or "未分类"
        folder = _slug(folder)
        fname = _slug(meta["title"] or "untitled")
        if meta["series"] and meta["seq"] is not None:
            fname = f"{int(meta['seq']):03d}-{fname}"
        folder_path = os.path.join(out_dir, folder)
        os.makedirs(folder_path, exist_ok=True)
        rel = os.path.relpath(os.path.join(folder_path, fname + ".md"), out_dir)
        with open(os.path.join(out_dir, rel), "w", encoding="utf-8") as f:
            f.write(md)

        index.append({
            "file": rel,
            "page_id": page_id,
            "title": meta["title"],
            "series": meta["series"],
            "seq": meta["seq"],
            "category": meta["category"],
            "tags": meta["tags"],
            "summary": meta["summary"],
            "url": meta["url"],
        })
        time.sleep(SLEEP)

    index.sort(key=lambda x: (x["series"] or "~~~~", x["seq"] if x["seq"] is not None else 10**9, x["title"]))
    with open(os.path.join(out_dir, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    _write_toc(index, os.path.join(out_dir, "index.md"))
    print(f"✅ 导出完成：{len(index)} 篇文章 → {out_dir}（失败 {failed}）")
    return {"pages": len(index), "failed": failed}


def _write_toc(index: list[dict], path: str) -> None:
    from collections import defaultdict
    by_series: dict[str, list[dict]] = defaultdict(list)
    others: list[dict] = []
    for it in index:
        if it["series"]:
            by_series[it["series"]].append(it)
        else:
            others.append(it)

    lines = ["# Notion 个人知识库索引", ""]
    for series, items in by_series.items():
        items = sorted(items, key=lambda x: x["seq"] if x["seq"] is not None else 10**9)
        lines += [f"## {series}", ""]
        for it in items:
            mark = f"[{it['title']}]({it['file']})"
            if it["seq"] == 0:
                lines.append(f"- {mark}（系列导览）")
            else:
                lines.append(f"- {mark}")
        lines.append("")

    if others:
        by_cat: dict[str, list[dict]] = defaultdict(list)
        for it in others:
            by_cat[it["category"] or "未分类"].append(it)
        lines += ["## 其他（未归系列）", ""]
        for cat, items in by_cat.items():
            lines += [f"### {cat}", ""]
            for it in items:
                lines.append(f"- [{it['title']}]({it['file']})")
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导出 Notion 知识库为本地 Markdown")
    ap.add_argument("--database-id", required=True)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--token", default=os.environ.get("NOTION_API_SECRET"))
    args = ap.parse_args(argv)
    if not args.token:
        print("请设置 NOTION_API_SECRET 或传 --token")
        return 2
    export(args.database_id, args.token, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
