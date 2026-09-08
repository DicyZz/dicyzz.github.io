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

if __name__ == "__main__":
    content = generate_briefing()
    send_email("【PerfPulse】每日硬件、系统与 LLM 性能简报", content)
