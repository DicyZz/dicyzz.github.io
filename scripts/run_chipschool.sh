#!/bin/bash
# 每周五 08:00 跑「芯片通识课」的下一讲（由 launchd 调起，见 setup_local_scheduler.sh）。
#
# 与 local_briefings.sh（周一至周四的四个周报）分开，互不影响：
#   - 四个周报：周一至周四，scripts/local_briefings.sh
#   - 芯片通识课：每周五，scripts/run_chipschool.sh → scripts/chipschool_push.py
#
# 也可以手动执行：
#     bash scripts/run_chipschool.sh                    # 自动跑当前讲（周五才真正发）
#     bash scripts/run_chipschool.sh --lesson 3         # 指定讲次（不推进进度）
#     bash scripts/run_chipschool.sh --force            # 强制跑当前讲并推进
#     bash scripts/run_chipschool.sh --dry-run          # 只生成落盘，不发信不推进
#
# 依赖的密钥同样放在 ~/.config/briefing-secrets.env（600 权限，不进仓库）。

set -uo pipefail

REPO_DIR="${BRIEFINGS_REPO:-$HOME/briefings}"
SECRETS_FILE="${BRIEFINGS_SECRETS:-$HOME/.config/briefing-secrets.env}"
LOG_DIR="${BRIEFINGS_LOG_DIR:-$HOME/Library/Logs/briefings}"
PYTHON="${BRIEFINGS_PYTHON:-/opt/homebrew/bin/python3}"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/chipschool-$(date +%Y-%m-%d).log"
exec >>"${LOG_FILE}" 2>&1

echo "===== $(date '+%F %T') 开始跑芯片通识课 ====="

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
  echo "   填好后可手动执行：bash ${REPO_DIR}/scripts/run_chipschool.sh"
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

"${PYTHON}" "scripts/chipschool_push.py" "$@"
code=$?

echo "===== 芯片通识课结束 exit=${code} $(date '+%F %T') ====="
echo "日志：${LOG_FILE}"
exit ${code}
