import os
import sys
import re
import asyncio
import smtplib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import markdown
from premailer import transform
import feedparser
import edge_tts

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
# 1. 各模块 Top 50 顶级数据源全量配置 (混合网站、YouTube、知乎/公众号桥接、ArXiv)
# ---------------------------------------------------------------------------
MODULE_FEEDS = {
    # === 模块一：LLM 系统与推理/训练加速 (Top 50) ===
    "LLM_Infra": {
        "ArXiv Machine Learning (cs.LG)": "http://export.arxiv.org/rss/cs.LG",
        "ArXiv Computation and Language (cs.CL)": "http://export.arxiv.org/rss/cs.CL",
        "ArXiv Artificial Intelligence (cs.AI)": "http://export.arxiv.org/rss/cs.AI",
        "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "Understanding AI": "https://www.understandingai.org/feed",
        "PyTorch Official Blog": "https://pytorch.org/feed.xml",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Anyscale / Ray Blog": "https://www.anyscale.com/blog/rss.xml",
        "VLLM Official Blog": "https://blog.vllm.ai/feed.xml",
        "DeepSpeed Official Blog": "https://www.deepspeed.ai/feed.xml",
        "Triton Compiler Blog": "https://triton-lang.org/main/feed.xml",
        "MLSys Conference News": "https://mlsys.org/rss.xml",
        "OpenAI Research": "https://openai.com/news/rss.xml",
        "Google AI Blog": "https://research.google/blog/rss/",
        "Meta AI Blog": "https://ai.meta.com/blog/rss/",
        "NVIDIA Developer AI Blog": "https://developer.nvidia.com/blog/category/ai-deep-learning/feed/",
        "Microsoft Research AI": "https://www.microsoft.com/en-us/research/feed/",
        "MIT CSAIL AI": "https://www.csail.mit.edu/news/rss",
        "Stanford HAI": "https://hai.stanford.edu/news/rss.xml",
        "Berkeley AI Research (BAIR)": "https://bair.berkeley.edu/blog/feed.xml",
        "LlamaIndex Blog": "https://www.llamaindex.ai/blog/rss.xml",
        "LangChain Blog": "https://blog.langchain.dev/rss/",
        "YouTube - Two Minute Papers": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbfYPyITQ-7l4upoX8nvctg",
        "YouTube - Yannic Kilcher": "https://www.youtube.com/feeds/videos.xml?channel_id=UCZHmXP3dRqiUqQy8WfWWPGA",
        "YouTube - Andrej Karpathy": "https://www.youtube.com/feeds/videos.xml?channel_id=UC37tpQG223v0pS2w1vU8A2A",
        "知乎热榜 - 人工智能": "https://rsshub.app/zhihu/hotlist",
        "V2EX AI 板块": "https://www.v2ex.com/feed/tab/ai.xml",
        "Weights & Biases Blog": "https://wandb.ai/site/blog/feed.xml",
        "MosaicML / Databricks AI": "https://www.databricks.com/blog/category/deep-learning/feed",
        "Together AI Blog": "https://www.together.ai/blog/rss.xml",
        "Groq Hardware & Infra": "https://groq.com/feed/",
        "Cerebras Blog": "https://cerebras.ai/feed/",
        "SambaNova Systems": "https://sambanova.ai/feed/",
        "Modal Labs Blog": "https://modal.com/blog/feed.xml",
        "RunPod Blog": "https://blog.runpod.io/rss/",
        "Lamini AI Blog": "https://www.lamini.ai/blog/rss.xml",
        "Unsloth AI Blog": "https://unsloth.ai/blog/rss.xml",
        "Predibase AI": "https://predibase.com/blog/rss.xml",
        "Baseten AI Blog": "https://www.baseten.co/blog/rss.xml",
        "Replicate Blog": "https://replicate.com/blog/rss.xml",
        "Fireworks AI Blog": "https://fireworks.ai/blog/rss.xml",
        "Pinecone Blog": "https://www.pinecone.io/blog/rss.xml",
        "Qdrant Blog": "https://qdrant.tech/blog/index.xml",
        "Chroma DB Blog": "https://www.trychroma.com/blog/rss.xml",
        "Weaviate Vector DB": "https://weaviate.io/blog/rss.xml",
        "AI News Digest": "https://ainews.com/rss.xml",
        "Paper with Code Trending": "https://paperswithcode.com/rss/latest",
        "MarkTechPost AI": "https://www.marktechpost.com/feed/",
        "Synced AI Technology": "https://syncedreview.com/feed/",
        "InfoQ AI & Data": "https://feed.infoq.com/ai-ml-data-eng/"
    },

    # === 模块二：体系结构与芯片动态 (Top 50) ===
    "Silicon_Architecture": {
        "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/rss/cs.AR",
        "SemiEngineering": "https://semiengineering.com/feed/",
        "AnandTech / Hardware Deep Dives": "https://www.anandtech.com/rss",
        "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
        "Hardware Times": "https://www.hardwaretimes.com/feed/",
        "EE Times China (电子工程专辑)": "https://www.eet-china.com/rss/news.xml",
        "Design & Reuse (IP & SoC)": "https://www.design-reuse.com/articles/rss/",
        "WikiChip Fuse": "https://fuse.wikichip.org/feed/",
        "ARM Technical Articles": "https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/rss",
        "RISC-V International News": "https://riscv.org/news/feed/",
        "ServeTheHome (STH)": "https://www.servethehome.com/feed/",
        "The Next Platform": "https://www.nextplatform.com/feed/",
        "EE Times Global": "https://www.eetimes.com/feed/",
        "Semiconductor Digest": "https://www.semiconductor-digest.com/feed/",
        "IEEE Spectrum Chips": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "Microprocessor Report": "https://www.techinsights.com/blog/rss.xml",
        "AnandTech Processors": "https://www.anandtech.com/tag/cpus/rss",
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
        "Phoronix Processors": "https://www.phoronix.com/rss.php",
        "ASCII.jp Hardware": "https://ascii.jp/serialarticles/420986/rss.xml",
        "YouTube - Asianometry": "https://www.youtube.com/feeds/videos.xml?channel_id=UC19beC0uPyeAC062A0p4JpA",
        "YouTube - Gamers Nexus": "https://www.youtube.com/feeds/videos.xml?channel_id=UCl2mFZoRqjw_ELAX4Yisf6w",
        "YouTube - TechTechPotato (Dr. Ian Cutress)": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1ZfSfZ0A_L4b40uJ5-G9_w",
        "YouTube - Moore's Law Is Dead": "https://www.youtube.com/feeds/videos.xml?channel_id=UCRBw_kG2EUpG1C_S8J9B4uA",
        "YouTube - Buildzoid (Actually Hardcore Overclocking)": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1mO2AUpk23C-QidmO9N_WA",
        "知乎 - 计算机体系结构讨论": "https://rsshub.app/zhihu/hotlist",
        "Semiconductor Engineering Memory": "https://semiengineering.com/category/memory/feed/",
        "Semiconductor Engineering EDA": "https://semiengineering.com/category/eda/feed/",
        "Semiconductor Engineering Packaging": "https://semiengineering.com/category/packaging/feed/",
        "ISCA Architecture Conference": "https://www.iscaconf.org/rss.xml",
        "MICRO Architecture Conference": "https://www.microarch.org/rss.xml",
        "HPCA Architecture News": "https://hpca-conf.org/rss.xml",
        "ASPLOS Architecture News": "https://www.asplos-conf.org/rss.xml",
        "SiFive RISC-V Blog": "https://www.sifive.com/blog/rss.xml",
        "Ventana Micro Systems": "https://www.ventanamicro.com/feed/",
        "Tenstorrent Blog": "https://tenstorrent.com/feed/",
        "Esperanto Technologies": "https://www.esperanto.ai/feed/",
        "Ampere Computing Blog": "https://amperecomputing.com/blog/rss.xml",
        "Graphcore Hardware Blog": "https://www.graphcore.ai/posts/rss.xml",
        "Untether AI Blog": "https://www.untether.ai/feed/",
        "Mythic AI Hardware": "https://mythic-ai.com/feed/",
        "Syntiant Edge AI": "https://www.syntiant.com/blog-feed.xml",
        "Cadence Design Systems Blog": "https://community.cadence.com/cadence_blogs_8/b/blogs/rss",
        "Synopsys Semiconductor Blog": "https://blogs.synopsys.com/feed/",
        "Siemens EDA Blog": "https://blogs.sw.siemens.com/eda/feed/",
        "Doulos SystemVerilog & VHDL": "https://www.doulos.com/rss.xml",
        "ConsortiumInfo Standards": "https://www.consortiuminfo.org/feed/",
        "Huodongxing Tech Events": "https://www.huodongxing.com/rss",
        "KKNews Silicon": "https://kknews.cc/rss.xml",
        "Yahoo Finance Tech & Semiconductor": "https://hk.finance.yahoo.com/rss"
    },

    # === 模块三：系统性能调优与 Kernel (Top 50) ===
    "Kernel_Performance": {
        "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/rss/cs.DC",
        "ArXiv Performance Evaluation (cs.PF)": "http://export.arxiv.org/rss/cs.PF",
        "Phoronix (Linux & Kernel)": "https://www.phoronix.com/rss.php",
        "LWN.net (Linux Kernel Direct)": "https://lwn.net/headlines/rss",
        "Slashdot (Developers/Systems)": "https://rss.slashdot.org/Slashdot/slashdotMain",
        "It's FOSS News": "https://news.itsfoss.com/rss/",
        "Ars Technica Tech": "https://feeds.arstechnica.com/arstechnica/index",
        "Packet Storm Security": "https://rss.packetstormsecurity.com/",
        "Alltop Linux": "https://alltop.com/linux",
        "Narkive Mailing Lists": "https://narkive.com/rss",
        "DZone Performance": "https://feeds.dzone.com/performance",
        "Kernel.org Releases & News": "https://www.kernel.org/feeds/kdist.xml",
        "Brendan Gregg Performance Blog": "https://www.brendangregg.com/blog/rss.xml",
        "Linux Magazine": "https://www.linux-magazine.com/rss/feed/lmg_full",
        "Phoronix Kernel Benchmarks": "https://www.phoronix.com/rss.php?mode=kernel",
        "Red Hat Research & Systems": "https://research.redhat.com/feed/",
        "Ubuntu Kernel Blog": "https://ubuntu.com/blog/tag/kernel/feed",
        "SUSE Blog Kernel & Performance": "https://www.suse.com/c/feed/",
        "Cloudflare Tech Blog": "https://blog.cloudflare.com/rss/",
        "Netflix Tech Blog (Systems)": "https://netflixtechblog.com/feed",
        "Uber Engineering Systems": "https://www.uber.com/blog/engineering/rss/",
        "Meta Engineering Systems": "https://engineering.fb.com/feed/",
        "Google Cloud Systems Blog": "https://cloud.google.com/blog/rss/",
        "AWS Architecture Blog": "https://aws.amazon.com/blogs/architecture/feed/",
        "Microsoft Azure Systems": "https://azure.microsoft.com/en-us/blog/feed/",
        "Intel System Performance": "https://community.intel.com/rss/board?board.id=tech-blogs",
        "AMD Instinct & ROCm Blog": "https://rocm.docs.amd.com/en/latest/rss.xml",
        "NVIDIA CUDA & Systems Blog": "https://developer.nvidia.com/blog/category/cuda/feed/",
        "eBPF Official Blog": "https://ebpf.io/feed.xml",
        "Cilium & eBPF Networking": "https://cilium.io/blog/rss.xml",
        "DPDK Fast Packet Processing": "https://www.dpdk.org/feed/",
        "SPDK Storage Performance": "https://spdk.io/feed.xml",
        "IO_uring Linux I/O": "https://kernel.dk/rss.xml",
        "LLVM Compiler Blog": "https://blog.llvm.org/feed.xml",
        "GCC Compiler News": "https://gcc.gnu.org/rss.xml",
        "Rust Compiler & Performance": "https://blog.rust-lang.org/feed.xml",
        "Golang Performance Blog": "https://go.dev/blog/feed.atom",
        "Java Performance (OpenJDK)": "https://openjdk.org/feed.xml",
        "Valgrind Performance Tools": "https://valgrind.org/rss.xml",
        "Perf Wiki Linux": "https://perf.wiki.kernel.org/index.php?title=Special:RecentChanges&feed=atom",
        "Systemd Project Releases": "https://github.com/systemd/systemd/releases.atom",
        "Bcachefs Linux Kernel": "https://bcachefs.org/feed.xml",
        "ZFS on Linux": "https://openzfs.github.io/openzfs-docs/feed.xml",
        "XFS Filesystem Kernel": "https://xfs.wiki.kernel.org/index.php?title=Special:RecentChanges&feed=atom",
        "Btrfs Filesystem Kernel": "https://btrfs.wiki.kernel.org/index.php?title=Special:RecentChanges&feed=atom",
        "Linux Security Module (LSM)": "https://kernelsecurity.com/feed/",
        "CNCF Systems & Performance": "https://www.cncf.io/blog/feed/",
        "KubeFlow Systems Blog": "https://www.kubeflow.org/blog/index.xml",
        "Ray Project Systems": "https://www.ray.io/blog/rss.xml",
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

def fetch_single_feed(source_name, feed_url, category, max_items=1):
    """单源抓取函数（供多线程并发调用）"""
    try:
        feed = feedparser.parse(feed_url, response_headers={'User-Agent': 'Mozilla/5.0'})
        fetched_items = []
        count = 0
        for entry in feed.entries:
            if count >= max_items:
                break
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

def fetch_all_50_feeds():
    """并发并行抓取 150 个顶级 RSS 订阅点"""
    print("1. 正在通过多线程并发并行拉取 3 大模块 Top 150 全球数据源...")
    raw_articles = []
    
    # 建立多线程池，并发 30 个线程，极速完成 150 个源的抓取
    with ThreadPoolExecutor(max_workers=30) as executor:
        future_to_source = {}
        for category, feeds in MODULE_FEEDS.items():
            for source_name, feed_url in feeds.items():
                future = executor.submit(fetch_single_feed, source_name, feed_url, category, max_items=1)
                future_to_source[future] = source_name

        for future in as_completed(future_to_source):
            items = future.result()
            if items:
                raw_articles.extend(items)

    if not raw_articles:
        print("❌ 未抓取到任何真实新闻，终止程序。")
        sys.exit(1)

    print(f"✅ 成功从全球 Top 150 权威源中并发抓取并提炼出 {len(raw_articles)} 条最新资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报与音频朗读脚本
# ---------------------------------------------------------------------------
def generate_briefing_and_audio_script():
    real_news_context = fetch_all_50_feeds()

    print("2. 正在通过 DeepSeek 严格基于真实多源上下文生成简报与播客脚本...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY！")
        sys.exit(1)

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    now = datetime.now()
    exact_iso_time = now.strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位极度严谨的系统与硬件架构师兼科技编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】（覆盖 150 个全球 Top 级别的 LLM Infra、体系结构半导体、Linux Kernel 与最新 ArXiv 预印本），整理一份【PerfPulse 每日技术简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 核心防幻觉与事实审判法则（CRITICAL RULES）：
1. **客观语气与进展限定**：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. **识别第三方/民间项目与官方发布**：对于民间第三方开源项目或非官方评测，必须明确标注“第三方社区/个人观点，非厂商官方发布”。
3. **多媒体与论文数据还原**：如果数据来自 ArXiv 论文、YouTube 视频或社区讨论，请客观提炼其核心研究论点或争议点，并附带原链接。
4. **严格数据源对齐**：绝不凭空臆造未出现的性能数据、代码片段或链接。

---

### 格式与排版规范：
- 全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。
- 代码片段必须包裹在标准 Markdown 围栏代码块中（```bash 或 ```cpp）。
- **静默跳过法则**：若某个领域在今日抓取数据中完全没有对应资讯，请直接静默忽略该板块标题，绝对不要输出“无直接相关数据”或“无相关内容”等废话。

---

### 输出结构（输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
用客观严谨的一句话总结真实发生的最新发布/论文。

### 芯片与 LLM 引擎收益
用客观严谨的一句话总结真实芯片或 AI 系统动态。

### Kernel 与编译调优干货
用客观严谨的一句话总结真实 Linux Kernel 或系统调优动态。

---

## 今日深度剖析 (Today's Deep Dive)
挑选上述数据中最具架构深度或讨论度最高的一条新闻/论文/视频，进行客观专业的深度分析（200-300 字）。分清“实验/评测观点”与“生产级落地”的界限。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)
根据真实上下文整理（若无相关数据则直接静默跳过此标题）。

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)
根据真实上下文整理（包含半导体、晶圆与架构新闻，若有第三方项目需明确标注）。

---

## 系统性能调优与 Kernel (Kernel & Performance)
根据真实上下文整理 Linux Kernel、OS 与编译调优动态。

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)
根据真实上下文整理，附原始链接。
"""

    try:
        briefing_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的技术新闻核查编辑。你的任务是基于提供的 150 个多源上下文提炼信息，绝不夸大事实，没有数据的板块直接跳过。"},
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
请将以下技术简报转换为一段适合 2-3 分钟口语化播客朗读的文本脚本。

要求：
1. 语言通俗自然、适合听觉吸收，去除所有 Markdown 格式符号（如 `#`、`*`、`[链接]` 等）。
2. 开头问好：“大家好，欢迎收听 PerfPulse 每日架构听力解读。”
3. 重点阐述 30 秒极速看点和今日深度剖析的内容。
4. 保持客观严谨，严禁夸大或编造内容。
5. 控制在 400-600 字之间。

=== 简报内容 ===
{md_content}
"""
        audio_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一位专业的科技播客主持人，擅长将硬核技术与多媒体资讯转换为自然流畅的口语表达。"},
                {"role": "user", "content": audio_script_prompt}
            ],
            temperature=0.2,
            stream=False
        )
        audio_script = audio_response.choices[0].message.content.strip()

        print("✅ 多源简报文字与播客脚本生成成功！")
        return md_content.strip(), audio_script
    except Exception as e:
        print(f"❌ DeepSeek 生成失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3. Edge-TTS 异步音频合成
# ---------------------------------------------------------------------------
async def generate_audio_async(text, output_mp3_path="perf_pulse_podcast.mp3"):
    print(f"3. 正在合成 3 分钟播客 MP3 音频文件 ({output_mp3_path})...")
    voice = "zh-CN-YunxiNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_mp3_path)
    print("✅ MP3 音频文件合成完成！")

def create_podcast_audio(script_text, output_file="perf_pulse_podcast.mp3"):
    asyncio.run(generate_audio_async(script_text, output_file))


# ---------------------------------------------------------------------------
# 4. 邮件渲染与发送
# ---------------------------------------------------------------------------
def send_email(subject, md_content, audio_script, mp3_path="perf_pulse_podcast.mp3"):
    print("4. 正在渲染适配公众号与邮件样式的 HTML 邮件...")

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

    audio_header_html = f"""
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #6366f1; padding: 16px; border-radius: 6px; margin-bottom: 24px;">
      <div style="font-weight: bold; font-size: 15px; color: #0f172a; margin-bottom: 8px;">
        🎧 PerfPulse 3分钟音频架构解读
      </div>
      <div style="font-size: 13px; color: #475569; line-height: 1.6; margin-bottom: 10px;">
        {audio_script[:120]}...
      </div>
      <div style="font-size: 12px; color: #6366f1; font-weight: 500;">
        💡 提示：今日音频文件（{mp3_path}）已自动合成并作为邮件附件随信附带，也可在 Github Releases / 播客端播放。
      </div>
    </div>
    """

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
      <h1>⚡ PerfPulse 每日技术与架构简报</h1>
      <div class="subtitle">发布日期：{today_date} | 真实硬件、体系结构与 Linux Kernel 严谨跟踪</div>
    </div>
    <div class="content">
      {audio_header_html}
      {raw_html}
    </div>
    <div class="footer">
      基于 Top 150 全球数据源 & DeepSeek 零幻觉模式构建
    </div>
  </div>
</body>
</html>
"""

    print("5. 正在进行 CSS 内联化转换...")
    inlined_html = transform(styled_html)

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = f"{subject} ({today_date})"

    message.attach(MIMEText(inlined_html, "html", "utf-8"))

    if os.path.exists(mp3_path):
        try:
            with open(mp3_path, "rb") as f:
                audio_data = f.read()
            audio_attachment = MIMEText(audio_data, "base64", "utf-8")
            audio_attachment["Content-Type"] = "audio/mpeg"
            audio_attachment["Content-Disposition"] = f'attachment; filename="{os.path.basename(mp3_path)}"'
            message.attach(audio_attachment)
            print("✅ 已成功添加 MP3 音频为邮件附件！")
        except Exception as e:
            print(f"⚠️ 添加音频附件失败: {e}")

    try:
        if EMAIL_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20)
            server.starttls()

        server.login(sender, EMAIL_PASSWORD.strip())
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("🎉 简报正文与 MP3 播客附件已成功发送！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主流程入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    md_content, audio_script = generate_briefing_and_audio_script()
    mp3_file = "perf_pulse_podcast.mp3"
    create_podcast_audio(audio_script, mp3_file)
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", md_content, audio_script, mp3_file)
