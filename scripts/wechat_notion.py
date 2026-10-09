#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信公众号文章 → Notion 个人知识库。

用法：
    python scripts/wechat_notion.py fetch            # 抓取并解析 URL 列表，下载图片，存 staging JSON
    python scripts/wechat_notion.py dedupe           # 去重 + 分类
    python scripts/wechat_notion.py push             # 推送到 Notion（需 NOTION_API_SECRET）

环境变量：
    NOTION_API_SECRET   Notion 内部集成令牌（ntn_ 或 secret_ 开头）
    NOTION_DATABASE_ID  目标数据库 id（默认取命令行 --database-id）
    DEEPSEEK_API_KEY    可选：用于自动分类（未配置则用规则分类）

默认读取 data/wechat_urls.txt 里的 URL。
"""

from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import json
import mimetypes
import os
import re
import sys
import time
from collections import OrderedDict
from urllib.parse import urlparse

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
IMAGES_DIR = os.path.join(DATA_DIR, "wechat_images")
STAGING_FILE = os.path.join(DATA_DIR, "wechat_articles.json")
RAW_FILE = os.path.join(DATA_DIR, "wechat_articles_raw.json")
URLS_FILE = os.path.join(DATA_DIR, "wechat_urls.txt")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# 分类规则（关键词命中，按顺序；用于没有 DeepSeek 时的兜底）
# 标题关键词分类（按顺序命中；标题比正文更精确，避免「大模型」等泛词在正文里误命中）
CATEGORY_RULES = [
    ("计算机体系结构", ["CS61C", "RISC-V", "RISC V", "数据路径", "指令集", "过程调用", "计算体系结构",
                  "总线", "AXI", "低功耗", "门控时钟", "Intrinsics", "CPU", "Olympus Core", "内核"]),
    ("存储与互联", ["HBM", "DDR", "SSD", "HDD", "内存", "CXL", "NVLink", "PCIe", "存算一体",
                 "HBF", "互联", "存储", "InfiniBand", "织网", "MEXT"]),
    ("封装与材料", ["封装", "载板", "基板", "光刻", "材料", "晶圆", "Chiplet", "芯粒", "CPO",
                 "硅中介", "Thermal Scaling", "先进封装", "3D"]),
    ("大模型与推理", ["vLLM", "KV Cache", "MoE", "混合专家", "Transformer", "大模型", "推理系统",
                 "DeepSeek", "世界模型", "LLM", "自注意力", "CS336"]),
    ("AI芯片与算力", ["AI芯片", "GPU", "TPU", "NPU", "LPU", "ASIC", "SIMD", "SIMT", "Tensor",
                 "脉动阵列", "推理芯片", "训练芯片", "超节点", "算力", "超集群", "加速器",
                 "加速", "向量", "芯片红利", "影子军团", "NextSilicon", "ARIES", "光子",
                 "量子计算"]),
    ("半导体与芯片", ["半导体", "芯片", "制程", "晶体管", "摩尔", "FinFET", "EUV", "EDA", "SoC"]),
]


def _slug(s: str, n: int = 80) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", s or "").strip("_")
    return s[:n] or "untitled"


def fetch_article(url: str, attempts: int = 3) -> dict | None:
    text = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                text = resp.text
                break
            if attempt + 1 < attempts:
                time.sleep(1.5)
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(1.5)
    if text is None:
        print(f"   ⚠️ {url} -> 抓取失败")
        return None

    title = ""
    m = re.search(r'property="og:title" content="([^"]+)"', text)
    if m:
        title = htmlmod.unescape(m.group(1))
    if not title:
        m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', text, re.S)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    title = (title or "").strip()

    author = ""
    m = re.search(r'<meta name="author" content="([^"]+)"', text)
    if m:
        author = m.group(1).strip()

    pub = ""
    m = re.search(r"var createTime\s*=\s*['\"]([^'\"]+)", text)
    if m:
        pub = m.group(1).strip()

    # 正文
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', text, re.S)
    if not m:
        m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*)', text, re.S)
    content_html = m.group(1) if m else ""

    is_video = bool(re.search(r"wxv_[A-Za-z0-9]{10,}", text)) and len(content_html) < 500

    return {
        "url": url,
        "title": title,
        "author": author,
        "published": pub,
        "content_html": content_html,
        "is_video": is_video,
    }


def extract_blocks(article: dict) -> list:
    """把正文 HTML 转成有序块列表：段落/标题/图片/引用，图片保留原始 URL。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(
        f"<div id=\"__content__\">{article['content_html']}</div>", "lxml"
    )
    root = soup.find("div", id="__content__")
    blocks = []
    image_seq = [0]

    def img_to_block(img, text_only_ctx=None):
        src = img.get("data-src") or img.get("src") or ""
        src = htmlmod.unescape(src).strip()
        if not src.startswith("http"):
            return None
        return {"type": "image", "url": src}

    for node in root.find_all(["p", "section", "h1", "h2", "h3", "img", "blockquote", "pre"], recursive=False):
        # js_content 顶层通常是 section
        if node.name == "img":
            b = img_to_block(node)
            if b:
                blocks.append(b)
            continue
        if node.name in ("h1", "h2", "h3"):
            text = node.get_text(" ", strip=True)
            if text:
                # 部分公众号（如 stephenxi）用 <h3> 包裹整段正文；
                # 长文本按段落处理，短标题才保留为 heading
                if len(text) > 24:
                    blocks.append({"type": "paragraph", "text": text})
                else:
                    blocks.append({"type": "heading", "level": int(node.name[1]), "text": text})
            continue
        if node.name == "blockquote":
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append({"type": "quote", "text": text})
            continue
        if node.name == "pre":
            text = node.get_text("", strip=False)
            if text.strip():
                blocks.append({"type": "code", "text": text})
            continue
        # p / section：可能是段落，也可能内嵌图片
        imgs = node.find_all("img")
        if imgs:
            for img in imgs:
                b = img_to_block(img)
                if b:
                    blocks.append(b)
        text = node.get_text(" ", strip=True)
        if text:
            blocks.append({"type": "paragraph", "text": text})

    # 若上面只抓到段落没抓到图片（结构嵌套），再全局兜底一次
    if not any(b["type"] == "image" for b in blocks):
        for img in soup.find_all("img"):
            b = img_to_block(img)
            if b:
                blocks.append(b)

    return blocks


def _render_blocks_playwright(url: str) -> list:
    """JS 渲染兜底：静态 HTML 取不到正文时用浏览器渲染提取文本/图片。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    blocks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        text = page.evaluate(
            "() => (document.getElementById('js_content') || document.body).innerText"
        )
        imgs = page.evaluate(
            "() => Array.from(document.querySelectorAll('#js_content img'))"
            ".map(i => i.currentSrc || i.src || i.getAttribute('data-src') || '')"
        )
        browser.close()
    if text:
        blocks.append({"type": "paragraph", "text": text.strip()})
    for src in imgs:
        if src.startswith("http"):
            blocks.append({"type": "image", "url": src})
    return blocks


def _download_image(url: str, dest_dir: str, seq: int) -> str | None:
    """下载图片到本地归档，保留原始格式；返回本地相对路径。"""
    try:
        # 若同名文件已存在（重新抓取时复用），直接返回
        existing = [f for f in (os.listdir(dest_dir) if os.path.isdir(dest_dir) else [])
                    if f.startswith(f"{seq:03d}.")]
        if existing:
            return existing[0]
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Referer": "https://mp.weixin.qq.com/"},
                         timeout=30)
        if r.status_code != 200 or not r.content:
            return None
        ext = mimetypes.guess_extension(r.headers.get("Content-Type", "")) or ""
        if not ext or ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            # 从 URL 的 wx_fmt 推断
            m = re.search(r"wx_fmt=(\w+)", url)
            fmt = m.group(1).lower() if m else ""
            ext = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "webp": ".webp"}.get(fmt, ".jpg")
        os.makedirs(dest_dir, exist_ok=True)
        fname = f"{seq:03d}{ext}"
        with open(os.path.join(dest_dir, fname), "wb") as f:
            f.write(r.content)
        return fname
    except Exception:
        return None


def _archive_images(article: dict, slug: str) -> None:
    """把文章里的图片下载到本地（原始格式归档），并在 block 里记录本地文件名。"""
    dest_dir = os.path.join(IMAGES_DIR, slug)
    seq = 0
    for b in article.get("blocks", []):
        if b.get("type") == "image":
            seq += 1
            fname = _download_image(b["url"], dest_dir, seq)
            if fname:
                b["local"] = os.path.join(slug, fname)


def fetch_all(urls_file: str = URLS_FILE, out_file: str | None = None) -> list:
    if out_file is None:
        out_file = RAW_FILE
    urls = [l.strip() for l in open(urls_file, encoding="utf-8") if l.strip()]
    articles = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        a = fetch_article(url)
        if not a:
            continue
        a["blocks"] = extract_blocks(a)
        if not a["blocks"]:
            if a.get("is_video"):
                a["blocks"] = [{"type": "paragraph", "text": "【视频课程】原文为视频内容，可点击原文链接观看。"}]
            else:
                a["blocks"] = _render_blocks_playwright(url)
        slug = _slug(a["title"]) + "_" + url.rstrip("/").split("/")[-1][:12]
        _archive_images(a, slug)
        n_img = sum(1 for b in a["blocks"] if b["type"] == "image")
        print(f"   ✓ {a['title'][:50]} | {a['author']} | {a['published']} | 图片 {n_img} 张"
              + (" | 视频" if a.get("is_video") else ""))
        articles.append(a)
        time.sleep(0.4)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 共抓取 {len(articles)}/{len(urls)} 篇，已保存到 {out_file}")
    return articles


def _norm_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"[\s\-—_·|:：;；,，、.。!！?？'\"“”‘’()（）\[\]【】《》]+", "", t)
    return t.lower()


def _char_bigrams(t: str) -> set:
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _title_similar(a: str, b: str) -> bool:
    """标题级去重：只合并「逐字相同」（跨公众号转载通常照抄标题）。

    用 bigram Jaccard 会把「Part1 / Part2」「L20 / L21」这类系列文章误合并，
    因此这里保守地只用标准化后完全相等；语义相近的合并交给后续 DeepSeek 聚类。
    """
    a, b = _norm_title(a), _norm_title(b)
    return bool(a) and a == b


def _content_hash(a: dict) -> str:
    parts = [a.get("title", ""), a.get("url", "")]
    for b in a.get("blocks", []):
        if b["type"] == "image":
            parts.append(b.get("url", ""))
        else:
            parts.append(b.get("text", ""))
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def _classify(a: dict) -> str:
    # 优先按标题分类（更精确）；标题为空时退回正文
    title_l = (a.get("title") or "").lower()
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw.lower() in title_l:
                return cat
    body = " ".join(b.get("text", "") for b in a.get("blocks", []) if b["type"] != "image").lower()
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw.lower() in body:
                return cat
    return "未分类"


def dedupe(in_file: str | None = None, out_file: str | None = None) -> dict:
    if in_file is None:
        in_file = RAW_FILE
    if out_file is None:
        out_file = STAGING_FILE
    articles = json.load(open(in_file, encoding="utf-8"))
    groups: OrderedDict[str, dict] = OrderedDict()
    seen_hash = set()
    stats = {"total": len(articles), "kept": 0, "duplicates": 0}

    for a in articles:
        # 精确内容去重
        ch = _content_hash(a)
        if ch in seen_hash:
            stats["duplicates"] += 1
            continue
        seen_hash.add(ch)

        # 相似标题去重（归入第一个出现的主题）
        merged_key = None
        for key, g in groups.items():
            if _title_similar(a["title"], g["title"]):
                merged_key = key
                break
        if merged_key is None:
            merged_key = _content_hash(a)
            groups[merged_key] = {"title": a["title"], "author": a["author"], "articles": []}
        groups[merged_key]["articles"].append(a)
        stats["kept"] += 1

    # 每个主题取一篇作为代表，其它来源合并进「related」
    result = []
    for key, g in groups.items():
        primary = g["articles"][0]
        primary["category"] = _classify(primary)
        primary["group_id"] = key
        if len(g["articles"]) > 1:
            primary["related"] = [x["url"] for x in g["articles"][1:]]
            primary["duplicate_count"] = len(g["articles"]) - 1
        else:
            primary["related"] = []
            primary["duplicate_count"] = 0
        result.append(primary)

    # 二次归类：同类重复检查后按分类排序
    result.sort(key=lambda x: (x.get("category", ""), x.get("published", "")))
    stats["kept"] = len(result)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ 去重整理：{stats['total']} 篇 → {stats['kept']} 个主题（去重 {stats['duplicates']} 篇）")
    return stats


# ---------------------------------------------------------------------------
# Notion 推送
# ---------------------------------------------------------------------------
def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _rich_text(text: str, link: str | None = None) -> dict:
    rt = {"type": "text", "text": {"content": (text or "")[:2000]}}
    if link:
        rt["text"]["link"] = {"url": link}
    return rt


def _block_from(b: dict) -> dict | None:
    t = b["type"]
    if t == "paragraph":
        return {"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [_rich_text(b.get("text", ""))]}}
    if t == "heading":
        level = min(max(b.get("level", 2), 1), 3)
        key = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
        return {"object": "block", "type": key,
                key: {"rich_text": [_rich_text(b.get("text", ""))]}}
    if t == "quote":
        return {"object": "block", "type": "quote",
                "quote": {"rich_text": [_rich_text(b.get("text", ""))]}}
    if t == "code":
        return {"object": "block", "type": "code",
                "code": {"rich_text": [_rich_text(b.get("text", ""))], "language": "plain text"}}
    if t == "image":
        url = b.get("url", "")
        if not url:
            return None
        return {"object": "block", "type": "image",
                "image": {"type": "external", "external": {"url": url}}}
    return None


def _get_database_schema(database_id: str, token: str) -> dict | None:
    """读取 Notion 数据库 schema，用于自动适配属性名。"""
    r = requests.get(f"https://api.notion.com/v1/databases/{database_id}",
                     headers=_notion_headers(token), timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("properties", {})


def _parse_date(published: str) -> str | None:
    """把 '2026-01-18 18:37' 解析成 Notion date 的 ISO 日期。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", (published or "").strip())
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _summary_from_blocks(a: dict, limit: int = 280) -> str:
    """用正文第一段非空文本做摘要。"""
    for b in a.get("blocks", []):
        if b["type"] not in ("paragraph", "heading", "quote"):
            continue
        text = (b.get("text") or "").strip()
        if len(text) >= 12:
            return text[:limit]
    return ""


def _adapt_properties(schema: dict, a: dict) -> tuple:
    """根据 Notion 数据库真实 schema 精确填充属性。

    按属性名优先匹配，找不到名字再按类型兜底。返回 (properties, title_prop)。
    """
    by_name = {name: spec for name, spec in (schema or {}).items()}

    title = (a.get("title") or "未命名文章")[:2000]
    author = (a.get("author") or "").strip() or "未知"
    published = (a.get("published") or "").strip()
    category = (a.get("category") or "未分类").strip()
    url = (a.get("url") or "").strip()
    summary = _summary_from_blocks(a)

    props = {}

    # 标题（type=title）
    title_prop = next((n for n, sp in by_name.items() if sp.get("type") == "title"), None)
    if title_prop:
        props[title_prop] = {"title": [{"text": {"content": title}}]}

    # 分类 / 公众号（select，按名字精确命中）
    for prop_name, value in (("分类", category), ("公众号", author)):
        spec = by_name.get(prop_name)
        if spec and spec.get("type") == "select":
            props[prop_name] = {"select": {"name": value}}

    # 发布日期（date）
    spec = by_name.get("发布日期")
    if spec and spec.get("type") == "date":
        d = _parse_date(published)
        if d:
            props["发布日期"] = {"date": {"start": d}}

    # 原文链接（url）
    spec = by_name.get("原文链接")
    if spec and spec.get("type") == "url" and url:
        props["原文链接"] = {"url": url}

    # 摘要（rich_text）
    spec = by_name.get("摘要")
    if spec and spec.get("type") == "rich_text" and summary:
        props["摘要"] = {"rich_text": [{"text": {"content": summary}}]}

    # 标签（multi_select）：用分类拆词生成几个粗标签，提升检索
    spec = by_name.get("标签")
    if spec and spec.get("type") == "multi_select":
        tags = [t.strip() for t in category.replace("与", " ").replace("和", " ").split()
                if t.strip() and t.strip() not in ("未分类",)]
        if tags:
            props["标签"] = {"multi_select": [{"name": t} for t in tags[:4]]}

    return props, title_prop


def _metadata_blocks(a: dict) -> list:
    """正文顶部的元信息块（即使数据库没有对应属性也能保证可检索）。"""
    category = a.get("category") or "未分类"
    author = a.get("author") or "未知"
    published = a.get("published") or "未知"
    url = a.get("url") or ""
    lines = [f"分类：{category}", f"公众号：{author}", f"发布时间：{published}"]
    if url:
        lines.append(f"原文链接：{url}")
    md = "\n".join(lines)
    return [{"object": "block", "type": "callout",
             "callout": {"rich_text": [_rich_text(md)], "icon": {"type": "emoji", "emoji": "📄"}}}]


def push_to_notion(database_id: str, token: str, in_file: str = STAGING_FILE,
                   dry_run: bool = False) -> dict:
    articles = json.load(open(in_file, encoding="utf-8"))
    base = "https://api.notion.com/v1"
    stats = {"pushed": 0, "failed": 0, "schema": None}

    schema = _get_database_schema(database_id, token)
    if schema:
        title_prop = next((n for n, s in schema.items() if s.get("type") == "title"), None)
        print(f"✅ 数据库 schema 读取成功：共 {len(schema)} 个属性，"
              f"标题属性=「{title_prop or '未找到'}」")
        stats["schema"] = list(schema.keys())
    else:
        print("⚠️ 无法读取数据库 schema（可能是集成未授权访问该数据库），"
              "将仅用正文块写入并自动找 title 属性")

    for i, a in enumerate(articles, 1):
        props, title_prop = _adapt_properties(schema, a)
        # 构造正文：元信息 + 正文块
        children = _metadata_blocks(a)
        for b in a.get("blocks", []):
            nb = _block_from(b)
            if nb:
                children.append(nb)
        chunked = [children[j:j + 90] for j in range(0, len(children), 90)]
        body = {
            "parent": {"database_id": database_id},
            "properties": props or {},
            "children": chunked[0] if chunked else [],
        }
        if dry_run:
            print(f"[dry-run] {i}/{len(articles)} [{a.get('category')}] {a['title'][:40]} "
                  f"| {len(children)} blocks | title_prop={title_prop}")
            stats["pushed"] += 1
            continue
        try:
            r = requests.post(f"{base}/pages", headers=_notion_headers(token), json=body, timeout=60)
            if r.status_code not in (200, 201):
                print(f"   ❌ {a['title'][:40]} -> {r.status_code} {r.text[:200]}")
                stats["failed"] += 1
                continue
            page_id = r.json()["id"]
            for extra in chunked[1:]:
                requests.patch(f"{base}/blocks/{page_id}/children",
                               headers=_notion_headers(token),
                               json={"children": extra}, timeout=60)
            print(f"   ✓ [{a.get('category')}] {a['title'][:40]} | {len(children)} blocks")
            stats["pushed"] += 1
            time.sleep(0.35)
        except Exception as e:
            print(f"   ❌ {a['title'][:40]} -> {type(e).__name__}: {e}")
            stats["failed"] += 1

    print(f"\n✅ 推送完成：成功 {stats['pushed']} 篇，失败 {stats['failed']} 篇")
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="公众号文章 → Notion 知识库")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("dedupe")
    push = sub.add_parser("push")
    push.add_argument("--database-id", default=os.environ.get("NOTION_DATABASE_ID", ""))
    push.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "fetch":
        fetch_all()
    elif args.cmd == "dedupe":
        dedupe()
    elif args.cmd == "push":
        token = os.environ.get("NOTION_API_SECRET", "").strip()
        if not token:
            print("❌ 缺少 NOTION_API_SECRET，请先配置 Notion 集成令牌")
            return 1
        db = args.database_id.strip()
        if not db:
            print("❌ 缺少 --database-id 或 NOTION_DATABASE_ID")
            return 1
        push_to_notion(db, token, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
