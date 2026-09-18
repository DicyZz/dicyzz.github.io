#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 BOSS 直聘指定城市/岗位的实时招聘信息，可选 DeepSeek 分析 + 邮件投递。

Cookie 来源优先级：
1. 环境变量 BOSS_COOKIES（GitHub Secrets，推荐）
2. 仓库文件 data/boss_cookies.json
"""

import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

import markdown
from openai import OpenAI
from premailer import transform
from playwright.sync_api import sync_playwright

# ==================== 1. 配置项 ====================
TARGET_CITY = os.getenv("TARGET_CITY") or "北京"
TARGET_JOB = os.getenv("TARGET_JOB") or "ESL建模工程师"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"

EMAIL_HOST = os.getenv("EMAIL_HOST") or "smtp.gmail.com"
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or 465)
EMAIL_SENDER = os.getenv("EMAIL_SENDER") or ""
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") or ""
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER") or EMAIL_SENDER

MAX_JOBS = int(os.getenv("MAX_JOBS") or 30)
COOKIE_FILE = "data/boss_cookies.json"

# BOSS 直聘城市代码（采用中国天气网城市编码）；未匹配到的城市回退到「全国」
CITY_CODE_MAP = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100",
    "武汉": "101200100", "南京": "101190100", "西安": "101110100",
    "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "青岛": "101120200",
    "济南": "101120100", "大连": "101070200", "沈阳": "101070100",
    "合肥": "101220100", "厦门": "101230200", "福州": "101230100",
    "东莞": "101281600", "佛山": "101280800", "珠海": "101280700",
    "宁波": "101210400", "无锡": "101190200", "昆明": "101290100",
    "哈尔滨": "101050100", "长春": "101060100", "石家庄": "101090100",
    "贵阳": "101260100", "南宁": "101300100", "南昌": "101240100",
}
NATIONWIDE_CITY_CODE = "100010000"


def resolve_city_code(city: str) -> str:
    return CITY_CODE_MAP.get(city.strip(), NATIONWIDE_CITY_CODE)


# ==================== 2. Cookie 处理 ====================
def load_cookies() -> list:
    """从环境变量或文件读取 Cookie，统一为 Playwright 可用的列表格式。"""
    raw = os.getenv("BOSS_COOKIES")
    source = "环境变量 BOSS_COOKIES"
    if not raw and os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            raw = f.read()
        source = COOKIE_FILE

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ Cookie 解析失败（{source}）: {e}")
        return []

    cookies = []
    if isinstance(data, list):
        cookies = data
    elif isinstance(data, dict):
        # 允许 {"name": "value"} 形式，统一补充 domain
        for name, value in data.items():
            cookies.append({"name": name, "value": str(value), "domain": ".zhipin.com", "path": "/"})
    else:
        print(f"⚠️ Cookie 格式不正确（{source}），应为 JSON 数组或对象")
        return []

    print(f"🔑 已从 {source} 读取 {len(cookies)} 条 Cookie")
    return cookies


# ==================== 3. 抓取 BOSS 直聘 ====================
def fetch_boss_jobs(city: str, keyword: str) -> list:
    print(f"🌐 正在抓取 [{city}] [{keyword}] 实时岗位...")
    jobs = []
    cookies = load_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        if cookies:
            try:
                context.add_cookies(cookies)
            except Exception as e:
                print(f"⚠️ 注入 Cookie 失败: {e}")

        page = context.new_page()
        try:
            city_code = resolve_city_code(city)
            search_url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={city_code}"
            page.goto(search_url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            # 登录/安全校验检测：被重定向说明 Cookie 失效或触发风控
            current_url = page.url
            if "passport" in current_url or "security_check" in current_url:
                print(f"⚠️ 被重定向到登录/安全校验页：{current_url}")
                print("   请更新 BOSS_COOKIES secret（需登录 BOSS 直聘后导出最新 Cookie）")
                return []

            # 滚动加载更多岗位
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)

            cards = page.query_selector_all(".job-card-wrapper")
            if not cards:
                cards = page.query_selector_all(".job-list-box li")
            print(f"🔍 检索到 {len(cards)} 个岗位卡片")

            for card in cards[:MAX_JOBS]:
                try:
                    title = card.query_selector(".job-name").inner_text().strip()
                    company = card.query_selector(".company-name").inner_text().strip()
                    salary = card.query_selector(".salary").inner_text().strip()
                    tags_el = card.query_selector(".job-tag-list")
                    tags = tags_el.inner_text().replace("\n", " ").strip() if tags_el else ""
                    area_el = card.query_selector(".job-area")
                    area = area_el.inner_text().strip() if area_el else city

                    jobs.append({
                        "company": company,
                        "title": title,
                        "city": area or city,
                        "salary": salary,
                        "jd_text": tags,
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ 页面渲染或抓取失败: {e}")
        finally:
            browser.close()

    return jobs


# ==================== 4. 结果落盘与 Actions 摘要 ====================
def save_results(jobs: list):
    with open("jobs_result.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    lines = [
        f"# 岗位抓取结果：{TARGET_CITY} · {TARGET_JOB}",
        f"- 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 岗位数量：{len(jobs)}",
        "",
        "| 公司 | 岗位 | 城市 | 薪资 | 标签 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for job in jobs:
        company = str(job.get("company", "")).replace("|", "\\|")
        title = str(job.get("title", "")).replace("|", "\\|")
        city = str(job.get("city", "")).replace("|", "\\|")
        salary = str(job.get("salary", "")).replace("|", "\\|")
        jd = str(job.get("jd_text", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {company} | {title} | {city} | {salary} | {jd} |")

    md = "\n".join(lines) + "\n"
    with open("jobs_result.md", "w", encoding="utf-8") as f:
        f.write(md)

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md)
    print("💾 结果已保存到 jobs_result.json / jobs_result.md")


# ==================== 5. DeepSeek 分析 + 邮件（可选） ====================
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
1. 正在招聘的公司与岗位清单（公司、岗位、薪资）。
2. 高频硬技能与工具要求。
3. 学历、经验年限分布及加分项。
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【PerfPulse】{TARGET_CITY} · {TARGET_JOB} 岗位分析 ({datetime.now().strftime('%Y-%m-%d')})"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(styled_html, "html", "utf-8"))

    if EMAIL_SENDER and EMAIL_PASSWORD:
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("🎉 邮件发送成功！")
    else:
        print("⚠️ 未配置邮件账号，跳过发送（分析结果已包含在运行日志中）")
        print(briefing_md)


if __name__ == "__main__":
    job_list = fetch_boss_jobs(TARGET_CITY, TARGET_JOB)
    save_results(job_list)
    analyze_and_send(job_list)
