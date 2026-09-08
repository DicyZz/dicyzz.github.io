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

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

def generate_briefing():
    print("1. 正在通过 DeepSeek 生成 PerfPulse 技术简报...")
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
今天是 {today_str}。请生成一份专业的【PerfPulse 每日技术简报】。

---

### 强制对标来源领域：

#### LLM 系统与 AI Infra
vLLM / SGLang GitHub & Blog, PyTorch Engineering Blog, NVIDIA Technical Blog, Tri Dao (FlashAttention) 动态, ArXiv (`cs.AR`, `cs.DC`, `cs.CL`), SemiAnalysis.
Understanding AI, TechCrunch AI, Ars Technica.

---

#### 体系结构与芯片/IP 微架构
Chips and Cheese, ServeTheHome, RISC-V International, ACM SIGARCH, IEEE Micro.
SemiEngineering, Hardware Times, WikiChip ARM, AnandTech, Design & Reuse, EET China, Doulos, Tom's Hardware, ASCII.jp.

---

#### HPC 与编译优化
LLVM Discourse/Commits, GCC Mailing List, MLIR News, TVM Discourse, OneAPI / ROCm Release Notes.

---

#### Linux 内核与系统性能调优
LWN.net, LKML, Brendan Gregg's Blog, ebpf.io, Cloudflare / Netflix TechBlog.
Phoronix, It's FOSS News, Slashdot, Alltop Linux, Narkive, DZone, Packet Storm Security.

---

### 多媒体与交互元素插入要求：

#### 科技图表
首图：![Banner](https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1000&q=80)

芯片微架构插图：![Microarchitecture](https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1000&q=80)

系统调优插图：![System Performance](https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1000&q=80)

---

#### 音频/播客解读卡片
在“今日深度剖析”之后按以下格式插入：
> 🎙️ **PerfPulse 3分钟音频架构解读**  
> 🎧 **主题**：[填写今日深度剖析的核心主题]  
> 💡 *提示：点击上方播放按钮，在通勤路上听完今日最核心的微架构瓶颈突破逻辑。*

---

#### 视频/论文演示卡片
若有视频/ Talk，按以下格式插入：
> 🎬 **视频演示 / Talk 推荐**：  
> 🔗 **视频标题**：[视频/讲座名称]  
> 📌 **核心看点**：[1句话说明视频展示的 benchmark 跑分或 CPU/GPU 内存火焰图] [查看视频/演示链接](链接地址)

---

### 排版与输出约束条件（非常重要）：
1. **绝对禁止符号**：严禁使用任何项目符号（如 `-`、`*`、`+`）或任何数字序号（如 `1.`、`2.`、`(1)`）。
2. **板块扩充规则**：除 TL;DR 外，其余每个核心板块（LLM系统、体系结构、HPC编译、系统调优、论文/开源）必须精确包含 **3 个** 独立的技术看点。
3. **三点排版规则**：这 3 个技术看点必须**分别直接将看点主题提炼并升级为独立子标题**（使用 `###` 或 `####`），下方紧跟具体技术细节与来源链接，板块与看点之间保持良好的间距。

---

### 输出结构要求：
严格按以下结构输出 Markdown 内容（切勿在全局包裹 ```markdown 标记）：

## 30 秒极速看点 (TL;DR)

### 突破/论文/开源发布
一句话总结今日最震撼的突破/论文/开源发布。

### 芯片与 LLM 引擎收益
一句话总结芯片或 LLM 引擎的核心性能收益。

### Kernel 与编译调优干货
一句话总结 Kernel 或编译调优干货。

---

## 今日深度剖析 (Today's Deep Dive)
挑选 1 个最具有架构影响力的技术突破/论文/开源重构，进行 300 字左右的架构级深度分析（微架构影响、Bottleneck 突破逻辑与性能收益）。

---

## LLM 系统与推理/训练加速 (LLM Infra & Acceleration)

### [技术看点一短标题]
具体技术分析、具体参数、性能数据，末尾带上 [来源/GitHub/ArXiv] 链接。

### [技术看点二短标题]
具体技术分析、具体参数、性能数据，末尾带上 [来源/GitHub/ArXiv] 链接。

### [技术看点三短标题]
具体技术分析、具体参数、性能数据，末尾带上 [来源/GitHub/ArXiv] 链接。

---

## 体系结构与芯片动态 (Silicon & Microarchitecture)

### [技术看点一短标题]
具体技术分析与指令集/微架构细节，末尾带上 [来源] 链接。

### [技术看点二短标题]
具体技术分析与指令集/微架构细节，末尾带上 [来源] 链接。

### [技术看点三短标题]
具体技术分析与指令集/微架构细节，末尾带上 [来源] 链接。

---

## 高性能计算与编译优化 (HPC & Compilers)

### [技术看点一短标题]
LLVM/GCC/Pass 优化与编译 Flag 分析，末尾带上 [来源] 链接。

### [技术看点二短标题]
LLVM/GCC/Pass 优化与编译 Flag 分析，末尾带上 [来源] 链接。

### [技术看点三短标题]
LLVM/GCC/Pass 优化与编译 Flag 分析，末尾带上 [来源] 链接。

---

## 系统性能调优与 Kernel (Kernel & Performance)

### [技术看点一短标题]
Perf/eBPF 诊断、Kernel Patch 与性能调优细节，末尾带上 [来源] 链接。

### [技术看点二短标题]
Perf/eBPF 诊断、Kernel Patch 与性能调优细节，末尾带上 [来源] 链接。

### [技术看点三短标题]
Perf/eBPF 诊断、Kernel Patch 与性能调优细节，末尾带上 [来源] 链接。

---

## 必读前沿论文与开源仓库 (ArXiv & Open Source)

### [项目/论文一短标题]
核心创新点、性能 Benchmark、开源地址或 ArXiv 链接。

### [项目/论文二短标题]
核心创新点、性能 Benchmark、开源地址或 ArXiv 链接。

### [项目/论文三短标题]
核心创新点、性能 Benchmark、开源地址或 ArXiv 链接。

---

### 代码与干货要求：
代码与命令包裹：所有 perf 诊断脚本、vLLM 参数、LLVM 编译 Flag 和代码片段，必须明确包裹在 Markdown 代码块中。

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
        
        content = response.choices[0].message.content.strip()

        if content.startswith("```markdown"):
            content = content[11:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        print("✅ 最新 PerfPulse 简报生成成功！")
        return content.strip()
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    *, *:before, *:after {{
      box-sizing: border-box !important;
    }}
    body {{
      font-family: -apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif;
      background-color: #ffffff;
      color: #24292e;
      margin: 0;
      padding: 0;
      width: 100% !important;
      -webkit-text-size-adjust: 100%;
    }}
    .container {{
      width: 100% !important;
      max-width: 100% !important;
      margin: 0 auto;
      background: #ffffff;
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 16px;
      border-bottom: 3px solid #6366f1;
    }}
    .header h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: 0.5px;
      line-height: 1.4;
    }}
    .header .subtitle {{
      margin-top: 10px;
      font-size: 12px;
      color: #a5b4fc;
      line-height: 1.5;
    }}
    .content {{
      padding: 16px 12px;
      font-size: 15px;
      line-height: 1.75;
      color: #334155;
      word-break: break-word;
    }}
    h2 {{
      color: #0f172a;
      font-size: 17px;
      background: #f1f5f9;
      border-left: 4px solid #4f46e5;
      padding: 8px 12px;
      border-radius: 0 4px 4px 0;
      margin-top: 36px;
      margin-bottom: 20px;
    }}
    h3 {{
      font-size: 16px;
      color: #0f172a;
      margin-top: 28px;
      margin-bottom: 12px;
      font-weight: 600;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 6px;
    }}
    h4 {{
      font-size: 15px;
      color: #1e293b;
      margin-top: 20px;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    p {{
      margin: 12px 0 16px 0;
      color: #334155;
      word-wrap: break-word;
      line-height: 1.75;
      text-align: justify;
    }}
    /* ------------------------------------------------------------------- */
    /* 专为公众号与邮件优化的图片样式 */
    /* ------------------------------------------------------------------- */
    img {{
      display: block !important;
      max-width: 100% !important;
      height: auto !important;
      margin: 20px auto !important;
      border-radius: 8px !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
      border: 1px solid #e2e8f0 !important;
    }}
    /* 恢复原生超链接外观，强调紫蓝色极客科技感 */
    a {{
      color: #4f46e5 !important;
      text-decoration: none !important;
      font-weight: 500 !important;
      border-bottom: 1px dashed #6366f1 !important;
      word-break: break-all !important;
    }}
    code {{
      background-color: #f1f5f9;
      color: #4f46e5;
      padding: 2px 5px;
      border-radius: 4px;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 88%;
      font-weight: 600;
    }}
    pre {{
      background-color: #0f172a;
      color: #f8fafc;
      padding: 14px;
      border-radius: 6px;
      overflow-x: auto;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      line-height: 1.6;
      margin: 16px 0;
      border: 1px solid #1e293b;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    pre code {{
      background-color: transparent;
      color: #f8fafc;
      padding: 0;
      font-weight: normal;
    }}
    blockquote {{
      margin: 20px 0;
      padding: 12px 14px;
      color: #1e293b;
      border-left: 4px solid #4f46e5;
      background-color: #f8fafc;
      border-radius: 0 6px 6px 0;
      font-size: 14px;
    }}
    blockquote p {{
      margin: 4px 0;
      color: #334155;
    }}
    hr {{
      border: none;
      border-top: 1px dashed #cbd5e1;
      margin: 32px 0;
    }}
    .footer {{
      background-color: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 20px 12px;
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

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
