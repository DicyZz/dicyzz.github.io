# 从 MacBook 远程访问这台 Mac mini

这台 Mac mini 既是 GitHub Actions 的 self-hosted runner（国内 IP 抓 BOSS 直聘），
也作为一台常开小服务器使用。本文记录「怎么连」「为什么下次还能连」「连不上怎么查」。

## 这台机器的身份信息

| 项目 | 值 |
| --- | --- |
| 电脑名称 | `jian的Mac mini`（Finder 网络里显示这个） |
| Bonjour 名称 | `jiandeMac-mini.local` ← **推荐用这个名字连，不受 IP 变化影响** |
| 局域网 IP | `192.168.3.29`（DHCP，可能变化） |
| 登录账号 | `jianzhang` |
| 系统 | macOS 15.3（Apple Silicon） |
| 网络 | Wi-Fi（SSID 见路由器），开着「私有 Wi-Fi 地址」，无线 MAC 会随机化 |
| 路由器 / DHCP | `192.168.3.1` |

## 一、在家里（同一个局域网）——现在就能用

MacBook 上三种方式任选：

1. **Finder** → 侧边栏「网络」→ 找到 `jian的Mac mini` → 点「共享屏幕」
2. **Finder** → 前往 → 连接服务器（⌘K）→ 输入：

   ```
   vnc://jiandeMac-mini.local
   ```

   （IP 方式也可用：`vnc://192.168.3.29`）

3. **直接打开屏幕共享 App**：`/System/Applications/Utilities/Screen Sharing.app`，
   然后输入同样的地址

登录时用 Mac mini 的账号 `jianzhang` 和它的登录密码。

**连不上时先做这个 3 秒检查**（在 MacBook 终端里）：

```bash
nc -vz jiandeMac-mini.local 5900
```

- 提示 `succeeded` → 网络通，问题在账号/客户端
- 提示 `Connection refused` / 超时 → 看下面「故障排查」

## 二、不在家（外网访问）——推荐 Tailscale

两台 Mac 都装 [Tailscale](https://tailscale.com/download)（或 App Store 版）并登录**同一个账号**，
之后在 MacBook 上用 Tailscale 分配的名字/IP 连：

```
vnc://<mac-mini 在 Tailscale 里的名字>
```

不要做端口映射把 5900 暴露到公网：VNC 被扫端口爆破的风险很高，Tailscale 是加密点对点，
不用改路由器。

## 三、为什么「下次还能连上」——当前已配置的保障

以下都是这台机器上**已确认生效**的设置（附验证命令，换机器或重装后照着重做即可）：

| 保障 | 当前状态 | 验证命令 |
| --- | --- | --- |
| 屏幕共享已开启且开机自启 | 已开启（`com.apple.screensharing => enabled`） | `launchctl print-disabled system \| grep screensharing` |
| 服务在监听所有网卡 | `*.5900` 监听中 | `netstat -an -p tcp \| grep 5900` |
| 认证方式为「账号密码」 | 提供 Apple DH / ARD 认证 | 见下方 python 握手脚本 |
| 允许访问的用户 | 未设置限制组 → 所有用户可连 | `dscl . -read /Groups/com.apple.access_screensharing`（报 `eDSRecordNotFound` 即无限制） |
| Bonjour 广播 | `_rfb._tcp → jian的Mac mini` | `dns-sd -B _rfb._tcp` |
| 防火墙 | 未启用（不会拦入站） | `defaults read /Library/Preferences/com.apple.alf globalstate`（报 `domain pair does not exist` 即从未启用） |
| 不会休眠 | `caffeinate`（runner）+ 远端会话持有断言 | `pmset -g assertions \| grep -i caffeinate` |
| 重启后自动登录 | 已开启（账号 `jianzhang`） | `defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser` |
| 断电恢复后自动开机 | `autorestart 1` | `pmset -g custom \| grep autorestart` |
| 网络唤醒 | `womp 1`（Ethernet 魔法包） | `pmset -g custom \| grep womp` |

认证方式自检（在 Mac mini 上跑）：

```bash
python3 - <<'PY'
import socket
s = socket.create_connection(("127.0.0.1", 5900), timeout=5)
ver = s.recv(12); s.sendall(ver)
n = s.recv(1)[0]
print("认证方式:", list(s.recv(n)))   # 含 30/33 表示用账号密码认证
s.close()
PY
```

## 四、已知会「哪天连不上」的坑，建议提前处理

1. **IP 变化**：`192.168.3.29` 是 DHCP 分配、3 小时续约一次，理论上可能变。
   - 最省事：一直用 `vnc://jiandeMac-mini.local`（Bonjour 名字，IP 变了也能解析）
   - 想固定 IP：在路由器里做 DHCP 保留。注意这台机器开了「私有 Wi-Fi 地址」，
     路由器看到的是随机 MAC `aa:20:a7:e7:f9:ce`（硬件 MAC 是 `5c:1b:f4:79:21:ca`）；
     要么按随机 MAC 保留，要么先在「系统设置 → 无线局域网 → 详细信息 → 私有 Wi-Fi 地址」
     关掉它，再用硬件 MAC 做保留
2. **只走 Wi-Fi**：内置以太网口 `en0` 目前没插网线。作为服务器建议插上有线，
   更稳且支持网络唤醒
3. **FileVault 目前是关闭的**——这正是「重启后自动登录 + 无人值守可连」的前提。
   如果以后打开 FileVault，重启后会停在解锁界面等人输入密码，远程就连不上了
4. **建议开一个 SSH 备用通道**（现在没开）。系统设置 → 通用 → 共享 → 远程登录；
   或终端执行（需要管理员密码）：

   ```bash
   sudo systemsetup -setremotelogin on
   ```

   之后 MacBook 上可 `ssh jianzhang@jiandeMac-mini.local`

## 五、故障排查顺序

| 现象 | 先查什么 |
| --- | --- |
| MacBook 侧边栏看不到这台 Mac | 两台是否在同一网段（`ipconfig getifaddr en1` 对比前三位）；路由器是否开了 AP 隔离 |
| 能看到但连不上（超时） | 在 Mac mini 上 `netstat -an -p tcp \| grep 5900` 确认在监听；`launchctl print-disabled system \| grep screensharing` |
| 提示用户名/密码错误 | 用账号 `jianzhang` + 登录密码（不是 Apple ID 密码）；`VNCLegacyConnectionsEnabled=0` 表示不支持「VNC 专用密码」那种老客户端 |
| 连接后是黑屏 / 停在登录界面 | 说明当前是登录窗口状态（没人登录或刚重启）：直接在远程画面里登录即可；自动登录已开启，重启后通常直接进桌面 |
| 完全连不上但机器应该开着 | 从 MacBook 跑 `nc -vz jiandeMac-mini.local 5900`；不通就考虑 IP 变了（换 `.local` 名字）或机器睡了（`pmset -g assertions` 看有没有 caffeinate） |
| 需要在外网连 | 装 Tailscale（见第二节），不要端口映射 |

## 六、和抓取 flow 的配合

- BOSS 直聘登录态过期时，不用跑到机器旁边：在屏幕共享里执行
  `python3 scripts/boss_login.py`，用手机扫码即可（Chrome 以有头模式打开，远程画面里能看到）
- 查看 runner 状态：`tail -f ~/actions-runner/runner.log`、
  `launchctl list | grep actions.runner`
- 抓取日志落在 runner 的工作目录：
  `~/actions-runner/_work/dicyzz.github.io/dicyzz.github.io/analysis.log`
