#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown
from openai import OpenAI
from premailer import transform

# ==========================================
# 1. 配置项 (读取 GitHub Actions 环境变量)
# ==========================================
TARGET_CITY = os.getenv("TARGET_CITY") or "北京"
TARGET_JOB = os.getenv("TARGET_JOB") or "ESL建模工程师"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

EMAIL_HOST = os.getenv("EMAIL_HOST") or "smtp.gmail.com"
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or 465)
EMAIL_SENDER = os.getenv("EMAIL_SENDER") or ""
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") or ""
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER") or EMAIL_SENDER

# 数据存储文件路径（可为本地导出的 JSON 文件）
JOBS_DATA_FILE = os.getenv("JOBS_DATA_FILE", "data/jobs.json")

# ==========================================
# 2. 真实岗位数据导入模块
# ==========================================
def load_real_job_listings(city: str, keyword: str) -> list:
    """
    优先读取本地/仓库 data/jobs.json 中保存的真实招聘数据。
    如果文件不存在，提供兜底格式说明提示。
    """
    print(f"📂 正在加载 [{city}] [{keyword}] 的真实招聘数据文件 ({JOBS_DATA_FILE})...")
    
    if os.path.exists(JOBS_DATA_FILE):
        try:
            with open(JOBS_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"✅ 成功从 {JOBS_DATA_FILE} 加载了 {len(data)} 条真实岗位记录。")
                return data
        except Exception as e:
            print(f"⚠️ 读取 {JOBS_DATA_FILE} 失败: {e}")
            
    print("⚠️ 暂未检测到 data/jobs.json 数据文件，将使用基础说明格式兜底。")
    return [
        {
            "title": f"资深 {keyword}",
            "company": "示例科技公司（请放入真实数据文件 data/jobs.json）",
            "city": city,
            "salary": "35k-50k",
            "jd_text": "负责 AI 芯片 C-Model / gem5 架构仿真，精通 C++17/Python，熟悉 RISC-V 指令集、PCIe 与 AXI4 总线协议。"
        }
    ]

# ==========================================
# 3. DeepSeek 分析模块
# ==========================================
def analyze_job_requirements(job_list: list, city: str, keyword: str) -> str:
    """调用 DeepSeek API 进行岗位要求归纳与 SWOT 分析"""
    print(f"🤖 正在调用 DeepSeek 分析 [{city} - {keyword}] 真实招聘需求...")
    
    if not DEEPSEEK_API_KEY:
        raise ValueError("❌ 未设置 DEEPSEEK_API_KEY 环境变量！")

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    prompt = f"""
你是一位专业的 IC 与系统架构技术猎头。请深入分析以下在【{city}】地区采集到的【{keyword}】真实岗位招聘数据。

【真实岗位数据】
{json.dumps(job_list, ensure_ascii=False, indent=2)}

【分析与输出要求】
1. **核心硬技能 (Hard Skills)**：提炼高频出现的编程语言（如 C++17/Python）、仿真工具（如 gem5, SystemC）、总线协议（AXI4, PCIe, CXL）与体系结构要求。
2. **经验与门槛要求**：总结学历门槛、工作年限分布及核心加分项（如 RISC-V, Vector Extensions）。
3. **薪资范围与行情评估**：给出该城市的薪资范围评估与市场供需趋势。
4. **SWOT 竞争力建议**：针对【{city}】市场的【{keyword}】求职者，列出优势(S)、劣势/短板(W)、机会(O)、威胁(T)及建议补充的关键技术点。

请使用结构清晰的 Markdown 格式输出。
"""

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "你是一位专注于硬件架构、系统仿真与芯片设计领域的专业技术猎头。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content

# ==========================================
# 4. 样式转换与邮件发送
# ==========================================
def convert_md_to_styled_html(md_text: str, city: str, keyword: str) -> str:
    raw_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 20px; }}
            .container {{ max-width: 700px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; padding: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            h1 {{ color: #0f172a; font-size: 20px; border-bottom: 2px solid #2563eb; padding-bottom: 10px; }}
            h2 {{ color: #2563eb; font-size: 16px; margin-top: 24px; border-left: 4px solid #2563eb; padding-left: 8px; }}
            p, li {{ line-height: 1.6; font-size: 14px; }}
            code {{ background-color: #f1f5f9; color: #2563eb; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>【PerfPulse】{city} · {keyword} 在招岗位需求分析</h1>
            {raw_html}
            <div class="footer">
                <p>由 PerfPulse Automated System 自动分析推送</p>
                <p>时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return transform(html_template)

def send_email(subject: str, html_content: str):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("⚠️ 未配置 EMAIL_SENDER 或 EMAIL_PASSWORD，跳过邮件发送。")
        return

    print(f"📧 正在通过 {EMAIL_HOST}:{EMAIL_PORT} 发送邮件至 {EMAIL_RECEIVER}...")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        if EMAIL_PORT == 465:
            with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        else:
            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("✅ 邮件投递成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

# ==========================================
# 5. 主程序入口
# ==========================================
if __name__ == "__main__":
    print(f"🚀 开始分析 [{TARGET_CITY}] [{TARGET_JOB}] 岗位...")
    jobs = load_real_job_listings(TARGET_CITY, TARGET_JOB)
    analysis_md = analyze_job_requirements(jobs, TARGET_CITY, TARGET_JOB)
    
    # 保存备份
    os.makedirs("output", exist_ok=True)
    with open(f"output/job_analysis_{datetime.now().strftime('%Y%m%d')}.md", "w", encoding="utf-8") as f:
        f.write(analysis_md)
        
    styled_html = convert_md_to_styled_html(analysis_md, TARGET_CITY, TARGET_JOB)
    send_email(f"【PerfPulse】{TARGET_CITY} · {TARGET_JOB} 真实岗位需求分析 ({datetime.now().strftime('%Y-%m-%d')})", styled_html)
    print("🎉 任务完成！")
