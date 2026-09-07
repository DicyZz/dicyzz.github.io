import os
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown

# 读取环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

def generate_briefing():
    print("1. 正在通过 DeepSeek 抓取与汇总最新 EasyPerf 技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    today_str = datetime.now().strftime("%Y年%m月%d日")

    # 强化 Prompt，要求DeepSeek总结最新动态并标注来源/链接
    prompt = f"""
你是一位专注于计算机体系结构、高性能计算（HPC）与系统性能优化的专家。
今天是 {today_str}。请检索并整理**最新**（近24-48小时内）的系统与硬件性能技术动态，生成一份专业的【EasyPerf 每日技术简报】。

请包含以下四个核心板块：
1. **🚀 体系结构与芯片动态** (CPU/GPU/NPU、微架构改进、指令集拓展如 RISC-V/AVX-512/AMX)
2. **⚡ 高性能计算与编译优化** (LLVM/GCC 优化、CUDA/ROCm、SVE/SME/SIMD 向量化、分布式并行算法)
3. **🛠️ 系统性能调优与 Kernel** (Linux Kernel 性能补丁、eBPF、内存管理、perf/Ftrace/VTune 实践)
4. **📄 必读论文与前沿解读** (来自 arXiv、ISCA、MICRO、ASPLOS、OSDI 等最新硬件/系统架构论文)

要求：
- 拒绝陈旧的通用泛泛介绍，必须包含具体技术细节（如具体的指令集、代码分支、内核提交、微架构参数）。
- 每一条资讯须附带简要的技术影响分析与可能关注的官方仓库/论文来源。
- 结构清晰，排版使用优雅的 Markdown 格式，适当使用列表与加粗。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个极具技术深度的系统性能架构师，善于追踪并精炼最前沿的硬件与软件性能技术情报。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            stream=False
        )
        print("✅ 最新简报生成成功！")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def send_email(subject, md_content):
    print("2. 正在渲染高颜值 HTML 邮件并发送...")
    
    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender
    
    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置（EMAIL_SENDER / EMAIL_PASSWORD）！")
        sys.exit(1)

    # 解析 Markdown
    raw_html = markdown.markdown(
        md_content, 
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br']
    )
    
    today_date = datetime.now().strftime("%Y-%m-%d")

    # 极简高颜值邮件模板 (GitHub/Notion 风格)
    styled_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          background-color: #f6f8fa;
          color: #24292e;
          margin: 0;
          padding: 20px;
        }}
        .container {{
          max-width: 800px;
          margin: 0 auto;
          background: #ffffff;
          border: 1px solid #e1e4e8;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }}
        .header {{
          background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
          color: #ffffff;
          padding: 28px 32px;
        }}
        .header h1 {{
          margin: 0;
          font-size: 24px;
          font-weight: 700;
          letter-spacing: -0.5px;
        }}
        .header .subtitle {{
          margin-top: 8px;
          font-size: 13px;
          color: #94a3b8;
        }}
        .content {{
          padding: 32px;
          font-size: 15px;
          line-height: 1.7;
        }}
        h2 {{
          color: #0f172a;
          font-size: 18px;
          border-bottom: 2px solid #f1f5f9;
          padding-bottom: 8px;
          margin-top: 28px;
          margin-bottom: 16px;
        }}
        h3 {{
          font-size: 16px;
          color: #334155;
          margin-top: 20px;
        }}
        p {{
          margin: 12px 0;
          color: #334155;
        }}
        ul, ol {{
          padding-left: 20px;
          margin: 12px 0;
        }}
        li {{
          margin-bottom: 8px;
          color: #334155;
        }}
        code {{
          background-color: #f1f5f9;
          color: #0f172a;
          padding: 2px 6px;
          border-radius: 4px;
          font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
          font-size: 85%;
        }}
        pre {{
          background-color: #0f172a;
          color: #f8fafc;
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
          font-size: 13px;
        }}
        blockquote {{
          margin: 16px 0;
          padding: 0 16px;
          color: #64748b;
          border-left: 4px solid #3b82f6;
          background: #eff6ff;
          border-radius: 0 6px 6px 0;
        }}
        a {{
          color: #2563eb;
          text-decoration: none;
        }}
        a:hover {{
          text-decoration: underline;
        }}
        .footer {{
          background-color: #f8fafc;
          border-top: 1px solid #e2e8f0;
          padding: 16px 32px;
          text-align: center;
          font-size: 12px;
          color: #94a3b8;
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>EasyPerf 每日技术简报</h1>
          <div class="subtitle">发布日期：{today_date} | 聚焦 CPU/GPU 微架构 · HPC 编译优化 · 系统调优</div>
        </div>
        <div class="content">
          {raw_html}
        </div>
        <div class="footer">
          由 DeepSeek & EasyPerf 自动驱动构建 | 保持对底层技术的终极好奇
        </div>
      </div>
    </body>
    </html>
    """

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = f"{subject} ({today_date})"
    message.attach(MIMEText(styled_html, "html", "utf-8"))

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(sender, EMAIL_PASSWORD.strip())
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("🎉 高颜值 EasyPerf 简报已成功发送至你的 Gmail 邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【EasyPerf】每日硬件与系统性能简报", content)
