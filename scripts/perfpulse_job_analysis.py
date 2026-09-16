#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown
import requests
from openai import OpenAI
from premailer import transform

# ==========================================
# 1. 动态配置项 (从环境变量获取目标城市与岗位)
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

# ==========================================
# 2. 数据采集/导入模块
# ==========================================
def fetch_job_listings(city: str, keyword: str) -> list:
    """
    根据指定城市与岗位关键词获取招聘数据。
    实际落地时可扩展为：
    1. 读取本地/仓库内导出的最新 JSON 文件 (例如 data/jobs.json)
    2. 调用第三方合规抓取/聚合 API
    3. Playwright 自动化抓取返回的数据
    """
    print(f"🌐 正在获取 [{city}] 地区的 [{keyword}] 岗位数据...")
    
    # 示例模拟数据结构（可替换为真实 API 或文件读取逻辑）
    mock_data = [
        {
            "title": f"{keyword}资深架构师",
            "company": "某芯片设计头部企业",
            "city": city,
            "salary": "35k-50k·16薪",
            "experience": "5-10年",
            "education": "硕士及以上",
            "jd_text": "负责NPU C-Model/gem5架构仿真与性能评估，精通C++17/Python，熟悉RISC-V指令集、PCIe与AXI总线协议，具备SystemC建模经验者优先。"
        },
        {
            "title": f"高级 {keyword}",
            "company": "某智能驾驶计算平台公司",
            "city": city,
            "salary": "30k-45k",
            "experience": "3-5年",
            "education": "本科及以上",
            "jd_text": "负责AI芯片ESL建模与软硬件联合仿真，精通gem5/SystemC，熟练掌握C++/Python，了解DMA控制器及Memory Bus Bridge机制。"
        }
    ]
    return mock_data

# ==========================================
# 3. DeepSeek 岗位要求提炼与 SWOT 分析
# ==========================================
def analyze_job_requirements(job_list: list, city: str, keyword: str) -> str:
    """调用 DeepSeek 对指定城市和岗位的招聘信息进行结构化分析与技能树提炼"""
    print(f"🤖 正在调用 DeepSeek 进行 [{city} - {keyword}] 岗位需求提炼...")
    
    if not DEEPSEEK_API_KEY:
        raise ValueError("❌ 未配置 DEEPSEEK_API_KEY 环境变量！")

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    prompt = f"""
你是一位专业的 IC 与软件技术猎头专家。请深入分析以下在【{city}】地区采集到的【{keyword}】岗位的原始招聘数据。

【原始招聘数据】
{json.dumps(job_list, ensure_ascii=False, indent=2)}

【分析与输出要求】
1. **核心硬技能 (Hard Skills)**：高频出现的编程语言（如 C++17/Python）、仿真工具/框架（如 gem5, SystemC）、总线协议（AXI4, PCIe）与体系结构要求。
2. **经验与门槛要求**：学历门槛、工作年限分布及核心加分项。
3. **薪资范围与行情评估**：结合该城市的市场情况给出薪资区间分析。
4. **SWOT 竞争力建议**：针对【{city}】市场的【{keyword}】求职者，列出优势(S)、劣势/短板(W)、机会(O)、威胁(T)及建议补充的关键技术点。

请使用结构清晰的 Markdown 格式输出。
"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一位专注于硬件架构、系统仿真与芯片设计领域的专业技术猎头。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            stream=False
        )
        briefing_md = response.choices[0].message.content
        print("✅ DeepSeek 岗位分析完成！")
        return briefing_md
    except Exception as e:
        print(f"❌ DeepSeek 分析失败: {e}")
        raise e

# ==========================================
# 4. HTML 渲染与样式转换
# ==========================================
def convert_md_to_styled_html(md_text: str, city: str, keyword: str) -> str:
    """转换 Markdown 为带有现代内联样式的 HTML 邮件格式"""
    raw_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #f8fafc;
                color: #1e293b;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 700px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                padding: 30px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            }}
            h1 {{
                color: #0f172a;
                font-size: 20px;
                border-bottom: 2px solid #2563eb;
                padding-bottom: 10px;
                margin-top: 0;
            }}
            h2 {{
                color: #2563eb;
                font-size: 16px;
                margin-top: 24px;
                border-left: 4px solid #2563eb;
                padding-left: 8px;
            }}
            p, li {{
                line-height: 1.6;
                font-size: 14px;
            }}
            code {{
                background-color: #f1f5f9;
                color: #2563eb;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 13px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 15px;
                border-top: 1px solid #e2e8f0;
                font-size: 12px;
                color: #94a3b8;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>【PerfPulse】{city} · {keyword} 岗位招聘需求分析</h1>
            {raw_html}
            <div class="footer">
                <p>由 PerfPulse Automated System 自动生成并推送</p>
                <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return transform(html_template)

# ==========================================
# 5. 备份与邮件推送模块
# ==========================================
def save_briefing_backup(content: str, city: str, keyword: str):
    """保存备份文件到 output/ 目录"""
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    filename = f"JobAnalysis_{city}_{keyword}_{datetime.now().strftime('%Y%m%d')}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"📁 报告 Markdown 已备份至: {filepath}")

def send_email(subject: str, html_content: str):
    """通过 SMTP 发送分析邮件"""
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
# 6. 主程序入口
# ==========================================
if __name__ == "__main__":
    print(f"🚀 开始对 [{TARGET_CITY}] 的 [{TARGET_JOB}] 岗位执行需求分析...")
    
    # 1. 获取岗位数据
    raw_jobs = fetch_job_listings(TARGET_CITY, TARGET_JOB)
    
    # 2. 调用 DeepSeek 分析提炼
    analysis_md = analyze_job_requirements(raw_jobs, TARGET_CITY, TARGET_JOB)
    
    # 3. 备份到 output/ 文件夹
    save_briefing_backup(analysis_md, TARGET_CITY, TARGET_JOB)
    
    # 4. 转换并发送邮件
    styled_html = convert_md_to_styled_html(analysis_md, TARGET_CITY, TARGET_JOB)
    email_subject = f"【PerfPulse】{TARGET_CITY} · {TARGET_JOB} 岗位需求情报 ({datetime.now().strftime('%Y-%m-%d')})"
    send_email(email_subject, styled_html)
    
    print("🎉 分析流程顺利完成！")
