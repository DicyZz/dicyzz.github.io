# 四份周报 flow（AIFrontier / ChinaTech / FinFrontier / PerfPulse）

每周一自动跑，用 RSS + 官方接口抓取各自领域的动态，交给 DeepSeek 提炼成中文简报，
发到邮箱（同时把正文备份到 `output/`、原始条目清单作为附件）。

| Flow | 触发（北京时间） | 领域（只放这个方向的数据源） |
| --- | --- | --- |
| AIFrontier | 周一 10:00 | AI 模型 / Agent / 多模态：OpenAI、Google、Meta、NVIDIA、HF、arXiv cs.LG/CL/AI/CV… |
| ChinaTech | 周一 12:00 | 国内科技公司与产业：IT之家、爱范儿、极客公园、钛媒体、量子位、雷峰网、OSCHINA、InfoQ 中文 + 新浪滚动 / 36氪热榜（JSON） |
| FinFrontier | 周一 11:00 | 金融 / 量化 / 市场：CNBC、MarketWatch、FT、The Economist、美联储、Bloomberg、arXiv q-fin、Quantocracy、QuantPedia、Alpha Architect、CoinDesk… |
| PerfPulse | 周一 09:00 | 硬件 / 微架构 / 系统 / HPC：Phoronix、LWN、kernel.org、SemiEngineering、EE Times、IEEE Spectrum Chips、Chips and Cheese、Tom's Hardware、TechPowerUp、RISC-V、arXiv cs.AR/DC/PF… |

## 代码结构

四个脚本（`scripts/*_push.py`）现在只保留**自己的东西**：

1. `MODULE_FEEDS`：本 flow 的专属数据源（分类 → 源名 → feed 地址）
2. `CATEGORY_MAX_ITEMS`：各板块每源取几条（差异化，避免某一方向淹没简报）
3. 提示词：决定简报的口吻与结构（每份都不一样）
4. 品牌文案：标题 / 副标题 / 邮件主题

抓取、清洗、去重、渲染、发送全部走公共实现 `scripts/digest_common.py`：

```
并发抓取（浏览器级请求头 + 单源超时 + 失败重试）
  → 时间过滤（7 天，按 UTC 解析）
  → 无发布时间条目限量（每源最多 1 条并标注「未知」）
  → 跨源去重（链接去参数 + 标题标准化）
  → 组装给模型的上下文（标题/链接/发布时间/摘要）
  → 邮件 HTML + 纯文本 + 原始条目清单附件
```

## 常用操作

```bash
# 源体检：逐个探测所有源，列出 HTTP 错误 / 空 feed / 60 天无内容
python scripts/digest_common.py --check                 # 全部四个 flow
python scripts/digest_common.py --check perfpulse       # 只看某一个

# 本地跑某个 flow（需要 DEEPSEEK_API_KEY / EMAIL_* 才会真正发信）
python scripts/perfpulse_push.py

# 单测（含公共模块与 workflow 自检）
python -m unittest discover -s tests -v
```

## 加一个新源

直接往对应 flow 的 `MODULE_FEEDS` 里加一行，然后跑一次源体检确认它可用：

```bash
python scripts/digest_common.py --check aifrontier
```

注意：**只往对应领域加**。想让某条源进两个 flow，就在两个文件里各写一次（这是有意的，
因为两个 flow 的筛选与提示词不同）。

## 本次优化做了什么（相对重构前）

| 问题 | 之前 | 现在 |
| --- | --- | --- |
| 请求头太素被 Cloudflare 拦 | 只带 User-Agent，量子位等源稳定 403 | 补 Accept / Accept-Language 浏览器头 + 失败重试一次 |
| 时间过滤时区错误 | `time.mktime` 把 UTC 当本机时区（UTC+8 会偏 8 小时） | `calendar.timegm` 严格按 UTC |
| 无发布时间的条目 | 永远通过 7 天过滤 → 旧文每周都混进「本周」 | 每源最多收 1 条并标注「发布时间: 未知」 |
| 跨源重复 | 完全没有去重，同一篇被多源收录就重复出现 | 链接去参数 + 标题标准化后去重 |
| DeepSeek 不可用时 | `sys.exit(1)`，当周直接没有邮件 | 改为照常发信，正文换成原始条目清单 |
| 邮件 | 只有 HTML | HTML + 纯文本 + 原始条目清单附件 |
| 失效源 | 12 个源已死但仍每周请求（Papers With Code 已关站等） | 逐个探测后按领域替换为可用源，失败源 0（量子位偶发限流除外） |
