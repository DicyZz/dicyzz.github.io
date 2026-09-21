#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions workflow 的静态自检（不需要联网）。

守住的坑：runner 会把 run 脚本里含 `${{ }}` 的文本交给表达式 `format()` 求值，
此时脚本里若还有普通花括号（例如 `${VAR:-}`），`format()` 会因非法占位符报错，
脚本根本不会生成，步骤 0.03 秒就失败且没有任何输出——极难排查。

运行：
    python -m unittest discover -s tests -v
"""

import glob
import os
import re
import subprocess
import unittest

try:
    import yaml
except ImportError:  # CI 上没装 PyYAML 时跳过，不让它变成假失败
    yaml = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")


def _iter_run_steps():
    """遍历所有 workflow 的 run 步骤，产出 (路径, 作业名, 步骤名, 脚本)。"""
    for path in sorted(glob.glob(os.path.join(WORKFLOW_DIR, "*.yml"))):
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run")
                if script:
                    yield path, job_name, step.get("name", "?"), script


@unittest.skipIf(yaml is None, "未安装 PyYAML")
class TestWorkflowScripts(unittest.TestCase):
    def test_expressions_do_not_mix_with_braces(self):
        """run 脚本里同时出现 ${{ }} 与普通花括号会触发 format() 报错。"""
        offenders = []
        for path, job, name, script in _iter_run_steps():
            if "${{" not in script:
                continue
            stripped = re.sub(r"\$\{\{.*?\}\}", "", script, flags=re.S)
            if "{" in stripped or "}" in stripped:
                offenders.append(f"{os.path.relpath(path, REPO_ROOT)} :: {job} :: {name}")
        self.assertEqual(
            offenders, [],
            "以下步骤同时使用了 ${{ }} 和普通花括号，会导致表达式求值失败：" + "; ".join(offenders),
        )

    def test_scripts_are_valid_bash(self):
        """每个 run 脚本都要能通过 bash 语法检查。"""
        for path, job, name, script in _iter_run_steps():
            result = subprocess.run(
                ["bash", "-n"], input=script, text=True, capture_output=True
            )
            self.assertEqual(
                result.returncode, 0,
                f"{os.path.relpath(path, REPO_ROOT)} :: {job} :: {name} 语法错误：{result.stderr}",
            )

    def test_job_monitor_defaults_suit_phone_trigger(self):
        """手机一键触发依赖这些默认值，改动时必须是有意的。"""
        with open(os.path.join(WORKFLOW_DIR, "job_monitor.yml"), encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        triggers = doc.get("on") or doc.get(True)
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["runner"]["default"], "self-hosted")
        self.assertIn("target_job", inputs)
        self.assertIn("target_city", inputs)
        job = doc["jobs"]["analyze-jobs"]
        self.assertIn("self-hosted", job["runs-on"])
        self.assertIn("concurrency", doc)
        names = [s.get("name") for s in job["steps"]]
        self.assertIn("Run Job Analysis Script", names)


if __name__ == "__main__":
    unittest.main()
