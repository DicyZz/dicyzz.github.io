#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时抓取指定城市/岗位的招聘信息。

数据源：牛客网（nowcoder.com）
- 覆盖校招 / 社招 / 实习
- 无需登录、无验证码，海内外网络均可访问
- 搜索结果由服务端直接渲染，requests 即可稳定抓取

用法：
    TARGET_CITY=北京 TARGET_JOB=芯片设计 python scripts/perfpulse_job_analysis.py
    TARGET_CITY 支持 "全国"（不筛选城市）
"""

import os
import json
import re
import smtplib
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

# 用于从岗位信息中识别城市字段
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


# ==================== 2. 牛客网抓取 ====================
def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#xeb52", "千")
        .replace("&#xea0a", "人")
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
        # 拆分类型前缀：校招 / 社招 / 实习
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
    """抓取牛客网指定关键词的岗位，并按城市过滤（客户端过滤）。"""
    url = (
        "https://www.nowcoder.com/search/job"
        f"?query={quote(keyword)}&type=job"
    )
    print(f"🌐 正在抓取牛客网 [{keyword}] 岗位...")
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ 牛客网请求失败: {e}")
        return []

    jobs = _parse_nowcoder(resp.text)
    print(f"🔍 原始检索到 {len(jobs)} 条岗位")

    # 城市过滤（"全国" 或空则不筛）
    if city and city != "全国":
        jobs = [j for j in jobs if j["city"] == city]
        print(f"📍 按城市 [{city}] 过滤后剩余 {len(jobs)} 条")

    return jobs


# ==================== 3. 结果落盘与 Actions 摘要 ====================
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


# ==================== 4. DeepSeek 分析 + 邮件（可选） ====================
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
    job_list = fetch_nowcoder_jobs(TARGET_JOB, TARGET_CITY)
    save_results(job_list)
    analyze_and_send(job_list)
