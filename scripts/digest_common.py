#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS 简报类 flow 的公共实现。

AIFrontier / ChinaTech / FinFrontier / PerfPulse 四个周报共用这套逻辑：

1. **抓取**：并发拉取 RSS/Atom，单源超时保护，记录每个源的健康状况
   （成功 / HTTP 错误 / 解析失败 / 0 条），便于事后体检。
2. **清洗**：HTML 摘要转纯文本；发布时间统一按 UTC 解析
   （原实现用 ``time.mktime`` 会把 UTC 当成机器本地时间，在国内机器上会偏移 8 小时）。
3. **过滤**：默认 7 天窗口；**没有发布时间的条目单独标记并限量**——
   原实现里这类条目永远通过时间过滤，导致同一条旧文每周都混进「本周」简报。
4. **去重**：同一篇文章被多个源收录时只保留一条（先按链接，再按标准化标题）。
5. **渲染**：条目 → 大模型上下文（保持 标题/链接/摘要 字段不变）；正文 → 邮件
   HTML + 纯文本 + 原始条目清单附件（附件保证模型漏写时素材不丢）。
6. **自检**：``python scripts/digest_common.py --check <flow>`` 体检各 flow 的所有源。
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import smtplib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import markdown
import requests
from premailer import transform

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 只带 User-Agent 会被不少站点（Cloudflare 前置）判为爬虫直接 403；
# 补上浏览器的 Accept / Accept-Language 后，量子位等源即可正常返回。
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
              "text/html;q=0.8, */*;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 单源抓取参数
DEFAULT_MAX_ITEMS_PER_SOURCE = 6
DEFAULT_MAX_HOURS = 168          # 7 天
DEFAULT_TIMEOUT = 15             # 秒（原实现是 8 秒，对慢源太紧）
DEFAULT_WORKERS = 24
MAX_UNDATED_PER_SOURCE = 1       # 没写发布时间的条目，每个源最多收几条
FETCH_ATTEMPTS = 2               # 网络抖动（SSL/超时）重试次数


# ---------------------------------------------------------------------------
# 条目清洗与时间处理
# ---------------------------------------------------------------------------
def clean_html_summary(html_text: str, limit: int = 400) -> str:
    """HTML → 单行纯文本摘要。"""
    if not html_text:
        return ""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = (
        text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def entry_datetime(entry) -> datetime | None:
    """从 feedparser 条目里取 UTC 时间；取不到返回 None。

    注意：feedparser 的 ``*_parsed`` 已经是 UTC 结构，必须用
    ``calendar.timegm`` 解析；用 ``time.mktime`` 会按本地时区解释，
    在 UTC+8 的机器上会整体偏移 8 小时。
    """
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    except Exception:
        return None


def is_recent(published: datetime | None, max_hours: int = DEFAULT_MAX_HOURS) -> bool:
    """有明确时间的按窗口过滤；没有时间的交给调用方单独处理。"""
    if published is None:
        return True
    return (datetime.now(timezone.utc) - published) <= timedelta(hours=max_hours)


def normalize_title(title: str) -> str:
    """标题标准化：去标签、去空白、去标点，用于跨源去重。"""
    text = re.sub(r"<[^>]+>", " ", title or "")
    # 中英文标点都要去掉：同一篇报道在不同源的标题常只差标点
    text = re.sub(r"[\s\-—_·|:：;；,，、.。!！?？'\"“”‘’()（）\[\]【】《》]+", "", text)
    return text.lower()


def _link_key(link: str) -> str:
    """链接去参数，避免同一篇文章因 utm 参数被当成两条。"""
    link = (link or "").strip()
    return link.split("?")[0].split("#")[0].rstrip("/").lower()


def make_item(category: str, source: str, title: str, link: str,
              summary: str = "", published: datetime | None = None) -> dict:
    """构造统一格式的条目。"""
    return {
        "category": category,
        "source": source,
        "title": (title or "").strip(),
        "link": (link or "").strip(),
        "summary": clean_html_summary(summary),
        "published": published,
    }


def dedupe_items(items: list) -> tuple:
    """跨源去重，返回 (去重后条目, 被丢弃条数)。"""
    seen_links, seen_titles, kept, dropped = set(), set(), [], 0
    for item in items:
        link_key = _link_key(item.get("link", ""))
        title_key = normalize_title(item.get("title", ""))
        if link_key and link_key in seen_links:
            dropped += 1
            continue
        if title_key and title_key in seen_titles:
            dropped += 1
            continue
        if link_key:
            seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        kept.append(item)
    return kept, dropped


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------
def fetch_source(source_name: str, feed_url: str, category: str,
                 max_items: int = DEFAULT_MAX_ITEMS_PER_SOURCE,
                 max_hours: int = DEFAULT_MAX_HOURS,
                 timeout: int = DEFAULT_TIMEOUT,
                 session: requests.Session | None = None) -> tuple:
    """抓取单个源，返回 (条目列表, 状态说明)。"""
    if not feed_url.startswith("http"):
        feed_url = "https://" + feed_url
    http = session or requests

    last_error = ""
    feed = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            resp = http.get(feed_url, headers=DEFAULT_HEADERS, timeout=timeout)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                # 403/404 重试通常没用，直接停
                if 400 <= resp.status_code < 500:
                    return [], last_error
                continue
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                return [], "空feed"
            break
        except Exception as e:
            last_error = f"异常:{type(e).__name__}"
            if attempt + 1 < FETCH_ATTEMPTS:
                time.sleep(1.5)  # 网络抖动（SSL/超时）值得再试一次
    if feed is None:
        return [], last_error

    items, undated = [], 0
    for entry in feed.entries:
        if len(items) >= max_items:
            break
        published = entry_datetime(entry)
        if published is None:
            if undated >= MAX_UNDATED_PER_SOURCE:
                continue
            undated += 1
        elif not is_recent(published, max_hours):
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        items.append(make_item(
            category, source_name, title,
            entry.get("link", "") or entry.get("id", ""),
            entry.get("summary") or entry.get("description") or "",
            published,
        ))
    note = "ok" if items else "无近期条目"
    if undated:
        note += f"（含{undated}条无日期）"
    return items, note


def is_broken(note: str) -> bool:
    """源是否处于「坏了」的状态（HTTP 错误 / 解析为空 / 请求异常）。"""
    return note.startswith("HTTP") or note in {"空feed"} or note.startswith("异常")


def collect(module_feeds: dict, extra_items: list | None = None,
            max_items_per_source: int = DEFAULT_MAX_ITEMS_PER_SOURCE,
            category_max_items: dict | None = None,
            max_hours: int = DEFAULT_MAX_HOURS,
            timeout: int = DEFAULT_TIMEOUT,
            workers: int = DEFAULT_WORKERS) -> tuple:
    """并发抓取全部源并做去重，返回 (条目, 统计信息)。

    Args:
        module_feeds: {分类: {源名: feed_url}}
        extra_items: 额外条目（例如 JSON 接口抓来的），会一起参与去重与统计
        category_max_items: 按分类覆盖每源条数上限（各 flow 原本的差异化配置）
    """
    items = list(extra_items or [])
    stats = {
        "sources": 0, "ok": 0, "empty": 0, "failed": 0, "failures": [],
        "items_raw": 0, "items": 0, "deduped": 0,
        "max_hours": max_hours,
        "undated": 0,
    }
    print(f"1. 并发拉取 {sum(len(v) for v in module_feeds.values())} 个 RSS 源"
          f"（{max_hours}h 时间窗，单源 {timeout}s 超时）...")

    with requests.Session() as session, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for category, feeds in module_feeds.items():
            cap = max_items_per_source
            if category_max_items:
                cap = category_max_items.get(category, cap)
            for source_name, feed_url in feeds.items():
                stats["sources"] += 1
                futures[pool.submit(
                    fetch_source, source_name, feed_url, category,
                    cap, max_hours, timeout, session,
                )] = source_name
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                found, note = future.result()
            except Exception as e:  # 理论上不会走到，兜底
                found, note = [], f"{type(e).__name__}"
            if found:
                stats["ok"] += 1
                items.extend(found)
            elif is_broken(note):
                stats["failed"] += 1
                stats["failures"].append(f"{source_name}({note})")
            else:
                stats["empty"] += 1

    stats["items_raw"] = len(items)
    items, dropped = dedupe_items(items)
    stats["deduped"] = dropped
    stats["items"] = len(items)
    stats["undated"] = sum(1 for i in items if not i.get("published"))

    print(f"   ✅ {stats['ok']} 个源有内容 / {stats['empty']} 个源无近期条目 / "
          f"{stats['failed']} 个源失败；去重丢弃 {dropped} 条，最终 {len(items)} 条")
    if stats["failures"]:
        print(f"   ⚠️ 失败的源：{'、'.join(stats['failures'][:8])}"
              + ("…" if len(stats["failures"]) > 8 else ""))
    if not items:
        print("   ⚠️ 未抓到任何条目")
    return items, stats


def build_context(items: list) -> str:
    """把条目组织成给大模型的上下文（保持原有的 模块/平台源/标题/链接/摘要 结构）。"""
    blocks = []
    for item in items:
        published = item.get("published")
        when = published.strftime("%Y-%m-%d %H:%M UTC") if published else "未知"
        blocks.append(
            f"【模块: {item['category']} | 平台源: {item['source']}】\n"
            f"标题: {item['title']}\n"
            f"链接: {item['link']}\n"
            f"发布时间: {when}\n"
            f"摘要: {item['summary']}\n"
        )
    return "\n---\n".join(blocks) if blocks else "本周暂无新动态更新。"


def stats_line(stats: dict) -> str:
    """邮件头部展示的一行统计。"""
    window = stats.get("max_hours", DEFAULT_MAX_HOURS)
    window_text = f"{window // 24} 天" if window % 24 == 0 else f"{window} 小时"
    parts = [
        f"扫描 {stats.get('sources', 0)} 个源",
        f"收录 {stats.get('items', 0)} 条",
        f"时间窗 {window_text}",
    ]
    if stats.get("deduped"):
        parts.append(f"去重 {stats['deduped']} 条")
    if stats.get("failures"):
        parts.append(f"{len(stats['failures'])} 个源不可用")
    return " · ".join(parts)


def items_to_markdown(items: list, title: str = "本期抓取到的原始条目") -> str:
    """把条目导出成 Markdown 清单（作为邮件附件，模型漏写时素材不丢）。"""
    lines = [f"# {title}", f"共 {len(items)} 条", ""]
    current = None
    for item in items:
        if item["category"] != current:
            current = item["category"]
            lines += [f"## {current}", ""]
        when = item["published"].strftime("%Y-%m-%d") if item.get("published") else "日期未知"
        lines.append(f"- **{item['title']}** — {item['source']}（{when}）")
        if item.get("link"):
            lines.append(f"  {item['link']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 邮件渲染与发送
# ---------------------------------------------------------------------------
def _markdown_to_text(md_text: str) -> str:
    """粗略的 Markdown → 纯文本（给不支持 HTML 的客户端用）。"""
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", md_text or "")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"`{1,3}", "", text)
    return text.strip()


def render_email(*, brand_title: str, subtitle: str, footer: str,
                 markdown_text: str, stats: dict, date_str: str) -> tuple:
    """渲染邮件，返回 (html, plain_text)。"""
    raw_html = markdown.markdown(
        markdown_text or "",
        extensions=["tables", "fenced_code", "codehilite", "nl2br", "toc"],
    )
    styled_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *, *:before, *:after {{ box-sizing: border-box !important; }}
    body {{
      font-family: -apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", Arial, sans-serif;
      background-color: #ffffff;
      color: #24292e;
      margin: 0;
      padding: 0;
      width: 100% !important;
    }}
    .container {{ width: 100% !important; margin: 0 auto; background: #ffffff; }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 16px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 700; color: #ffffff; }}
    .header .subtitle {{ margin-top: 10px; font-size: 12px; color: #a5b4fc; }}
    .header .stats {{
      margin-top: 12px;
      font-size: 12px;
      color: #cbd5e1;
      background: rgba(148, 163, 184, 0.18);
      border-radius: 6px;
      padding: 6px 10px;
      display: inline-block;
    }}
    .content {{ padding: 16px 12px; font-size: 15px; line-height: 1.75; color: #334155; }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 4px solid #4f46e5;
      padding: 8px 12px;
      margin-top: 36px;
      margin-bottom: 20px;
    }}
    h3 {{ font-size: 16px; color: #0f172a; margin-top: 28px; margin-bottom: 12px; font-weight: 600; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    p {{ margin: 12px 0 16px 0; color: #334155; line-height: 1.75; text-align: justify; }}
    a {{ color: #4f46e5 !important; text-decoration: none !important; font-weight: 500 !important; border-bottom: 1px dashed #6366f1 !important; }}
    code {{ background-color: #f1f5f9; color: #4f46e5; padding: 2px 5px; border-radius: 4px; font-size: 88%; font-weight: 600; }}
    pre {{
      background-color: #0f172a !important;
      color: #f8fafc !important;
      padding: 14px !important;
      border-radius: 6px !important;
      overflow-x: auto !important;
      font-size: 12px !important;
      line-height: 1.6 !important;
      margin: 16px 0 !important;
    }}
    pre code {{ background-color: transparent !important; color: #f8fafc !important; padding: 0 !important; }}
    blockquote {{ margin: 20px 0; padding: 12px 14px; color: #1e293b; border-left: 4px solid #4f46e5; background-color: #f8fafc; font-size: 14px; }}
    .notice {{ margin: 0 0 18px 0; padding: 10px 12px; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; color: #9a3412; font-size: 13px; }}
    .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 12px; text-align: center; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{brand_title}</h1>
      <div class="subtitle">{subtitle} · 发布日期：{date_str}</div>
      <div class="stats">{stats_line(stats)}</div>
    </div>
    <div class="content">
      {raw_html}
    </div>
    <div class="footer">
      {footer}
    </div>
  </div>
</body>
</html>
"""
    return transform(styled_html), _markdown_to_text(markdown_text)


def send_email(subject: str, html: str, plain_text: str,
               attachments: list | None = None) -> bool:
    """发送邮件（465 用 SSL，其它端口用 STARTTLS）。attachments: [(文件名, 内容)]"""
    sender = (os.environ.get("EMAIL_SENDER") or "").strip()
    receiver = (os.environ.get("EMAIL_RECEIVER") or "").strip() or sender
    password = (os.environ.get("EMAIL_PASSWORD") or "").strip()
    host = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
    try:
        port = int(os.environ.get("EMAIL_PORT", "465"))
    except ValueError:
        port = 465

    if not sender or not password:
        print("❌ 缺少 EMAIL_SENDER / EMAIL_PASSWORD，无法发送")
        return False

    message = MIMEMultipart("mixed")
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = subject

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_text or "", "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    message.attach(alternative)

    for filename, content in (attachments or []):
        part = MIMEBase("text", "markdown")
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(part)

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print(f"🎉 邮件已发送到 {receiver}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {type(e).__name__}: {e}")
        return False


def save_backup(markdown_text: str, date_str: str, path: str) -> None:
    """把简报正文落盘备份（workflow 会把它作为 artifact 上传）。"""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown_text or "")
        print(f"💾 简报已备份到 {path}")
    except Exception as e:
        print(f"⚠️ 备份失败: {e}")


# ---------------------------------------------------------------------------
# 源体检 CLI：python scripts/digest_common.py --check aifrontier
# ---------------------------------------------------------------------------
def _load_flow(name: str):
    """加载某个 flow 脚本，取它的 MODULE_FEEDS / JSON_FEEDS。"""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}_push.py")
    spec = importlib.util.spec_from_file_location(f"{name}_push", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_sources(flow_names: list) -> int:
    """体检各 flow 的所有源，打印失效/陈旧清单。返回失败源数量。"""
    bad_total = 0
    for name in flow_names:
        module = _load_flow(name)
        feeds = getattr(module, "MODULE_FEEDS", {})
        pool = [(cat, src, url) for cat, items in feeds.items() for src, url in items.items()]
        print(f"\n===== {name}: {len(pool)} 个源 =====")
        with ThreadPoolExecutor(max_workers=DEFAULT_WORKERS) as ex:
            results = list(ex.map(
                lambda x: fetch_source(x[1], x[2], x[0], max_items=3, max_hours=24 * 60), pool
            ))
        bad = []
        for (cat, src, url), (items, note) in zip(pool, results):
            if is_broken(note):
                bad.append((src, note, url))
            elif not items:
                bad.append((src, "60天内无内容", url))
        bad_total += len(bad)
        for src, note, url in bad:
            print(f"  ❌ {src:32} {note:14} {url[:90]}")
        print(f"  → {len(pool) - len(bad)}/{len(pool)} 个源正常")
    return bad_total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RSS 简报公共模块 / 源体检工具")
    parser.add_argument("--check", nargs="*", default=None,
                        help="体检指定 flow（如 aifrontier chinatech），留空表示全部")
    args = parser.parse_args(argv)
    if args.check is None and len(sys.argv) == 1:
        parser.print_help()
        return 0
    flows = args.check or ["aifrontier", "chinatech", "finfrontier", "perfpulse"]
    bad = check_sources(flows)
    print(f"\n总结：共发现 {bad} 个需要处理的源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
