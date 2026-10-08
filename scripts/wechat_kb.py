#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号知识库：抓取 → 分类 → 去重/相似合并 → 导出 Markdown。

设计目标：把自己关注的微信公众号内容汇总成一个可检索、按分类归档的知识库，
相同事件被多个公众号重复报道时合并成一条主题。

依赖 wewe-rss（自建在 Mac mini 上的 Docker 服务）把公众号转成带全文的 RSS/Atom：
    https://github.com/cooderl/wewe-rss
安装后：
    1. 浏览器打开 http://<mac-mini>:4000 ，用微信读书扫码登录
    2. 在页面里把关注的公众号添加进去（或使用它的「同步关注」能力）
    3. 运行本脚本前配置环境变量 WEWE_RSS_BASE=http://127.0.0.1:4000

本脚本用到的分类规则放在 data/wechat_accounts.yml（参考 example 文件），
DeepSeek 负责给每篇文章打标签 + 一句话摘要，并做「同主题文章」聚类合并。

用法：
    python scripts/wechat_kb.py init              # 建库 + 生成账号清单模板
    python scripts/wechat_kb.py list-accounts     # 列出 wewe-rss 里的公众号与分类
    python scripts/wechat_kb.py fetch             # 抓取所有公众号文章入库
    python scripts/wechat_kb.py classify          # DeepSeek 打标签 + 摘要
    python scripts/wechat_kb.py merge             # 去重 + 相似主题合并
    python scripts/wechat_kb.py export            # 导出到 knowledge_base/
    python scripts/wechat_kb.py full              # 依次执行上面全部步骤

环境变量：
    WEWE_RSS_BASE     wewe-rss 地址，默认 http://127.0.0.1:4000
    DEEPSEEK_API_KEY  可选；不配置则跳过 AI 打标签/聚类，仅做标题去重
    DEEPSEEK_MODEL    默认 deepseek-chat
    KB_ACCOUNTS_FILE  账号清单路径，默认 data/wechat_accounts.yml
    KB_DB_FILE        SQLite 路径，默认 data/wechat_kb.sqlite3
    KB_EXPORT_DIR     导出目录，默认 knowledge_base/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher

import feedparser
import requests
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ACCOUNTS_FILE = os.path.join(REPO_ROOT, "data", "wechat_accounts.yml")
DEFAULT_DB_FILE = os.path.join(REPO_ROOT, "data", "wechat_kb.sqlite3")
DEFAULT_EXPORT_DIR = os.path.join(REPO_ROOT, "knowledge_base")

WEWE_RSS_BASE = os.environ.get("WEWE_RSS_BASE", "http://127.0.0.1:4000").rstrip("/")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
ACCOUNTS_FILE = os.environ.get("KB_ACCOUNTS_FILE", DEFAULT_ACCOUNTS_FILE)
DB_FILE = os.environ.get("KB_DB_FILE", DEFAULT_DB_FILE)
EXPORT_DIR = os.environ.get("KB_EXPORT_DIR", DEFAULT_EXPORT_DIR)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.7"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,     -- wewe-rss feed id（公众号 biz id）
    name        TEXT,                 -- 公众号名
    category    TEXT DEFAULT '未分类',
    first_seen  TEXT
);
CREATE TABLE IF NOT EXISTS articles (
    url          TEXT PRIMARY KEY,    -- 去参数后的原文链接
    title        TEXT,
    account_id   TEXT,
    account_name TEXT,
    category     TEXT,
    published    TEXT,
    summary      TEXT,                -- RSS 摘要/导语
    content      TEXT,                -- 全文（若源提供）
    tags         TEXT,                -- JSON 数组
    ai_summary   TEXT,                -- DeepSeek 一句话摘要
    merged_key   TEXT,                -- 合并后的主题 id
    fetched_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_account ON articles(account_id);
"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_title(title: str) -> str:
    """标题标准化：去空白/标点，用于跨公众号去重。"""
    text = re.sub(r"<[^>]+>", " ", title or "")
    text = re.sub(r"[\s\-—_·|:：;；,，、.。!！?？'\"“”‘’()（）\[\]【】《》]+", "", text)
    return text.lower()


def link_key(link: str) -> str:
    return (link or "").strip().split("?")[0].split("#")[0].rstrip("/")


def get_db(db_file: str = DB_FILE) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# 账号清单（分类规则）
# ---------------------------------------------------------------------------
def load_categories(path: str | None = None) -> list:
    """读取分类清单，返回 [{"name": str, "keywords": [str]}]。"""
    if path is None:
        path = ACCOUNTS_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    categories = []
    for cat in data.get("categories", []):
        name = (cat.get("name") or "").strip()
        keywords = [str(k).strip() for k in cat.get("accounts", []) if str(k).strip()]
        if name and keywords:
            categories.append({"name": name, "keywords": keywords})
    return categories


def match_category(account_name: str, categories: list) -> str:
    """按「公众号名包含关键词」匹配分类，命中第一个即返回。"""
    name = account_name or ""
    for cat in categories:
        for kw in cat["keywords"]:
            if kw and kw in name:
                return cat["name"]
    return "未分类"


# ---------------------------------------------------------------------------
# wewe-rss 抓取
# ---------------------------------------------------------------------------
def list_feeds(base: str = WEWE_RSS_BASE) -> list:
    """GET /feeds 返回公众号列表。"""
    resp = requests.get(f"{base}/feeds", headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("data", data.get("feeds", []))
    return data if isinstance(data, list) else []


def fetch_feed_entries(base: str, feed_id: str) -> list:
    """抓取某个公众号的 Atom，返回条目列表。"""
    url = f"{base}/feeds/{feed_id}.atom"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    if resp.status_code != 200:
        return []
    feed = feedparser.parse(resp.content)
    return feed.entries or []


def entry_published(entry) -> str:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        try:
            return datetime(*struct[:6]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return ""


def fetch_and_store(db_file: str = DB_FILE, base: str = WEWE_RSS_BASE) -> dict:
    """拉取所有公众号文章入库，返回统计。"""
    categories = load_categories()
    conn = get_db(db_file)
    stats = {"accounts": 0, "new_articles": 0, "skipped": 0, "feeds_failed": []}

    try:
        feeds = list_feeds(base)
    except Exception as e:
        print(f"❌ 无法访问 wewe-rss（{base}/feeds）：{e}")
        print("   请确认 Docker 服务已启动、已扫码登录，并设置了 WEWE_RSS_BASE")
        conn.close()
        return stats

    for feed in feeds:
        feed_id = str(feed.get("id") or feed.get("mpId") or "").strip()
        name = (feed.get("mpName") or feed.get("name") or feed_id).strip()
        if not feed_id:
            continue
        stats["accounts"] += 1
        category = match_category(name, categories)
        conn.execute(
            "INSERT INTO accounts(id, name, category, first_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category",
            (feed_id, name, category, now_str()),
        )

        try:
            entries = fetch_feed_entries(base, feed_id)
        except Exception as e:
            stats["feeds_failed"].append(f"{name}: {type(e).__name__}")
            continue

        for e in entries:
            link = link_key(e.get("link") or e.get("id") or "")
            if not link:
                continue
            title = (e.get("title") or "").strip()
            if not title:
                continue
            summary = ""
            for key in ("summary", "description", "subtitle"):
                val = e.get(key) or ""
                if val:
                    summary = re.sub(r"<[^>]+>", " ", val)
                    summary = re.sub(r"\s+", " ", summary).strip()
                    break
            content = ""
            for key in ("content", "description"):
                val = e.get(key)
                if val:
                    content = re.sub(r"<[^>]+>", " ", val)
                    content = re.sub(r"\s+", " ", content).strip()
                    if content:
                        break
            exists = conn.execute("SELECT 1 FROM articles WHERE url=?", (link,)).fetchone()
            if exists:
                stats["skipped"] += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO articles"
                "(url,title,account_id,account_name,category,published,summary,content,tags,ai_summary,merged_key,fetched_at)"
                " VALUES(?,?,?,?,?,?,?,?,'[]',NULL,NULL,?)",
                (link, title, feed_id, name, category, entry_published(e), summary, content, now_str()),
            )
            stats["new_articles"] += 1

    conn.commit()
    print(f"   ✅ 抓取完成：{stats['accounts']} 个公众号，新增 {stats['new_articles']} 篇，"
          f"已存在跳过 {stats['skipped']} 篇，失败源 {len(stats['feeds_failed'])} 个")
    for msg in stats["feeds_failed"][:10]:
        print(f"   ⚠️ 抓取失败：{msg}")
    conn.close()
    return stats


# ---------------------------------------------------------------------------
# DeepSeek 分类（打标签 + 一句话摘要）
# ---------------------------------------------------------------------------
def _deepseek_client():
    from openai import OpenAI
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def classify_articles(db_file: str = DB_FILE, batch_size: int = 30) -> dict:
    """给尚未打标签的文章批量打标签 + 摘要。"""
    conn = get_db(db_file)
    rows = conn.execute(
        "SELECT url, title, category, summary, content FROM articles "
        "WHERE ai_summary IS NULL OR tags='[]'"
    ).fetchall()
    conn.close()

    if not rows:
        print("   ℹ️ 没有需要分类的文章")
        return {"classified": 0}

    if not DEEPSEEK_API_KEY:
        print("   ⚠️ 未配置 DEEPSEEK_API_KEY，跳过 AI 打标签/摘要")
        return {"classified": 0}

    client = _deepseek_client()
    classified = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        items = []
        for j, r in enumerate(batch):
            text = (r["summary"] or r["content"] or "")[:600]
            items.append({
                "idx": j,
                "title": r["title"],
                "category": r["category"],
                "text": text,
            })
        payload = json.dumps(items, ensure_ascii=False)
        prompt = f"""
你是知识库整理助手。下面是 {len(items)} 篇微信公众号文章（已给出标题、分类、摘要/正文片段）。
请为每篇文章输出：
- tags：2-4 个简短中文标签（主题/领域/关键词，逗号分隔）
- summary：一句话中文摘要（不超过 60 字，忠于原文，不得编造原文没有的信息）

严格只依据给出的信息，不要编造。输出 JSON 数组，每项格式：
{{"idx": 0, "tags": ["标签1", "标签2"], "summary": "一句话摘要"}}

文章列表：
{payload}
"""
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": "你是严谨的知识库整理助手，只依据输入内容打标签和写摘要。"},
                          {"role": "user", "content": prompt}],
                temperature=0.0,
            )
            content = resp.choices[0].message.content.strip()
            content = re.sub(r"^```(json)?", "", content).strip()
            content = re.sub(r"```$", "", content).strip()
            parsed = json.loads(content)
        except Exception as e:
            print(f"   ⚠️ DeepSeek 分类失败：{e}，跳过本批")
            continue

        if not isinstance(parsed, list):
            continue
        conn = get_db(db_file)
        for item in parsed:
            idx = item.get("idx")
            if idx is None or idx >= len(batch):
                continue
            row = batch[idx]
            tags = item.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            conn.execute(
                "UPDATE articles SET tags=?, ai_summary=? WHERE url=?",
                (json.dumps(tags, ensure_ascii=False), (item.get("summary") or "").strip(), row["url"]),
            )
            classified += 1
        conn.commit()
        conn.close()
        time.sleep(0.5)

    print(f"   ✅ 分类完成：{classified}/{len(rows)} 篇")
    return {"classified": classified}


# ---------------------------------------------------------------------------
# 去重 + 相似合并
# ---------------------------------------------------------------------------
def _norm_title_for_merge(title: str) -> str:
    return normalize_title(title)


def _char_bigrams(text: str) -> set:
    """字符二元组，用于中文标题的相似度判断。"""
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _title_similar(a: str, b: str) -> bool:
    """同题判断：优先用 bigram Jaccard（对中文标题更稳），再辅以 SequenceMatcher。"""
    a, b = a or "", b or ""
    if not a or not b:
        return False
    ba, bb = _char_bigrams(a), _char_bigrams(b)
    jaccard = len(ba & bb) / len(ba | bb) if (ba | bb) else 0.0
    if jaccard >= 0.55:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.9


def merge_articles(db_file: str = DB_FILE, cluster_batch: int = 40) -> dict:
    """标题去重 + DeepSeek 同主题聚类，写入 merged_key。"""
    conn = get_db(db_file)
    rows = conn.execute(
        "SELECT url, title, category, account_name, published FROM articles ORDER BY category, published DESC"
    ).fetchall()

    # —— 第一步：标题级去重（同题不同公众号 → 归入同一主题） ——
    # 按分类分组，逐条与已有主题比对
    groups: dict[str, dict] = {}          # key -> {urls:[], title:代表标题, category}
    by_norm: dict[str, str] = {}          # norm_title -> merged_key
    updates = []
    for r in rows:
        norm = _norm_title_for_merge(r["title"])
        merged_key = None
        if norm in by_norm:
            merged_key = by_norm[norm]
        else:
            for key, g in groups.items():
                if g["category"] == r["category"] and _title_similar(norm, _norm_title_for_merge(g["title"])):
                    merged_key = key
                    break
        if merged_key is None:
            merged_key = f"{r['category']}|{norm[:60]}|{len(groups)}"
            groups[merged_key] = {"title": r["title"], "category": r["category"], "urls": []}
            by_norm[norm] = merged_key
        groups[merged_key]["urls"].append(r["url"])
        updates.append((merged_key, r["url"]))

    conn.executemany("UPDATE articles SET merged_key=? WHERE url=?", updates)

    # —— 第二步：同分类内跨标题的「同主题」聚类（DeepSeek） ——
    cluster_stats = {"merged_topics": len(groups), "ai_merged_pairs": 0}
    if DEEPSEEK_API_KEY:
        client = _deepseek_client()
        # 取有多个不同标题的分类，做主题聚类
        for category in {r["category"] for r in rows if r["category"] != "未分类"}:
            cat_rows = [r for r in rows if r["category"] == category]
            if len(cat_rows) < 3:
                continue
            for i in range(0, len(cat_rows), cluster_batch):
                batch = cat_rows[i:i + cluster_batch]
                titles = [{"idx": j, "title": r["title"], "account": r["account_name"]} for j, r in enumerate(batch)]
                prompt = f"""
下面是一个分类「{category}」下的 {len(titles)} 篇文章。请找出「报道同一事件/同一主题」的重复文章组
（例如同一条新闻被多个公众号转载，或同一话题的不同转述）。
只返回 JSON 数组，每项是一组相近文章的 idx 列表，例如：
[{{"idxs": [0, 3, 7], "topic": "主题名"}}]
没有明显重复就返回 []。不要编造主题，只依据标题判断。
文章列表：{json.dumps(titles, ensure_ascii=False)}
"""
                try:
                    resp = client.chat.completions.create(
                        model=DEEPSEEK_MODEL,
                        messages=[{"role": "system", "content": "你是严谨的文档去重助手，只依据标题判断是否同一主题。"},
                                  {"role": "user", "content": prompt}],
                        temperature=0.0,
                    )
                    content = resp.choices[0].message.content.strip()
                    content = re.sub(r"^```(json)?", "", content).strip()
                    content = re.sub(r"```$", "", content).strip()
                    clusters = json.loads(content)
                except Exception as e:
                    print(f"   ⚠️ DeepSeek 聚类失败（{category}）：{e}")
                    continue
                if not isinstance(clusters, list):
                    continue
                for cl in clusters:
                    idxs = cl.get("idxs") or []
                    if len(idxs) < 2:
                        continue
                    topic = cl.get("topic") or "合并主题"
                    rep = batch[idxs[0]]
                    new_key = f"{category}|{topic[:40]}|ai{int(time.time()*1000)}"
                    urls = [batch[j]["url"] for j in idxs if 0 <= j < len(batch)]
                    if len(urls) < 2:
                        continue
                    conn.execute(
                        "UPDATE articles SET merged_key=? WHERE url IN (%s)"
                        % ",".join("?" * len(urls)),
                        [new_key] + urls,
                    )
                    cluster_stats["ai_merged_pairs"] += 1
                time.sleep(0.5)
        conn.commit()

    conn.commit()
    print(f"   ✅ 合并完成：主题 {cluster_stats['merged_topics']} 个（含 AI 跨标题合并 {cluster_stats['ai_merged_pairs']} 组）")
    conn.close()
    return cluster_stats


# ---------------------------------------------------------------------------
# 导出 Markdown 知识库
# ---------------------------------------------------------------------------
def _safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s or "").strip()
    return s[:60] or "未命名"


def export_kb(db_file: str = DB_FILE, export_dir: str = EXPORT_DIR) -> dict:
    conn = get_db(db_file)
    topics = conn.execute(
        "SELECT merged_key, category, COUNT(*) n, MAX(title) title "
        "FROM articles GROUP BY merged_key ORDER BY category, n DESC, title"
    ).fetchall()
    categories = sorted({t["category"] for t in topics})

    os.makedirs(export_dir, exist_ok=True)
    index_lines = ["# 公众号知识库", "", f"更新时间：{now_str()}", ""]

    for cat in categories:
        cat_dir = os.path.join(export_dir, _safe_name(cat))
        os.makedirs(cat_dir, exist_ok=True)
        cat_topics = [t for t in topics if t["category"] == cat]
        index_lines.append(f"\n## {cat}（{len(cat_topics)} 个主题）")
        for t in cat_topics:
            rows = conn.execute(
                "SELECT * FROM articles WHERE merged_key=? ORDER BY published DESC",
                (t["merged_key"],),
            ).fetchall()
            if not rows:
                continue
            topic_title = rows[0]["title"] or t["title"]
            fname = _safe_name(topic_title)
            path = os.path.join(cat_dir, f"{fname}.md")
            lines = [
                f"# {topic_title}",
                "",
                f"> 分类：{cat} ｜ 来源 {len(rows)} 篇 ｜ 最近更新 {now_str()}",
                "",
            ]
            for r in rows:
                tags = []
                try:
                    tags = json.loads(r["tags"] or "[]")
                except Exception:
                    tags = []
                lines.append(f"## {r['title']}")
                lines.append("")
                lines.append(f"- **公众号**：{r['account_name']}")
                lines.append(f"- **时间**：{r['published'] or '未知'}")
                if tags:
                    lines.append(f"- **标签**：{'、'.join(tags)}")
                if r["ai_summary"]:
                    lines.append(f"- **摘要**：{r['ai_summary']}")
                lines.append(f"- **原文**：{r['url']}")
                if r["summary"]:
                    lines.append("")
                    lines.append(r["summary"][:800])
                if r["content"] and r["content"] != r["summary"]:
                    lines.append("")
                    lines.append("> 全文：")
                    lines.append("")
                    lines.append(r["content"][:4000])
                lines.append("")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            index_lines.append(f"- [{topic_title}]({_safe_name(cat)}/{fname}.md)（{t['n']} 篇）")

    with open(os.path.join(export_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines) + "\n")

    conn.close()
    print(f"   ✅ 导出完成：{len(categories)} 个分类，{len(topics)} 个主题 → {export_dir}")
    return {"categories": len(categories), "topics": len(topics)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_init(args):
    conn = get_db()
    conn.close()
    if not os.path.exists(ACCOUNTS_FILE):
        import shutil
        example = os.path.join(os.path.dirname(ACCOUNTS_FILE), "wechat_accounts.example.yml")
        if os.path.exists(example):
            shutil.copyfile(example, ACCOUNTS_FILE)
            print(f"   ✅ 已生成账号清单模板：{ACCOUNTS_FILE}（请按需修改）")
        else:
            open(ACCOUNTS_FILE, "w", encoding="utf-8").write("categories: []\n")
            print(f"   ✅ 已生成空账号清单：{ACCOUNTS_FILE}")
    print(f"   ✅ 数据库已就绪：{DB_FILE}")


def cmd_list_accounts(args):
    try:
        feeds = list_feeds()
    except Exception as e:
        print(f"❌ 无法访问 wewe-rss：{e}")
        return
    categories = load_categories()
    print(f"共 {len(feeds)} 个公众号：")
    for feed in feeds:
        feed_id = str(feed.get("id") or feed.get("mpId") or "")
        name = (feed.get("mpName") or feed.get("name") or feed_id).strip()
        cat = match_category(name, categories)
        print(f"  - [{cat}] {name}  (id={feed_id})")


def cmd_full(args):
    print("== 1/4 抓取 ==")
    fetch_and_store()
    print("\n== 2/4 分类 ==")
    classify_articles()
    print("\n== 3/4 合并 ==")
    merge_articles()
    print("\n== 4/4 导出 ==")
    export_kb()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="公众号知识库：抓取 → 分类 → 去重合并 → 导出")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建库并生成账号清单模板")
    sub.add_parser("list-accounts", help="列出 wewe-rss 里的公众号及分类")
    sub.add_parser("fetch", help="抓取所有公众号文章入库")
    sub.add_parser("classify", help="DeepSeek 打标签 + 摘要")
    sub.add_parser("merge", help="去重 + 相似主题合并")
    sub.add_parser("export", help="导出 Markdown 知识库")
    sub.add_parser("full", help="依次执行 fetch→classify→merge→export")

    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init,
        "list-accounts": cmd_list_accounts,
        "fetch": lambda a: fetch_and_store(),
        "classify": lambda a: classify_articles(),
        "merge": lambda a: merge_articles(),
        "export": lambda a: export_kb(),
        "full": cmd_full,
    }
    handlers[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
