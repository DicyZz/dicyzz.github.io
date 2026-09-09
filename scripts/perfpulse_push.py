import os
import sys
import re
import time
import smtplib
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import feedparser
import markdown
from premailer import transform
from openai import OpenAI

# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 各模块 Top 顶级数据源全量配置
# ---------------------------------------------------------------------------
MODULE_FEEDS = {
    # === 模块一：LLM 系统与推理/训练加速 ===
    "LLM_Infra": {
        "ArXiv Machine Learning (cs.LG)": "http://export.arxiv.org/rss/cs.LG",
        "ArXiv Computation and Language (cs.CL)": "http://export.arxiv.org/rss/cs.CL",
        "ArXiv Artificial Intelligence (cs.AI)": "http://export.arxiv.org/rss/cs.AI",
        "PyTorch Official Blog": "https://pytorch.org/feed.xml",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Anyscale / Ray Blog": "https://www.anyscale.com/blog/rss.xml",
        "vLLM Official Blog": "https://blog.vllm.ai/feed.xml",
        "vLLM GitHub Releases": "https://github.com/vllm-project/vllm/releases.atom",
        "TensorRT-LLM GitHub Releases": "https://github.com/NVIDIA/TensorRT-LLM/releases.atom",
        "DeepSpeed Official Blog": "https://www.deepspeed.ai/feed.xml",
        "Triton Compiler Blog": "https://triton-lang.org/main/feed.xml",
        "MLSys Conference News": "https://mlsys.org/rss.xml",
        "OpenAI Research": "https://openai.com/news/rss.xml",
        "Google AI Blog": "https://research.google/blog/rss/",
        "Meta AI Blog": "https://ai.meta.com/blog/rss/",
        "NVIDIA Developer AI Blog": "https://developer.nvidia.com/blog/category/ai-deep-learning/feed/",
        "LlamaIndex Blog": "https://www.llamaindex.ai/blog/rss.xml",
        "LangChain Blog": "https://blog.langchain.dev/rss/",
        "Unsloth AI Blog": "https://unsloth.ai/blog/rss.xml",
        "Together AI Blog": "https://www.together.ai/blog/rss.xml",
        "Groq Hardware & Infra": "https://groq.com/feed/",
        "Modal Labs Blog": "https://modal.com/blog/feed.xml",
        "Paper with Code Trending": "https://paperswithcode.com/rss/latest"
    },

    # === 模块二：体系结构与 CPU/GPU 芯片动态 ===
    "Silicon_Architecture": {
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
        "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/rss/cs.AR",
        "SemiEngineering": "https://semiengineering.com/feed/",
        "WikiChip Fuse": "https://fuse.wikichip.org/feed/",
        "ServeTheHome (STH)": "https://www.servethehome.com/feed/",
        "The Next Platform": "https://www.nextplatform.com/feed/",
        "EE Times Global": "https://www.eetimes.com/feed/",
        "IEEE Spectrum Chips": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "Phoronix Processors": "https://www.phoronix.com/rss.php",
        "ARM Technical Articles": "https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/rss",
        "RISC-V International News": "https://riscv.org/news/feed/",
        "SiFive RISC-V Blog": "https://www.sifive.com/blog/rss.xml",
        "Tenstorrent Blog": "https://tenstorrent.com/feed/",
        "YouTube - Asianometry": "https://www.youtube.com/feeds/videos.xml?channel_id=UC19beC0uPyeAC062A0p4JpA",
        "YouTube - TechTechPotato": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1ZfSfZ0A_L4b40uJ5-G9_w"
    },

    # === 模块三：HPC、编译优化与 Linux Kernel ===
    "Kernel_Performance_HPC": {
        "LLVM Weekly": "llvmweekly.org/rss.xml",
        "LLVM Compiler Blog": "https://blog.llvm.org/feed.xml",
        "GCC Compiler News": "https://gcc.gnu.org/rss.xml",
        "LWN.net (Linux Kernel Direct)": "https://lwn.net/headlines/rss",
        "Brendan Gregg Performance Blog": "https://www.brendangregg.com/blog/rss.xml",
        "Phoronix (Linux & Kernel)": "https://www.phoronix.com/rss.php",
        "Kernel.org Releases": "https://www.kernel.org/feeds/kdist.xml",
        "eBPF Official Blog": "https://ebpf.io/feed.xml",
        "Rust Compiler & Performance": "https://blog.rust-lang.org/feed.xml",
        "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/rss/cs.DC",
        "ArXiv Performance Evaluation (cs.PF)": "http://export.arxiv.org/rss/cs.PF",
        "Cloudflare Tech Blog": "https://blog.cloudflare.com/rss/",
        "Netflix Tech Blog": "https://netflixtechblog.com/feed",
        "NVIDIA CUDA & Systems Blog": "https://developer.nvidia.com/blog/category/cuda/feed/",
        "AMD Instinct & ROCm Docs": "https://rocm.docs.amd.com/en/latest/rss.xml",
        "Hacker News Systems Tech": "https://news.ycombinator.com/rss"
    }
}

def clean_html_summary(html_text):
    """清洗 HTML 标签，提炼纯文本"""
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text[:400]

def is_recent_entry(entry, max_hours=48):
    """检查文章是否在最近 max_hours 小时内发布"""
    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published_struct:
        return True
    try:
        pub_time = datetime.fromtimestamp(time.mktime(published_struct), tz=timezone.utc)
        now_time = datetime.now(timezone.utc)
        return (now_time - pub_time) <= timedelta(hours=max_hours)
    except Exception:
        return True

def fetch_single_feed(source_name, feed_url, category, max_items=2):
    """单源抓取函数（增加超时与 48 小时时间过滤）"""
    if not feed_url.startswith("http"):
        feed_url = "https://" + feed_url

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PerfPulseBot/1.0'}
    
    try:
        resp = requests.get(feed_url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []
        
        feed = feedparser.parse(resp.content)
        fetched_items = []
        count = 0

        for entry in feed.entries:
            if count >= max_items:
                break
            
            if not is_recent_entry(entry, max_hours=48):
                continue

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = clean_html_summary(entry.get("summary", entry.get("description", "")))
            
            if title:
                fetched_items.append(
                    f"【模块: {category} | 平台源: {source_name}】\n"
                    f"标题: {title}\n"
                    f"链接: {link}\n"
                    f"摘要: {summary}\n"
                )
                count += 1
        return fetched_items
    except Exception:
        return []

def fetch_all_feeds():
    """并发并行抓取全量 RSS 订阅点"""
    print("1. 正在通过并发线程池拉取全球技术数据源（含超时控制与 48h 过滤）...")
    raw_articles = []
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        future_to_source = {}
        for category, feeds in MODULE_FEEDS.items():
            for source_name, feed_url in feeds.items():
                future = executor.submit(fetch_single_feed, source_name, feed_url, category, max_items=2)
                future_to_source[future] = source_name

        for future in as_completed(future_to_source):
            items = future.result()
            if items:
                raw_articles.extend(items)

    if not raw_articles:
        print("⚠️ 未抓取到 48 小时内的新资讯，将使用保底逻辑。")
        return "今日暂无 48 小时内的新动态更新。"

    print(f"✅ 成功从权威源中抓取并筛选出 {len(raw_articles)} 条最新资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报与微信音频朗读文本
# ---------------------------------------------------------------------------
def generate_briefing_and_audio_script():
    real_news_context = fetch_all_feeds()

    print("2. 正在通过 DeepSeek 提炼专业技术简报与微信播客脚本...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    exact_iso_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位极度严谨的系统与硬件架构师兼科技编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【PerfPulse 每日架构与系统性能简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的技术主题（优先提炼以下方向）：
1. **LLM 系统加速**：KV Cache 管理、Speculative Decoding、PagedAttention、Quantization (FP8/INT4/AWQ)、FlashAttention/FlashDecoding、vLLM/TensorRT-LLM 优化、Distributed Training/Inference (Pipeline/Tensor Parallelism)。
2. **CPU/GPU 微架构**：Cache Hierarchy (L1/L2/L3/SLC)、Branch Predictor、Out-of-Order Execution、ROB/Execution Units、Vector/Matrix Extensions (AVX-512, AMX, SVE, Tensor Cores)、Interconnect (NVLink, CXL, PCIe Gen6)。
3. **HPC 与编译优化**：LLVM/MLIR Passes、Loop Transformations (Tiling, Unrolling, Fusion)、Triton/TVM/XLA 代码生成、CUDA/ROCm/SYCL 内核优化、MPI/NCCL 通信重叠。
4. **Linux Kernel & Performance**：eBPF/XDP、io_uring、Memory Management (THP, NUMA balancing, ZSWAP)、Scheduler (EEVDF)、Filesystem/Block Layer (bcachefs, NVMe-oF)、perf/BPF 性能分析。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. **区分民间与官方**：对于民间第三方开源项目或非官方评测，必须明确标注“第三方社区/个人观点”。
3. **静默跳过法则**：若某个领域在今日抓取数据中完全没有对应资讯，直接静默忽略该板块标题，严禁输出“无相关内容”。
4. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
用客观严谨的一句话总结最新发布或论文。

### 芯片与 LLM 引擎收益
用客观严谨的一句话总结真实芯片或 AI 系统动态。

### Kernel 与编译调优干货
用客观严谨的一句话总结 Linux Kernel 或编译调优动态。

---

## 今日深度剖析 (Today's Deep Dive)
挑选上述数据中最具架构深度的一条新闻/论文/更新，进行客观专业的深度分析（200-300 字）。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
根据真实上下文整理（若无相关数据则静默跳过）。

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)
根据真实上下文整理（若无相关数据则静默跳过）。

---

## HPC、编译优化与 Linux Kernel (HPC, Compilers & Kernel)
根据真实上下文整理 LLVM、CUDA、Linux Kernel 与 HPC 动态（若无相关数据则静默跳过）。

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)
根据真实上下文整理，附原始链接。
"""

    try:
        briefing_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的技术核查编辑。只提炼真实上下文，绝不夸大事实，没有数据的板块直接跳过。"},
                {"role": "user", "content": briefing_prompt}
            ],
            temperature=0.0,
            stream=False
        )

        md_content = briefing_response.choices[0].message.content.strip()
        if md_content.startswith("```markdown"):
            md_content = md_content[11:]
        elif md_content.startswith("```"):
            md_content = md_content[3:]
        if md_content.endswith("```"):
            md_content = md_content[:-3]

        audio_script_prompt = f"""
请将以下技术简报转换为一段适合微信公众号“文字转语音”或者公众号朗读文本的口语化脚本。

要求：
1. 语言通俗自然，去除所有 Markdown 格式符号（如 `#`、`*`、`[链接]` 等）。
2. 开头问好：“大家好，欢迎收听 PerfPulse 每日架构听力解读。”
3. 重点阐述 30 秒极速看点和今日深度剖析的内容。
4. 控制在 400-600 字之间。

=== 简报内容 ===
{md_content}
"""
        audio_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位专业的科技播客主持人，擅长将硬核技术转换为自然流畅的口语表达。"},
                {"role": "user", "content": audio_script_prompt}
            ],
            temperature=0.2,
            stream=False
        )
        audio_script = audio_response.choices[0].message.content.strip()

        print("✅ 多源简报文字与公众号音频文本生成成功！")
        return md_content.strip(), audio_script
    except Exception as e:
        print(f"❌ DeepSeek 生成失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3. 邮件渲染与发送 (已移除 MP3 附件逻辑)
# ---------------------------------------------------------------------------
def send_email(subject, md_content, audio_script):
    print("3. 正在渲染适配邮件样式的 HTML 正文...")

    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender

    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置！")
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *, *:before, *:after {{ box-sizing: border-box !important; }}
    body {{
      font-family: -apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", Arial, sans-serif;
      background-color: #ffffff;
      color: #24292e;
      margin: 0;
      padding: 0;
      width: 100% !important;
    }}
    .container {{
      width: 100% !important;
      margin: 0 auto;
      background: #ffffff;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 16px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 700; color: #ffffff; }}
    .header .subtitle {{ margin-top: 10px; font-size: 12px; color: #a5b4fc; }}
    .content {{ padding: 16px 12px; font-size: 15px; line-height: 1.75; color: #334155; }}
    .audio-script-box {{
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #6366f1;
      padding: 16px;
      border-radius: 6px;
      margin-bottom: 24px;
    }}
    .audio-script-title {{
      font-weight: bold;
      font-size: 15px;
      color: #0f172a;
      margin-bottom: 8px;
    }}
    .audio-script-text {{
      font-size: 13px;
      color: #475569;
      line-height: 1.6;
    }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 4px solid #4f46e5;
      padding: 8px 12px;
      margin-top: 36px;
      margin-bottom: 20px;
    }}
    h3 {{ font-size: 16px; color: #0f172a; margin-top: 28px; margin-bottom: 12px; font-weight: 600; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    p {{ margin: 12px 0 16px 0; color: #334155; line-height: 1.75; text-align: justify; }}
    a {{ color: #4f46e5 !important; text-decoration: none !important; font-weight: 500 !important; border-bottom: 1px dashed #6366f1 !important; }}
    code {{ background-color: #f1f5f9; color: #4f46e5; padding: 2px 5px; border-radius: 4px; font-size: 88%; font-weight: 600; }}
    pre {{
      background-color: #0f172a !important;
      color: #f8fafc !important;
      padding: 14px !important;
      border-radius: 6px !important;
      overflow-x: auto !important;
      font-size: 12px !important;
      line-height: 1.6 !important;
      margin: 16px 0 !important;
    }}
    pre code {{ background-color: transparent !important; color: #f8fafc !important; padding: 0 !important; }}
    blockquote {{ margin: 20px 0; padding: 12px 14px; color: #1e293b; border-left: 4px solid #4f46e5; background-color: #f8fafc; font-size: 14px; }}
    .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 12px; text-align: center; font-size: 12px; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>⚡ PerfPulse 每日微架构、系统与 HPC 简报</h1>
      <div class="subtitle">发布日期：{today_date} | 真实硬件、LLM 加速与 Linux Kernel 严谨跟踪</div>
    </div>
    <div class="content">
      <div class="audio-script-box">
        <div class="audio-script-title">🎙️ 今日公众号语音脚本（可直接复制使用）</div>
        <div class="audio-script-text">{audio_script}</div>
      </div>
      {raw_html}
    </div>
    <div class="footer">
      基于顶级数据源 & DeepSeek 零幻觉模式构建
    </div>
  </div>
</body>
</html>
"""

    print("4. 正在进行 CSS 内联化转换并发送邮件...")
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
        print("🎉 简报正文及公众号语音脚本已成功发送至邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主流程入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    md_content, audio_script = generate_briefing_and_audio_script()
    send_email("【PerfPulse】每日硬件、微架构与 LLM 性能简报", md_content, audio_script)
