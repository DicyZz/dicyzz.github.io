#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOSS 直聘（zhipin.com）岗位抓取模块。

设计要点
--------
1. 两级数据来源：优先调用站点自身的 JSON 接口
   （/wapi/zpgeek/search/joblist.json，字段完整、翻页便宜），
   接口不可用时自动回退到渲染后的 DOM 解析。
2. 两种登录态：国内 self-hosted runner 复用持久化 profile
   （~/boss_chrome_profile，见 boss_login.py）；云端 runner 只能注入 Cookie
   （海外 IP 大概率被风控）。
3. 可离线单测：所有解析逻辑都是「HTML/JSON 文本 -> 岗位列表」的纯函数，
   不依赖浏览器，便于在 CI 里跑回归测试。

环境变量
--------
BOSS_COOKIES     登录 Cookie（JSON 数组或 name->value 对象），云端模式使用
BOSS_PROXY       出口代理，支持 http/https/socks5，仅填 host:port 也可
BOSS_PROFILE_DIR 持久化浏览器 profile 目录，默认 ~/boss_chrome_profile
BOSS_HEADFUL     1 有头（默认，反风控成功率更高）/ 0 无头
BOSS_PAGES       每个关键词翻页数，默认 1，上限 10
BOSS_MAX_JOBS    单次运行最多保留的岗位数，默认取 MAX_JOBS（30）
BOSS_MAX_DETAIL  需要抓取详情正文的岗位数，默认 0（关闭，避免触发风控）
BOSS_MODE        auto（默认）/ api / dom，强制指定数据来源
BOSS_DEBUG_DIR   诊断目录；设置后失败时保存 HTML 与截图

本地调试
--------
    python scripts/boss_scraper.py --city 北京 --keyword 芯片设计 --pages 2
    python scripts/boss_scraper.py --city 全国 --keyword 芯片设计 --dump-html work/boss_dump
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote, urlparse

from lxml import html as lxml_html

SITE = "https://www.zhipin.com"
SEARCH_PATH = "/web/geek/job"
JOB_LIST_API = SITE + "/wapi/zpgeek/search/joblist.json"
DETAIL_URL_TMPL = SITE + "/job_detail/{job_id}.html"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_PROFILE_DIR = os.path.expanduser("~/boss_chrome_profile")
DEFAULT_COOKIE_FILE = "data/boss_cookies.json"

# BOSS 城市编码（与中国天气网同款编码）；未匹配到的城市回退到「全国」
BOSS_CITY_CODE_MAP = {
    "全国": "100010000",
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100",
    "武汉": "101200100", "南京": "101190100", "西安": "101110100",
    "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "青岛": "101120200",
    "济南": "101120100", "大连": "101070200", "沈阳": "101070100",
    "合肥": "101220100", "厦门": "101230200", "福州": "101230100",
    "东莞": "101281600", "佛山": "101280800", "珠海": "101280700",
    "宁波": "101210400", "无锡": "101190200", "昆明": "101290100",
    "石家庄": "101090100", "哈尔滨": "101050100", "长春": "101060100",
    "太原": "101100100", "南宁": "101300100", "贵阳": "101260100",
    "兰州": "101160100", "乌鲁木齐": "101130100", "海口": "101310100",
    "南昌": "101240100", "常州": "101191100", "温州": "101210700",
    "嘉兴": "101210300", "绍兴": "101210500", "泉州": "101230500",
    "惠州": "101280300", "中山": "101281700", "烟台": "101120500",
    "潍坊": "101120600", "徐州": "101190800", "南通": "101190500",
}
BOSS_NATIONWIDE_CITY_CODE = "100010000"

# 页面/接口返回这些内容说明没登录或已被风控
BLOCK_TEXT_MARKERS = (
    "安全验证", "请先登录", "登录后查看", "操作过于频繁", "访问异常",
    "当前IP访问受限", "当前ip访问受限", "请完成验证", "拖动滑块",
    "用户不存在", "账号异常", "您的操作存在异常",
)
# URL 命中这些片段说明被重定向到登录页/风控页
BLOCK_URL_MARKERS = ("passport", "security_check", "captcha", "/web/user/", "/login")

# 岗位卡片样式随站点改版会变，这里保留多套选择器兜底
CARD_XPATHS = (
    "//li[contains(@class,'job-card-wrapper')]",
    "//div[contains(@class,'job-card-wrapper')]",
    "//li[contains(@class,'job-card-box')]",
    "//ul[contains(@class,'job-list-box')]/li",
)

JOB_TYPE_LABELS = {0: "社招", 1: "实习", 2: "兼职"}


class BossError(RuntimeError):
    """BOSS 抓取过程中的可预期异常。"""


class BossBlocked(BossError):
    """未登录 / 被风控拦截。"""


# ==================== 纯函数：URL 与城市 ====================
def resolve_city_code(city: str) -> str:
    """城市名 -> BOSS 城市编码；未知城市回退到全国。"""
    return BOSS_CITY_CODE_MAP.get((city or "").strip(), BOSS_NATIONWIDE_CITY_CODE)


def city_label(city: str) -> str:
    """用于日志展示：编码为全国时统一显示「全国」。"""
    code = resolve_city_code(city)
    return "全国" if code == BOSS_NATIONWIDE_CITY_CODE else city


def build_search_url(keyword: str, city: str, page: int = 1) -> str:
    """构造 BOSS 搜索页 URL（page > 1 时追加翻页参数）。"""
    url = f"{SITE}{SEARCH_PATH}?query={quote(keyword)}&city={resolve_city_code(city)}"
    if page and page > 1:
        url += f"&page={page}"
    return url


def build_list_api_params(keyword: str, city: str, page: int = 1, page_size: int = 30) -> dict:
    """构造岗位列表接口的查询参数（与站点前端保持一致，含空筛选项）。"""
    return {
        "scene": "1",
        "query": keyword,
        "city": resolve_city_code(city),
        "page": str(page),
        "pageSize": str(page_size),
        "experience": "",
        "payType": "",
        "partTime": "",
        "degree": "",
        "industry": "",
        "scale": "",
        "stage": "",
        "position": "",
        "jobType": "",
        "salary": "",
        "multiBusinessDistrict": "",
        "multiSubway": "",
        "_": str(int(time.time() * 1000)),
    }


def absolutize(href: str) -> str:
    """把岗位相对链接补全为绝对链接（原实现直接输出相对路径，邮件里点不开）。"""
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return SITE + href
    if href.startswith("http"):
        return href
    return SITE + "/" + href.lstrip("./")


def build_job_url(job_id: str, lid: str = "", security_id: str = "") -> str:
    """由 encryptJobId/securityId 组装岗位详情链接。"""
    if not job_id:
        return ""
    url = DETAIL_URL_TMPL.format(job_id=job_id)
    query = []
    if lid:
        query.append(f"lid={quote(str(lid))}")
    if security_id:
        query.append(f"securityId={quote(str(security_id))}")
    return url + ("?" + "&".join(query) if query else "")


def normalize_location(city_name: str, area: str = "", business: str = "", fallback: str = "") -> str:
    """拼装「城市·区域·商圈」，中间为「·」；缺失时回退到调用方给定城市。"""
    parts = [p.strip() for p in (city_name, area, business) if p and str(p).strip()]
    if not parts:
        return fallback or ""
    # BOSS 卡片里「区域/商圈」有时与城市重复
    deduped = [parts[0]]
    for part in parts[1:]:
        if part not in deduped:
            deduped.append(part)
    return "·".join(deduped)


# ==================== 纯函数：风控识别 ====================
def detect_block(text: str) -> str | None:
    """从页面/接口文本中识别风控或未登录，返回命中的特征词。"""
    if not text:
        return None
    for marker in BLOCK_TEXT_MARKERS:
        if marker in text:
            return marker
    return None


def is_blocked_url(url: str) -> bool:
    """URL 是否被重定向到登录/风控页。"""
    url = (url or "").lower()
    return any(marker in url for marker in BLOCK_URL_MARKERS)


# ==================== 纯函数：接口数据 -> 岗位 ====================
def parse_list_api_payload(payload, city: str) -> tuple:
    """解析岗位列表接口响应，返回 (岗位列表, 是否还有下一页)。

    接口正常返回形如 {"code": 0, "zpData": {"jobList": [...], "hasMore": true}}；
    code 非 0（如 37/1001）通常代表未登录或风控。
    """
    if not isinstance(payload, dict):
        raise BossError("接口返回不是 JSON 对象，可能已被风控或接口已调整")

    code = payload.get("code")
    if code not in (0, "0", None):
        message = payload.get("message") or payload.get("msg") or ""
        if str(code) in {"37", "1001", "-1"} or detect_block(str(message)):
            raise BossBlocked(f"接口返回 code={code} message={message}")
        raise BossError(f"接口返回 code={code} message={message}")

    data = payload.get("zpData") or {}
    if not isinstance(data, dict):
        raise BossError("接口返回缺少 zpData 字段")

    items = data.get("jobList") or []
    jobs = [job_from_api_item(item, city) for item in items if isinstance(item, dict)]
    jobs = [job for job in jobs if job.get("title")]
    return jobs, bool(data.get("hasMore"))


def job_from_api_item(item: dict, city: str) -> dict:
    """把接口返回的单条岗位转换成统一的岗位字典。"""
    labels = [str(x) for x in (item.get("jobLabels") or []) if x]
    skills = [str(x) for x in (item.get("skills") or []) if x]
    welfare = [str(x) for x in (item.get("welfareList") or []) if x]
    boss = " ".join(str(x) for x in (item.get("bossName"), item.get("bossTitle")) if x)

    title = (item.get("jobName") or "").strip()
    job_type = item.get("jobType")
    type_label = JOB_TYPE_LABELS.get(job_type if isinstance(job_type, int) else -1, "社招")
    if "校招" in title:
        type_label = "校招"

    info_parts = []
    if labels:
        info_parts.append(" / ".join(labels))
    if skills:
        info_parts.append("技能：" + "、".join(skills))
    if boss:
        info_parts.append("招聘者：" + boss)
    if welfare:
        info_parts.append("福利：" + "、".join(welfare[:6]))
    if item.get("bossActiveTimeDesc"):
        info_parts.append("活跃：" + str(item["bossActiveTimeDesc"]))

    return {
        "source": "BOSS直聘",
        "type": type_label,
        "title": title,
        "salary": (item.get("salaryDesc") or "").strip(),
        "city": normalize_location(
            item.get("cityName") or "", item.get("areaDistrict") or "",
            item.get("businessDistrict") or "", fallback=city,
        ),
        "company": (item.get("brandName") or "").strip(),
        "industry": (item.get("brandIndustry") or "").strip(),
        "scale": (item.get("brandScaleName") or "").strip(),
        "info": " | ".join(info_parts),
        "url": build_job_url(
            item.get("encryptJobId") or "",
            item.get("lid") or "",
            item.get("securityId") or "",
        ),
    }


# ==================== 纯函数：DOM -> 岗位 ====================
def _first_text(node, xpaths) -> str:
    for xpath in xpaths:
        try:
            found = node.xpath(xpath)
        except Exception:
            continue
        for el in found:
            text = el if isinstance(el, str) else (el.text_content() or "")
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text
    return ""


def _first_attr(node, xpaths, attr) -> str:
    for xpath in xpaths:
        try:
            found = node.xpath(xpath)
        except Exception:
            continue
        for el in found:
            if isinstance(el, str):
                continue
            value = (el.get(attr) or "").strip()
            if value:
                return value
    return ""


def parse_job_cards_html(html: str, city: str) -> list:
    """从搜索结果页 HTML 解析岗位卡片。

    作为接口兜底路径，字段完整度低于接口，但足以产出可用的岗位列表。
    """
    if not html or not html.strip():
        return []
    try:
        doc = lxml_html.fromstring(html)
    except Exception as e:  # 页面可能是空文档或被截断
        raise BossError(f"HTML 解析失败: {e}") from e

    cards = []
    for xpath in CARD_XPATHS:
        cards = doc.xpath(xpath)
        if cards:
            break

    jobs = []
    for card in cards:
        title = _first_text(card, [
            ".//span[contains(@class,'job-name')]",
            ".//*[contains(@class,'job-title')]//span[1]",
            ".//a[contains(@class,'job-name')]",
        ])
        if not title:
            continue

        href = _first_attr(card, [
            ".//a[contains(@href,'job_detail')]",
            ".//a[contains(@href,'jobDetail')]",
            ".//a[@href]",
        ], "href")

        tags = [
            re.sub(r"\s+", " ", el.text_content() or "").strip()
            for el in card.xpath(".//div[contains(@class,'tag-list')]//li")
        ]
        tags = [t for t in tags if t]

        company_tags = [
            re.sub(r"\s+", " ", el.text_content() or "").strip()
            for el in card.xpath(".//ul[contains(@class,'company-tag-list')]//li")
        ]
        company_tags = [t for t in company_tags if t]

        boss = _first_text(card, [".//span[contains(@class,'boss-name')]"])
        boss_title = _first_text(card, [".//span[contains(@class,'boss-title')]"])

        area = _first_text(card, [
            ".//span[contains(@class,'job-area')]",
            ".//*[contains(@class,'job-area-wrapper')]",
        ])

        info_parts = []
        if tags:
            info_parts.append(" / ".join(tags[:3]))
        if boss:
            info_parts.append("招聘者：" + " ".join(x for x in (boss, boss_title) if x))

        area_parts = area.split("·") if area else []
        location = normalize_location(
            area_parts[0] if area_parts else "",
            "·".join(area_parts[1:]) if len(area_parts) > 1 else "",
            "",
            fallback=city,
        )

        jobs.append({
            "source": "BOSS直聘",
            "type": "校招" if "校招" in title else "社招",
            "title": title,
            "salary": _first_text(card, [".//span[contains(@class,'salary')]"]),
            "city": location,
            "company": _first_text(card, [
                ".//*[contains(@class,'company-name')]",
                ".//*[contains(@class,'company-info')]//h3",
            ]),
            "industry": company_tags[0] if company_tags else "",
            "scale": company_tags[-1] if len(company_tags) > 1 else "",
            "info": " | ".join(info_parts),
            "url": absolutize(href),
        })
    return jobs


def dedupe_by_url(jobs: list) -> list:
    """按链接（缺失时按公司+岗位）去重，保持原有顺序。"""
    seen = set()
    result = []
    for job in jobs:
        key = job.get("url") or (job.get("company", ""), job.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


# ==================== 登录态与启动参数 ====================
def load_cookies(cookie_file: str | None = None) -> list:
    """从 BOSS_COOKIES 环境变量或 Cookie 文件读取登录态。"""
    raw = os.getenv("BOSS_COOKIES")
    source = "环境变量 BOSS_COOKIES"
    if not raw:
        path = cookie_file or DEFAULT_COOKIE_FILE
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            source = path
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ [BOSS] Cookie 解析失败（{source}）: {e}")
        return []

    cookies = []
    if isinstance(data, list):
        cookies = data
    elif isinstance(data, dict):
        cookies = [
            {"name": name, "value": str(value), "domain": ".zhipin.com", "path": "/"}
            for name, value in data.items()
        ]
    else:
        print(f"⚠️ [BOSS] Cookie 格式不正确（{source}），应为 JSON 数组或对象")
        return []
    print(f"🔑 [BOSS] 已从 {source} 读取 {len(cookies)} 条 Cookie")
    return cookies


def resolve_proxy(raw: str | None = None) -> dict:
    """把代理字符串转成 Playwright 的 proxy 参数。"""
    raw = (raw if raw is not None else os.getenv("BOSS_PROXY") or "").strip()
    if not raw:
        return {}
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        print(f"⚠️ [BOSS] BOSS_PROXY 格式无效: {raw}")
        return {}
    port = parsed.port or (1080 if parsed.scheme in ("socks5", "socks5h") else 80)
    return {
        "server": f"{parsed.scheme}://{parsed.hostname}:{port}",
        "username": parsed.username or "",
        "password": parsed.password or "",
    }


def stealth_init_script() -> str:
    """在页面注入的伪装脚本：隐藏自动化特征（与 boss_login.py 保持同一策略）。"""
    return """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]

CONTEXT_KWARGS = {
    "viewport": {"width": 1440, "height": 900},
    "locale": "zh-CN",
    "timezone_id": "Asia/Shanghai",
    "user_agent": USER_AGENT,
}


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 10**9) -> int:
    try:
        value = int(str(os.getenv(name, "")).strip() or default)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _sleep_between_requests(low: float = 1.2, high: float = 2.6) -> None:
    """随机间隔，避免固定节奏触发风控。"""
    time.sleep(random.uniform(low, high))


def warn(message: str) -> None:
    """在 GitHub Actions 上输出 annotation（手机/网页上直接可见），否则打印普通告警。"""
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::warning::[BOSS] {message}")
    else:
        print(f"⚠️ [BOSS] {message}")


def proxy_hint(proxy_options: dict, log=print) -> None:
    """配置了代理却抓不到时，提示这是最常见的原因。

    国内机器直连 BOSS 才是正确姿势；走境外代理会被判定为异常访问，
    典型表现是 Page.goto 报 ERR_RESPONSE_HEADERS_TRUNCATED / 连接被重置。
    """
    if proxy_options:
        log(
            f"   ↳ 提示：当前通过 {proxy_options.get('server')} 访问 BOSS。"
            "若本机已在国内，请去掉 BOSS_PROXY（境外出口会被风控掐断连接）"
        )


def _dump_debug(debug_dir: str, name: str, page=None, text: str = "") -> str:
    """把出问题的页面存下来，方便回看。返回落盘路径。"""
    if not debug_dir:
        return ""
    os.makedirs(debug_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = []
    if text:
        path = os.path.join(debug_dir, f"{name}-{stamp}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        saved.append(path)
    if page is not None:
        try:
            path = os.path.join(debug_dir, f"{name}-{stamp}.png")
            page.screenshot(path=path, full_page=False)
            saved.append(path)
        except Exception:
            pass
    if saved:
        print(f"   ↳ 诊断产物: {', '.join(saved)}")
    return saved[0] if saved else ""


# ==================== 浏览器层 ====================
def _api_headers(keyword: str, city: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Referer": build_search_url(keyword, city),
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": USER_AGENT,
    }


def _fetch_page_via_api(context, keyword: str, city: str, page: int, timeout_ms: int) -> tuple:
    """通过页面自带的 JSON 接口取一页岗位（复用浏览器 Cookie）。"""
    response = context.request.get(
        JOB_LIST_API,
        params=build_list_api_params(keyword, city, page),
        headers=_api_headers(keyword, city),
        timeout=timeout_ms,
    )
    body = response.text()
    content_type = (response.headers or {}).get("content-type", "")
    if "json" not in content_type.lower() and body.lstrip()[:1] not in ("{", "["):
        blocker = detect_block(body)
        if blocker:
            raise BossBlocked(f"列表接口返回非 JSON，命中风控特征「{blocker}」")
        raise BossError(f"列表接口返回非 JSON（HTTP {response.status}）")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise BossError(f"列表接口返回无法解析的 JSON: {e}") from e
    return parse_list_api_payload(payload, city)


def _scroll_for_more(page, rounds: int = 3) -> None:
    """滚动触发懒加载，让首屏之外的岗位进入 DOM。"""
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 4000)
        except Exception:
            break
        page.wait_for_timeout(random.randint(900, 1600))


def _fetch_page_via_dom(page, keyword: str, city: str, page_no: int) -> list:
    """回退路径：打开搜索页并解析渲染后的 DOM。"""
    page.goto(
        build_search_url(keyword, city, page_no),
        timeout=60000,
        wait_until="domcontentloaded",
    )
    try:  # 等岗位卡片出现，最多 15 秒
        page.wait_for_selector(
            "li.job-card-wrapper, li.job-card-box, ul.job-list-box li", timeout=15000
        )
    except Exception:
        pass
    _scroll_for_more(page)
    content = page.content()
    blocker = detect_block(content)
    if blocker:
        raise BossBlocked(f"页面命中风控特征「{blocker}」")
    return parse_job_cards_html(content, city)


def _enrich_with_detail(page, job: dict, cache: dict, timeout_ms: int) -> None:
    """补充岗位详情正文（默认关闭，开启后仅抓取前 N 条）。"""
    url = job.get("url") or ""
    if not url:
        return
    if url not in cache:
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(random.randint(1200, 2000))
            content = page.content()
            if detect_block(content):
                cache[url] = ""
            else:
                doc = lxml_html.fromstring(content)
                sections = doc.xpath(
                    "//div[contains(@class,'job-sec-text')]//text()"
                    "|//div[contains(@class,'job-detail-section')]//text()"
                )
                text = re.sub(r"\s+", " ", " ".join(t.strip() for t in sections if t.strip()))
                cache[url] = text[:1200]
        except Exception:
            cache[url] = ""
    detail = cache.get(url) or ""
    if detail:
        job["info"] = (job.get("info") or "") + " | 职位描述：" + detail


def _open_context(playwright, auth_mode: str, profile_dir: str, headful: bool, proxy: dict) -> tuple:
    """按登录态模式启动浏览器上下文，返回 (context, browser)。"""
    if auth_mode == "profile":
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=not headful,
            args=LAUNCH_ARGS + ["--start-maximized"],
            ignore_default_args=["--enable-automation"],
            proxy=proxy or None,
            **CONTEXT_KWARGS,
        )
        context.add_init_script(stealth_init_script())
        return context, None

    # 先确认有登录态再启动浏览器，避免白等一次冷启动
    cookies = load_cookies()
    if not cookies:
        raise BossError("未配置 BOSS_COOKIES / 登录 profile，跳过 BOSS 直聘")
    browser = playwright.chromium.launch(
        headless=True,
        args=LAUNCH_ARGS,
        ignore_default_args=["--enable-automation"],
        proxy=proxy or None,
    )
    context = browser.new_context(**CONTEXT_KWARGS)
    context.add_init_script(stealth_init_script())
    try:
        context.add_cookies(cookies)
    except Exception as e:
        print(f"⚠️ [BOSS] 注入 Cookie 失败: {e}")
    return context, browser


def fetch_jobs(
    keywords,
    city: str,
    *,
    pages: int | None = None,
    mode: str | None = None,
    profile_dir: str | None = None,
    headful: bool | None = None,
    proxy: str | None = None,
    max_jobs: int | None = None,
    max_detail: int | None = None,
    debug_dir: str | None = None,
    quiet: bool = False,
) -> list:
    """抓取 BOSS 直聘岗位。

    Args:
        keywords: 单个关键词或关键词列表（列表会依次抓取，间隔随机）。
        city: 目标城市，「全国」或未收录城市按全国抓取。
        pages: 每个关键词抓取页数，默认取环境变量 BOSS_PAGES（1）。
        mode: auto（默认，接口优先）/ api / dom。
        profile_dir: 持久化 profile 目录；目录存在时走 profile 模式。
        max_jobs: 结果上限，默认 BOSS_MAX_JOBS 或 MAX_JOBS（30）。
        max_detail: 需要补详情正文的岗位数，默认 BOSS_MAX_DETAIL（0）。
        debug_dir: 诊断目录，失败时保存 HTML/截图。

    Returns:
        统一格式的岗位列表；未登录/被风控/未安装 playwright 时返回空列表。
    """
    def log(message: str) -> None:
        if not quiet:
            print(message)

    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k for k in (keywords or []) if k]
    if not keywords:
        return []

    pages = pages if pages is not None else _env_int("BOSS_PAGES", 1, 1, 10)
    max_jobs = max_jobs if max_jobs is not None else _env_int(
        "BOSS_MAX_JOBS", _env_int("MAX_JOBS", 30, 1), 1
    )
    max_detail = max_detail if max_detail is not None else _env_int("BOSS_MAX_DETAIL", 0, 0, 20)
    mode = (mode or os.getenv("BOSS_MODE") or "auto").strip().lower()
    if mode not in {"auto", "api", "dom"}:
        mode = "auto"
    debug_dir = debug_dir if debug_dir is not None else (os.getenv("BOSS_DEBUG_DIR") or "")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("⚠️ [BOSS] 未安装 playwright，跳过 BOSS 直聘")
        return []

    profile_dir = profile_dir or os.getenv("BOSS_PROFILE_DIR") or DEFAULT_PROFILE_DIR
    use_profile = os.path.isdir(profile_dir)
    auth_mode = "profile" if use_profile else "cookies"
    if headful is None:
        headful = (os.getenv("BOSS_HEADFUL", "1").strip().lower()
                   not in {"0", "false", "no", "off"})
    # Cookie 注入模式只能无头（云端 runner 无显示器）
    headful = headful and auth_mode == "profile"

    log(
        f"🌐 [BOSS直聘] 从 {'持久化 profile' if use_profile else 'Cookie 注入'} 登录态抓取 "
        f"[{'、'.join(keywords)}]（{city_label(city)}，{pages} 页，模式 {mode}）..."
    )
    if not use_profile:
        log("   ↳ 提示：云端 runner 为海外 IP，BOSS 基本抓不到；建议使用国内 self-hosted runner")

    proxy_options = resolve_proxy(proxy)
    if proxy_options:
        log(f"   ↳ 使用代理: {proxy_options['server']}")

    jobs: list = []
    browser = None
    context = None
    page = None
    api_failures = 0
    try:
        with sync_playwright() as p:
            context, browser = _open_context(p, auth_mode, profile_dir, headful, proxy_options)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)

            # 先打开搜索页：既确认登录态，也让 Cookie/风控标记进入正常状态
            page.goto(build_search_url(keywords[0], city), timeout=60000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(random.randint(2000, 3500))
            if is_blocked_url(page.url):
                warn(f"未登录或被风控，已跳转：{page.url}")
                warn("登录态可能已过期：请在服务器上运行 python3 scripts/boss_login.py 重新扫码")
                proxy_hint(proxy_options, log)
                _dump_debug(debug_dir, "blocked", page, page.content())
                return []
            blocker = detect_block(page.content())
            if blocker:
                warn(f"页面命中风控特征「{blocker}」：{page.url}")
                warn("若持续出现，请先停止抓取几分钟再重试，或换网络出口")
                proxy_hint(proxy_options, log)
                _dump_debug(debug_dir, "blocked", page, page.content())
                return []

            for keyword in keywords:
                for page_no in range(1, pages + 1):
                    page_jobs: list = []
                    has_more = False
                    source_used = ""

                    if mode in {"auto", "api"}:
                        try:
                            page_jobs, has_more = _fetch_page_via_api(
                                context, keyword, city, page_no, 30000
                            )
                            source_used = "接口"
                            # 接口返回空结果时用 DOM 复核一次，避免接口静默降级导致漏抓
                            if mode == "auto" and not page_jobs and page_no == 1:
                                dom_jobs = _fetch_page_via_dom(page, keyword, city, page_no)
                                if dom_jobs:
                                    log("ℹ️ [BOSS] 接口返回空列表但页面有岗位，改用 DOM 结果")
                                    page_jobs, has_more = dom_jobs, True
                                    source_used = "DOM"
                        except BossBlocked as e:
                            warn(str(e))
                            if mode == "api":
                                return jobs
                            api_failures += 1
                        except Exception as e:
                            api_failures += 1
                            if mode == "api":
                                log(f"⚠️ [BOSS] 接口方式失败: {e}")
                                return jobs
                            log(f"ℹ️ [BOSS] 接口不可用（{e}），回退 DOM 解析")

                    if not source_used:
                        page_jobs = _fetch_page_via_dom(page, keyword, city, page_no)
                        has_more = bool(page_jobs)
                        source_used = "DOM"

                    log(f"   ↳ [{keyword}] 第 {page_no} 页（{source_used}）获取 {len(page_jobs)} 条")
                    jobs.extend(page_jobs)
                    if not page_jobs or not has_more:
                        break
                    _sleep_between_requests()

            jobs = dedupe_by_url(jobs)[:max_jobs]
            log(f"🔍 [BOSS直聘] 去重后共 {len(jobs)} 条")

            if max_detail > 0 and jobs:
                log(f"   ↳ 抓取前 {min(max_detail, len(jobs))} 条岗位的详情正文...")
                cache: dict = {}
                for job in jobs[:max_detail]:
                    _enrich_with_detail(page, job, cache, 45000)
                    _sleep_between_requests(0.8, 1.6)

    except BossError as e:
        log(f"ℹ️ [BOSS] {e}")
    except Exception as e:
        log(f"⚠️ [BOSS] 抓取失败: {e}")
        proxy_hint(proxy_options, log)
        _dump_debug(debug_dir, "error", page, "")
    finally:
        for closer in (context, browser):
            if closer is not None:
                try:
                    closer.close()
                except Exception:
                    pass

    if api_failures and not jobs:
        warn("接口连续失败：可能登录态已过期或站点接口调整，请重跑 python3 scripts/boss_login.py")
    return jobs


# ==================== CLI ====================
def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="BOSS 直聘岗位抓取（本地调试 / 独立运行）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--keyword", "-k", action="append", default=None,
                        help="岗位关键词，可重复传入")
    parser.add_argument("--city", "-c", default="全国", help="目标城市")
    parser.add_argument("--pages", "-p", type=int, default=1, help="翻页数（1-10）")
    parser.add_argument("--mode", default="auto", choices=["auto", "api", "dom"])
    parser.add_argument("--headless", action="store_true", help="使用无头浏览器")
    parser.add_argument("--max-jobs", type=int, default=30)
    parser.add_argument("--detail", type=int, default=0, help="抓取详情正文的岗位数")
    parser.add_argument("--json", dest="json_out", default="", help="结果写入的 JSON 路径")
    parser.add_argument("--dump-html", dest="dump_dir", default="", help="诊断产物目录")
    args = parser.parse_args(argv)

    jobs = fetch_jobs(
        args.keyword or ["芯片设计"],
        args.city,
        pages=max(1, min(10, args.pages)),
        mode=args.mode,
        headful=not args.headless,
        max_jobs=args.max_jobs,
        max_detail=args.detail,
        debug_dir=args.dump_dir,
    )

    for job in jobs:
        print(f"  · {job['title']} | {job['salary']} | {job['city']} | {job['company']}")
    if args.json_out:
        parent = os.path.dirname(os.path.abspath(args.json_out))
        os.makedirs(parent, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        print(f"💾 已写入 {args.json_out}")
    return 0 if jobs else 1


if __name__ == "__main__":
    sys.exit(_main())
