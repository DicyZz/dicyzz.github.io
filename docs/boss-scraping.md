# BOSS 直聘岗位抓取（job_monitor flow）

这条 flow 的目标：每天定时（或手动触发）把指定城市 + 岗位的 BOSS 直聘在招职位，
和其他招聘源一起汇总成邮件 / JSON，并可选交给 DeepSeek 做二次分析。

相关文件：

| 文件 | 作用 |
| --- | --- |
| `.github/workflows/job_monitor.yml` | GitHub Actions flow（定时 + 手动触发） |
| `scripts/perfpulse_job_analysis.py` | 多源抓取主流程（牛客/猎聘/智联/51job/BOSS/海外源） |
| `scripts/boss_scraper.py` | BOSS 直聘抓取模块（接口优先 + DOM 兜底 + 翻页 + 诊断） |
| `scripts/boss_login.py` | 在国内 Mac 上扫码登录，保存持久化登录态 |
| `scripts/export_boss_cookies.py` | 从本机 Chrome 导出 Cookie（云端 runner 兼容模式用） |
| `scripts/setup_macmini_runner.sh` | 在国内 Mac mini 上一键部署 self-hosted runner |
| `tests/test_boss_scraper.py` | 离线回归测试（不需要浏览器/登录态） |

## 为什么必须国内 IP

BOSS 直聘对海外 IP 会重定向到登录 / 安全校验页，GitHub 云端 runner（`ubuntu-latest`）
抓不到。因此 flow 的 `runner` 输入要填成国内 self-hosted runner 的标签（如 `self-hosted`，
由 `setup_macmini_runner.sh` 注册）。

## 抓取流程

```
启动浏览器（持久化 profile 或注入 Cookie）
   └─ 打开一次搜索页 → 校验登录态 / 是否被风控（被拦截则保存诊断产物并退出）
        └─ 逐关键词、逐页抓取
             ├─ 优先：站点 JSON 接口 wxapi/zpgeek/search/joblist.json（字段完整、翻页便宜）
             └─ 兜底：渲染后的 DOM 解析（接口不可用时自动切换）
                  └─ 可选：抓取前 N 条岗位的详情正文（BOSS_MAX_DETAIL）
                       └─ 去重 → 与其他数据源合并 → 行业过滤 → 邮件 / JSON / DeepSeek 分析
```

> 岗位详情链接在邮件里必须可点：BOSS 卡片里的 `href` 是相对路径，模块会补全为
> `https://www.zhipin.com/job_detail/xxx.html`。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BOSS_COOKIES` | 空 | 登录 Cookie（JSON 数组或 `name->value` 对象），云端兼容模式使用 |
| `BOSS_PROFILE_DIR` | `~/boss_chrome_profile` | 持久化浏览器 profile 目录；**目录存在时自动优先用它** |
| `BOSS_PROXY` | 空 | 出口代理，`http://user:pass@host:port` 或 `socks5://...`，仅填 `host:port` 也行 |
| `BOSS_HEADFUL` | `1` | 有头模式（反风控成功率更高）；`0` 为无头 |
| `BOSS_PAGES` | `1` | 每个关键词翻页数，上限 10 |
| `BOSS_KEYWORDS_COUNT` | `1` | 使用前 N 个扩展关键词搜索 |
| `BOSS_MAX_DETAIL` | `0` | 抓取详情正文的岗位数（关闭为 0，建议 ≤5） |
| `BOSS_MODE` | `auto` | `auto` 接口优先 / `api` 只用接口 / `dom` 只用 DOM |
| `BOSS_DEBUG_DIR` | 空 | 诊断目录，命中风控或报错时保存 HTML + 截图 |

## 两种登录态

**推荐：持久化 profile（国内 Mac mini / self-hosted runner）**

```bash
bash scripts/setup_macmini_runner.sh   # 注册 runner + 安装依赖 + 扫码登录
# 之后登录态过期时重跑：
python scripts/boss_login.py
```

**兼容：Cookie 注入（仅当没有国内机器时的兜底，成功率低）**

```bash
python scripts/export_boss_cookies.py   # 输出 JSON，粘贴到 Secrets: BOSS_COOKIES
```

## 本地调试

```bash
# 单跑 BOSS 抓取（有头，方便观察是否被风控）
python scripts/boss_scraper.py --city 北京 --keyword 芯片设计 --pages 2

# 多关键词 + 抓详情 + 诊断产物
python scripts/boss_scraper.py -k 芯片设计 -k 数字ic --city 上海 --detail 3 \
    --dump-html work/boss_dump --json work/boss_jobs.json

# 离线单测（不需要浏览器与登录态）
python -m unittest discover -s tests -v
```

## 排查清单

| 现象 | 原因与处理 |
| --- | --- |
| 日志出现「未登录或被风控，已跳转」 | 登录态过期：在国内 Mac 上重跑 `boss_login.py`；同时看 `boss_debug/` 里的截图与 HTML |
| 日志出现「接口不可用…回退 DOM 解析」 | 站点接口调整或临时风控；DOM 兜底仍能抓到数据，若长期如此可对比 `boss_debug/` 里的 HTML 更新选择器 |
| 抓到 0 条但没报风控 | 关键词/城市组合太窄，换更通用的关键词；或把 `BOSS_PAGES` 调到 2 |
| 云端 runner 上 BOSS 永远是 0 条 | 海外 IP 被拦截，属预期行为；改用国内 self-hosted runner |
| 结果里有岗位但城市显示成「全国」 | 该城市未收录在 `boss_scraper.BOSS_CITY_CODE_MAP`，补一行编码即可 |
