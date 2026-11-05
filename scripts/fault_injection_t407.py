#!/usr/bin/env python3
"""T-4.0.7 故障注入验证：lint、secret-scan、pytest 必须各自拦截一次。

用法：.venv/bin/python scripts/fault_injection_t407.py
只有三项门禁均按预期失败、且主工作区状态不变时，脚本才返回 0。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("tests/unit/test_gates.py")
PROBE = "secret_scan_probe.txt"


def run(command: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = run(["git", *args], cwd)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：\n{result.stdout}{result.stderr}")
    return result


def make(worktree: Path, target: str) -> subprocess.CompletedProcess[str]:
    return run(["make", f"PYTHON={sys.executable}", target], worktree)


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"故障注入锚点不唯一或已变化：{old.strip()}")
    return text.replace(old, new, 1)


def expect_blocked(
    name: str, result: subprocess.CompletedProcess[str], expected_output: tuple[str, ...]
) -> None:
    output = result.stdout + result.stderr
    missing = [text for text in expected_output if text not in output]
    if result.returncode == 0 or missing:
        print(output, file=sys.stderr)
        raise RuntimeError(f"{name} 未按预期拦截：exit={result.returncode}，缺少输出={missing}")
    print(f"[PASS] {name} 按预期拦截（exit={result.returncode}）")


def run_fault_injections(worktree: Path) -> None:
    target = worktree / TARGET
    original = target.read_text(encoding="utf-8")

    lint_anchor = "def test_check_sql_accepts_readonly_with_limit():\n"
    lint_fault = replace_once(
        original,
        lint_anchor,
        lint_anchor + "    unused_negative_probe = 1\n\n",
    )
    target.write_text(lint_fault, encoding="utf-8")
    expect_blocked(
        "make lint / F841",
        make(worktree, "lint"),
        ("F841", "unused_negative_probe"),
    )

    # 假密钥只在临时 worktree 中生成，避免脚本自身触发全仓密钥扫描。
    probe = worktree / PROBE
    probe.write_text(
        "".join(("api", "_key", " = ", '"', "sk-", "12345678", '"', "\n")),
        encoding="utf-8",
    )
    git(worktree, "add", "--", PROBE)
    expect_blocked(
        "make secret-scan / 假密钥",
        make(worktree, "secret-scan"),
        (PROBE, "疑似密钥"),
    )

    assertion = "    assert verdict.ok is True\n"
    test_fault = replace_once(original, assertion, "    assert verdict.ok is False\n")
    target.write_text(test_fault, encoding="utf-8")
    expect_blocked(
        "make test / 错误断言",
        make(worktree, "test"),
        ("1 failed", "test_check_sql_accepts_readonly_with_limit"),
    )


def main() -> int:
    if sys.version_info[:2] < (3, 13):
        print("需要 Python 3.13：请用 .venv/bin/python 运行本脚本", file=sys.stderr)
        return 2

    before = git(ROOT, "status", "--porcelain").stdout
    try:
        with tempfile.TemporaryDirectory(prefix="riskqa-t407-") as temp_dir:
            worktree = Path(temp_dir) / "worktree"
            added = False
            try:
                git(ROOT, "worktree", "add", "--detach", str(worktree), "HEAD")
                added = True
                run_fault_injections(worktree)
            finally:
                if added:
                    # 只强制删除脚本创建的临时 worktree，故障文件随之一并清理。
                    git(ROOT, "worktree", "remove", "--force", str(worktree))
    finally:
        after = git(ROOT, "status", "--porcelain").stdout
        if after != before:
            raise RuntimeError("主工作区状态发生变化，请立即检查 git status")

    print("T-4.0.7 故障注入验证通过：3/3 拦截，主工作区状态未变")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
