#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions workflow 的本地自检（不需要联网）。

守住的坑（都真踩过）：

1. self-hosted macOS 上 runner 用的是系统自带的 **/bin/bash 3.2**，在
   ``LANG=en_US.UTF-8``（runner 的 .env 里就是这么设的）下会把 ``$PY（`` 里的
   全角括号当成变量名的一部分，报 ``PY<?>: unbound variable``，配上 ``set -u``
   直接退出 1。错误只出现在 GitHub 的 job 日志里，本地很难发现。
   → 变量后面紧跟中文标点时，务必写成 ``${VAR}``，或把标点换成 ASCII。

2. 本地彩排若用了别的 bash 或别的 locale，就会漏掉这类问题。
   → 这里直接用 /bin/bash + UTF-8 locale 实跑每个 run 脚本（外部命令用桩替换）。

运行：
    python -m unittest discover -s tests -v
"""

import glob
import os
import re
import subprocess
import sys
import tempfile
import unittest

try:
    import yaml
except ImportError:  # CI 上没装 PyYAML 时跳过，不让它变成假失败
    yaml = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

# 这些外部命令在自检里用桩替换，避免真的装依赖 / 抓数据
STUBBED_COMMANDS = (
    "python3", "python", "pip", "uname", "caffeinate", "launchctl", "npm", "node", "npx",
)

# $VAR 后面紧跟非 ASCII 字符（中文标点等）会被 bash 3.2 误解析，写成 ${VAR} 才安全
UNSAFE_VARIABLE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*?#$!-])[^\x00-\x7F]")


def _iter_run_steps():
    """遍历所有 workflow 的 run 步骤。

    产出 (路径, 作业名, 步骤名, 脚本, if 条件, 步骤 env)。
    """
    for path in sorted(glob.glob(os.path.join(WORKFLOW_DIR, "*.yml"))):
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run")
                if script:
                    yield (
                        path, job_name, step.get("name", "?"), script,
                        step.get("if", "") or "", step.get("env") or {},
                    )


def _read_env_file(path: str) -> dict:
    """读取模拟的 $GITHUB_ENV 文件。"""
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "=" in line:
                    key, value = line.rstrip("\n").split("=", 1)
                    values[key] = value
    return values


def _condition_allows(condition: str, env: dict) -> bool:
    """只支持 workflow 里实际用到的 `env.X != 'Y'` 形式条件。"""
    match = re.search(r"env\.(\w+)\s*!=\s*'([^']*)'", condition)
    if not match:
        return True
    return env.get(match.group(1)) != match.group(2)


def _stub_env(tmpdir: str) -> dict:
    """构造一个「外部命令全是桩」的环境，用来安全地实跑 run 脚本。"""
    stub = os.path.join(tmpdir, "stub")
    os.makedirs(stub, exist_ok=True)
    for name in STUBBED_COMMANDS:
        path = os.path.join(stub, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nexit 0\n")
        os.chmod(path, 0o755)
    for name in ("github_env", "summary.md"):
        open(os.path.join(tmpdir, name), "w", encoding="utf-8").close()
    return {
        "PATH": f"{stub}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": tmpdir,
        "GITHUB_ENV": os.path.join(tmpdir, "github_env"),
        "GITHUB_STEP_SUMMARY": os.path.join(tmpdir, "summary.md"),
        "GITHUB_ACTIONS": "true",
        # 关键：和 runner 的 .env 保持一致，否则复现不出 bash 3.2 的多字节问题
        "LANG": "en_US.UTF-8",
        "RUNNER_ENVIRONMENT": "self-hosted",
        "RUNNER_OS": "macOS",
    }


@unittest.skipIf(yaml is None, "未安装 PyYAML")
class TestWorkflowScripts(unittest.TestCase):
    def test_no_non_ascii_right_after_variable(self):
        """$VAR 后面不能紧跟中文标点（bash 3.2 会把标点吃进变量名）。"""
        offenders = []
        for path, job, name, script, _cond, _env in _iter_run_steps():
            if UNSAFE_VARIABLE.search(script):
                line = next(l for l in script.splitlines() if UNSAFE_VARIABLE.search(l)).strip()
                offenders.append(f"{os.path.relpath(path, REPO_ROOT)} :: {name} :: {line[:70]}")
        self.assertEqual(
            offenders, [],
            "以下脚本里 $VAR 紧跟中文标点，macOS 的 bash 3.2 会解析失败（改用 ${VAR}）："
            + " | ".join(offenders),
        )

    def test_scripts_are_valid_bash(self):
        """每个 run 脚本都要能通过 /bin/bash 语法检查。"""
        for path, job, name, script, _cond, _env in _iter_run_steps():
            result = subprocess.run(
                ["/bin/bash", "-n"], input=script, text=True, capture_output=True
            )
            self.assertEqual(
                result.returncode, 0,
                f"{os.path.relpath(path, REPO_ROOT)} :: {job} :: {name} 语法错误：{result.stderr}",
            )

    def test_run_scripts_execute_cleanly(self):
        """用 /bin/bash（macOS 上是 3.2）+ UTF-8 locale 按顺序实跑每个 run 脚本。

        同一个作业内共享 $GITHUB_ENV（和真实 runner 一致），所以引用上一步设置的
        环境变量（如 PYTHON_BIN）不会误报。
        """
        version = subprocess.run(
            ["/bin/bash", "--version"], capture_output=True, text=True
        ).stdout.splitlines()[0]
        with tempfile.TemporaryDirectory(prefix="wf_scripts_") as tmpdir:
            base_env = _stub_env(tmpdir)
            current_job = None
            for path, job, name, script, condition, step_env in _iter_run_steps():
                if (path, job) != current_job:  # 换作业就换一份 $GITHUB_ENV
                    current_job = (path, job)
                    open(base_env["GITHUB_ENV"], "w", encoding="utf-8").close()
                # 步骤自身的 env（跳过 ${{ }} 表达式，值由 GitHub 注入，本地无法还原）
                literals = {
                    k: str(v) for k, v in step_env.items()
                    if not (isinstance(v, str) and "${{" in v)
                }
                runtime_env = {**base_env, **literals, **_read_env_file(base_env["GITHUB_ENV"])}
                if not _condition_allows(condition, runtime_env):
                    continue
                script_file = os.path.join(tmpdir, "step.sh")
                with open(script_file, "w", encoding="utf-8", newline="\n") as f:
                    f.write(script)
                result = subprocess.run(
                    ["/bin/bash", "-e", script_file], cwd=tmpdir, env=runtime_env,
                    capture_output=True, text=True, errors="replace",
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{os.path.relpath(path, REPO_ROOT)} :: {job} :: {name} 执行失败"
                    f"（{version}）：{result.stderr.strip()}",
                )

    def test_job_monitor_is_one_tap_friendly(self):
        """手机一键触发依赖这些约定，改动时必须是有意的。"""
        with open(os.path.join(WORKFLOW_DIR, "job_monitor.yml"), encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        triggers = doc.get("on") or doc.get(True)
        inputs = triggers["workflow_dispatch"]["inputs"]
        # 所有输入都必须是「可选 + 有默认值」，这样手机上直接点 Run 就能跑
        for name, spec in inputs.items():
            self.assertFalse(spec.get("required", False), f"{name} 不应是必填项")
            self.assertTrue(spec.get("default"), f"{name} 缺少默认值，一键触发会拿到空值")
        # 三个抓取范围开关：平台 / 翻页数 / 关键词个数
        for name in ("target_job", "target_city", "source", "pages", "keywords"):
            self.assertIn(name, inputs)
        job = doc["jobs"]["analyze-jobs"]
        self.assertEqual(job["runs-on"], "self-hosted")
        self.assertIn("concurrency", doc)
        names = [s.get("name") for s in job["steps"]]
        self.assertIn("Run Job Analysis Script", names)

    def test_other_suites_pass_with_workflow_env(self):
        """单测不能在 workflow 注入的环境变量下失败。

        workflow 会把 SOURCES / PAGES / KEYWORD_LIMIT 等传给任务，如果某个用例
        直接读取 import 时算出的模块常量，就会「本地过、runner 挂」——这里用
        workflow 的实际取值再跑一遍其余测试模块，把这种情况挡在本地。
        """
        polluted = {
            **os.environ,
            "SOURCES": "all",
            "PAGES": "2",          # 表单默认值
            "KEYWORD_LIMIT": "0",  # 表单默认值
        }
        for module in ("test_boss_scraper.py", "test_job_sources.py"):
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", module, "-v"],
                cwd=REPO_ROOT, env=polluted, capture_output=True, text=True, errors="replace",
            )
            self.assertEqual(
                result.returncode, 0,
                f"{module} 在 workflow 注入的环境下失败：\n{result.stderr[-2000:]}",
            )


if __name__ == "__main__":
    unittest.main()
