#!/bin/bash
# 在本机（Mac mini）按计划跑四个周报 flow。
#
# 为什么不靠 GitHub 的 schedule：实测该仓库的定时任务稳定迟到 4.5–5.5 小时
# （计划 00:00 UTC 的 Job Monitor 实际 04:31 才跑），做不到北京时间 8:00。
#
# 由 launchd 在周一至周四 08:00 调起（见 scripts/setup_local_scheduler.sh），
# 也可以手动执行：
#     bash scripts/local_briefings.sh
#
# 依赖的密钥放在 ~/.config/briefing-secrets.env（600 权限，不进仓库）：
#     DEEPSEEK_API_KEY=...
#     EMAIL_SENDER=...
#     EMAIL_PASSWORD=...
#     EMAIL_RECEIVER=...        # 可省略，默认等于 EMAIL_SENDER
#     EMAIL_HOST=smtp.gmail.com # 可省略
#     EMAIL_PORT=465            # 可省略

set -uo pipefail

REPO_DIR="${BRIEFINGS_REPO:-$HOME/briefings}"
SECRETS_FILE="${BRIEFINGS_SECRETS:-$HOME/.config/briefing-secrets.env}"
LOG_DIR="${BRIEFINGS_LOG_DIR:-$HOME/Library/Logs/briefings}"
PYTHON="${BRIEFINGS_PYTHON:-/opt/homebrew/bin/python3}"
FLOWS=(perfpulse aifrontier finfrontier chinatech)

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/$(date +%Y-%m-%d).log"
exec >>"${LOG_FILE}" 2>&1

echo "===== $(date '+%F %T') 开始跑四个周报 ====="

# 当天已经成功发过信的 flow 会留下标记，避免重复发信
# （例如手动跑过一次后，08:00 的定时任务会跳过；想强制重跑就删掉对应标记文件）
TODAY="$(date +%Y-%m-%d)"
STATE_DIR="${LOG_DIR}/.state"
mkdir -p "${STATE_DIR}"

if [ ! -f "${SECRETS_FILE}" ]; then
  echo "❌ 缺少密钥文件 ${SECRETS_FILE}"
  echo "   参考 docs/weekly-briefings.md 填写后重试"
  exit 1
fi

# shellcheck disable=SC1090
set -a
. "${SECRETS_FILE}"
set +a

missing=""
for key in DEEPSEEK_API_KEY EMAIL_SENDER EMAIL_PASSWORD; do
  if [ -z "$(printenv "${key}" || true)" ]; then
    missing="${missing} ${key}"
  fi
done
if [ -n "${missing}" ]; then
  echo "❌ 密钥文件里缺少：${missing}"
  echo "   填好后可手动执行：bash ${REPO_DIR}/scripts/local_briefings.sh"
  exit 1
fi

if [ ! -x "${PYTHON}" ]; then
  PYTHON="$(command -v python3 || true)"
fi
if [ -z "${PYTHON}" ]; then
  echo "❌ 找不到 python3"
  exit 1
fi

cd "${REPO_DIR}" || { echo "❌ 仓库目录不存在：${REPO_DIR}"; exit 1; }

echo "→ 拉取最新代码（失败则用本地代码继续）"
/usr/bin/git pull --ff-only --quiet || echo "⚠️ git pull 失败，使用当前代码"

failed=0
skipped=0
for flow in "${FLOWS[@]}"; do
  marker="${STATE_DIR}/${TODAY}-${flow}.ok"
  if [ -f "${marker}" ]; then
    echo "⏭  ${flow} 今天（${TODAY}）已成功跑过，跳过"
    skipped=$((skipped + 1))
    continue
  fi
  echo ""
  echo "----- ${flow} 开始 $(date '+%T') -----"
  "${PYTHON}" "scripts/${flow}_push.py"
  code=$?
  echo "----- ${flow} 结束 exit=${code} $(date '+%T') -----"
  if [ "${code}" -eq 0 ]; then
    touch "${marker}"
  else
    failed=$((failed + 1))
  fi
done

echo ""
echo "===== 全部结束：4 个 flow，跳过 ${skipped} 个，失败 ${failed} 个，$(date '+%F %T') ====="
echo "日志：${LOG_FILE}"
exit 0
