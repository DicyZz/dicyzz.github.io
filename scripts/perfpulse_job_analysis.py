#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时抓取指定城市/岗位的招聘信息，支持多数据源。

数据源：
1. 牛客网（nowcoder.com）：无需登录、无验证码，requests 直接抓取，
   覆盖校招 / 社招 / 实习，海内外网络均可访问。
2. 猎聘（liepin.com）：数据量大、偏社招，使用 Playwright 无头浏览器
   绕过阿里云 WAF（acw_tc 校验）后抓取其搜索接口返回的 JSON。

用法：
    TARGET_CITY=北京 TARGET_JOB=芯片设计 python scripts/perfpulse_job_analysis.py
    TARGET_CITY 支持 "全国"（不筛选城市）
"""

import os
import json
import re
import random
import smtplib
import string
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

import requests
import markdown
from openai import OpenAI
from premailer import transform

# ==================== 1. 配置项 ====================
TARGET_CITY = os.getenv("TARGET_CITY") or "全国"
TARGET_JOB = os.getenv("TARGET_JOB") or "芯片设计"

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

# 用于从牛客网岗位信息中识别城市字段
CITIES = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京",
    "西安", "苏州", "天津", "重庆", "长沙", "郑州", "青岛", "济南",
    "大连", "沈阳", "合肥", "厦门", "福州", "东莞", "佛山", "珠海",
    "宁波", "无锡", "昆明", "哈尔滨", "长春", "石家庄", "贵阳",
    "南宁", "南昌", "太原", "兰州", "乌鲁木齐", "海口",
]

# 岗位卡片里属于「标签」的噪声词，不计入城市/经验/学历
NOISE_ITEMS = {
    "兼顾学业", "HR刚处理简历", "HR今日在线", "刚刚有人投递过",
    "简历直投官网", "发展前景广阔", "有转正", "学历友好榜", "高新技术",
}

# 猎聘城市代码（dq），"410" 为全国
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


# ==================== 2. 牛客网抓取（requests） ====================
def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return text.strip()


def _extract_city(items: list) -> str:
    for item in items:
        for city in CITIES:
            if item == city or item.startswith(city):
                return city
    return ""


def _parse_nowcoder(html: str) -> list:
    """解析牛客网搜索结果页，提取岗位列表。"""
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
            "source": "牛客网",
            "type": jtype,
            "title": jtitle,
            "salary": _clean(salary.group(1)) if salary else "",
            "city": city,
            "company": _clean(company.group(1)) if company else "",
            "industry": industry,
            "scale": scale,
            "info": " / ".join(others),
            "url": url.group(1) if url else "",
        })

    return jobs


def fetch_nowcoder_jobs(keyword: str, city: str) -> list:
    url = "https://www.nowcoder.com/search/job" + f"?query={quote(keyword)}&type=job"
    print(f"🌐 [牛客网] 正在抓取 [{keyword}] 岗位...")
    jobs = []
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            # 牛客网偶发返回短小的风控/加载页，检测到就重试
            if 'job-card-item job-card' not in resp.text:
                print(f"   第 {attempt + 1} 次返回拦截页（长度 {len(resp.text)}），重试...")
                time.sleep(2)
                continue
            jobs = _parse_nowcoder(resp.text)
            break
        except Exception as e:
            print(f"⚠️ 牛客网第 {attempt + 1} 次请求失败: {e}")
            time.sleep(2)

    print(f"🔍 [牛客网] 原始检索到 {len(jobs)} 条岗位")

    if city and city != "全国":
        jobs = [j for j in jobs if j["city"] == city]
        print(f"📍 [牛客网] 按城市 [{city}] 过滤后剩余 {len(jobs)} 条")

    return jobs


# ==================== 3. 猎聘抓取（Playwright） ====================
def fetch_liepin_jobs(keyword: str, city: str) -> list:
    """使用 Playwright 抓取猎聘，返回结构化的岗位列表。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ [猎聘] 未安装 playwright，跳过该数据源")
        return []

    city_code = LIEPIN_CITY_CODE.get(city, LIEPIN_NATIONWIDE if city in ("", "全国") else LIEPIN_NATIONWIDE)
    # 未收录城市时回退到全国，避免报错
    if city not in LIEPIN_CITY_CODE and city not in ("", "全国"):
        print(f"⚠️ [猎聘] 未收录城市 [{city}]，按全国范围搜索")
        city_code = LIEPIN_NATIONWIDE

    url = f"https://www.liepin.com/zhaopin/?key={quote(keyword)}&dq={city_code}"
    print(f"🌐 [猎聘] 正在抓取 [{keyword}] 岗位（dq={city_code}）...")

    captured = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            page = context.new_page()

            def on_response(resp):
                if "pc-search-job" in resp.url and "cond-init" not in resp.url:
                    try:
                        captured.append(resp.text())
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(url, timeout=60000, wait_until="load")
            page.wait_for_timeout(8000)
            browser.close()
    except Exception as e:
        print(f"⚠️ [猎聘] 页面加载或抓取失败: {e}")
        return []

    if not captured:
        print("⚠️ [猎聘] 未捕获到搜索接口响应")
        return []

    try:
        data = json.loads(captured[0])
        cards = data.get("data", {}).get("data", {}).get("jobCardList", [])
    except Exception as e:
        print(f"⚠️ [猎聘] 响应解析失败: {e}")
        return []

    jobs = []
    for c in cards:
        j = c.get("job", {})
        comp = c.get("comp", {})
        jobs.append({
            "source": "猎聘",
            "type": "社招",
            "title": j.get("title", ""),
            "salary": j.get("salary", ""),
            "city": j.get("dq", city),
            "company": comp.get("compName", ""),
            "industry": comp.get("compIndustry", ""),
            "scale": comp.get("compScale", ""),
            "info": " / ".join(x for x in [
                j.get("requireWorkYears", ""),
                j.get("requireEduLevel", ""),
            ] if x),
            "url": j.get("link", ""),
        })

    print(f"🔍 [猎聘] 检索到 {len(jobs)} 条岗位")
    return jobs


# ==================== 4. 结果去重 ====================
def dedupe_jobs(jobs: list) -> list:
    seen = set()
    result = []
    for job in jobs:
        # 优先用详情链接去重，链接缺失时退回到 公司+岗位
        key = job.get("url") or (job.get("company", ""), job.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


# ==================== 5. 结果落盘与 Actions 摘要 ====================
def save_results(jobs: list):
    with open("jobs_result.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    lines = [
        f"# 岗位抓取结果：{TARGET_CITY} · {TARGET_JOB}",
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
        lines.append("⚠️ 未检索到匹配岗位，请尝试更换关键词或城市。")

    md = "\n".join(lines) + "\n"
    with open("jobs_result.md", "w", encoding="utf-8") as f:
        f.write(md)

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print("💾 结果已保存到 jobs_result.json / jobs_result.md")


# ==================== 6. DeepSeek 分析 + 邮件（可选） ====================
def analyze_and_send(jobs: list):
    if not jobs:
        print("ℹ️ 无岗位数据，跳过分析")
        return
    if not DEEPSEEK_API_KEY:
        print("ℹ️ 未配置 DEEPSEEK_API_KEY，跳过 AI 分析与邮件")
        return

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = f"""
你是一位资深招聘分析师。请分析以下在【{TARGET_CITY}】采集到的【{TARGET_JOB}】实时招聘数据。

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
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
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
        print("⚠️ 未配置邮件账号，跳过发送（分析结果见运行日志）")
        print(briefing_md)


if __name__ == "__main__":
    all_jobs = []
    all_jobs.extend(fetch_nowcoder_jobs(TARGET_JOB, TARGET_CITY))
    all_jobs.extend(fetch_liepin_jobs(TARGET_JOB, TARGET_CITY))

    all_jobs = dedupe_jobs(all_jobs)
    print(f"\n📊 合计去重后 {len(all_jobs)} 条岗位")
    save_results(all_jobs)
    analyze_and_send(all_jobs)
