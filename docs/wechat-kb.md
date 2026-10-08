# 公众号知识库

把自己关注的微信公众号内容抓取、按分类归档、相似内容合并，生成一个可检索的
Markdown 知识库，并支持持续新增公众号。

## 一句话原理

微信没有开放「导出我关注的公众号文章」的官方接口，直接抓微信客户端既难又容易封号。
这里用 **wewe-rss**（自建服务）走「微信读书」通道，把公众号变成带全文的 RSS/Atom，
再用本仓库的 `scripts/wechat_kb.py` 抓取 → DeepSeek 分类 → 去重合并 → 导出。

```
wewe-rss(Docker)  ──RSS/Atom──▶  wechat_kb.py  ──▶  SQLite  ──▶  knowledge_base/*.md
   ^                                     │
   └── 微信读书扫码登录                 ├─ DeepSeek 打标签 + 摘要
       （添加关注的公众号）              └─ 去重 + 同主题合并
```

## 第一步：装 wewe-rss（Mac mini 上跑一次）

项目：https://github.com/cooderl/wewe-rss

```bash
# Docker（Mac mini 上）
docker run -d --restart=unless-stopped \
  -p 4000:4000 \
  -e AUTH_CODE=你自设的访问密码 \
  -e DATABASE_URL=file:/app/data/wewe-rss.db \
  -v wewe-rss-data:/app/data \
  --name wewe-rss \
  cooderl/wewe-rss:latest
```

然后：

1. 浏览器打开 `http://<mac-mini-ip>:4000`（本机就是 `http://127.0.0.1:4000`），
   输入 `AUTH_CODE`。
2. 用 **微信读书** 扫码登录。
3. 在页面里「添加公众号」：把你关注的公众号逐个加进去；新版 wewe-rss 也支持
   一键同步微信读书里已关注的公众号。
4. 确认页面里能看到公众号列表和文章全文。

> 说明：wewe-rss 走的是微信读书通道，因此「微信读书里没有的公众号 / 文章」可能
> 抓不到；微信 App 的「订阅号」关注列表与微信读书的关注列表不一定 100% 一致，
> 需要对照补录。

## 第二步：整理账号清单（分类规则）

```bash
cd ~/briefings
python scripts/wechat_kb.py init          # 生成 data/wechat_accounts.yml 模板
```

编辑 `data/wechat_accounts.yml`，把「公众号名 → 分类」填进去：

```yaml
categories:
  - name: 半导体与芯片
    accounts: [芯东西, 半导体行业观察, 芯片超人]
  - name: AI与科技
    accounts: [机器之心, 量子位, 新智元]
```

- 分类名就是知识库的一级目录。
- 匹配规则：公众号名「包含」关键词即命中，命中第一个分类即停；未命中自动进「未分类」。
- **新增公众号**：在对应分类下加一行即可，下次同步自动纳入；再加个新分类也只需加一段。

可以用 `python scripts/wechat_kb.py list-accounts` 查看 wewe-rss 里已有哪些公众号、
分别命中哪个分类，再据此补清单。

## 第三步：同步一次

```bash
# 环境变量（可写入 ~/.config/briefing-secrets.env）
export WEWE_RSS_BASE=http://127.0.0.1:4000
export DEEPSEEK_API_KEY=sk-...   # 可选：不配则跳过 AI 分类，只做标题去重

# 一键跑完：抓取 → 分类 → 合并 → 导出
bash scripts/wechat_kb_sync.sh
# 或分步：
python scripts/wechat_kb.py full
```

产出在 `knowledge_base/`：

```
knowledge_base/
├── README.md                     # 分类索引（含每个主题链接）
├── 半导体与芯片/
│   ├── 台积电发布3nm新工艺.md     # 同主题多篇已合并
│   └── ...
└── AI与科技/
    └── ...
```

## 第四步：定期自动同步（Mac mini）

在 `~/Library/LaunchAgents/` 加一个定时任务（例如每天 20:00 跑一次）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jianzhang.wechat-kb</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-s</string>
    <string>/bin/bash</string>
    <string>/Users/你的用户名/briefings/scripts/wechat_kb_sync.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BRIEFINGS_REPO</key><string>/Users/你的用户名/briefings</string>
    <key>BRIEFINGS_SECRETS</key><string>/Users/你的用户名/.config/briefing-secrets.env</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>20</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
</dict>
</plist>
```

保存为 `com.jianzhang.wechat-kb.plist` 后：

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jianzhang.wechat-kb.plist
# 立即试跑
launchctl kickstart -k gui/$UID/com.jianzhang.wechat-kb
```

## 检索

知识库是纯 Markdown 文件夹，直接用你习惯的工具打开：

- 本地全文检索：`rg "关键词" knowledge_base/`
- 笔记软件：把 `knowledge_base/` 作为 Obsidian / Logseq 仓库打开，天然支持链接、标签、双链
- 也可以后续把 `articles` 表接向量库做语义检索（本脚本已把标签/摘要存进 SQLite）

## 相似合并是怎么做的

1. **标题去重**：跨公众号、标题几乎相同的文章（转载/同稿）合并成一个主题，
   用「字符 bigram Jaccard 相似度 + 序列相似度」判断，对中文标题较稳。
2. **AI 主题聚类**：配了 `DEEPSEEK_API_KEY` 时，再按分类把「不同标题但同一事件」
   的文章聚成一组（例如同一发布会被多个号分别报道）。
3. 每个主题导出一个 `.md`，把多篇来源的标题、公众号、时间、链接、摘要、全文列在一起。

## 注意事项

- **版权**：仅用于个人学习研究，不要对外发布或商用；全文版权归原作者所有。
- **账号与频率**：wewe-rss 走微信读书，相对温和，但仍属灰色地带；别设过高频次
  （每天 1 次足够），避免影响登录状态。
- **稳定性**：微信读书接口可能变动，wewe-rss 若失效需升级到新版或换账号重新扫码。
- **数据不提交**：`data/wechat_accounts.yml`、`data/wechat_kb.sqlite3`、`knowledge_base/`
  都已加入 `.gitignore`，不会误传到 GitHub。
