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
    print("1. 正在通过 DeepSeek 抓取与汇总最新 PerfPulse 技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    today_str = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""
你是一位专注于计算机体系结构、高性能计算（HPC）、LLM 系统架构与系统性能优化的资深专家。
今天是 {today_str}。请检索并整理**最新**（近 24-48 小时内）的全网最前沿技术动态，生成一份专业的【PerfPulse 每日技术简报】。

### 📌 强制数据检索来源参考：
- **体系结构与硬件**：Phoronix, AnandTech, Chips and Cheese, ServeTheHome, IEEE Micro, Hot Chips
- **LLM 系统与推理/训练加速**：Hugging Face Blog, PyTorch Core / vLLM / SGLang GitHub, FlashAttention 提交, ArXiv (cs.CL / cs.DC / cs.AR), SemiAnalysis
- **HPC 与编译优化**：LLVM Discourse / Commits, GCC Mailing List, NVIDIA Developer Blog, CUDA/ROCm Releases, MLIR News
- **系统与 Kernel 调优**：LWN.net, Linux Kernel Mailing List (LKML), eBPF.io, Brendan Gregg's Blog, Performance Mailing List

---

### 📝 请按以下 5 个核心板块输出内容：

1. **🧠 LLM 系统与推理/训练加速**
   - 关注：大模型推理引擎（vLLM, TensorRT-LLM, SGLang）、分布式并行算法（Tensor/Pipeline/Context Parallelism, SUMMA）、FlashAttention/FlashDecoding、量化技术（FP8/FP4/AWQ/GPTQ）及 GPU/NPU 内存带宽 bottlenecks（Prefill/Decode 阶段优化）。

2. **🚀 计算机体系结构与芯片动态**
   - 关注：CPU/GPU/NPU/TPU 最新架构、指令集扩展（RISC-V/AVX-512/AMX/SVE）、微架构流水线改进、Cache & Interconnect 设计。

3. **⚡ 高性能计算与编译优化**
   - 关注：LLVM/GCC 优化 Passes、MLIR 编译器基础设施、CUDA/ROCm 编程模型优化、Auto-vectorization/SIMD 优化。

4. **🛠️ 系统性能调优与 Kernel 内核**
   - 关注：Linux Kernel 关键性能 Patch、eBPF 监控实践、NUMA / 内存管理 (THP/PAGE_SIZE) 调优、perf / Ftrace / VTune 抓取与调优案例。

5. **📄 必读前沿论文与开源项目**
   - 整理 2-3 篇来自 arXiv、ISCA、MICRO、ASPLOS、OSDI、MLSys 的最新论文/开源仓库，附带简要技术分析与链接。

---

### 💡 输出要求：
- **拒绝陈旧的泛泛科普**：必须包含具体的技术细节（如具体的指令集、代码分支、内核 Patch 号、微架构参数、数学/算法公式或参数对比）。
- **必须附带来源/仓库链接**：每条动态末尾需标注信息出处或 GitHub/ArXiv 链接。
- 排版请使用标准 Markdown 格式，保持层级分明、阅读舒适。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个极具技术深度的系统与大模型硬件性能架构师，善于追踪并精炼最前沿的硬件、系统与 LLM 加速技术情报。"},
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
    print("2. 正在渲染高颜值 HTML 邮件并发送至 Gmail...")
    
    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender
    
    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置（EMAIL_SENDER / EMAIL_PASSWORD）！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content, 
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br']
    )
    
    today_date = datetime.now().strftime("%Y-%m-%d")

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
          max-width: 820px;
          margin: 0 auto;
          background: #ffffff;
          border: 1px solid #e1e4e8;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        }}
        .header {{
          background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
          color: #ffffff;
          padding: 30px 36px;
        }}
        .header h1 {{
          margin: 0;
          font-size: 25px;
          font-weight: 700;
          letter-spacing: -0.5px;
        }}
        .header .subtitle {{
          margin-top: 10px;
          font-size: 13px;
          color: #a5b4fc;
          line-height: 1.5;
        }}
        .content {{
          padding: 36px;
          font-size: 15px;
          line-height: 1.75;
        }}
        h2 {{
          color: #0f172a;
          font-size: 19px;
          border-bottom: 2px solid #e2e8f0;
          padding-bottom: 8px;
          margin-top: 32px;
          margin-bottom: 16px;
        }}
        h3 {{
          font-size: 16px;
          color: #1e293b;
          margin-top: 22px;
        }}
        p {{
          margin: 12px 0;
          color: #334155;
        }}
        ul, ol {{
          padding-left: 22px;
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
          padding: 4px 16px;
          color: #475569;
          border-left: 4px solid #6366f1;
          background: #eeef2e10;
          border-radius: 0 6px 6px 0;
        }}
        a {{
          color: #4f46e5;
          text-decoration: none;
          font-weight: 500;
        }}
        a:hover {{
          text-decoration: underline;
        }}
        .footer {{
          background-color: #f8fafc;
          border-top: 1px solid #e2e8f0;
          padding: 18px 36px;
          text-align: center;
          font-size: 12px;
          color: #94a3b8;
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>⚡ PerfPulse 每日技术与架构简报</h1>
          <div class="subtitle">日期：{today_date} | 聚焦 LLM 系统加速 · CPU/GPU 微架构 · HPC 编译优化 · Linux Kernel</div>
        </div>
        <div class="content">
          {raw_html}
        </div>
        <div class="footer">
          由 DeepSeek & PerfPulse 自动化驱动构建 | 持续追踪全球顶级硬件与系统前沿
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
        print("🎉 高颜值 PerfPulse 简报已成功发送至你的 Gmail 邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
