import os
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown
from premailer import transform

# 读取环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

def generate_briefing():
    print("1. 正在通过 DeepSeek 检索全网顶级源并生成 PerfPulse 技术简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    today_str = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""
你是一位专注于计算机体系结构、高性能计算（HPC）、LLM 系统架构与系统性能调优的顶级资深架构师。
今天是 {today_str}。请检索全网**最新**（近 24-48 小时内）的前沿技术情报，生成一份专业的【PerfPulse 每日技术简报】。

---

### 📌 强制数据检索与对标来源（请检索并参考以下源头的最新更新）：
1. **LLM 系统 & AI Infra**：vLLM / SGLang GitHub & Blog, PyTorch Engineering Blog, NVIDIA Technical Blog (CUDA/CUTLASS), Hugging Face Blog, Tri Dao (FlashAttention) 动态, MLSys, ArXiv (`cs.AR`, `cs.DC`, `cs.CL`), SemiAnalysis.
2. **体系结构 & 芯片微架构**：Chips and Cheese, Phoronix, ServeTheHome, AnandTech, RISC-V International, ACM SIGARCH (Computer Architecture Today), IEEE Micro.
3. **HPC & 编译优化**：LLVM Discourse/Commits, GCC Mailing List, MLIR News, TVM Discourse, OneAPI / ROCm Release Notes.
4. **Linux 内核 & 系统调优**：LWN.net, LKML, Brendan Gregg's Blog, ebpf.io, Cilium Blog, Cloudflare Tech Blog, Netflix Systems Blog.

---

### 📝 请按以下结构输出简报内容：

#### 🌟 0. 今日深度剖析 (Today's Deep Dive)
- 从近期的更新中遴选 **1 个最具有架构影响力的技术突破/论文/开源重构**（如：某个重要系统的 Prefill/Decode 优化、新指令集扩展、重磅内核 Patch 或 FlashAttention 级突破）。
- 进行 300 字左右的架构级深度分析，阐述其**微架构影响、Bottleneck 突破逻辑与性能收益**。

#### 🧠 1. LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
- 关注：大模型推理引擎（vLLM, SGLang, TensorRT-LLM）、分布式并行（Tensor/Pipeline/Context Parallelism, SUMMA）、Quantization (FP8/FP4/AWQ)、GPU 内存带宽/KV Cache 优化。

#### 🚀 2. 体系结构与芯片动态 (Silicon & Microarchitecture)
- 关注：CPU/GPU/NPU/TPU 最新微架构、指令集扩展（RISC-V/AVX-512/AMX/SVE/SME）、流水线/Cache/Interconnect 设计。

#### ⚡ 3. 高性能计算与编译优化 (HPC & Compilers)
- 关注：LLVM/GCC 优化 Passes、MLIR 编译器、CUDA/ROCm 编程模型、Auto-vectorization/SIMD 优化。

#### 🛠️ 4. 系统性能调优与 Kernel (Kernel & Performance)
- 关注：Linux Kernel 关键性能 Patch、eBPF 观察与安全、NUMA/内存管理调优、perf / Ftrace / VTune 调优实战。

#### 📄 5. 必读前沿论文与开源仓库 (ArXiv & Open Source)
- 精选 1-2 篇 ArXiv 最新论文或 GitHub 热门性能工具仓库，附带简要技术点评估与链接。

---

### 💡 输出要求：
1. **拒绝对话式废话与陈旧科普**：直奔主题，包含具体的技术细节（如具体的指令集、代码分支、内核 Patch 号、微架构参数、数学/算法公式或参数对比）。
2. **附带实用干货**：如适用，请附带 1-2 行实用的 `perf` 诊断命令、vLLM 参数配置或编译 Flag。
3. **出处标注**：每条资讯末尾须带上 [来源/GitHub/ArXiv] 链接。
4. 使用结构清晰的 Markdown 格式输出。
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
        print("✅ 最新 PerfPulse 简报生成成功！")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ DeepSeek 生成简报失败: {str(e)}")
        sys.exit(1)

def send_email(subject, md_content):
    print("2. 正在渲染高颜值 HTML 邮件并自动内联 CSS...")
    
    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender
    
    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置（EMAIL_SENDER / EMAIL_PASSWORD）！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content, 
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'toc']
    )
    
    today_date = datetime.now().strftime("%Y-%m-%d")

    # 包含兼容公众号和邮箱的 CSS 样式表
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
          padding: 10px;
        }}
        .container {{
          max-width: 800px;
          margin: 0 auto;
          background: #ffffff;
          border: 1px solid #e1e4e8;
          border-radius: 12px;
          overflow: hidden;
        }}
        .header {{
          background-color: #0f172a;
          color: #ffffff;
          padding: 24px 30px;
        }}
        .header h1 {{
          margin: 0;
          font-size: 22px;
          font-weight: 700;
          color: #ffffff;
        }}
        .header .subtitle {{
          margin-top: 8px;
          font-size: 13px;
          color: #a5b4fc;
          line-height: 1.5;
        }}
        .content {{
          padding: 28px 30px;
          font-size: 15px;
          line-height: 1.75;
          color: #334155;
        }}
        h2 {{
          color: #0f172a;
          font-size: 18px;
          border-bottom: 2px solid #e2e8f0;
          padding-bottom: 6px;
          margin-top: 28px;
          margin-bottom: 14px;
        }}
        h3 {{
          font-size: 16px;
          color: #1e293b;
          margin-top: 20px;
          margin-bottom: 10px;
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
          margin-bottom: 6px;
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
          padding: 14px;
          border-radius: 8px;
          overflow-x: auto;
          font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
          font-size: 13px;
          line-height: 1.5;
        }}
        blockquote {{
          margin: 16px 0;
          padding: 8px 16px;
          color: #334155;
          border-left: 4px solid #6366f1;
          background-color: #f0f4ff;
          border-radius: 0 6px 6px 0;
        }}
        a {{
          color: #4f46e5;
          text-decoration: none;
          font-weight: 500;
        }}
        .footer {{
          background-color: #f8fafc;
          border-top: 1px solid #e2e8f0;
          padding: 16px 30px;
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
          <div class="subtitle">发布日期：{today_date} | 聚焦 LLM 系统加速 · CPU/GPU 微架构 · HPC 编译优化 · Linux Kernel</div>
        </div>
        <div class="content">
          {raw_html}
        </div>
        <div class="footer">
          由 DeepSeek & PerfPulse 自动化驱动构建 | 保持对底层技术的终极好奇
        </div>
      </div>
    </body>
    </html>
    """

    # 【关键处理】自动将 <style> 中的样式转为 style="..." 属性嵌到每个 HTML 元素上
    print("3. 正在使用 Premailer 将样式转换为内联属性（兼容公众号直接复制）...")
    inlined_html = transform(styled_html)

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = f"{subject} ({today_date})"
    message.attach(MIMEText(inlined_html, "html", "utf-8"))

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(sender, EMAIL_PASSWORD.strip())
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("🎉 高颜值且支持公众号无缝复制的 PerfPulse 简报已成功发送！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
