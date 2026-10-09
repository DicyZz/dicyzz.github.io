# 公众号文章 → Notion 个人知识库（批量导入）

把一组微信公众号文章抓取下来，保留正文与原始图片，自动分类、去重后写入 Notion
数据库，做成可全文检索的个人知识库。

## 能力

- 抓取 `mp.weixin.qq.com/s/...` 文章：标题、公众号、发布时间、正文、图片
- 图片按原始格式下载到本地归档（`data/wechat_images/`），Notion 里用原始图片外链展示
- 学习导向三层结构：**分类**（一级领域）→ **系列**（多讲连载）→ **序号**（讲次排序）
- 自动分类 + 自动识别连载系列（CCIX/CXL/PCIe/UCIe/CS61C/CS336…）并填讲次
- 去重：URL 去重 + 内容哈希 + 标题逐字去重（不误合并「Part1/Part2」「L20/L21」）
- 推送到 Notion：自动读取数据库 schema，适配标题/分类/公众号/系列/序号/链接等属性

## 使用

```bash
# 1) 把要导入的文章 URL 逐行写进 data/wechat_urls.txt

# 2) 抓取 + 解析 + 下载图片
python scripts/wechat_notion.py fetch --urls-file data/wechat_urls.txt

# 3) 去重 + 分类（生成 data/wechat_articles.json）
python scripts/wechat_notion.py dedupe

# 4) 推送到 Notion（需要集成令牌 + 数据库 id）
export NOTION_API_SECRET=ntn_...
python scripts/wechat_notion.py push --database-id <id> --only-new

# 5) 重整理已有页面（统一分类/系列/序号/标签）
python scripts/wechat_notion.py reorg --database-id <id>

# 6) 为每个「系列」生成一篇通俗导览（写回 Notion，序号=0，排在系列最前）
python scripts/notion_series_summary.py --database-id <id> [--dry-run]
```

推送前可以先 `--dry-run` 预览：

```bash
python scripts/wechat_notion.py push --database-id <id> --dry-run
```

## 准备 Notion 集成

1. 打开 https://www.notion.so/my-integrations → New integration → 复制
   「Internal Integration Secret」（`ntn_` 或 `secret_` 开头）。
2. 打开目标数据库页面，右上角 `...` → `Connections`（连接）→ 添加你刚建的集成，
   授予该数据库的读写权限。
3. 数据库 id 就是数据库 URL 里的那串 32 位 id，例如
   `https://app.notion.com/p/<32位id>?v=...` 里的 `<32位id>`。

## 学习导向的分类体系

`scripts/wechat_notion.py` 里内置了「分类 + 系列 + 序号」三层结构：

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| 分类 | select | 一级学习领域，共 6 类 |
| 系列 | select | 多讲连载的学习主线（CCIX/CXL/PCIe/UCIe/CS61C/CS336/内存异构分层） |
| 序号 | number | 系列内的讲次，可在 Notion 里按序号升序学习 |
| 标签 | multi_select | 系列名 + 标题提取的技术词，用于跨领域检索 |

**一级分类（6 类）**

- 互连与总线：CCIX、CXL、PCIe、UCIe、NVLink、InfiniBand、AXI、内存池化
- 存储与内存：HBM、DDR、HBF、存算一体、异构分层、MEXT
- AI芯片与算力：SIMD/SIMT、Tensor、脉动阵列、TPU/NPU/ASIC、超节点、训练/推理芯片
- 大模型与推理：vLLM、KV Cache、MoE、Transformer、DeepSeek、世界模型
- 封装与材料：先进封装、载板、基板、CPO、Chiplet、光刻、半导体材料
- 计算机体系结构：CS61C、RISC-V、指令集、数据路径、低功耗、门控时钟

**连载系列（自动识别讲次）**

- CCIX（9 讲）、CXL（11 讲 + Pond 论文）、PCIe（10 讲 + LTR/OBFF）、UCIe（10 讲）
- CS61C·RISC-V（按 L12/L20/L21/L23）、CS336·MoE（Part1/2）、内存异构分层（2 讲）

想调整分类或系列规则，直接改 `CATEGORY_RULES` / `_series_of` / `_tag_terms`。

## 说明

- 抓取走公开网页，仅供个人学习研究，请勿对外发布或商用，版权归原作者所有。
- 微信对高频访问有反爬；脚本内置重试，个别文章可能偶发返回「环境异常」，重新跑
  `fetch` 即可补齐（图片已缓存，会复用）。
- 视频类文章（正文为视频）会以「【视频课程】」占位并保留原文链接，视频本身不进 Notion。
