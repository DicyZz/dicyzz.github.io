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
    print("1. 正在通过 DeepSeek 检索全网顶级源（含用户 News 收藏书签）并生成 PerfPulse 技术简报...")
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

### 📌 强制数据检索与对标来源（已集成用户的「收藏/News/」全量书签）：

1. **LLM 系统 & AI Infra**：
   - vLLM / SGLang GitHub & Blog, PyTorch Engineering Blog, NVIDIA Technical Blog, Tri Dao (FlashAttention) 动态, ArXiv (`cs.AR`, `cs.DC`, `cs.CL`), SemiAnalysis.
   - **来自 News 收藏源**：Understanding AI (understandingai.org), TechCrunch AI (techcrunch.com/category/artificial-intelligence/), Ars Technica (arstechnica.com).

2. **体系结构 & 芯片/IP 微架构**：
   - Chips and Cheese, ServeTheHome, RISC-V International, ACM SIGARCH, IEEE Micro.
   - **来自 News 收藏源**：SemiEngineering (semiengineering.com), Hardware Times (hardwaretimes.com), WikiChip ARM (wikichip.org), AnandTech (anandtech.com), Design & Reuse (design-reuse.com), EET China 电子工程专辑 (eet-china.com), Doulos (doulos.com), Tom's Hardware (tomshardware.com), ASCII.jp 硬件连载 (ascii.jp), ConsortiumInfo (consortiuminfo.org).

3. **HPC & 编译优化**：
   - LLVM Discourse/Commits, GCC Mailing List, MLIR News, TVM Discourse, OneAPI / ROCm Release Notes.

4. **Linux 内核 & 系统性能调优**：
   - LWN.net, LKML, Brendan Gregg's Blog, ebpf.io, Cloudflare / Netflix TechBlog.
   - **来自 News 收藏源**：Phoronix (phoronix.com), It's FOSS News (news.itsfoss.com), Slashdot (slashdot.org), Alltop Linux (alltop.com/linux), Narkive 邮件列表 (narkive.com), DZone (dzone.com), Packet Storm Security (packetstormsecurity.com).

---

### 🖼️ 📸 🎥 多媒体与交互元素插入要求：

1. **科技图表与动态演示 (GIF/PNG)**：
   - 首图：![Banner](https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1000&q=80)
   - 芯片微架构插图：![Microarchitecture](https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1000&q=80)
   - 系统调优插图：![System Performance](https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1000&q=80)

2. **音频/播客解读占位卡片 (Podcast/Audio Card)**：
   在“今日深度剖析”之后按以下格式插入：
   ```markdown
   > 🎙️ **PerfPulse 3分钟音频架构解读**
   > 🎧 **主题**：[填写今日深度剖析的核心主题]
   > 💡 *提示：点击上方播放按钮，在通勤路上听完今日最核心的微架构瓶颈突破逻辑。（在公众号发布时，可在公众号后台插入对应的音频文件）*
视频/论文演示占位卡片 (Video Demo Card)：
若有视频/ Talk，按以下格式插入：

Markdown
> 🎬 **视频演示 / Talk 推荐**：
> 🔗 **视频标题**：[视频/讲座名称]
> 📌 **核心看点**：[1句话说明视频展示的 benchmark 跑分或 CPU/GPU 内存火焰图] [查看视频/演示链接](链接地址)
📝 输出结构要求：
请严格按以下结构输出 Markdown 内容：

💡 30 秒极速看点 (TL;DR)

观点 1：一句话总结今日最震撼的突破/论文/开源发布。

观点 2：一句话总结芯片或 LLM 引擎的核心性能收益。

观点 3：一句话总结 Kernel 或编译调优干货。

🌟 0. 今日深度剖析 (Today's Deep Dive)
挑选 1 个最具有架构影响力的技术突破/论文/开源重构，进行 300 字左右的架构级深度分析（微架构影响、Bottleneck 突破逻辑与性能收益）。

🧠 1. LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
关注：大模型推理引擎（vLLM, SGLang, TensorRT-LLM）、分布式并行、Quantization (FP8/FP4/AWQ)、GPU 内存带宽/KV Cache 优化。

🚀 2. 体系结构与芯片动态 (Silicon & Microarchitecture)
关注：CPU/GPU/NPU/TPU 最新微架构、指令集扩展（RISC-V/AVX-512/AMX/SVE/SME）、流水线/Cache/Interconnect 设计、IP/EDA 动态。

⚡ 3. 高性能计算与编译优化 (HPC & Compilers)
关注：LLVM/GCC 优化 Passes、MLIR 编译器、CUDA/ROCm 编程模型、Auto-vectorization/SIMD 优化。

🛠️ 4. 系统性能调优与 Kernel (Kernel & Performance)
关注：Linux Kernel 关键性能 Patch、eBPF 观察、NUMA/内存管理调优、perf / Ftrace / VTune 实战。

📄 5. 必读前沿论文与开源仓库 (ArXiv & Open Source)
精选 1-2 篇 ArXiv 最新论文或 GitHub 热门性能工具仓库，附带简要技术评估与链接。

💡 代码与干货要求：
代码与命令包裹：所有 perf 诊断脚本、vLLM 参数、LLVM 编译 Flag 和代码片段，必须明确包裹在 Markdown 代码块中（如 bash ...  或 python ... ）。

拒绝陈旧科普：直奔主题，输出具体参数、指令集、Patch 号、性能提升百分比数据。

出处标注：每条资讯末尾须带上 [来源/GitHub/ArXiv] 链接。
"""

try:
response = client.chat.completions.create(
model="deepseek-chat",
messages=[
{"role": "system", "content": "你是一个极具技术深度的系统与大模型硬件性能架构师，善于追踪并精炼最前沿的技术情报，且熟知公众号与极客社区的高质量排版习惯。"},
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
print("2. 正在渲染适配微信公众号排版的高颜值 HTML 邮件...")

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

styled_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: #f4f6f8;
      color: #24292e;
      margin: 0;
      padding: 8px;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 28px 24px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{
      margin: 0;
      font-size: 21px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: 0.5px;
      line-height: 1.4;
    }}
    .header .subtitle {{
      margin-top: 10px;
      font-size: 12px;
      color: #a5b4fc;
      line-height: 1.6;
    }}
    .content {{
      padding: 20px 22px;
      font-size: 15px;
      line-height: 1.8;
      color: #334155;
    }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 5px solid #4f46e5;
      padding: 8px 12px;
      border-radius: 0 6px 6px 0;
      margin-top: 32px;
      margin-bottom: 16px;
    }}
    h3 {{
      font-size: 15px;
      color: #1e293b;
      margin-top: 22px;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    p {{
      margin: 12px 0;
      color: #334155;
      word-wrap: break-word;
    }}
    ul, ol {{
      padding-left: 18px;
      margin: 12px 0;
    }}
    li {{
      margin-bottom: 8px;
      color: #334155;
      line-height: 1.75;
    }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      margin: 18px 0;
      display: block;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    code {{
      background-color: #e2e8f0;
      color: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 85%;
      font-weight: 600;
    }}
    pre {{
      background-color: #0f172a;
      color: #f8fafc;
      padding: 16px;
      border-radius: 8px;
      overflow-x: auto;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.6;
      margin: 16px 0;
      border: 1px solid #1e293b;
    }}
    pre code {{
      background-color: transparent;
      color: #f8fafc;
      padding: 0;
      font-weight: normal;
    }}
    blockquote {{
      margin: 16px 0;
      padding: 12px 16px;
      color: #1e293b;
      border-left: 4px solid #4f46e5;
      background-color: #f0fdf4;
      border-radius: 0 8px 8px 0;
      font-size: 14px;
    }}
    blockquote p {{
      margin: 4px 0;
      color: #166534;
    }}
    a {{
      color: #4f46e5;
      text-decoration: none;
      font-weight: 500;
      border-bottom: 1px dashed #6366f1;
    }}
    .footer {{
      background-color: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 18px 24px;
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

print("3. 正在使用 Premailer 自动将 CSS 样式转换为内联属性...")
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
    print("🎉 包含全量 News 书签数据源的 PerfPulse 简报已成功发送！")
except Exception as e:
    print(f"❌ 邮件发送失败: {str(e)}")
    sys.exit(1)
if name == "main":
content = generate_briefing()
send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
