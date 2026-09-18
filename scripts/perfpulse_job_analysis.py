#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多源实时抓取指定城市/岗位/行业的招聘信息。

数据源：
  国内：牛客网、猎聘、智联招聘、前程无忧(51job)
  国外：RemoteOK、We Work Remotely、Remotive
说明：拉勾因滑块验证码无法自动化，已排除；BOSS 直聘因海外 IP 风控已排除。

用法：
    TARGET_CITY=北京 TARGET_JOB=芯片设计 TARGET_INDUSTRY=半导体 python scripts/perfpulse_job_analysis.py
    TARGET_CITY 支持 "全国"；TARGET_INDUSTRY 支持 "不限" 或预定义行业。
"""

import os
import json
import re
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests
import markdown
from openai import OpenAI
from premailer import transform

# ==================== 1. 配置项 ====================
TARGET_CITY = os.getenv("TARGET_CITY") or "全国"
TARGET_JOB = os.getenv("TARGET_JOB") or "芯片设计"
TARGET_INDUSTRY = os.getenv("TARGET_INDUSTRY") or "不限"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"

EMAIL_HOST = os.getenv("EMAIL_HOST") or "smtp.gmail.com"
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or 465)
EMAIL_SENDER = os.getenv("EMAIL_SENDER") or ""
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") or ""
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER") or EMAIL_SENDER

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ==================== 2. 行业定义与城市代码 ====================
INDUSTRY_OPTIONS = {
    "不限": [],
    "互联网/软件/IT": ["互联网", "软件", "it", "科技", "网络", "云计算", "大数据", "信息", "计算机", "software", "internet", "web", "saas", "tech", "technology"],
    "半导体/电子/芯片": ["半导体", "集成电路", "芯片", "微电子", "电子", "ic", "硬件", "semiconductor", "chip", "electronics", "hardware"],
    "人工智能": ["人工智能", "ai", "机器学习", "深度学习", "大模型", "artificial intelligence", "machine learning", "llm", "agent"],
    "金融": ["金融", "银行", "证券", "保险", "基金", "投资", "支付", "finance", "banking", "insurance", "fintech"],
    "医疗健康": ["医疗", "医药", "健康", "医院", "生物", "制药", "healthcare", "medical", "bio", "pharma", "biotech"],
    "汽车/新能源": ["汽车", "新能源", "电池", "整车", "自动驾驶", "automotive", "ev", "battery", "auto"],
    "教育/培训": ["教育", "培训", "education", "training", "edtech"],
    "游戏": ["游戏", "game", "gaming"],
    "制造业": ["制造", "工业", "机械", "重工", "manufacturing", "industrial", "mechanical"],
    "通信": ["通信", "电信", "5g", "telecom", "communication"],
    "电商/零售/消费": ["电商", "电子商务", "零售", "消费", "e-commerce", "ecommerce", "retail", "consumer"],
    "企业服务": ["企业服务", "saas", "b2b", "企业级", "enterprise"],
    "广告/营销/传媒": ["广告", "营销", "传媒", "媒体", "marketing", "media", "advertising"],
}

# 牛客/猎聘等通用的中文城市列表（用于客户端识别城市字段）
CITIES = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京",
    "西安", "苏州", "天津", "重庆", "长沙", "郑州", "青岛", "济南",
    "大连", "沈阳", "合肥", "厦门", "福州", "东莞", "佛山", "珠海",
    "宁波", "无锡", "昆明", "哈尔滨", "长春", "石家庄", "贵阳",
    "南宁", "南昌", "太原", "兰州", "乌鲁木齐", "海口",
]

# 牛客岗位卡片里的噪声标签
NOISE_ITEMS = {
    "兼顾学业", "HR刚处理简历", "HR今日在线", "刚刚有人投递过",
    "简历直投官网", "发展前景广阔", "有转正", "学历友好榜", "高新技术",
}

# 猎聘城市代码（dq），410 为全国
LIEPIN_CITY_CODE = {
    "北京": "010", "上海": "020", "天津": "030", "重庆": "040",
    "深圳": "050090", "广州": "050020", "杭州": "070020", "成都": "280020",
    "武汉": "170020", "南京": "060020", "西安": "270020", "苏州": "060080",
    "长沙": "180020", "郑州": "150020", "青岛": "250070", "济南": "250020",
    "大连": "210040", "沈阳": "210020", "合肥": "080020", "厦门": "090040",
    "福州": "090020", "东莞": "050040", "佛山": "050050", "珠海": "050140",
    "宁波": "070030", "无锡": "060100", "昆明": "310020", "哈尔滨": "160020",
    "石家庄": "140020", "贵阳": "120020", "南宁": "110020", "南昌": "200020",
    "太原": "260020", "兰州": "100020", "乌鲁木齐": "300020", "海口": "130020",
    "常州": "060040", "温州": "070040", "嘉兴": "070090", "绍兴": "070050",
    "泉州": "090030", "惠州": "050060", "中山": "050130",
}
LIEPIN_NATIONWIDE = "410"

# 智联招聘城市代码（jl 参数），0 为全国
ZHILIAN_CITY_CODE = {
    "北京": 530, "上海": 538, "深圳": 765, "广州": 763, "杭州": 653,
    "成都": 801, "武汉": 736, "南京": 635, "西安": 854, "苏州": 639,
    "天津": 531, "重庆": 551, "长沙": 749, "郑州": 719, "青岛": 703,
    "济南": 702, "大连": 600, "沈阳": 599, "合肥": 664, "厦门": 682,
    "福州": 681, "东莞": 779, "佛山": 768, "珠海": 766, "宁波": 654,
    "无锡": 636,
}

# 51job 城市代码（jobArea 参数），空字符串为全国
JOB51_CITY_CODE = {
    "北京": "010000", "上海": "020000", "深圳": "040000", "广州": "030200",
    "杭州": "080200", "成都": "090200", "天津": "050000", "重庆": "060000",
    "武汉": "180200", "南京": "070200", "西安": "200200", "苏州": "070300",
    "长沙": "190200", "青岛": "120300", "合肥": "150200", "东莞": "030800",
    "佛山": "030600", "珠海": "030500", "宁波": "080300", "无锡": "070400",
    "昆明": "250200",
}

# 中文岗位关键词 -> 英文匹配词（用于国外远程岗位源）
JOB_EN_KEYWORDS = {
    "芯片": ["chip", "semiconductor", "silicon", "fpga", "rtl", "vlsi"],
    "集成电路": ["chip", "semiconductor", "vlsi", "integrated circuit"],
    "算法": ["algorithm", "machine learning", "ml", "ai"],
    "人工智能": ["ai", "artificial intelligence", "machine learning", "ml", "llm"],
    "大模型": ["llm", "large language model", "ai", "generative"],
    "后端": ["backend", "back-end", "server", "api", "server-side"],
    "前端": ["frontend", "front-end", "web", "react", "vue"],
    "嵌入": ["embedded", "firmware", "iot"],
    "数据": ["data", "database", "data science", "analytics"],
    "运维": ["devops", "sre", "infrastructure", "platform"],
    "测试": ["test", "qa", "quality", "testing"],
    "安全": ["security"],
    "云": ["cloud", "aws", "azure", "gcp"],
    "区块链": ["blockchain", "web3", "crypto"],
    "游戏": ["game", "gaming", "unity", "unreal"],
    "java": ["java"],
    "python": ["python"],
    "c++": ["c++", "cpp", "cplusplus"],
    "c#": ["c#", "csharp", ".net"],
    "golang": ["go", "golang"],
    "go": ["go", "golang"],
    "rust": ["rust"],
    "javascript": ["javascript", "js", "node"],
    "前端开发": ["frontend", "react", "vue", "web"],
    "产品": ["product", "product manager"],
    "运营": ["operations", "marketing", "growth"],
}


def _translate_en(keyword: str) -> list:
    """把中文岗位关键词翻译成英文匹配词列表。"""
    kw = keyword.strip().lower()
    words = set()
    for cn, ens in JOB_EN_KEYWORDS.items():
        if cn in kw:
            words.update(ens)
    # 英文原词也保留
    if kw and all(ord(ch) < 128 for ch in kw):
        words.add(kw)
    return list(words)


def _match_en(title: str, tags: list, en_words: list) -> bool:
    """判断英文岗位是否匹配翻译后的关键词。"""
    if not en_words:
        return False
    text = (title or "").lower() + " " + " ".join(tags or []).lower()
    for w in en_words:
        # 纯字母/数字词用词边界匹配，含特殊符号（c++ 等）用子串
        if re.fullmatch(r"[a-z0-9]+", w):
            if re.search(r"\b" + re.escape(w) + r"\b", text):
                return True
        else:
            if w in text:
                return True
    return False


# ==================== 3. 通用工具 ====================
def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = (
        text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&#xeb52", "千").replace("&#xea0a", "人")
    )
    return text.strip()


def _extract_city(items: list) -> str:
    for item in items:
        for city in CITIES:
            if item == city or item.startswith(city):
                return city
    return ""


def filter_by_industry(jobs: list, industry: str) -> list:
    """按行业关键词过滤岗位（匹配 industry 字段或标题）。"""
    if not industry or industry == "不限":
        return jobs
    keywords = INDUSTRY_OPTIONS.get(industry, [industry.strip()])
    if not keywords:
        return jobs
    result = []
    for job in jobs:
        text = (job.get("industry", "") + " " + job.get("title", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            result.append(job)
    return result


def dedupe_jobs(jobs: list) -> list:
    seen = set()
    result = []
    for job in jobs:
        key = job.get("url") or (job.get("company", ""), job.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


# ==================== 4. 牛客网（requests） ====================
def _parse_nowcoder(html: str) -> list:
    jobs = []
    cards = html.split('job-card-item job-card')[1:]
    for card in cards:
        url = re.search(r'href="(https://www\.nowcoder\.com/jobs/detail/\d+)[^"]*"', card)
        job_name = re.search(r'class="job-name"[^>]*>(.*?)</span>', card, re.S)
        salary = re.search(r'class="job-salary[^"]*"[^>]*>(.*?)</span>', card, re.S)
        company = re.search(r'class="company-name"[^>]*>(.*?)</span>', card, re.S)
        info_items = re.findall(r'class="job-info-item[^"]*"[^>]*>(.*?)</div>', card, re.S)
        comp_items = re.findall(r'class="company-info-item"[^>]*>(.*?)</div>', card, re.S)

        title = _clean(job_name.group(1)) if job_name else ""
        jtype, jtitle = "社招", title
        for t in ("校招", "社招", "实习"):
            if t in title:
                jtype = t
                jtitle = title.replace(f"{t} | ", "").replace(f"{t}|", "").strip()
                break

        items = [x for x in (_clean(x) for x in info_items) if x]
        city = _extract_city(items)
        others = [x for x in items if x != city and x not in NOISE_ITEMS]
        comps = [x for x in (_clean(x) for x in comp_items) if x]
        industry = comps[0] if len(comps) > 0 else ""
        scale = comps[1] if len(comps) > 1 else ""
        if not jtitle:
            continue
        jobs.append({
            "source": "牛客网", "type": jtype, "title": jtitle,
            "salary": _clean(salary.group(1)) if salary else "",
            "city": city, "company": _clean(company.group(1)) if company else "",
            "industry": industry, "scale": scale,
            "info": " / ".join(others), "url": url.group(1) if url else "",
        })
    return jobs


def fetch_nowcoder_jobs(keyword: str, city: str) -> list:
    url = "https://www.nowcoder.com/search/job" + f"?query={quote(keyword)}&type=job"
    print(f"🌐 [牛客网] 抓取 [{keyword}]...")
    jobs = []
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            if 'job-card-item job-card' not in resp.text:
                print(f"   第 {attempt + 1} 次返回拦截页，重试...")
                time.sleep(2)
                continue
            jobs = _parse_nowcoder(resp.text)
            break
        except Exception as e:
            print(f"⚠️ 牛客网第 {attempt + 1} 次失败: {e}")
            time.sleep(2)
    print(f"🔍 [牛客网] 检索到 {len(jobs)} 条")
    if city and city != "全国":
        jobs = [j for j in jobs if j["city"] == city]
        print(f"📍 [牛客网] 按城市 [{city}] 过滤后 {len(jobs)} 条")
    return jobs


# ==================== 5. 猎聘（Playwright） ====================
def fetch_liepin_jobs(keyword: str, city: str, max_pages: int = None) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ [猎聘] 未安装 playwright，跳过")
        return []
    if max_pages is None:
        try:
            max_pages = int(os.getenv("MAX_PAGES") or 3)
        except ValueError:
            max_pages = 3
    max_pages = max(1, min(max_pages, 10))

    city_code = LIEPIN_CITY_CODE.get(city, LIEPIN_NATIONWIDE)
    base_url = f"https://www.liepin.com/zhaopin/?key={quote(keyword)}&dq={city_code}"
    print(f"🌐 [猎聘] 抓取 [{keyword}]（dq={city_code}，{max_pages} 页）...")
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800}, locale="zh-CN")
            page = context.new_page()
            page.goto(base_url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            for cur in range(max_pages):
                url = base_url + f"&currentPage={cur}"
                try:
                    with page.expect_response(
                        lambda r: "pc-search-job" in r.url and "cond-init" not in r.url, timeout=30000,
                    ) as ri:
                        page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    data = json.loads(ri.value.text())
                    cards = data.get("data", {}).get("data", {}).get("jobCardList", [])
                except Exception as e:
                    if cur == 0:
                        print(f"⚠️ [猎聘] 抓取失败: {e}")
                    break
                if not cards:
                    break
                for c in cards:
                    j = c.get("job", {}); comp = c.get("comp", {})
                    title = j.get("title", "")
                    jobs.append({
                        "source": "猎聘", "type": "社招", "title": title,
                        "salary": j.get("salary", ""), "city": j.get("dq", city),
                        "company": comp.get("compName", ""),
                        "industry": comp.get("compIndustry", ""),
                        "scale": comp.get("compScale", ""),
                        "info": " / ".join(x for x in [j.get("requireWorkYears", ""), j.get("requireEduLevel", "")] if x),
                        "url": j.get("link", ""),
                    })
                page.wait_for_timeout(500)
            browser.close()
    except Exception as e:
        print(f"⚠️ [猎聘] 失败: {e}")
    print(f"🔍 [猎聘] 检索到 {len(jobs)} 条")
    return jobs


# ==================== 6. 智联招聘（Playwright） ====================
def fetch_zhilian_jobs(keyword: str, city: str) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ [智联] 未安装 playwright，跳过")
        return []
    city_code = ZHILIAN_CITY_CODE.get(city)
    url = f"https://sou.zhaopin.com/?kw={quote(keyword)}"
    if city_code:
        url += f"&jl={city_code}"
    print(f"🌐 [智联] 抓取 [{keyword}]（{'全国' if not city_code else city}）...")
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            html = page.content()
            browser.close()
    except Exception as e:
        print(f"⚠️ [智联] 失败: {e}")
        return []

    m = re.search(r'__INITIAL_STATE__=(\{.*?\})\s*</script>', html, re.S)
    if not m:
        print("⚠️ [智联] 未找到 __INITIAL_STATE__")
        return []
    try:
        data = json.loads(m.group(1))
        pl = data.get("positionList", [])
    except Exception as e:
        print(f"⚠️ [智联] 解析失败: {e}")
        return []

    for item in pl:
        try:
            cc = json.loads(item.get("cardCustomJson") or "{}")
        except Exception:
            cc = {}
        jobs.append({
            "source": "智联", "type": item.get("workType", "全职"),
            "title": item.get("name", ""),
            "salary": item.get("salary60") or cc.get("salary60", ""),
            "city": item.get("workCity", city),
            "company": item.get("companyName", ""),
            "industry": item.get("industryName", ""),
            "scale": item.get("companySize", ""),
            "info": " / ".join(x for x in [item.get("education", ""), item.get("propertyName", "")] if x),
            "url": item.get("positionURL") or item.get("positionUrl", ""),
        })
    print(f"🔍 [智联] 检索到 {len(jobs)} 条")
    return jobs


# ==================== 7. 前程无忧 51job（Playwright） ====================
def fetch_51job_jobs(keyword: str, city: str) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ [51job] 未安装 playwright，跳过")
        return []
    area = JOB51_CITY_CODE.get(city, "")
    url = "https://we.51job.com/pc/search?keyword=" + quote(keyword) + "&searchType=2"
    if area:
        url += f"&jobArea={area}"
    print(f"🌐 [51job] 抓取 [{keyword}]（jobArea={area or '全国'}）...")
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            # 用 DOM 提取，比解析 HTML 字符串更可靠
            items = page.evaluate("""() => {
                const nodes = document.querySelectorAll('.joblist-item');
                return Array.from(nodes).map(n => {
                    const sensor = n.querySelector('[sensorsdata]');
                    const cname = n.querySelector('.cname');
                    const dc = n.querySelector('.dc');
                    const tags = Array.from(n.querySelectorAll('.tags, .tag, .weal, .provides li, .provides span')).map(x => x.textContent.trim());
                    return {
                        sensor: sensor ? sensor.getAttribute('sensorsdata') : null,
                        company: cname ? cname.textContent.trim() : '',
                        industry: dc ? dc.textContent.trim() : '',
                        tags: tags.filter(Boolean).join(' / ')
                    };
                }).filter(x => x.sensor);
            }""")
            browser.close()
    except Exception as e:
        print(f"⚠️ [51job] 失败: {e}")
        return []

    for it in items:
        try:
            s = json.loads(it.get("sensor") or "{}")
        except Exception:
            s = {}
        jobs.append({
            "source": "51job", "type": "全职",
            "title": s.get("jobTitle", ""),
            "salary": s.get("jobSalary", ""),
            "city": s.get("jobArea", city),
            "company": it.get("company", ""),
            "industry": it.get("industry", ""),
            "scale": "",
            "info": " / ".join(x for x in [s.get("jobYear", ""), s.get("jobDegree", "")] if x),
            "url": f"https://jobs.51job.com/{s.get('jobId', '')}.html" if s.get("jobId") else "",
        })
    print(f"🔍 [51job] 检索到 {len(jobs)} 条")
    return jobs


# ==================== 8. 国外源（requests） ====================
def fetch_remoteok_jobs(keyword: str, city: str) -> list:
    """RemoteOK 远程岗位 API（英文，按关键词过滤）。"""
    print(f"🌐 [RemoteOK] 抓取 [{keyword}]...")
    en_words = _translate_en(keyword)
    jobs = []
    try:
        resp = requests.get("https://remoteok.com/api", headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"⚠️ [RemoteOK] 失败: {e}")
        return []
    for item in data[1:]:  # 第一条是 legal notice
        title = item.get("position", "")
        tags = item.get("tags") or []
        # 关键词相关性过滤（中文翻译成英文匹配）
        if en_words and not _match_en(title, tags, en_words):
            continue
        salary = ""
        if item.get("salary_min") or item.get("salary_max"):
            salary = f"${item.get('salary_min', '')}-${item.get('salary_max', '')}"
        jobs.append({
            "source": "RemoteOK", "type": "远程",
            "title": title,
            "salary": salary,
            "city": item.get("location", "全球"),
            "company": item.get("company", ""),
            "industry": " / ".join(tags[:3]) if tags else "远程/科技",
            "scale": "",
            "info": "远程",
            "url": item.get("url", ""),
        })
    print(f"🔍 [RemoteOK] 检索到 {len(jobs)} 条")
    return jobs


def fetch_wwr_jobs(keyword: str, city: str) -> list:
    """We Work Remotely 远程岗位 RSS（英文）。"""
    print(f"🌐 [WWR] 抓取 [{keyword}]...")
    en_words = _translate_en(keyword)
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    for feed in feeds:
        try:
            resp = requests.get(feed, headers={"User-Agent": USER_AGENT}, timeout=20)
            root = ET.fromstring(resp.text)
            for it in root.findall(".//item"):
                title = it.findtext("title", "")
                category = it.findtext("category", "")
                if en_words and not _match_en(title, [category], en_words):
                    continue
                link = it.findtext("link", "")
                region = it.findtext("region", "")
                jobs.append({
                    "source": "WWR", "type": "远程",
                    "title": title, "salary": "",
                    "city": region or "全球", "company": "",
                    "industry": category, "scale": "",
                    "info": "远程", "url": link,
                })
        except Exception as e:
            print(f"⚠️ [WWR] {feed} 失败: {e}")
    print(f"🔍 [WWR] 检索到 {len(jobs)} 条")
    return jobs


def fetch_remotive_jobs(keyword: str, city: str) -> list:
    """Remotive 远程岗位 API（英文）。"""
    print(f"🌐 [Remotive] 抓取 [{keyword}]...")
    en_words = _translate_en(keyword)
    jobs = []
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs", headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("jobs", [])
    except Exception as e:
        print(f"⚠️ [Remotive] 失败: {e}")
        return []
    for item in data:
        title = item.get("title", "")
        tags = item.get("tags") or []
        if en_words and not _match_en(title, tags, en_words):
            continue
        jobs.append({
            "source": "Remotive", "type": "远程",
            "title": title, "salary": item.get("salary", ""),
            "city": item.get("candidate_required_location", "全球"),
            "company": item.get("company_name", ""),
            "industry": item.get("category", ""), "scale": "",
            "info": item.get("job_type", "远程"),
            "url": item.get("url", ""),
        })
    print(f"🔍 [Remotive] 检索到 {len(jobs)} 条")
    return jobs


# ==================== 9. 结果落盘与 Actions 摘要 ====================
def save_results(jobs: list):
    with open("jobs_result.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    lines = [
        f"# 岗位抓取结果：{TARGET_CITY} · {TARGET_JOB}" + (f" · {TARGET_INDUSTRY}" if TARGET_INDUSTRY != "不限" else ""),
        f"- 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 岗位数量：{len(jobs)}",
        "",
    ]
    if jobs:
        lines += [
            "| 来源 | 类型 | 岗位 | 薪资 | 城市 | 公司 | 行业 | 规模 | 详情 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for job in jobs:
            def esc(v):
                return str(v or "").replace("|", "\\|").replace("\n", " ")
            url = esc(job.get("url", ""))
            title = esc(job.get("title", ""))
            lines.append(
                f"| {esc(job.get('source'))} | {esc(job.get('type'))} | {title} "
                f"| {esc(job.get('salary'))} | {esc(job.get('city'))} "
                f"| {esc(job.get('company'))} | {esc(job.get('industry'))} "
                f"| {esc(job.get('scale'))} | [查看]({url}) |"
            )
    else:
        lines.append("⚠️ 未检索到匹配岗位，请尝试更换关键词、城市或行业。")

    md = "\n".join(lines) + "\n"
    with open("jobs_result.md", "w", encoding="utf-8") as f:
        f.write(md)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print("💾 结果已保存到 jobs_result.json / jobs_result.md")


# ==================== 10. DeepSeek 分析 + 邮件（可选） ====================
def analyze_and_send(jobs: list):
    if not jobs:
        print("ℹ️ 无岗位数据，跳过分析")
        return
    if not DEEPSEEK_API_KEY:
        print("ℹ️ 未配置 DEEPSEEK_API_KEY，跳过 AI 分析与邮件")
        return
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = f"""
你是一位资深招聘分析师。请分析以下在【{TARGET_CITY}】采集到的【{TARGET_JOB}】实时招聘数据（行业：{TARGET_INDUSTRY}）。

【原始岗位数据】
{json.dumps(jobs, ensure_ascii=False, indent=2)}

【分析要求】
1. 正在招聘的公司与岗位清单（公司、岗位、薪资、城市）。
2. 高频硬技能与工具要求（如有）。
3. 学历、经验年限分布。
4. 针对该岗位的求职建议。

使用结构清晰的 Markdown 格式输出，避免编造数据中不存在的信息。
"""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.2,
    )
    briefing_md = response.choices[0].message.content
    raw_html = markdown.markdown(briefing_md, extensions=["tables", "fenced_code"])
    styled_html = transform(
        f"<html><body><div style='max-width:700px;margin:0 auto;padding:20px;'>{raw_html}</div></body></html>"
    )
    if EMAIL_SENDER and EMAIL_PASSWORD:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"【PerfPulse】{TARGET_CITY} · {TARGET_JOB} 岗位分析 ({datetime.now().strftime('%Y-%m-%d')})"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg.attach(MIMEText(styled_html, "html", "utf-8"))
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("🎉 邮件发送成功！")
    else:
        print("⚠️ 未配置邮件账号，跳过发送")


if __name__ == "__main__":
    all_jobs = []
    # 国内源
    all_jobs.extend(fetch_nowcoder_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_liepin_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_zhilian_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_51job_jobs(TARGET_JOB, TARGET_CITY))
    # 国外源（远程岗位，城市不做硬过滤）
    all_jobs.extend(fetch_remoteok_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_wwr_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_remotive_jobs(TARGET_JOB, TARGET_CITY))

    all_jobs = dedupe_jobs(all_jobs)
    print(f"\n📊 去重后共 {len(all_jobs)} 条岗位")

    # 行业过滤
    all_jobs = filter_by_industry(all_jobs, TARGET_INDUSTRY)
    print(f"🏭 按行业 [{TARGET_INDUSTRY}] 过滤后 {len(all_jobs)} 条")

    save_results(all_jobs)
    analyze_and_send(all_jobs)
