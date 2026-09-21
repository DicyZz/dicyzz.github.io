#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取范围开关（平台 / 翻页数 / 关键词个数）的单元测试。

运行：
    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import perfpulse_job_analysis as job  # noqa: E402


def _reload_with_env(**env):
    """带指定环境变量重新加载模块，返回新的模块对象。"""
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update({key: str(value) for key, value in env.items()})
    try:
        return importlib.reload(job)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestParseSources(unittest.TestCase):
    def test_empty_or_all_means_everything(self):
        self.assertEqual(job.parse_sources(""), set(job.SOURCE_KEYS))
        self.assertEqual(job.parse_sources("all"), set(job.SOURCE_KEYS))
        self.assertEqual(job.parse_sources("全部"), set(job.SOURCE_KEYS))
        self.assertEqual(job.parse_sources(None), set(job.SOURCE_KEYS))

    def test_pick_single_platform(self):
        self.assertEqual(job.parse_sources("boss"), {"boss"})
        self.assertEqual(job.parse_sources("liepin"), {"liepin"})

    def test_pick_multiple_platforms_with_spaces_and_case(self):
        self.assertEqual(job.parse_sources("BOSS, liepin"), {"boss", "liepin"})
        self.assertEqual(
            job.parse_sources("boss,liepin,zhilian,job51"),
            {"boss", "liepin", "zhilian", "job51"},
        )

    def test_unknown_platform_ignored(self):
        self.assertEqual(job.parse_sources("boss,nonsense"), {"boss"})
        self.assertEqual(job.parse_sources("nonsense"), set())


class TestSelectKeywords(unittest.TestCase):
    KEYWORDS = ["芯片设计", "IC设计", "数字IC设计", "模拟IC设计"]

    def test_zero_means_all(self):
        self.assertEqual(job.select_keywords(self.KEYWORDS, 0), self.KEYWORDS)
        self.assertEqual(job.select_keywords(self.KEYWORDS), self.KEYWORDS)

    def test_positive_limit_takes_first_n(self):
        self.assertEqual(job.select_keywords(self.KEYWORDS, 2), self.KEYWORDS[:2])

    def test_limit_larger_than_list(self):
        self.assertEqual(job.select_keywords(self.KEYWORDS, 99), self.KEYWORDS)


class TestEnvOverrides(unittest.TestCase):
    """SOURCES / PAGES / KEYWORD_LIMIT 通过环境变量生效。"""

    def tearDown(self):
        # 还原成干净配置，避免污染其他测试
        _reload_with_env(SOURCES="all", PAGES="1", KEYWORD_LIMIT="0")

    def test_sources_from_env(self):
        module = _reload_with_env(SOURCES="boss,liepin")
        self.assertEqual(module.SOURCES, {"boss", "liepin"})

    def test_pages_from_env_and_clamped(self):
        self.assertEqual(_reload_with_env(PAGES="3").PAGES, 3)
        self.assertEqual(_reload_with_env(PAGES="99").PAGES, 10)  # 上限 10
        self.assertEqual(_reload_with_env(PAGES="0").PAGES, 1)    # 下限 1
        self.assertEqual(_reload_with_env(PAGES="abc").PAGES, 1)  # 非法值回退

    def test_legacy_max_pages_still_works(self):
        self.assertEqual(_reload_with_env(MAX_PAGES="4").PAGES, 4)

    def test_keyword_limit_defaults_to_all(self):
        self.assertEqual(_reload_with_env(KEYWORD_LIMIT="0").KEYWORD_LIMIT, 0)
        self.assertEqual(_reload_with_env(KEYWORD_LIMIT="5").KEYWORD_LIMIT, 5)


class TestDefaultConfig(unittest.TestCase):
    def test_defaults_are_sane(self):
        self.assertGreaterEqual(job.PAGES, 1)
        self.assertLessEqual(job.PAGES, 10)
        self.assertEqual(job.KEYWORD_LIMIT, 0)  # 默认用全部扩展关键词
        self.assertEqual(job.SOURCES, set(job.SOURCE_KEYS))


if __name__ == "__main__":
    unittest.main()
