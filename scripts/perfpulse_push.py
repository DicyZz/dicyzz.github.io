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
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 各模块 Top 顶级数据源全量配置（按简报四板块组织）
# ---------------------------------------------------------------------------
MODULE_FEEDS = {
    # === 新闻与发布 ===
    "News": {
        "Phoronix Processors": "https://www.phoronix.com/rss.php",
        "LWN.net (Linux Kernel Direct)": "https://lwn.net/headlines/rss",
        "Kernel.org Releases": "https://www.kernel.org/feeds/kdist.xml",
        "SemiEngineering": "https://semiengineering.com/feed/",
        "The Next Platform": "https://www.nextplatform.com/feed/",
        "EE Times Global": "https://www.eetimes.com/feed/",
        "IEEE Spectrum Chips": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "ServeTheHome (STH)": "https://www.servethehome.com/feed/",
        "HPC Wire": "https://www.hpcwire.com/feed/",
        "LLVM Weekly": "https://llvmweekly.org/rss.xml",
        "OpenAI Research": "https://openai.com/news/rss.xml",
        "Google AI Blog": "https://research.google/blog/rss/",
    },

    # === 深度文章 / 性能博客 ===
    "Blog_Posts": {
        "Brendan Gregg Performance Blog": "https://www.brendangregg.com/blog/rss.xml",
        "Easyperf (Denis Bakhvalov)": "https://easyperf.net/feed.xml",
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
        "Daniel Lemire": "https://lemire.me/blog/feed/",
        "MaskRay (compiler/linker)": "https://maskray.me/blog/atom.xml",
        "Johnny's Software Lab": "https://johnysswlab.com/feed/",
        "Fabian Giesen (ryg)": "https://fgiesen.wordpress.com/feed/",
        "Herb Sutter": "https://herbsutter.com/feed/",
        "Real World Tech": "https://www.realworldtech.com/feed/",
        "Travis Downs (perf analysis)": "https://travisdowns.github.io/feed.xml",
        "Jeff Preshing (concurrency/perf)": "https://preshing.com/feed/",
        "John Regehr (compilers)": "https://blog.regehr.org/feed/",
        "Paul E. McKenney (kernel/RCU)": "https://paulmck.livejournal.com/data/rss",
        "High Scalability": "https://highscalability.com/feed/",
        "SemiAnalysis (chips/inference)": "https://semianalysis.com/feed/",
        "Matt Godbolt (compilers/xania)": "https://xania.org/feed.atom",
        "The Chip Letter (Substack)": "https://thechipletter.substack.com/feed",
        "Lobsters (performance)": "https://lobste.rs/t/performance.rss",
        "Lobsters (compilers)": "https://lobste.rs/t/compilers.rss",
        "Glenn Klockwood (HPC/storage)": "https://blog.glennklockwood.com/feeds/posts/default",
        "Scientific Computing in Rust": "https://scientificcomputing.rs/monthly/rss.xml",
        "Cloudflare Tech Blog": "https://blog.cloudflare.com/rss/",
        "Netflix Tech Blog": "https://netflixtechblog.com/feed",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Anyscale / Ray Blog": "https://www.anyscale.com/blog/rss.xml",
        "DeepSpeed Blog": "https://www.deepspeed.ai/feed.xml",
        "NVIDIA Developer AI Blog": "https://developer.nvidia.com/blog/category/ai-deep-learning/feed/",
        "NVIDIA CUDA & Systems Blog": "https://developer.nvidia.com/blog/category/cuda/feed/",
        "Rust Compiler & Performance": "https://blog.rust-lang.org/feed.xml",
        "ARM Technical Articles": "https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/rss",
        "SiFive RISC-V Blog": "https://www.sifive.com/blog/rss.xml",
    },

    # === 论文 ===
    "Research_Papers": {
        "ArXiv Machine Learning (cs.LG)": "http://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Computation and Language (cs.CL)": "http://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Artificial Intelligence (cs.AI)": "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/api/query?search_query=cat:cs.AR&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/api/query?search_query=cat:cs.DC&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Performance Evaluation (cs.PF)": "http://export.arxiv.org/api/query?search_query=cat:cs.PF&sortBy=submittedDate&sortOrder=descending&max_results=10",
    },

    # === 其他资料（发布、工具、聚合） ===
    "Other_Materials": {
        "vLLM GitHub Releases": "https://github.com/vllm-project/vllm/releases.atom",
        "TensorRT-LLM GitHub Releases": "https://github.com/NVIDIA/TensorRT-LLM/releases.atom",
        "llama.cpp GitHub Releases": "https://github.com/ggml-org/llama.cpp/releases.atom",
        "NVIDIA TensorRT Releases": "https://github.com/NVIDIA/TensorRT/releases.atom",
        "Hacker News Systems Tech": "https://news.ycombinator.com/rss",
    }
}

def clean_html_summary(html_text):
    """清洗 HTML 标签，提炼纯文本"""
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text[:400]

def is_recent_entry(entry, max_hours=168):
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

def fetch_single_feed(source_name, feed_url, category, max_items=6):
    """单源抓取函数（增加超时与 7 天时间过滤）"""
    if not feed_url.startswith("http"):
        feed_url = "https://" + feed_url

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PerfPulseBot/1.0'}
    
    try:
        resp = requests.get(feed_url, headers=headers, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ 源抓取失败 [{source_name}] 状态码 {resp.status_code}")
            return []
        
        feed = feedparser.parse(resp.content)
        fetched_items = []
        count = 0

        for entry in feed.entries:
            if not is_recent_entry(entry, max_hours=168):
                continue

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
    except Exception as e:
        print(f"⚠️ 源抓取异常 [{source_name}] {type(e).__name__}: {e}")
        return []

def fetch_all_feeds():
    """并发并行抓取全量 RSS 订阅点"""
    print("1. 正在通过并发线程池拉取全球技术数据源（含超时控制与 7 天过滤）...")
    raw_articles = []
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        future_to_source = {}
        for category, feeds in MODULE_FEEDS.items():
            for source_name, feed_url in feeds.items():
                future = executor.submit(fetch_single_feed, source_name, feed_url, category, max_items=6)
                future_to_source[future] = source_name

        for future in as_completed(future_to_source):
            items = future.result()
            if items:
                raw_articles.extend(items)

    if not raw_articles:
        print("⚠️ 未抓取到 7 天内的新资讯，将使用保底逻辑。")
        return "本周暂无 7 天内的新动态更新。"

    print(f"✅ 成功从权威源中抓取并筛选出 {len(raw_articles)} 条最新资讯！")
    return "\n---\n".join(raw_articles)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报
# ---------------------------------------------------------------------------
def generate_briefing():
    real_news_context = fetch_all_feeds()

    print("2. 正在通过 DeepSeek 提炼专业技术简报...")
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
基于下方【真实抓取数据上下文】，整理一份【PerfPulse 每周架构与系统性能简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的技术主题（优先提炼以下方向）：
1. **LLM 系统加速**：KV Cache 管理、Speculative Decoding、PagedAttention、Quantization (FP8/INT4/AWQ)、FlashAttention/FlashDecoding、vLLM/TensorRT-LLM 优化、Distributed Training/Inference (Pipeline/Tensor Parallelism)。
2. **CPU/GPU 微架构**：Cache Hierarchy (L1/L2/L3/SLC)、Branch Predictor、Out-of-Order Execution、ROB/Execution Units、Vector/Matrix Extensions (AVX-512, AMX, SVE, Tensor Cores)、Interconnect (NVLink, CXL, PCIe Gen6)。
3. **HPC 与编译优化**：LLVM/MLIR Passes、Loop Transformations (Tiling, Unrolling, Fusion)、Triton/TVM/XLA 代码生成、CUDA/ROCm/SYCL 内核优化、MPI/NCCL 通信重叠。
4. **Linux Kernel & Performance**：eBPF/XDP、io_uring、Memory Management (THP, NUMA balancing, ZSWAP)、Scheduler (EEVDF)、Filesystem/Block Layer (bcachefs, NVMe-oF)、perf/BPF 性能分析。

### 性能相关性强过滤（最高优先级，逐条判定）：
本简报只收录「与性能提升直接相关」的内容，即必须至少满足以下之一：
- 包含具体的性能收益数据（吞吐、延迟、IPC、带宽、功耗、编译/训练/推理耗时等）；
- 描述可落地的优化技术或机制（Cache/流水线/并行化/量化/KV Cache/调度/编译器 Pass/内核调优等）；
- 是针对上述方向的论文、开源发布或 benchmark。

凡属于以下类型，一律整条剔除，不得收录：
- 市场预测、营收、资本开支、数据中心需求等商业话题（如 Dell/HPE 预测）；
- 政策建议、国家战略、生态演讲、行业报告等非技术内容；
- 仅有功能发布/换壳升级、无性能数据的普通产品发布（如交换机、媒体服务器）；
- 与性能无关的 bugfix、AI 治理、合规类新闻。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. **区分民间与官方**：对于民间第三方开源项目或非官方评测，必须明确标注“第三方社区/个人观点”。
3. **静默跳过法则**：若某个领域在今日抓取数据中完全没有对应资讯，直接静默忽略该板块标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[标题](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、PR 编号或开发者姓名。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（参考 Easyperf Newsletter 的 digest 风格，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题、不加项目符号，直接一行自然句）：
"本期看点：……，以及更多。" 用 3-4 个短语点出本期最值得关注的点。

随后按「内容类型」分区，只保留真实上下文中确实有内容的板块，缺内容的板块整块标题静默删除：

## 新闻与发布 (News)
## 深度文章 (Blog Posts)
## 论文 (Research Papers)
## 其他资料 (Other Materials)

每条统一格式（正文段落，禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「这是什么 → 核心优化机制/技术点 → 量化性能收益（尽量写具体数字，如 x 倍、百分比、带宽/延迟数值）→ 局限或适用条件（如有）」，末尾统一用 `[原文](原始链接)` 收尾。

链接规范（非常重要）：
- 链接文字一律写固定词 `原文`，**严禁用文章标题作为链接文字**。标题常含 `[`、`]`、`(`、`"` 等特殊字符，会破坏 Markdown 解析。
- 若需点明条目标题，在描述正文中用普通文字自然写出即可，不要加粗、不要做成链接。
- 每个板块标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

如为视频/工具类，链接文字可写 `原文` 或 `视频` / `GitHub` 等不含特殊字符的固定词。

风格要求：
- 每条都必须是「性能干货」，宁可少而精，不要堆砌无关条目。
- 可附一句克制的编辑点评，但必须基于上下文、客观中立，禁止编造观点。
- 论文/第三方评测必须标注「第三方/社区」属性；未落地内容不得写成「重大突破」。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
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

        print("✅ 多源简报文字生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"❌ DeepSeek 生成失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3. 邮件渲染与发送 (已移除 MP3 附件逻辑)
# ---------------------------------------------------------------------------
def save_briefing_backup(md_content, today_date):
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"perfpulse_{today_date}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"💾 简报 Markdown 已备份：{out_path}")
    return out_path


def send_email(subject, md_content):
    print("3. 正在渲染适配邮件样式的 HTML 正文...")

    today_date = datetime.now().strftime("%Y-%m-%d")
    save_briefing_backup(md_content, today_date)

    sender = EMAIL_SENDER.strip() if EMAIL_SENDER else ""
    receiver = EMAIL_RECEIVER.strip() if EMAIL_RECEIVER else sender

    if not sender or not EMAIL_PASSWORD:
        print("❌ 错误：缺少邮箱环境变量配置！")
        sys.exit(1)

    raw_html = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'codehilite', 'nl2br', 'toc']
    )

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
      <h1>⚡ PerfPulse 每周微架构、系统与 HPC 简报</h1>
      <div class="subtitle">发布日期：{today_date} | 真实硬件、LLM 加速与 Linux Kernel 严谨跟踪</div>
    </div>
    <div class="content">
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
        print("🎉 简报正文已成功发送至邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主流程入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    md_content = generate_briefing()
    send_email("【PerfPulse】每周硬件、微架构与 LLM 性能简报", md_content)
