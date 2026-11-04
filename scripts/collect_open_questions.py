#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_open_questions.py — 把所有文档里的 ⚙️ 待确认 / ⚙️ 待你确认 汇总成一张清单

用法：
    python3 collect_open_questions.py [项目根]              # 更新 OPEN-QUESTIONS.md
    python3 collect_open_questions.py [项目根] --dry-run    # 只看结果，不写文件
    python3 collect_open_questions.py [项目根] --stdout     # 打印到屏幕

为什么要做这一步（实测）：
    待确认项散落在 constraints.md（9 处）、text-to-sql.md（6 处）、semantic_layer.yaml（4 处）…
    最后是靠"地毯式搜索"才找全的。这个脚本把它变成一条命令。
    ★ 更重要的是"阻塞 / 非阻塞"分级 —— 十来个待确认项里，真正阻塞的通常只有两三个。

写入规则（非破坏性）：
    只在 <!-- AUTO-COLLECT:BEGIN --> 与 <!-- AUTO-COLLECT:END --> 之间替换，
    第一节"阻塞项"、第二节"非阻塞项"里你手写的内容**一个字都不动**。
    若文件里没有这对标记，则在文件末尾追加一节，不改动原有内容。
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date

MARKER_BEGIN = "<!-- AUTO-COLLECT:BEGIN"
MARKER_END = "<!-- AUTO-COLLECT:END -->"

# 哪些词出现时，判为"阻塞"（当同一行/上一行含这些词）
BLOCKING_HINTS = ["阻塞", "必须", "前置条件", "硬条件", "否则", "作废", "拿不到"]
# 建议值：行内形如 "建议：xxx" / "默认：xxx" / "-> xxx"
ADVICE_PAT = re.compile(r"(?:建议|默认|推荐|按)\s*[:：]\s*([^。；;|]{1,40})")
# 该问谁
WHO_PAT = re.compile(r"(?:该问谁|问|找)\s*[:：]?\s*(财务|合规|法务|DBA|运维|老板|业务方|"
                     r"客户|供应商|你自己|你|产品)")
IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", ".mypy_cache",
               "__pycache__", ".pytest_cache", ".ruff_cache"}

MARKER = re.compile(r"⚙️\s*待(?:你)?确认")


def is_ignored(path, root):
    parts = set(os.path.relpath(path, root).split(os.sep))
    return bool(parts & IGNORE_DIRS)


def extract_quote(ln):
    """从一行里取出"那句话"。表格行只取含标记的那一格，避免整行噪音。"""
    if ln.strip().startswith("|"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        for c in cells:
            if MARKER.search(c):
                return MARKER.sub("", c).strip(" -—:：")[:90]
    return MARKER.sub("", ln).strip(" -—:：|·")[:90]


def scan(root):
    """返回 [(文件, 行号, 那句话, 所在小节, 是否阻塞, 建议, 该问谁)]"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in sorted(filenames):
            if not (fn.endswith(".md") or fn.endswith(".yaml") or fn.endswith(".yml")):
                continue
            path = os.path.join(dirpath, fn)
            if is_ignored(path, root):
                continue
            if fn == "OPEN-QUESTIONS.md":
                continue
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            lines = text.splitlines()
            heading = "(文件开头)"
            for i, ln in enumerate(lines):
                m = re.match(r"^#{2,4}\s+(.*)", ln)
                if m:
                    heading = m.group(1).strip()
                if not MARKER.search(ln):
                    continue
                ctx = " ".join(lines[max(0, i - 1):i + 2])
                blocking = any(h in ctx for h in BLOCKING_HINTS)
                am = ADVICE_PAT.search(ln) or ADVICE_PAT.search(ctx)
                advice = am.group(1).strip() if am else ""
                wm = WHO_PAT.search(ctx)
                who = wm.group(1) if wm else ""
                # 那句话：去掉标记本身，取剩余文本
                quote = extract_quote(ln)
                out.append({
                    "file": os.path.relpath(path, root),
                    "line": i + 1,
                    "quote": quote[:90],
                    "section": heading,
                    "blocking": blocking,
                    "advice": advice,
                    "who": who,
                })
    return out


def build_section(items, root):
    blocking = [i for i in items if i["blocking"]]
    soft = [i for i in items if not i["blocking"]]

    L = []
    L.append(f"### 🤖 自动汇总（{date.today().isoformat()} · 共 {len(items)} 处）")
    L.append("")
    L.append(f"扫描根目录：`{root}`")
    L.append("")
    L.append("> **先说结论**：十来个待确认项里，真正阻塞的通常只有两三个。")
    L.append("> 把阻塞项挑出来后可以立刻开工，其余给保守默认值即可 ——")
    L.append("> 保守默认值本身就是安全的那一侧，不需要任何人签字。")
    L.append("")

    L.append(f"#### 一、可能阻塞（{len(blocking)} 处）")
    L.append("")
    if not blocking:
        L.append("_没有扫描到带阻塞线索的条目。请人工复核下面的非阻塞清单。_")
    else:
        L.append("| # | 问题 | 出现在 | 所在小节 | 我的建议 | 该问谁 |")
        L.append("|---|---|---|---|---|---|")
        for n, it in enumerate(blocking, 1):
            loc = f"`{it['file']}` L{it['line']}"
            L.append(f"| {n} | {it['quote']} | {loc} | {it['section'][:24]} | "
                     f"{it['advice'] or '⚙️ 待填'} | {it['who'] or '⚙️ 待填'} |")
    L.append("")

    L.append(f"#### 二、非阻塞（{len(soft)} 处，可先给保守默认值开工）")
    L.append("")
    if not soft:
        L.append("_无_")
    else:
        L.append("| # | 问题 | 出现在 | 所在小节 | 我的建议 | 该问谁 |")
        L.append("|---|---|---|---|---|---|")
        for n, it in enumerate(soft, 1):
            loc = f"`{it['file']}` L{it['line']}"
            L.append(f"| {n} | {it['quote']} | {loc} | {it['section'][:24]} | "
                     f"{it['advice'] or '⚙️ 待填'} | {it['who'] or '⚙️ 待填'} |")
    L.append("")

    # 按文件分布，方便判断哪份文件"欠债"最多
    by_file = defaultdict(int)
    for it in items:
        by_file[it["file"]] += 1
    if by_file:
        L.append("#### 三、按文件分布（哪份文件欠债最多）")
        L.append("")
        L.append("| 文件 | 处数 |")
        L.append("|---|---|")
        for f, c in sorted(by_file.items(), key=lambda kv: -kv[1]):
            L.append(f"| `{f}` | {c} |")
        L.append("")

    L.append("> ⚠️ 这是**机械汇总**，只按关键词猜测「阻塞 / 非阻塞」，**必须人工过一遍**。")
    L.append("> 处理完后，把结论填到上面第一节 / 第二节的表里，并删掉这里的对应行。")
    return "\n".join(L)


def write_back(path, section):
    if not os.path.exists(path):
        content = ("# OPEN-QUESTIONS.md · 待确认项清单\n\n"
                   "> 由 collect_open_questions.py 生成。第一节、第二节可以手工维护。\n\n"
                   "## 一、阻塞项（不定下来就没法开工）\n\n_（待填）_\n\n"
                   "## 二、非阻塞项（有保守默认值，可以先开工）\n\n_（待填）_\n\n"
                   "---\n\n"
                   f"{MARKER_BEGIN} -->\n{section}\n{MARKER_END}\n")
        return content, True
    text = open(path, encoding="utf-8").read()
    b = text.find(MARKER_BEGIN)
    e = text.find(MARKER_END)
    if b != -1 and e != -1 and e > b:
        head = text[:b]
        tail = text[e + len(MARKER_END):]
        new = f"{head}{MARKER_BEGIN} -->\n{section}\n{MARKER_END}{tail}"
        return new, True
    new = text.rstrip() + "\n\n---\n\n" + f"{MARKER_BEGIN} -->\n{section}\n{MARKER_END}\n"
    return new, True


def main():
    ap = argparse.ArgumentParser(description="汇总所有 ⚙️ 待确认")
    ap.add_argument("root", nargs="?", default=".", help="项目根目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    ap.add_argument("--stdout", action="store_true", help="等价于 --dry-run")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"目录不存在：{root}")
        return 2

    items = scan(root)
    section = build_section(items, root)

    if args.dry_run or args.stdout:
        print(section)
        print(f"\n[共 {len(items)} 处；未写文件]")
        return 0

    target = os.path.join(root, "OPEN-QUESTIONS.md")
    content, _ = write_back(target, section)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)

    blocking = sum(1 for i in items if i["blocking"])
    print(f"✓ 已更新 {os.path.relpath(target, root)}")
    print(f"  共 {len(items)} 处 ⚙️ 待确认（其中可能阻塞 {blocking} 处）")
    print("  下一步：人工过一遍自动汇总，把结论填进第一节 / 第二节。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
