# 公众号文章 → Notion 个人知识库（批量导入）

把一组微信公众号文章抓取下来，保留正文与原始图片，自动分类、去重后写入 Notion
数据库，做成可全文检索的个人知识库。

## 能力

- 抓取 `mp.weixin.qq.com/s/...` 文章：标题、公众号、发布时间、正文、图片
- 图片按原始格式下载到本地归档（`data/wechat_images/`），Notion 里用原始图片外链展示
- 自动分类（规则关键词，可后续接 DeepSeek）
- 去重：URL 去重 + 内容哈希 + 标题逐字去重（不误合并「Part1/Part2」这类系列文章）
- 推送到 Notion：自动读取数据库 schema，适配标题/分类/公众号/链接等属性

## 使用

```bash
# 1) 把要导入的文章 URL 逐行写进 data/wechat_urls.txt

# 2) 抓取 + 解析 + 下载图片（生成 data/wechat_articles_raw.json）
python scripts/wechat_notion.py fetch

# 3) 去重 + 分类（生成 data/wechat_articles.json）
python scripts/wechat_notion.py dedupe

# 4) 推送到 Notion（需要集成令牌 + 数据库 id）
export NOTION_API_SECRET=ntn_...
python scripts/wechat_notion.py push --database-id <数据库id>
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

## 分类规则

`scripts/wechat_notion.py` 里的 `CATEGORY_RULES` 用标题关键词分类，当前分类：

- AI芯片与算力、大模型与推理、存储与互联、封装与材料、计算机体系结构、半导体与芯片

分类会写入 Notion 的 `select` 类型属性（若数据库里没有对应 select 属性，则只写进
页面顶部的元信息 callout，不影响导入）。想换分类/新增分类，直接改 `CATEGORY_RULES`
即可；想要更精准，可接 DeepSeek（见 wechat_kb.py 的 `classify_articles`）。

## 说明

- 抓取走公开网页，仅供个人学习研究，请勿对外发布或商用，版权归原作者所有。
- 微信对高频访问有反爬；脚本内置重试，个别文章可能偶发返回「环境异常」，重新跑
  `fetch` 即可补齐（图片已缓存，会复用）。
- 视频类文章（正文为视频）会以「【视频课程】」占位并保留原文链接，视频本身不进 Notion。
