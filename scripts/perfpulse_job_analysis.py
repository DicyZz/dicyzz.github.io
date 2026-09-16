import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI

# ==================== 1. 配置项 (默认适配 Gmail SMTP) ====================
TARGET_CITY = os.getenv("TARGET_CITY") or "北京"
TARGET_JOB = os.getenv("TARGET_JOB") or "ESL建模工程师"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 默认适配 Gmail 的 SMTP 配置
SMTP_SERVER = os.getenv("SMTP_SERVER") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or 465)

SENDER_EMAIL = os.getenv("SENDER_EMAIL") or ""
SENDER_PASS = os.getenv("SENDER_PASS") or ""  # 填入 Gmail 生成的 16 位 App Password
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL") or SENDER_EMAIL

# 初始化 OpenAI 客户端 (对接 DeepSeek API)
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ==================== 2. 数据采集/导入入口 ====================
def fetch_raw_job_listings(city: str, keyword: str) -> list:
    """
    岗位数据入口。
    后续可在此处直接对接 Playwright 抓取导出的数据或本地 JSON 文本。
    """
    mock_data = [
        {
            "title": f"{keyword}专家",
            "company": "某芯片设计头部企业",
            "city": city,
            "salary": "35k-50k·16薪",
            "jd_text": "负责NPU C-Model/gem5架构仿真，精通C++17/Python，熟悉RISC-V指令集、PCIe与AXI总线协议，具备SystemC建模经验者优先。"
        },
        {
            "title": f"高级 {keyword}",
            "company": "某智能驾驶计算平台公司",
            "city": city,
            "salary": "30k-45k",
            "jd_text": "负责AI芯片ESL建模与性能评估，精通gem5/SystemC，熟练掌握C++/Python，了解DMA控制器及Memory Bus Bridge机制。"
        }
    ]
    return mock_data

# ==================== 3. DeepSeek 分析模块 ====================
def analyze_job_requirements(job_list: list, city: str, keyword: str) -> str:
    """调用 DeepSeek API 进行岗位要求归纳与分析，生成支持 HTML 展示的文本"""
    
    prompt = f"""
你是一位专业的 IC 与软件技术猎头。请分析以下在【{city}】采集到的【{keyword}】相关岗位的原始招聘信息。

【原始数据】
{json.dumps(job_list, ensure_ascii=False, indent=2)}

【分析要求】
1. **核心硬技能 (Hard Skills)**：提炼高频出现的编程语言、仿真工具（如 gem5, SystemC）、总线协议及硬件体系结构要求。
2. **经验与门槛要求**：总结学历、年限要求及加分项。
3. **薪资区间与市场行情**：给出该城市的薪资范围评估。
4. **SWOT 竞争力建议**：针对此类岗位，求职者或团队应补充哪些关键技术项？

【输出格式】
请直接输出干净的 HTML 片段（无需 Markdown 格式包裹，不要包含 ```html 标记），使用内联样式（Inline CSS），支持在邮件客户端直接渲染。
    """
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content

# ==================== 4. 邮件推送模块 (Gmail SSL) ====================
def send_email_report(html_content: str, city: str, keyword: str):
    """通过 Gmail SMTP SSL 发送分析报告"""
    if not SENDER_EMAIL or not SENDER_PASS:
        raise ValueError(
            "缺少发件人配置！请确保在 GitHub Secrets 中已设置 SENDER_EMAIL "
            "和 SENDER_PASS (Gmail 16 位应用密码)。"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【PerfPulse】{city}·{keyword} 岗位市场情报与要求提炼 ({datetime.now().strftime('%Y-%m-%d')})"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"正在通过 Gmail SMTP ({SMTP_SERVER}:{SMTP_PORT}) 发送邮件，发件人: {SENDER_EMAIL}...")
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())

# ==================== 5. 主流程执行 ====================
if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始收集 [{TARGET_CITY}] [{TARGET_JOB}] 岗位数据...")
    raw_jobs = fetch_raw_job_listings(TARGET_CITY, TARGET_JOB)
    
    print("正在调用 DeepSeek 进行岗位要求提炼与总结...")
    analysis_html = analyze_job_requirements(raw_jobs, TARGET_CITY, TARGET_JOB)
    
    print("正在发送分析报告邮件...")
    send_email_report(analysis_html, TARGET_CITY, TARGET_JOB)
    print("分析与邮件推送顺利完成！")
