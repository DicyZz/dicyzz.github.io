#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boss_scraper 的离线回归测试（不需要浏览器、不需要登录态）。

运行：
    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import boss_scraper as boss  # noqa: E402


# 模拟站点搜索结果页的岗位卡片结构（含改版后的多种 class 命名）
LIST_PAGE_HTML = """
<html><body>
<ul class="job-list-box">
  <li class="job-card-wrapper">
    <div class="job-card-body clearfix">
      <a href="/job_detail/enc_aaa111.html?lid=1abc&amp;securityId=sec1" target="_blank">
        <div class="job-card-left">
          <div class="job-title clearfix">
            <span class="job-name">数字IC设计工程师</span>
            <span class="salary">30-60K·15薪</span>
          </div>
          <div class="job-area-wrapper"><span class="job-area">北京·朝阳区·望京</span></div>
          <div class="tag-list"><ul><li>3-5年</li><li>本科</li></ul></div>
        </div>
      </a>
      <div class="job-card-right">
        <div class="company-info">
          <h3 class="company-name"><a href="/gongsi/xyz.html">某某微电子</a></h3>
          <ul class="company-tag-list"><li>半导体/芯片</li><li>B轮</li><li>100-499人</li></ul>
        </div>
        <div class="info-public"><span class="boss-name">张女士</span><span class="boss-title">招聘者</span></div>
      </div>
    </div>
  </li>
  <li class="job-card-wrapper">
    <a href="/job_detail/enc_bbb222.html?lid=2def" target="_blank">
      <div class="job-card-left">
        <div class="job-title"><span class="job-name">模拟IC设计（校招）</span><span class="salary">20-35K</span></div>
        <div class="job-area-wrapper"><span class="job-area">上海·浦东新区</span></div>
      </div>
    </a>
    <div class="job-card-right">
      <div class="company-info"><h3 class="company-name">另一家公司</h3></div>
    </div>
  </li>
</ul>
</body></html>
"""

LOGIN_PAGE_HTML = """
<html><body><div class="login-dialog"><p>请先登录后查看该页面</p></div></body></html>
"""


def api_payload():
    """模拟 /wapi/zpgeek/search/joblist.json 的响应。"""
    return {
        "code": 0,
        "message": "Success",
        "zpData": {
            "hasMore": True,
            "totalCount": 128,
            "jobList": [
                {
                    "encryptJobId": "enc_aaa111",
                    "lid": "1abc",
                    "securityId": "sec1",
                    "jobName": "数字IC验证工程师",
                    "salaryDesc": "35-65K·16薪",
                    "jobLabels": ["3-5年", "本科"],
                    "skills": ["SystemVerilog", "UVM"],
                    "welfareList": ["五险一金", "股票期权"],
                    "jobType": 0,
                    "cityName": "北京",
                    "areaDistrict": "海淀区",
                    "businessDistrict": "中关村",
                    "brandName": "某某芯片",
                    "brandIndustry": "半导体/芯片",
                    "brandScaleName": "500-999人",
                    "bossName": "李女士",
                    "bossTitle": "HRBP",
                    "bossActiveTimeDesc": "刚刚活跃",
                },
                {
                    "encryptJobId": "enc_ccc333",
                    "jobName": "IC设计实习生",
                    "jobType": 1,
                    "cityName": "上海",
                    "brandName": "实习公司",
                },
                {"jobName": "", "encryptJobId": "enc_empty"},
            ],
        },
    }


class TestUrlAndCity(unittest.TestCase):
    def test_known_city(self):
        self.assertEqual(boss.resolve_city_code("深圳"), "101280600")

    def test_unknown_city_falls_back_to_nationwide(self):
        self.assertEqual(boss.resolve_city_code("曹县"), boss.BOSS_NATIONWIDE_CITY_CODE)

    def test_city_label(self):
        self.assertEqual(boss.city_label("深圳"), "深圳")
        self.assertEqual(boss.city_label("曹县"), "全国")

    def test_search_url_encodes_keyword_and_pages(self):
        url = boss.build_search_url("芯片设计", "北京")
        self.assertIn("query=%E8%8A%AF%E7%89%87%E8%AE%BE%E8%AE%A1", url)
        self.assertIn("city=101010100", url)
        self.assertNotIn("page=", url)
        self.assertIn("page=3", boss.build_search_url("芯片设计", "北京", 3))

    def test_absolutize(self):
        self.assertEqual(
            boss.absolutize("/job_detail/a.html?lid=1"),
            "https://www.zhipin.com/job_detail/a.html?lid=1",
        )
        self.assertEqual(boss.absolutize("//www.zhipin.com/x"), "https://www.zhipin.com/x")
        self.assertEqual(boss.absolutize("https://www.zhipin.com/y"), "https://www.zhipin.com/y")
        self.assertEqual(boss.absolutize(""), "")

    def test_build_job_url(self):
        url = boss.build_job_url("enc1", "lid1", "sec1")
        self.assertEqual(url, "https://www.zhipin.com/job_detail/enc1.html?lid=lid1&securityId=sec1")
        self.assertEqual(boss.build_job_url("", "lid1"), "")

    def test_normalize_location(self):
        self.assertEqual(boss.normalize_location("北京", "朝阳区", "望京"), "北京·朝阳区·望京")
        self.assertEqual(boss.normalize_location("北京", "北京"), "北京")
        self.assertEqual(boss.normalize_location("", "", "", fallback="北京"), "北京")


class TestApiPayload(unittest.TestCase):
    def test_parse_payload(self):
        jobs, has_more = boss.parse_list_api_payload(api_payload(), "北京")
        self.assertTrue(has_more)
        self.assertEqual(len(jobs), 2)  # 标题为空的那条被丢弃

    def test_job_fields(self):
        jobs, _ = boss.parse_list_api_payload(api_payload(), "北京")
        job = jobs[0]
        self.assertEqual(job["title"], "数字IC验证工程师")
        self.assertEqual(job["source"], "BOSS直聘")
        self.assertEqual(job["type"], "社招")
        self.assertEqual(job["salary"], "35-65K·16薪")
        self.assertEqual(job["city"], "北京·海淀区·中关村")
        self.assertEqual(job["company"], "某某芯片")
        self.assertEqual(job["industry"], "半导体/芯片")
        self.assertEqual(job["scale"], "500-999人")
        self.assertTrue(job["url"].startswith("https://www.zhipin.com/job_detail/enc_aaa111.html?"))
        for token in ("3-5年", "本科", "SystemVerilog", "李女士", "五险一金", "刚刚活跃"):
            self.assertIn(token, job["info"])

    def test_intern_type_and_city_fallback(self):
        jobs, _ = boss.parse_list_api_payload(api_payload(), "北京")
        self.assertEqual(jobs[1]["type"], "实习")
        self.assertEqual(jobs[1]["city"], "上海")

    def test_blocked_code_raises(self):
        for code in (37, 1001, -1):
            with self.assertRaises(boss.BossBlocked):
                boss.parse_list_api_payload({"code": code, "message": "当前IP访问受限"}, "北京")

    def test_business_error_raises(self):
        with self.assertRaises(boss.BossError):
            boss.parse_list_api_payload({"code": 4001, "message": "参数错误"}, "北京")

    def test_non_dict_payload_raises(self):
        with self.assertRaises(boss.BossError):
            boss.parse_list_api_payload("<html>waf</html>", "北京")

    def test_missing_zpdata_treated_as_no_result(self):
        # code=0 但没有 zpData，说明该关键词无结果，不应报错
        self.assertEqual(boss.parse_list_api_payload({"code": 0, "zpData": None}, "北京"), ([], False))

    def test_malformed_zpdata_raises(self):
        with self.assertRaises(boss.BossError):
            boss.parse_list_api_payload({"code": 0, "zpData": "unexpected"}, "北京")

    def test_empty_job_list(self):
        jobs, has_more = boss.parse_list_api_payload(
            {"code": 0, "zpData": {"jobList": [], "hasMore": False}}, "北京"
        )
        self.assertEqual(jobs, [])
        self.assertFalse(has_more)


class TestDomParsing(unittest.TestCase):
    def test_parse_cards(self):
        jobs = boss.parse_job_cards_html(LIST_PAGE_HTML, "北京")
        self.assertEqual(len(jobs), 2)
        first = jobs[0]
        self.assertEqual(first["title"], "数字IC设计工程师")
        self.assertEqual(first["salary"], "30-60K·15薪")
        self.assertEqual(first["city"], "北京·朝阳区·望京")
        self.assertEqual(first["company"], "某某微电子")
        self.assertEqual(first["industry"], "半导体/芯片")
        self.assertEqual(first["scale"], "100-499人")
        self.assertIn("3-5年", first["info"])
        self.assertIn("张女士", first["info"])
        # 相对链接必须补全，否则邮件里点不开
        self.assertTrue(first["url"].startswith("https://www.zhipin.com/job_detail/enc_aaa111.html"))

    def test_second_card_without_tags(self):
        jobs = boss.parse_job_cards_html(LIST_PAGE_HTML, "北京")
        self.assertEqual(jobs[1]["title"], "模拟IC设计（校招）")
        self.assertEqual(jobs[1]["type"], "校招")
        self.assertEqual(jobs[1]["company"], "另一家公司")

    def test_no_cards_returns_empty(self):
        self.assertEqual(boss.parse_job_cards_html("<html><body>空页面</body></html>", "北京"), [])
        self.assertEqual(boss.parse_job_cards_html("", "北京"), [])


class TestBlockDetection(unittest.TestCase):
    def test_detect_block_text(self):
        self.assertEqual(boss.detect_block(LOGIN_PAGE_HTML), "请先登录")
        self.assertEqual(boss.detect_block("<p>请完成验证</p>"), "请完成验证")
        self.assertIsNone(boss.detect_block("<p>正常页面</p>"))
        self.assertIsNone(boss.detect_block(""))

    def test_blocked_url(self):
        self.assertTrue(boss.is_blocked_url("https://www.zhipin.com/web/user/?ka=header-login"))
        self.assertTrue(boss.is_blocked_url("https://www.zhipin.com/security_check?x=1"))
        self.assertFalse(boss.is_blocked_url("https://www.zhipin.com/web/geek/job?query=ic"))

    def test_keyword_containing_verify_is_not_blocked(self):
        # 回归：旧实现用宽泛的 "verify" 子串判断风控，会误判这类正常搜索
        self.assertFalse(boss.is_blocked_url(boss.build_search_url("验证工程师", "北京")))


class TestMisc(unittest.TestCase):
    def test_dedupe_by_url(self):
        jobs = [
            {"url": "https://a", "title": "x"},
            {"url": "https://a", "title": "x"},
            {"url": "", "title": "y", "company": "c"},
            {"url": "", "title": "y", "company": "c"},
        ]
        self.assertEqual(len(boss.dedupe_by_url(jobs)), 2)

    def test_api_params_shape(self):
        params = boss.build_list_api_params("ic", "北京", 2)
        self.assertEqual(params["page"], "2")
        self.assertEqual(params["city"], "101010100")
        self.assertEqual(params["query"], "ic")

    def test_load_cookies_from_env_dict(self):
        os.environ["BOSS_COOKIES"] = json.dumps({"bst": "token-value"})
        try:
            cookies = boss.load_cookies()
        finally:
            os.environ.pop("BOSS_COOKIES", None)
        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0]["name"], "bst")
        self.assertEqual(cookies[0]["domain"], ".zhipin.com")

    def test_load_cookies_invalid_json(self):
        os.environ["BOSS_COOKIES"] = "{not-json"
        try:
            self.assertEqual(boss.load_cookies(), [])
        finally:
            os.environ.pop("BOSS_COOKIES", None)

    def test_resolve_proxy(self):
        self.assertEqual(boss.resolve_proxy(""), {})
        self.assertEqual(boss.resolve_proxy("1.2.3.4:8080")["server"], "http://1.2.3.4:8080")
        proxy = boss.resolve_proxy("socks5://user:pwd@1.2.3.4:1080")
        self.assertEqual(proxy["server"], "socks5://1.2.3.4:1080")
        self.assertEqual(proxy["username"], "user")

    def test_fetch_jobs_without_keywords_returns_empty(self):
        self.assertEqual(boss.fetch_jobs([], "北京"), [])


# ==================== 编排逻辑：用假浏览器离线跑通 ====================
class FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    def text(self):
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


class FakeAPIRequest:
    """模拟 context.request：按 page 参数返回预置响应。"""

    def __init__(self, pages_payload):
        self.pages_payload = pages_payload
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params or {}))
        page = int((params or {}).get("page", 1))
        payload = self.pages_payload.get(page)
        if payload is None:
            payload = {"code": 0, "zpData": {"jobList": [], "hasMore": False}}
        return FakeResponse(payload)


class FakePage:
    def __init__(self, html, url="https://www.zhipin.com/web/geek/job?query=x&city=101010100"):
        self.html = html
        self.url = url
        self.goto_urls = []

    def set_default_timeout(self, *a):
        pass

    def goto(self, url, **kwargs):
        self.goto_urls.append(url)
        self.url = url
        return None

    def wait_for_timeout(self, *a):
        pass

    def wait_for_selector(self, *a, **k):
        return None

    def content(self):
        return self.html

    def screenshot(self, path=None, **k):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("fake")

    class _Mouse:
        def wheel(self, *a):
            pass

    mouse = _Mouse()


class FakeContext:
    def __init__(self, html, pages_payload, url=None):
        self.page = FakePage(html, **({"url": url} if url else {}))
        self.pages = [self.page]
        self.request = FakeAPIRequest(pages_payload)
        self.closed = False
        self.init_scripts = []
        self.cookies = []

    def new_page(self):
        return self.page

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, html, pages_payload, url=None):
        self.context = FakeContext(html, pages_payload, url)
        self.launch_calls = []
        self.persistent_calls = []

    def launch_persistent_context(self, **kwargs):
        self.persistent_calls.append(kwargs)
        return self.context

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return types.SimpleNamespace(
            new_context=lambda **k: self.context,
            close=lambda: None,
        )


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePlaywrightModuleTestCase(unittest.TestCase):
    """注入假的 playwright.sync_api，验证 fetch_jobs 的编排逻辑。"""

    HTML_WITH_JOBS = LIST_PAGE_HTML
    HTML_LOGIN = LOGIN_PAGE_HTML

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="boss_profile_")
        self._saved_modules = {
            name: sys.modules.get(name) for name in ("playwright", "playwright.sync_api")
        }
        self._saved_sleep = boss._sleep_between_requests
        boss._sleep_between_requests = lambda *a, **k: None
        os.environ.pop("BOSS_COOKIES", None)

    def tearDown(self):
        boss._sleep_between_requests = self._saved_sleep
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        os.environ.pop("BOSS_COOKIES", None)
        os.environ.pop("BOSS_DEBUG_DIR", None)

    def _install_fake_playwright(self, chromium):
        package = types.ModuleType("playwright")
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = lambda: FakePlaywright(chromium)
        package.sync_api = sync_api
        sys.modules["playwright"] = package
        sys.modules["playwright.sync_api"] = sync_api

    def test_profile_mode_uses_api_and_stops_when_no_more(self):
        payload = api_payload()
        payload["zpData"]["hasMore"] = False  # 只有一页数据
        chromium = FakeChromium(self.HTML_WITH_JOBS, {1: payload})
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(["芯片设计"], "北京", pages=3, profile_dir=self._tmp, quiet=True)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "数字IC验证工程师")
        self.assertEqual(jobs[0]["type"], "社招")
        # hasMore=False，即使请求了 3 页也只请求第 1 页
        self.assertEqual([c["page"] for c in chromium.context.request.calls], ["1"])
        # 走了持久化 profile 模式
        self.assertEqual(len(chromium.persistent_calls), 1)
        self.assertEqual(chromium.launch_calls, [])
        self.assertTrue(chromium.context.closed)
        # 注入了反自动化脚本
        self.assertIn("webdriver", chromium.context.init_scripts[0])

    def test_pagination_follows_has_more(self):
        page1 = {"code": 0, "zpData": {"hasMore": True, "jobList": [
            {"encryptJobId": "a1", "jobName": "岗位A", "cityName": "北京"},
        ]}}
        page2 = {"code": 0, "zpData": {"hasMore": False, "jobList": [
            {"encryptJobId": "a2", "jobName": "岗位B", "cityName": "北京"},
        ]}}
        chromium = FakeChromium(self.HTML_WITH_JOBS, {1: page1, 2: page2})
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(["芯片设计"], "北京", pages=5, profile_dir=self._tmp, quiet=True)

        self.assertEqual([j["title"] for j in jobs], ["岗位A", "岗位B"])
        self.assertEqual([c["page"] for c in chromium.context.request.calls], ["1", "2"])

    def test_dedupes_across_pages(self):
        dup = {"encryptJobId": "same", "jobName": "重复岗位", "cityName": "北京"}
        page1 = {"code": 0, "zpData": {"hasMore": True, "jobList": [dup]}}
        page2 = {"code": 0, "zpData": {"hasMore": False, "jobList": [dict(dup)]}}
        chromium = FakeChromium(self.HTML_WITH_JOBS, {1: page1, 2: page2})
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(["芯片设计"], "北京", pages=2, profile_dir=self._tmp, quiet=True)
        self.assertEqual(len(jobs), 1)

    def test_blocked_page_returns_empty_and_dumps_debug(self):
        debug_dir = tempfile.mkdtemp(prefix="boss_debug_")
        chromium = FakeChromium(
            self.HTML_LOGIN, {},
            url="https://www.zhipin.com/web/user/?ka=header-login",
        )
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(
            ["芯片设计"], "北京", profile_dir=self._tmp, debug_dir=debug_dir, quiet=True
        )

        self.assertEqual(jobs, [])
        self.assertEqual(chromium.context.request.calls, [])  # 命中拦截后不再请求接口
        self.assertTrue(os.listdir(debug_dir))  # 留下了诊断产物

    def test_api_falls_back_to_dom_when_not_json(self):
        chromium = FakeChromium(self.HTML_WITH_JOBS, {1: "<html>waf</html>"})
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(["芯片设计"], "北京", profile_dir=self._tmp, quiet=True)

        self.assertEqual(len(jobs), 2)  # 接口失效，DOM 兜底仍然抓到
        self.assertTrue(jobs[0]["url"].startswith("https://www.zhipin.com/job_detail/"))

    def test_cookie_mode_without_cookies_skips_browser(self):
        chromium = FakeChromium(self.HTML_WITH_JOBS, {})
        self._install_fake_playwright(chromium)

        missing_profile = os.path.join(self._tmp, "not-exist")
        jobs = boss.fetch_jobs(["芯片设计"], "北京", profile_dir=missing_profile, quiet=True)

        self.assertEqual(jobs, [])
        self.assertEqual(chromium.launch_calls, [])

    def test_respects_max_jobs(self):
        payload = {"code": 0, "zpData": {"hasMore": False, "jobList": [
            {"encryptJobId": f"j{i}", "jobName": f"岗位{i}", "cityName": "北京"} for i in range(10)
        ]}}
        chromium = FakeChromium(self.HTML_WITH_JOBS, {1: payload})
        self._install_fake_playwright(chromium)

        jobs = boss.fetch_jobs(
            ["芯片设计"], "北京", profile_dir=self._tmp, max_jobs=3, quiet=True
        )
        self.assertEqual(len(jobs), 3)


if __name__ == "__main__":
    unittest.main()
