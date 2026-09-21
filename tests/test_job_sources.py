#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取范围开关（平台 / 翻页数 / 关键词个数）的单元测试。

注意：这些用例必须**显式指定环境**再重载模块。workflow 运行时会注入
PAGES / KEYWORD_LIMIT / SOURCES（来自表单输入），如果用例直接读模块里
import 时算出来的常量，就会在 runner 上得出和本地不同的结果。

运行：
    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import perfpulse_job_analysis as job  # noqa: E402

# 会被 run 环境注入、且影响模块常量的环境变量
ENV_KEYS = ("SOURCES", "PAGES", "MAX_PAGES", "KEYWORD_LIMIT")


def _reload_with_env(**env):
    """清掉相关环境变量后按给定值重载模块；值传 None 表示保持未设置。"""
    saved = {key: os.environ.get(key) for key in set(ENV_KEYS) | set(env)}
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    for key, value in env.items():
        if value is not None:
            os.environ[key] = str(value)
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


class TestConfigFromEnv(unittest.TestCase):
    """SOURCES / PAGES / KEYWORD_LIMIT 通过环境变量生效。"""

    def tearDown(self):
        # 用恢复后的真实环境重载，避免污染其他用例
        importlib.reload(job)

    def test_defaults_when_env_is_clean(self):
        module = _reload_with_env()  # 全部清空
        self.assertEqual(module.PAGES, 1)
        self.assertEqual(module.KEYWORD_LIMIT, 0)  # 0 = 用全部扩展关键词
        self.assertEqual(module.SOURCES, set(module.SOURCE_KEYS))

    def test_sources_from_env(self):
        self.assertEqual(_reload_with_env(SOURCES="boss,liepin").SOURCES, {"boss", "liepin"})
        self.assertEqual(_reload_with_env(SOURCES="boss").SOURCES, {"boss"})

    def test_pages_from_env_and_clamped(self):
        self.assertEqual(_reload_with_env(PAGES="3").PAGES, 3)
        self.assertEqual(_reload_with_env(PAGES="99").PAGES, 10)  # 上限 10
        self.assertEqual(_reload_with_env(PAGES="0").PAGES, 1)    # 下限 1
        self.assertEqual(_reload_with_env(PAGES="abc").PAGES, 1)  # 非法值回退

    def test_pages_takes_precedence_over_legacy_max_pages(self):
        # workflow 同时注入 PAGES 时，以 PAGES 为准
        self.assertEqual(_reload_with_env(PAGES="3", MAX_PAGES="9").PAGES, 3)

    def test_legacy_max_pages_used_when_pages_absent(self):
        self.assertEqual(_reload_with_env(MAX_PAGES="4").PAGES, 4)

    def test_keyword_limit_from_env(self):
        self.assertEqual(_reload_with_env(KEYWORD_LIMIT="0").KEYWORD_LIMIT, 0)
        self.assertEqual(_reload_with_env(KEYWORD_LIMIT="5").KEYWORD_LIMIT, 5)


if __name__ == "__main__":
    unittest.main()
