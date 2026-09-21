#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digest_common（四个周报 flow 的公共实现）单元测试。

覆盖重点：
- 时间解析必须按 UTC（原实现用 time.mktime，在 UTC+8 机器上会偏移 8 小时）
- 没有发布时间的条目要限量，避免旧文每周反复混进「本周」简报
- 跨源去重、按分类的每源条数上限、渲染与统计

运行：
    python -m unittest discover -s tests -v
"""

import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import digest_common as digest  # noqa: E402


def _struct(dt_utc: datetime):
    """把 UTC 时间转成 feedparser 风格的 time.struct_time（UTC 语义）。"""
    return time.gmtime(dt_utc.timestamp())


class FakeResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """只返回预置内容的假会话，用来离线测试抓取逻辑。"""

    def __init__(self, responses):
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def rss_bytes(items):
    """拼一个最小可用的 RSS。items: [(标题, 链接, 发布时间或 None)]"""
    entries = []
    for title, link, published in items:
        date = f"<pubDate>{published.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>" if published else ""
        entries.append(f"<item><title>{title}</title><link>{link}</link>{date}"
                       f"<description>desc</description></item>")
    body = "".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>t</title><link>https://x.test</link>{body}</channel></rss>"
    ).encode("utf-8")


class TestTimeHandling(unittest.TestCase):
    def test_entry_datetime_is_utc(self):
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        parsed = digest.entry_datetime({"published_parsed": _struct(dt)})
        self.assertEqual(parsed, dt)  # 按 UTC 解析，不受本机时区影响

    def test_entry_datetime_missing(self):
        self.assertIsNone(digest.entry_datetime({}))

    def test_is_recent(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(digest.is_recent(now - timedelta(hours=1)))
        self.assertTrue(digest.is_recent(None))          # 无日期交给调用方单独限量
        self.assertFalse(digest.is_recent(now - timedelta(days=8)))
        self.assertTrue(digest.is_recent(now - timedelta(days=8), max_hours=24 * 30))


class TestCleaning(unittest.TestCase):
    def test_clean_html_summary(self):
        self.assertEqual(digest.clean_html_summary("<p>Hello&nbsp;<b>World</b></p>"), "Hello World")
        self.assertEqual(digest.clean_html_summary(""), "")
        self.assertEqual(len(digest.clean_html_summary("x" * 500)), 400)

    def test_normalize_title(self):
        self.assertEqual(digest.normalize_title("Same  Title!"), digest.normalize_title("same title"))
        self.assertEqual(digest.normalize_title("A、B：C"), "abc")

    def test_make_item_cleans_summary(self):
        item = digest.make_item("News", "src", "标题", "https://x.test/a", "<p>摘 要</p>")
        self.assertEqual(item["summary"], "摘 要")
        self.assertEqual(item["published"], None)


class TestDedupe(unittest.TestCase):
    def test_dedupe_by_link_ignoring_query(self):
        items = [
            digest.make_item("News", "A", "标题一", "https://x.test/a?utm=1"),
            digest.make_item("News", "B", "标题一（转载）", "https://x.test/a"),
        ]
        kept, dropped = digest.dedupe_items(items)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, 1)

    def test_dedupe_by_normalized_title(self):
        items = [
            digest.make_item("News", "A", "Chip! News", "https://a.test/1"),
            digest.make_item("News", "B", "chip news", "https://b.test/2"),
        ]
        kept, dropped = digest.dedupe_items(items)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, 1)


class TestFetchSource(unittest.TestCase):
    def test_parses_recent_entries(self):
        now = datetime.now(timezone.utc)
        session = FakeSession(FakeResponse(200, rss_bytes([
            ("新文章", "https://x.test/1", now - timedelta(hours=2)),
            ("旧文章", "https://x.test/2", now - timedelta(days=30)),
        ])))
        items, note = digest.fetch_source("src", "https://feed.test/rss", "News",
                                          max_hours=168, session=session)
        self.assertEqual([i["title"] for i in items], ["新文章"])
        self.assertEqual(items[0]["source"], "src")
        self.assertEqual(items[0]["category"], "News")
        self.assertEqual(note, "ok")
        # 请求头必须带浏览器特征（不少站点只认这些，缺了就 403）
        self.assertEqual(session.calls[0]["headers"], digest.DEFAULT_HEADERS)

    def test_undated_entries_are_capped(self):
        session = FakeSession(FakeResponse(200, rss_bytes([
            ("无日期A", "https://x.test/a", None),
            ("无日期B", "https://x.test/b", None),
            ("无日期C", "https://x.test/c", None),
        ])))
        items, note = digest.fetch_source("src", "https://feed.test/rss", "News",
                                          max_hours=168, session=session)
        self.assertEqual(len(items), digest.MAX_UNDATED_PER_SOURCE)
        self.assertIn("无日期", note)

    def test_http_error_reported(self):
        session = FakeSession(FakeResponse(403))
        items, note = digest.fetch_source("src", "https://feed.test/rss", "News", session=session)
        self.assertEqual(items, [])
        self.assertEqual(note, "HTTP 403")
        self.assertEqual(len(session.calls), 1)  # 4xx 不重试

    def test_retry_on_exception(self):
        class FlakySession(FakeSession):
            def get(self, url, headers=None, timeout=None):
                self.calls.append({"url": url})
                if len(self.calls) == 1:
                    raise ConnectionError("boom")
                return FakeResponse(200, rss_bytes([
                    ("重试成功", "https://x.test/1", datetime.now(timezone.utc)),
                ]))

        session = FlakySession(FakeResponse(500))
        items, note = digest.fetch_source("src", "https://feed.test/rss", "News", session=session)
        self.assertEqual([i["title"] for i in items], ["重试成功"])
        self.assertEqual(len(session.calls), 2)

    def test_empty_feed(self):
        session = FakeSession(FakeResponse(
            200, b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        ))
        items, note = digest.fetch_source("src", "https://feed.test/rss", "News", session=session)
        self.assertEqual(items, [])
        self.assertEqual(note, "空feed")


class TestCollect(unittest.TestCase):
    def setUp(self):
        self._saved = digest.fetch_source
        self.calls = []

        def fake_fetch(source_name, feed_url, category, max_items=6, max_hours=168,
                       timeout=15, session=None):
            self.calls.append((source_name, category, max_items))
            return [digest.make_item(category, source_name, f"{source_name}-标题", f"https://x.test/{source_name}")], "ok"

        digest.fetch_source = fake_fetch

    def tearDown(self):
        digest.fetch_source = self._saved

    def test_category_caps_are_applied(self):
        module_feeds = {
            "Macro_Markets": {"CNBC": "https://a", "FT": "https://b"},
            "Crypto": {"CoinDesk": "https://c"},
        }
        items, stats = digest.collect(module_feeds, category_max_items={"Macro_Markets": 3, "Crypto": 4})
        caps = {(name, cat): cap for name, cat, cap in self.calls}
        self.assertEqual(caps[("CNBC", "Macro_Markets")], 3)
        self.assertEqual(caps[("FT", "Macro_Markets")], 3)
        self.assertEqual(caps[("CoinDesk", "Crypto")], 4)
        self.assertEqual(stats["sources"], 3)
        self.assertEqual(stats["ok"], 3)
        self.assertEqual(stats["items"], 3)

    def test_flat_cap_when_no_category_map(self):
        digest.collect({"News": {"A": "https://a"}})
        self.assertEqual(self.calls[0][2], digest.DEFAULT_MAX_ITEMS_PER_SOURCE)

    def test_failures_and_dedupe_are_counted(self):
        digest.fetch_source = lambda *a, **k: ([], "HTTP 403")
        items, stats = digest.collect({"News": {"A": "https://a"}})
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertEqual(items, [])
        self.assertIn("A(HTTP 403)", stats["failures"][0])


class TestRendering(unittest.TestCase):
    def test_build_context_keeps_expected_fields(self):
        items = [
            digest.make_item("News", "Phoronix", "标题", "https://x.test/a", "摘要",
                             datetime(2026, 9, 20, 1, 2, 3, tzinfo=timezone.utc)),
            digest.make_item("News", "Phoronix", "无日期标题", "https://x.test/b"),
        ]
        context = digest.build_context(items)
        self.assertIn("【模块: News | 平台源: Phoronix】", context)
        self.assertIn("标题: 标题", context)
        self.assertIn("链接: https://x.test/a", context)
        self.assertIn("发布时间: 2026-09-20 01:02 UTC", context)
        self.assertIn("发布时间: 未知", context)
        self.assertEqual(digest.build_context([]), "本周暂无新动态更新。")

    def test_stats_line(self):
        stats = {"sources": 54, "items": 120, "deduped": 8, "failures": ["x"], "max_hours": 168}
        line = digest.stats_line(stats)
        self.assertIn("扫描 54 个源", line)
        self.assertIn("收录 120 条", line)
        self.assertIn("时间窗 7 天", line)
        self.assertIn("1 个源不可用", line)

    def test_items_to_markdown(self):
        items = [
            digest.make_item("News", "A", "标题一", "https://x.test/a", published=datetime(2026, 9, 20, tzinfo=timezone.utc)),
            digest.make_item("Papers", "B", "标题二", "https://x.test/b"),
        ]
        md = digest.items_to_markdown(items)
        self.assertIn("## News", md)
        self.assertIn("## Papers", md)
        self.assertIn("**标题一** — A（2026-09-20）", md)
        self.assertIn("日期未知", md)

    def test_render_email_has_stats_and_plain_text(self):
        html, text = digest.render_email(
            brand_title="测试简报", subtitle="副标题", footer="页脚",
            markdown_text="## 新闻\n\n**要点**：[标题](https://x.test/a) 提升 **2 倍**。",
            stats={"sources": 10, "items": 20, "deduped": 1, "failures": [], "max_hours": 168},
            date_str="2026-09-22",
        )
        self.assertIn("测试简报", html)
        self.assertIn("扫描 10 个源", html)
        self.assertIn("2026-09-22", html)
        # 纯文本版本要保留链接目标、去掉 markdown 标记
        self.assertIn("标题 (https://x.test/a)", text)
        self.assertNotIn("**", text)
        self.assertNotIn("##", text)


if __name__ == "__main__":
    unittest.main()
