# 五个简报 flow（PerfPulse / AIFrontier / FinFrontier / GlobalTech / ChipSchool）

每天只跑一个 flow，用 RSS + 官方接口抓取各自领域的动态，交给 DeepSeek 提炼成中文简报，
发到邮箱（同时把正文备份到 `output/`、原始条目清单作为附件）。

| Flow | 领域（只放这个方向的数据源） |
| --- | --- |
| AIFrontier | AI 模型 / Agent / 多模态：OpenAI、Google、Meta、NVIDIA、HF、arXiv cs.LG/CL/AI/CV… |
| ChinaTech（GlobalTech） | 全球科技资讯：The Verge、TechCrunch、Ars Technica、Wired、BBC Tech、IT之家、爱范儿、极客公园、钛媒体、量子位、雷峰网、OSCHINA、少数派 + 新浪滚动 / 36氪热榜（JSON） |
| FinFrontier | 金融 / 量化 / 市场：CNBC、MarketWatch、FT、The Economist、美联储、Bloomberg、arXiv q-fin、Quantocracy、QuantPedia、Alpha Architect、CoinDesk… |
| PerfPulse | 硬件 / 微架构 / 系统 / HPC：Phoronix、LWN、kernel.org、SemiEngineering、EE Times、IEEE Spectrum Chips、Chips and Cheese、Tom's Hardware、TechPowerUp、RISC-V、arXiv cs.AR/DC/PF… |
| ChipSchool | 半导体基础科普系列（15 讲，每讲一个主题）：知识部分讲教科书级共识，每期附 1–2 条真实抓取的芯片新闻做实例解读，每周五自动下一讲 |

> 触发时间（均为北京时间，由本机 Mac mini 触发，一天一个 flow）：
>
> | 星期 | 时间 | Flow |
> | --- | --- | --- |
> | 周一 | 08:00 | PerfPulse |
> | 周二 | 08:00 | AIFrontier |
> | 周三 | 08:00 | FinFrontier |
> | 周四 | 08:00 | GlobalTech（chinatech） |
> | 周五 | 08:00 | ChipSchool |
> | 周六 / 周日 | — | 不安排 |

## 触发方式：本机 launchd（不用 GitHub 定时）

实测本仓库 GitHub Actions 自带的 `schedule` **稳定迟到 4.5–5.5 小时**：

| 计划时间 (UTC) | 实际触发 (UTC) | 延迟 |
| --- | --- | --- |
| Job Monitor 09-21 00:00 | 04:31 | +4h31m |
| Job Monitor 09-20 00:00 | 04:33 | +4h33m |
| PerfPulse 09-21 01:00 | 05:57 | +4h57m |
| AIFrontier 09-21 02:00 | 07:16 | +5h16m |
| FinFrontier 09-21 03:00 | 08:26 | +5h26m |
| ChinaTech 09-21 04:00 | 09:19 | +5h19m |

也就是说「早上 8 点」在 GitHub 上做不到。所以：

- 四个 `*_push.yml` 的 `schedule` 已注释停用（`workflow_dispatch` 保留，手机上仍可手动触发）
- 改由 Mac mini 上的 launchd 定时：**周一至周五 08:00**，每天由 `local_briefings.sh` 按星期几分派当天的那个 flow

```bash
# 一键部署（在 Mac mini 上执行一次：克隆 ~/briefings + 密钥模板 + 安装 LaunchAgent）
bash scripts/setup_local_scheduler.sh

# 手动试跑「今天对应的 flow」（不用等到 08:00）
launchctl kickstart -k "gui/$UID/com.jianzhang.briefings"

# 手动指定某个 flow（不按星期几）
bash scripts/local_briefings.sh perfpulse    # 或 aifrontier / finfrontier / chinatech / chipschool

# 芯片通识课指定讲次 / 预览 / 强制推进（详见 --help）
python scripts/chipschool_push.py --lesson 3
python scripts/chipschool_push.py --dry-run
python scripts/chipschool_push.py --force

# 看日志
tail -f ~/Library/Logs/briefings/$(date +%Y-%m-%d).log

# 暂停 / 恢复
launchctl bootout "gui/$UID/com.jianzhang.briefings"
launchctl bootstrap "gui/$UID" ~/Library/LaunchAgents/com.jianzhang.briefings.plist
```

本机运行需要密钥文件 `~/.config/briefing-secrets.env`（600 权限，不进仓库）：

```bash
DEEPSEEK_API_KEY=sk-...
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=465
EMAIL_SENDER=you@gmail.com
EMAIL_PASSWORD=<Gmail 应用专用密码>
EMAIL_RECEIVER=you@gmail.com
```

没填密钥时定时任务只会在日志里提示「缺少密钥」，不会发信、也不会报错刷屏。
想恢复云端兜底：打开对应 `*_push.yml`，取消 `schedule:` 那两行注释
（注意会与本机定时重复发信）。

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

# 按星期几分派（一天一个 flow；手动指定可传 flow 名）
bash scripts/local_briefings.sh
bash scripts/local_briefings.sh chipschool

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
