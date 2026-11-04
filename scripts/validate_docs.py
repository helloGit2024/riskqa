#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_docs.py — 前置文档集自检脚本（三类检查）

用法：
    python3 validate_docs.py [项目根目录]        # 默认当前目录
    python3 validate_docs.py . --json            # 输出 JSON（供 CI 用）
    python3 validate_docs.py . --quiet           # 只输出问题

三类检查：
    格式类   —— 能不能被机器正确读（YAML / 表格 / 围栏 / HTML 锚点）
    一致性类 —— 多处说法是否对得上（接口数 / 门禁编号 / 任务编号 / 计数 / ★ 数）
    纪律类   —— 有没有违反自己定的规矩（常驻规则行数 / frontmatter / Reject List /
              ⚙️ 归属 / 废弃词 / 命名空间 / 宪法引用完整性 / 上下文预算）
    动词类   —— 可执行承诺是否兑现（make 命令 target 存在 / 代码缺口已入账）

可选配置：项目根下的 .docs-bootstrap.yaml（不存在则用默认值）

    resident_rule_max_lines: 180          # 常驻规则文件行数上限（ERROR）
    budget:                               # 上下文预算（见 references/context-budget.md）
      ondemand_rule_max_lines: 150        # 按需规则（WARN）
      constitution_max_lines: 300         # AGENTS.md / CLAUDE.md（WARN）
      doc_max_lines: 600                  # 一般文档（WARN）
      ledger_max_lines: 300               # 台账类（WARN）
    count_phrases:                        # 需要跨文件核对的"N 个XX"（正则）
      - "接口总数"
      - "共 (\\d+) 份文档"
    ignore_dirs: [.git, .venv, node_modules, .mypy_cache, __pycache__, .pytest_cache]

单文件豁免预算：在该文件首 5 行内写 `<!-- budget-exempt: 理由 -->`

退出码：0 = 无 ERROR；1 = 有 ERROR（可用于 CI 门禁）
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------- 基础工具

DEFAULT_IGNORE_DIRS = {
    ".git", ".venv", "venv", "node_modules", ".mypy_cache",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
}

PLATFORM_RULES = [
    (".trae/rules", "trae"),
    (".cursor/rules", "cursor"),
    (".claude/rules", "claude"),
]

# 上下文预算默认值（见 references/context-budget.md）
# 只列"没被 check_rules 管"的那几类 —— 常驻规则的硬上限由 check_rules 报 ERROR，
# 这里不重复报，避免同一个问题出现两条。
BUDGET_DEFAULTS = {
    "ondemand_rule_max_lines": 150,
    "constitution_max_lines": 300,
    "doc_max_lines": 600,
    "ledger_max_lines": 300,
}

# 宪法文件（硬规则编号 P-xx 的定义处）
CONSTITUTION_NAMES = ("AGENTS.md", "CLAUDE.md")
CONSTITUTION_DIRS = ("docs", ".")

# 台账类文件：天然会越长越长，但要知道它在长
LEDGER_NAMES = {
    "OPEN-QUESTIONS.md", "assumptions.md", "risk-register.md",
    "00-index.md", "tasks.md", "glossary.md", "experiments", "casebook.md",
}

BUDGET_EXEMPT = re.compile(r"<!--\s*budget-exempt\s*:\s*(.+?)\s*-->")


class Findings:
    """收集所有问题。level: ERROR / WARN / INFO"""

    def __init__(self):
        self.items = []

    def add(self, level, group, path, line, msg):
        self.items.append(
            {"level": level, "group": group, "path": path, "line": line, "msg": msg}
        )

    def error(self, group, path, line, msg):
        self.add("ERROR", group, path, line, msg)

    def warn(self, group, path, line, msg):
        self.add("WARN", group, path, line, msg)

    def info(self, group, path, line, msg):
        self.add("INFO", group, path, line, msg)

    @property
    def errors(self):
        return [i for i in self.items if i["level"] == "ERROR"]

    @property
    def warns(self):
        return [i for i in self.items if i["level"] == "WARN"]


def load_config(root):
    cfg = {
        "resident_rule_max_lines": 180,
        "budget": dict(BUDGET_DEFAULTS),
        "count_phrases": [],
        "ignore_dirs": sorted(DEFAULT_IGNORE_DIRS),
    }
    path = os.path.join(root, ".docs-bootstrap.yaml")
    if not os.path.exists(path):
        return cfg
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict):
            budget = data.pop("budget", None)
            cfg.update(data)
            if isinstance(budget, dict):
                cfg["budget"] = {**BUDGET_DEFAULTS, **budget}
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 读取 .docs-bootstrap.yaml 失败，使用默认配置：{e}")
    return cfg


def iter_files(root, cfg, exts=None):
    ignore = set(cfg.get("ignore_dirs") or [])
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore]
        for fn in filenames:
            if fn.startswith(".") and fn not in (".env.example",):
                continue
            if exts and not any(fn.endswith(e) for e in exts):
                continue
            yield os.path.join(dirpath, fn)


def rel(root, path):
    return os.path.relpath(path, root)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def strip_fences(text):
    """返回 (无围栏内容的行列表, 围栏是否成对)。供表格检查用。"""
    out, in_fence, balanced = [], False, True
    fence_re = re.compile(r"^\s*(```|~~~)")
    for line in text.splitlines():
        if fence_re.match(line):
            in_fence = not in_fence
            out.append("")  # 保留行号
            continue
        out.append("" if in_fence else line)
    if in_fence:
        balanced = False
    return out, balanced


# ---------------------------------------------------------------- 格式类


def check_yaml(root, cfg, f: Findings):
    """1) 所有 YAML 文件可解析"""
    try:
        import yaml  # type: ignore
    except ImportError:
        f.warn("格式/YAML", "-", 0,
               "未安装 pyyaml，跳过 YAML 解析检查。安装：pip install pyyaml")
        return
    n = 0
    for path in iter_files(root, cfg, exts=(".yaml", ".yml")):
        n += 1
        rp = rel(root, path)
        text = read_text(path)
        try:
            yaml.safe_load(text)
        except Exception as e:  # noqa: BLE001
            first = str(e).splitlines()[0] if str(e) else "解析失败"
            line = 0
            m = re.search(r"line (\d+)", str(e))
            if m:
                line = int(m.group(1))
            f.error("格式/YAML", rp, line, f"YAML 解析失败：{first}")
    f.info("格式/YAML", "-", 0, f"已检查 {n} 个 YAML 文件")


def check_openapi_refs(root, cfg, f: Findings):
    """2) openapi.yaml 里的 $ref 无悬空"""
    try:
        import yaml  # type: ignore
    except ImportError:
        return
    targets = [p for p in iter_files(root, cfg, exts=(".yaml", ".yml"))
               if "openapi" in os.path.basename(p).lower()]
    for path in targets:
        rp = rel(root, path)
        try:
            doc = yaml.safe_load(read_text(path))
        except Exception:  # noqa: BLE001
            continue  # 已由 YAML 检查报过
        if not isinstance(doc, dict):
            continue
        refs = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "$ref" and isinstance(v, str):
                        refs.append(v)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(doc)
        for r in refs:
            if not r.startswith("#/"):
                f.warn("格式/OpenAPI", rp, 0,
                       f"外部 $ref（本脚本不校验）：{r}")
                continue
            cur = doc
            ok = True
            for part in r[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if not ok:
                f.error("格式/OpenAPI", rp, 0, f"$ref 悬空：{r}")


def _split_md_row(line):
    """按未转义、且不在反引号内的 | 切分。"""
    cells, buf, in_code, esc = [], [], False, False
    for ch in line:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "`":
            in_code = not in_code
            buf.append(ch)
            continue
        if ch == "|" and not in_code:
            cells.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    cells.append("".join(buf))
    return cells


def check_md_tables(root, cfg, f: Findings):
    """3) Markdown 表格列数一致 + 4) 代码围栏成对"""
    for path in iter_files(root, cfg, exts=(".md",)):
        rp = rel(root, path)
        text = read_text(path)
        lines, balanced = strip_fences(text)
        if not balanced:
            f.error("格式/Markdown", rp, 0, "代码围栏 ``` 不成对")

        block, start = [], 0
        def flush():
            if len(block) < 2:
                return
            counts = []
            for ln_no, ln in block:
                cells = _split_md_row(ln)
                # 去掉首尾空单元（| a | b | 切成 ['', 'a', 'b', '']）
                if cells and cells[0].strip() == "":
                    cells = cells[1:]
                if cells and cells[-1].strip() == "":
                    cells = cells[:-1]
                counts.append((ln_no, len(cells)))
            ref = counts[0][1]
            for ln_no, c in counts[1:]:
                if c != ref:
                    f.error("格式/Markdown 表格", rp, ln_no,
                            f"列数不一致：本行 {c} 列，表头 {ref} 列")

        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("|") and s.count("|") >= 2:
                if not block:
                    start = i + 1
                block.append((i + 1, ln))
            else:
                flush()
                block = []
        flush()


def check_html(root, cfg, f: Findings):
    """5) HTML 标签闭合 / 锚点不悬空 / id 不重复 / 表格列数（考虑 colspan）"""
    VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base",
            "col", "embed", "source", "track", "wbr", "path", "rect",
            "circle", "line", "polygon", "polyline", "ellipse", "use",
            "stop", "text", "tspan", "marker", "defs", "desc", "title"}

    for path in iter_files(root, cfg, exts=(".html", ".htm")):
        rp = rel(root, path)
        text = read_text(path)

        # --- 标签闭合（跳过 script/style 内容与自闭合标签）
        body = re.sub(r"<(script|style)\b.*?</\1>", "", text,
                      flags=re.S | re.I)
        stack, ok = [], True
        for m in re.finditer(r"<\s*(/?)\s*([a-zA-Z][\w:-]*)([^>]*?)(/?)\s*>", body):
            closing, tag, attrs, selfclose = m.group(1), m.group(2).lower(), \
                m.group(3), m.group(4)
            if tag in VOID or selfclose:
                continue
            if not closing:
                stack.append((tag, body[:m.start()].count("\n") + 1))
            else:
                if not stack:
                    f.warn("格式/HTML", rp,
                           body[:m.start()].count("\n") + 1,
                           f"多余的闭合标签 </{tag}>")
                    ok = False
                    continue
                open_tag, ln = stack.pop()
                if open_tag != tag:
                    f.error("格式/HTML", rp, ln,
                            f"标签未正确闭合：<{open_tag}> 被 </{tag}> 关闭")
                    ok = False
        if stack:
            for tag, ln in stack:
                f.error("格式/HTML", rp, ln, f"标签未闭合：<{tag}>")

        # --- id 重复
        ids = re.findall(r"\bid\s*=\s*[\"']([^\"']+)[\"']", text)
        dup = {i for i in ids if ids.count(i) > 1}
        for d in sorted(dup):
            f.error("格式/HTML", rp, 0, f"id 重复：{d}")

        # --- 锚点不悬空
        for m in re.finditer(r"href\s*=\s*[\"']#([^\"']+)[\"']", text):
            target = m.group(1)
            if target not in ids:
                ln = text[:m.start()].count("\n") + 1
                f.error("格式/HTML", rp, ln, f"锚点悬空：# {target} 没有对应的 id")


# ---------------------------------------------------------------- 一致性类


def check_numbering(root, cfg, f: Findings):
    """7) 门禁编号 8) 任务编号：连续、无重复"""
    patterns = [
        ("门禁", re.compile(r"\b([HS])(\d{2})\b")),
        ("任务", re.compile(r"\bT(\d{2})\b")),
        ("验收标准", re.compile(r"\bAC-(\d{2})\b")),
    ]
    for label, pat in patterns:
        found = defaultdict(set)  # prefix -> set(numbers)
        for path in iter_files(root, cfg, exts=(".md",)):
            rp = rel(root, path)
            text = read_text(path)
            for m in pat.finditer(text):
                groups = m.groups()
                prefix = groups[0] if len(groups) == 2 else ""
                num = int(groups[-1])
                found[prefix].add(num)
                found[prefix + "@" + rp].add(num)
        for key, nums in sorted(found.items()):
            if "@" in key:
                continue
            if not nums:
                continue
            lo, hi = min(nums), max(nums)
            missing = [n for n in range(lo, hi + 1) if n not in nums]
            if missing:
                f.warn("一致性/编号", f"{label}{key}", 0,
                       f"编号不连续，缺 {[f'{key}{n:02d}' if key else f'{n:02d}' for n in missing]}")


def check_counts(root, cfg, f: Findings):
    """6) 计数一致：同一段文字在多份文件里出现但数字不同"""
    phrases = cfg.get("count_phrases") or []
    if not phrases:
        # 默认只用"高精度"模式：必须带明确的锚点词，避免误报。
        # 想检查自己的口径，请在 .docs-bootstrap.yaml 的 count_phrases 里补正则。
        phrases = [r"接口总数\s*[:：]?\s*(\d+)",
                   r"共\s*(\d+)\s*个接口",
                   r"共\s*(\d+)\s*份(?:文档|文件)",
                   r"共\s*(\d+)\s*条硬规则",
                   r"(\d+)\s*条硬规则"]
    for phrase in phrases:
        try:
            pat = re.compile(phrase)
        except re.error:
            f.warn("一致性/计数", "-", 0, f"count_phrases 里的正则不合法，已跳过：{phrase}")
            continue
        hits = defaultdict(list)
        for path in iter_files(root, cfg, exts=(".md",)):
            text = read_text(path)
            for m in pat.finditer(text):
                hits[m.group(1)].append(rel(root, path))
        if len(hits) > 1:
            detail = "；".join(f"{v} 处见 {sorted(set(fs))[:3]}" for v, fs in hits.items())
            f.error("一致性/计数", "-", 0,
                    f"计数不一致（模式 {phrase}）：{detail}")


def check_star_count(root, cfg, f: Findings):
    """10) ★ 标记数量与文字说明一致（项目级，只在有明确"声明句"时检查）

    声明句形如："★ 数量为 15" / "共 15 个 ★" / "15 处标 ★"。
    只认这种带"数量/共/处"锚点的句子，避免把正文里的数字误判成声明。
    """
    declared = []          # (文件, 行号, 声明数)
    actual = 0             # 项目内 ★ 实际出现次数（不含声明句自身）
    decl_pat = re.compile(r"(?:★\s*(?:数量|标记)\s*[:：为]?\s*(\d+))"
                          r"|(?:共\s*(\d+)\s*(?:份|个|处)\s*[^\n]{0,4}★)"
                          r"|(?:(\d+)\s*处\s*[^\n]{0,6}★)")
    for path in iter_files(root, cfg, exts=(".md",)):
        rp = rel(root, path)
        text = read_text(path)
        for i, ln in enumerate(text.splitlines()):
            m = decl_pat.search(ln)
            if m:
                num = next(int(g) for g in m.groups() if g)
                declared.append((rp, i + 1, num))
                # 声明句里的 ★ 不计入实际数
                actual += ln.count("★") - 1 if "★" in ln else 0
            else:
                actual += ln.count("★")
    if not declared or actual <= 0:
        return
    for rp, line, num in declared:
        if abs(num - actual) > max(2, int(actual * 0.15)):
            f.warn("一致性/★", rp, line,
                   f"声明 ★ 数量为 {num}，但整个项目实际出现约 {actual} 个 ★（差 {abs(num-actual)}）")


# ---------------------------------------------------------------- 纪律类


def detect_rule_files(root, cfg):
    """返回 [(路径, 是否常驻, 是否平台规则目录内的文件)]

    ★ 区分很重要：
      - 平台规则目录（.trae/rules、.cursor/rules）里的文件 —— 需要 frontmatter，常驻的受行数限制
      - 根目录 AGENTS.md / CLAUDE.md —— 是"项目宪法/按需读的全量参考"，不需要 frontmatter，
        也不受 180 行限制（它本来就不是每轮注入的那一份）
    """
    out = []
    for sub, _plat in PLATFORM_RULES:
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(d, fn)
            text = read_text(path)
            head = text[:1200]
            always = bool(re.search(r"^alwaysApply\s*:\s*true", head, re.M))
            out.append((path, always, True))
    for cand in ("CLAUDE.md", "AGENTS.md"):
        p = os.path.join(root, cand)
        if os.path.exists(p):
            out.append((p, False, False))
    return out


def check_rules(root, cfg, f: Findings):
    """11) 常驻规则行数 12) 按需规则 frontmatter 完整"""
    limit = int(cfg.get("resident_rule_max_lines", 180))
    files = detect_rule_files(root, cfg)
    if not files:
        f.warn("纪律/规则", "-", 0,
               "没有找到平台规则文件（.trae/rules/ 或 .cursor/rules/ 或 CLAUDE.md）")
        return
    has_resident = any(is_res for _p, is_res, _pd in files)
    for path, is_resident, is_platform_dir in files:
        rp = rel(root, path)
        text = read_text(path)
        n = len(text.splitlines())

        if is_resident and n > limit:
            f.error("纪律/规则", rp, n,
                    f"常驻规则 {n} 行，超过上限 {limit} 行（会挤占上下文）")
        if is_resident and "## " not in text:
            f.warn("纪律/规则", rp, 0, "常驻规则里没有分节标题，可能没按模板写")

        if not is_platform_dir:
            # AGENTS.md / CLAUDE.md：只做提示，不强制 frontmatter
            if not re.search(r"^#{1,2}\s", text, re.M):
                f.warn("纪律/规则", rp, 0, "没有一级标题，可能不是一份说明书")
            continue

        if not text.startswith("---"):
            f.error("纪律/规则", rp, 1, "缺少 frontmatter（--- 开头）")
            continue
        end = text.find("\n---", 3)
        if end == -1:
            f.error("纪律/规则", rp, 1, "frontmatter 没有闭合的 ---")
            continue
        fm = text[3:end]
        if not re.search(r"^\s*description\s*:", fm, re.M):
            f.error("纪律/规则", rp, 1, "frontmatter 缺 description 字段")
        if not re.search(r"^\s*alwaysApply\s*:", fm, re.M):
            f.error("纪律/规则", rp, 1, "frontmatter 缺 alwaysApply 字段")
        if not is_resident and not re.search(r"^\s*globs\s*:", fm, re.M):
            f.error("纪律/规则", rp, 1,
                    "按需规则缺 globs 字段（不带 globs 就永远不会被自动加载）")
    if files and not has_resident:
        f.error("纪律/规则", "-", 0,
                "平台规则目录里没有 alwaysApply: true 的常驻规则文件 —— "
                "每轮注入的硬约束就没有来源了")


def check_reject_list(root, cfg, f: Findings):
    """13) 禁止清单里混入了'本版本不做'的条目"""
    version_words = re.compile(r"本版本|当前版本|本期|这一版|V0\.1 阶段不做")
    # 说明性文字不算违规（引用块 / 明显在讲"该写到别处"的话）
    explain = re.compile(r"请写到|移到|应写到|不要混|不应放|另行写|见.*版本范围")
    for path in iter_files(root, cfg, exts=(".md",)):
        rp = rel(root, path)
        if not re.search(r"(REPO|ROOT)", rp) and "AGENTS" not in rp \
                and "rules" not in rp:
            continue
        text = read_text(path)
        lines = text.splitlines()
        in_reject = False
        for i, ln in enumerate(lines):
            if re.search(r"绝对禁止|Reject\s*List|禁止清单", ln):
                in_reject = True
                continue
            if in_reject and re.match(r"^#{2,3}\s", ln):
                in_reject = False
                continue
            if not in_reject:
                continue
            s = ln.strip()
            if s.startswith(">") or explain.search(s):
                continue          # 说明 / 引用块，跳过
            if not s.startswith(("-", "*", "|")):
                continue          # 只检查真正的清单条目
            if version_words.search(s):
                f.error("纪律/RejectList", rp, i + 1,
                        "禁止清单里出现'本版本不做'类条目 —— 进新版本时会忘了删，"
                        "应移到'当前版本范围'一节")


def check_pending_markers(root, cfg, f: Findings):
    """14) 所有 ⚙️ 待确认 是否都在 OPEN-QUESTIONS.md 里登记"""
    marker = re.compile(r"⚙️\s*待确认|⚙️\s*待你确认")
    oq = None
    for cand in ("OPEN-QUESTIONS.md",):
        p = os.path.join(root, cand)
        if os.path.exists(p):
            oq = read_text(p)
    for path in iter_files(root, cfg, exts=(".md",)):
        rp = rel(root, path)
        if os.path.basename(path) == "OPEN-QUESTIONS.md":
            continue
        text = read_text(path)
        hits = [i + 1 for i, ln in enumerate(text.splitlines()) if marker.search(ln)]
        if not hits:
            continue
        if oq is None:
            f.warn("纪律/待确认", rp, hits[0],
                   f"有 {len(hits)} 处 ⚙️ 待确认，但项目里没有 OPEN-QUESTIONS.md")
            continue
        # 粗测：至少要有相近数量的条目（无法逐条匹配，只提示量级）
        oq_lines = len(re.findall(r"^\|\s*\d+\s*\|", oq, re.M))
        f.info("纪律/待确认", rp, hits[0],
               f"{len(hits)} 处 ⚙️ 待确认（OPEN-QUESTIONS.md 现有 {oq_lines} 条）")


def check_no_orphan_facts(root, cfg, f: Findings):
    """15) 目录树与实际结构分叉的粗测"""
    conv = os.path.join(root, "REPO_CONVENTION.md")
    if not os.path.exists(conv):
        return
    text = read_text(conv)
    m = re.search(r"```[a-zA-Z]*\n([^`]{20,})```", text)
    if not m:
        f.warn("纪律/目录树", "REPO_CONVENTION.md", 0,
               "没有找到目录树代码块（目录结构应写在这里）")
        return
    tree = m.group(1)
    # 抽出看起来像顶层条目名字，检查是否存在
    names = set(re.findall(r"^\s*[│├└─\s]*([\w.\-]+)/", tree, re.M))
    actual = {d for d in os.listdir(root)
              if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")}
    if actual and names:
        only_in_doc = {n for n in names if n not in actual
                       and not n.startswith("{{") and "." not in n}
        only_in_fs = {d for d in actual
                      if d not in names and d not in {
                          "evals", "docs", "scripts", "tests", "app", "src",
                          "config", "alembic", "migrations"}}
        if only_in_fs:
            f.warn("纪律/目录树", "REPO_CONVENTION.md", 0,
                   f"目录树里没画这些实际存在的目录：{sorted(only_in_fs)}")


def check_deprecated_terms(root, cfg, f: Findings):
    """16) 术语表里标为「已废弃」的旧名，全库是否还有残留

    术语表是唯一事实来源：只要它把某个名字标成废弃（删除线 `~~x~~`，或写
    "禁止 `x`"），这里就全库扫一遍 —— 防的是"改完这次、下次又长回来"。
    实测这一族词漂移过 4 次（scope_hash / user_scope / get_user_scope /
    user_scope_keys 被当参数名用），所以它值得一条自动检查，而不是靠人记得复查。
    ★ 但这条检查只能抓"白名单之外的拼写"；"白名单之内的错位"由下一项负责。
    """
    gloss = None
    for cand in ("docs/glossary.md", "glossary.md"):
        p = os.path.join(root, cand)
        if os.path.exists(p):
            gloss = p
            break
    if gloss is None:
        return
    text = read_text(gloss)
    banned = set(re.findall(r"~~`([A-Za-z_][\w.]*)`~~", text))
    banned |= set(re.findall(
        r"禁止(?:再出现|写成|使用|出现|用)?[^`\n]{0,8}`([A-Za-z_][\w.]*)`", text))
    banned = {b for b in banned if len(b) >= 4}
    if not banned:
        return

    # 「在讨论命名」的行不算违规 —— 这些行本来就必须写出旧名
    discuss = re.compile(r"~~|禁止|废弃|旧名|旧别名|写成|漂移|❌|历史遗留|不要写")
    exts = (".md", ".py", ".ts", ".js", ".sql", ".yaml", ".yml", ".json")
    for path in iter_files(root, cfg, exts=exts):
        if os.path.abspath(path) == os.path.abspath(gloss):
            continue
        if f"{os.sep}.git{os.sep}" in path:
            continue
        rp = rel(root, path)
        for i, ln in enumerate(read_text(path).splitlines(), 1):
            if discuss.search(ln):
                continue
            for b in sorted(banned):
                if re.search(rf"\b{re.escape(b)}\b", ln):
                    f.error("纪律/废弃词", rp, i,
                            f"出现已废弃的旧名 `{b}` —— 术语表已把它标为禁用。"
                            f"该用哪个名字见 `docs/glossary.md` 第七节")


def _def_signatures(text):
    """产出 [(函数名, 参数文本, 行号)]。用括号配平取完整签名，支持跨行参数。"""
    out = []
    for m in re.finditer(
        r"^[ \t]*(?:async[ \t]+)?def[ \t]+([A-Za-z_]\w*)[ \t]*\(", text, re.M
    ):
        i = m.end() - 1                      # 指向 '('
        depth, j = 0, i
        while j < len(text):
            c = text[j]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        line = text.count("\n", 0, m.start()) + 1
        out.append((m.group(1), text[i + 1:j], line))
    return out


def check_name_roles(root, cfg, f: Findings):
    """17) 术语表登记为「函数名」的词不许当值名字用（反之亦然）

    上一项只能抓"白名单**之外**的拼写"。真正漏网的是**同一个拼写占了两处位置**：
    `user_scope_keys` 在术语表里登记为函数名，同时又被当参数名用
    （`search_chunks(query_vec, user_scope_keys)`）—— 名字**在白名单上**，
    所以废弃词扫不到它，可值名一侧已经长出了第二种拼写。

    判据：术语表那一行的「类型」列写的就是该词**允许出现的位置**。
    """
    gloss = None
    for cand in ("docs/glossary.md", "glossary.md"):
        p = os.path.join(root, cand)
        if os.path.exists(p):
            gloss = p
            break
    if gloss is None:
        return

    func_names, value_names = set(), set()
    for ln in read_text(gloss).splitlines():
        s = ln.strip()
        if not s.startswith("|") or "~~" in s:
            continue                          # 已废弃行交给「纪律/废弃词」
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        m = re.match(r"^`([A-Za-z_]\w*)\s*(?:\([^`]*\))?`", cells[0])
        if not m:
            continue
        if "函数名" in cells[1]:
            func_names.add(m.group(1))
        elif "值" in cells[1]:
            value_names.add(m.group(1))
    if not func_names and not value_names:
        return

    for path in iter_files(root, cfg, exts=(".py",)):
        rp = rel(root, path)
        src = read_text(path)
        for fname, params, line in _def_signatures(src):
            for ident in re.findall(r"\b([A-Za-z_]\w*)\b", params):
                if ident in func_names:
                    f.warn("纪律/命名空间", rp, line,
                           f"`{ident}` 在术语表里是**函数名**，此处却被当参数名用"
                           f"（函数 `{fname}`）—— 同一个拼写占了两处位置")
            if fname in value_names:
                f.warn("纪律/命名空间", rp, line,
                       f"`{fname}` 在术语表里是**值名**，此处却被定义成函数")
        for m in re.finditer(r"\b([A-Za-z_]\w*)[ \t]*=", src):
            if m.group(1) in func_names:
                line = src.count("\n", 0, m.start()) + 1
                f.warn("纪律/命名空间", rp, line,
                       f"`{m.group(1)}` 在术语表里是**函数名**，"
                       f"此处却出现在赋值 / 关键字传参位置")


def _find_constitution(root):
    """找到项目宪法文件（AGENTS.md / CLAUDE.md），没有则返回 None。"""
    for d in CONSTITUTION_DIRS:
        for name in CONSTITUTION_NAMES:
            p = os.path.join(root, name) if d == "." else os.path.join(root, d, name)
            if os.path.isfile(p):
                return p
    return None


def check_constitution_refs(root, cfg, f: Findings):
    """18) 宪法的硬规则编号 P-xx：定义连续 + 别处引用不悬空

    宪法（AGENTS.md）是这套文档体系的最高约束，它最容易出的两类问题都不是
    "内容写错"，而是**引用失配**：
      ① 别处写"见 AGENTS.md P-03"，宪法里根本没有 P-03 —— 读的人找不到依据；
      ② 删规则时把编号一起删了，编号出现空洞，历史引用改指向了别的内容。
    所以：编号不连续报 WARN（允许保留编号并标「已废止」），引用悬空报 ERROR。
    用旧编号（R1/R2）的项目自动跳过，不误报。
    """
    const = _find_constitution(root)
    if const is None:
        return
    rp_const = rel(root, const)
    text = read_text(const)
    defined = set(re.findall(r"\bP-(\d{2})\b", text))
    if not defined:
        f.info("纪律/宪法", rp_const, 0,
               "未发现 P-xx 形式的硬规则编号 —— 若本项目沿用 R1/R2 旧编号，"
               "本检查组自动跳过（新项目建议用 P-xx，见 AGENTS.md 模板第〇节）")
        return

    nums = sorted(int(n) for n in defined)
    missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
    if missing and not re.search(r"已废止|已作废|deprecated", text):
        f.warn("纪律/宪法", rp_const, 0,
               f"硬规则编号不连续，缺 {[f'P-{n:02d}' for n in missing]}"
               "（若是有意删除，请保留编号并标「已废止」，防止历史引用指错内容）")

    for path in iter_files(root, cfg, exts=(".md",)):
        if os.path.abspath(path) == os.path.abspath(const):
            continue
        rp = rel(root, path)
        for i, ln in enumerate(read_text(path).splitlines(), 1):
            for n in re.findall(r"\bP-(\d{2})\b", ln):
                if n not in defined:
                    f.error("纪律/宪法", rp, i,
                            f"引用了宪法里不存在的硬规则编号 P-{n} —— "
                            f"依据应在 `{rp_const}` 第四节，请先补规则或改引用")


def check_context_budget(root, cfg, f: Findings):
    """19) 上下文预算：按"文件什么时候进上下文"分类核行数

    为什么单独立一条：常驻规则的行数上限（check_rules 管的那个）只是冰山一角 ——
    真正拖垮会话的是"一堆各自看起来都合理的文件同时被加载"。
    本检查按加载时机分类：按需规则 / 项目宪法 / 台账 / 一般文档。
    常驻规则不在这里重复报（它由 check_rules 报 ERROR）。

    超限一律 WARN：因为"该拆还是该留"要人判断；只有常驻规则超限才是 ERROR。
    单文件豁免：首 5 行内写 `<!-- budget-exempt: 理由 -->`（见 context-budget.md）。
    """
    budget = cfg.get("budget") or BUDGET_DEFAULTS
    checked = 0
    for path in iter_files(root, cfg, exts=(".md",)):
        rp = rel(root, path)
        base = os.path.basename(path)
        text = read_text(path)

        m = BUDGET_EXEMPT.search("\n".join(text.splitlines()[:5]))
        if m:
            f.info("纪律/预算", rp, 0, f"已豁免预算（理由：{m.group(1)}）")
            continue

        in_rule_dir = any(rp.startswith(sub) for sub, _p in PLATFORM_RULES)
        if in_rule_dir:
            if re.search(r"^alwaysApply\s*:\s*true", text[:1200], re.M):
                continue                       # 常驻规则：check_rules 已管
            cat, limit = "按需规则", int(budget.get("ondemand_rule_max_lines", 150))
        elif base in CONSTITUTION_NAMES:
            cat, limit = "项目宪法", int(budget.get("constitution_max_lines", 300))
        elif base in LEDGER_NAMES:
            cat, limit = "台账", int(budget.get("ledger_max_lines", 300))
        else:
            cat, limit = "一般文档", int(budget.get("doc_max_lines", 600))
        checked += 1

        n = len(text.splitlines())
        if n > limit:
            f.warn("纪律/预算", rp, n,
                   f"{cat} {n} 行，超过预算 {limit} 行 —— 先搜「这段内容别处"
                   "有没有」（多半是违反了唯一事实来源），再考虑移出去或拆分；"
                   "确需保留则在本文件首 5 行加 `<!-- budget-exempt: 理由 -->`")
    f.info("纪律/预算", "-", 0, f"已按预算检查 {checked} 份文档")


# ---------------------------------------------------------------- 动词类
# 术语漂移（名词）由上面的废弃词 / 命名空间检查管；这里管**动词漂移**：
# 文档写下的可执行承诺——一条命令、一个"待实现"——与实现脱节。
# （rag-kb 实测：`make test -k permission` 写进硬门禁 H6 却从未跑通过；
#   kb_id 轴只在 permission.py 的 docstring 里承认，tasks.md 里没有。）


def _makefile_targets(root):
    """解析根目录 Makefile 的目标名集合；没有 Makefile 返回 None。"""
    path = os.path.join(root, "Makefile")
    if not os.path.isfile(path):
        return None
    targets = set()
    for line in read_text(path).splitlines():
        if line.startswith(("\t", " ")):
            continue  # recipe 行 / 续行
        m = re.match(r"^([a-zA-Z_][\w.-]*)\s*:", line)
        if m and "=" not in line.split(":")[0]:
            targets.add(m.group(1))
    return targets


def _make_command_targets(cmd: str):
    """从一条 make 命令串里提取 target 列表（跳过选项与变量赋值）。

    `make test T="-k permission"` 必须只解析出 [test]——带引号赋值后面的
    token 属于变量值，不是 target（否则会把合法用法误报成坏 target）。
    `make test -k permission` 则解析出 [test, permission]——
    permission 不是 Makefile 目标，这正是 rag-kb 踩过的坑。
    """
    targets, in_quote = [], False
    for tok in cmd.split():
        if in_quote:
            if '"' in tok:
                in_quote = False
            continue
        if "=" in tok:
            if tok.count('"') % 2 == 1:
                in_quote = True
            continue
        if tok.startswith("-"):
            continue
        targets.append(tok.strip("`'\""))
    return targets


def check_make_targets(root, cfg, f: Findings):
    """文档里的 `make ...` 命令，target 必须真实存在于 Makefile。

    验收命令写下来却没跑过 = 门禁画在墙上。本检查抓其中**可静态判定的
    一半**：target 不存在 → 命令从未可能跑通（选项语义如 `-k` 静态查不了，
    要靠"写下来当天跑一遍"）。只检查 inline code 与围栏代码块内的命令——
    裸叙述里的"make xxx 输出（…）"无法可靠切分命令与说明（实测误报源）。
    """
    targets = _makefile_targets(root)
    if targets is None:
        return
    inline_re = re.compile(r"`([^`\n]*\bmake\s[^`\n]*)`")
    fence_re = re.compile(r"^\s*(```|~~~)")
    for path in iter_files(root, cfg, exts=(".md", ".yaml", ".yml")):
        in_fence = False
        for i, line in enumerate(read_text(path).splitlines(), 1):
            if fence_re.match(line):
                in_fence = not in_fence
                continue
            cmds = [line] if in_fence else inline_re.findall(line)
            for cmd in cmds:
                # 复合命令按 && / || / ; / | 切开，逐段解析
                for part in re.split(r"&&|\|\||;|\|", cmd):
                    part = part.split("#", 1)[0]  # 剥掉行内注释
                    m = re.search(r"\bmake\s+(.+)", part)
                    if not m:
                        continue
                    for t in _make_command_targets(m.group(1)):
                        # target 必须长得像 make 目标（ASCII 标识符），
                        # 滤掉叙述尾巴里被吞进来的词（表名 / 中文说明）；
                        # "make" 本身永远不是 target（防二次匹配）。
                        if (
                            t
                            and t != "make"
                            and re.fullmatch(r"[A-Za-z_][\w.-]*", t)
                            and t not in targets
                        ):
                            f.warn(
                                "动词/命令",
                                rel(root, path),
                                i,
                                f"make 命令的 target `{t}` 不存在于 Makefile"
                                f"（命令：make {m.group(1).strip()}）——"
                                "若是当前阶段的门禁 / 验收命令，写进文档前必须"
                                "实际跑通过；若是未来阶段计划可忽略",
                            )


_GAP_PATTERN = re.compile(
    r"(?:要等|留到|留待|推迟到)\s*(?:V[\w.-]*\s*)?T\d+|待实现|尚未实现|not implemented\b",
    re.IGNORECASE,
)
_TODO_PATTERN = re.compile(r"\b(TODO|FIXME)\b")


def check_unimplemented_notes(root, cfg, f: Findings):
    """代码注释里承认的缺口，必须能在 tasks.md / OPEN-QUESTIONS.md 找到落点。

    注释是给读代码的人的，不是给排期的人的——只住在注释里的缺口对规划
    不可见。**编号出现在任务清单里不等于覆盖**（rag-kb 实测：注释说
    "要等 T15"，T15 在清单里却只做了部门轴），所以命中一律 WARN，
    人工核对后二选一：入账，或在行内加「已入账」豁免标记。
    tests/ 跳过：护栏测试的 docstring 引用缺口是刻意为之。
    """
    ledger_paths = [
        os.path.join(root, "tasks.md"),
        os.path.join(root, "docs", "tasks.md"),
        os.path.join(root, "OPEN-QUESTIONS.md"),
    ]
    ledger = "".join(read_text(p) for p in ledger_paths if os.path.isfile(p))

    for path in iter_files(root, cfg, exts=(".py",)):
        rp = rel(root, path)
        if rp.startswith(("tests", "test")):
            continue
        for i, line in enumerate(read_text(path).splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith('"') and not stripped.startswith('"""'):
                continue  # 字符串字面量（如日志文案），不是注释 / docstring
            for m in _GAP_PATTERN.finditer(line):
                if "已入账" in line:
                    f.info(
                        "动词/缺口",
                        rp,
                        i,
                        f"注释承认缺口并已标注入账（{m.group(0).strip()}）——抽查即可",
                    )
                else:
                    f.warn(
                        "动词/缺口",
                        rp,
                        i,
                        f"注释承认缺口（{m.group(0).strip()}）——确认 tasks.md / "
                        "OPEN-QUESTIONS.md 里真的有落点（编号在清单里 ≠ 覆盖此缺口）；"
                        "核对无误后可在行内加「已入账」豁免",
                    )
            for m in _TODO_PATTERN.finditer(line):
                f.info(
                    "动词/缺口", rp, i, f"注释有 {m.group(1)}——确认已在任务清单或有意保留"
                )


# ---------------------------------------------------------------- 主流程

CHECKS = [
    ("格式类", check_yaml),
    ("格式类", check_openapi_refs),
    ("格式类", check_md_tables),
    ("格式类", check_html),
    ("一致性类", check_numbering),
    ("一致性类", check_counts),
    ("一致性类", check_star_count),
    ("纪律类", check_rules),
    ("纪律类", check_reject_list),
    ("纪律类", check_pending_markers),
    ("纪律类", check_no_orphan_facts),
    ("纪律类", check_deprecated_terms),
    ("纪律类", check_name_roles),
    ("纪律类", check_constitution_refs),
    ("纪律类", check_context_budget),
    ("动词类", check_make_targets),
    ("动词类", check_unimplemented_notes),
]


def main():
    ap = argparse.ArgumentParser(description="前置文档集自检")
    ap.add_argument("root", nargs="?", default=".", help="项目根目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出问题")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"目录不存在：{root}")
        return 2

    cfg = load_config(root)
    f = Findings()
    for _name, fn in CHECKS:
        try:
            fn(root, cfg, f)
        except Exception as e:  # noqa: BLE001
            f.warn("脚本自身", "-", 0, f"检查 {fn.__name__} 出错：{e}")

    if args.json:
        print(json.dumps({
            "root": root,
            "errors": len(f.errors),
            "warns": len(f.warns),
            "items": f.items,
        }, ensure_ascii=False, indent=2))
        return 1 if f.errors else 0

    # 分组输出
    order = ["ERROR", "WARN", "INFO"]
    icon = {"ERROR": "✗", "WARN": "!", "INFO": "·"}
    by_group = defaultdict(list)
    for it in f.items:
        if args.quiet and it["level"] == "INFO":
            continue
        by_group[(it["level"], it["group"])].append(it)

    print("=" * 68)
    print(f"文档集自检 · {root}")
    print("=" * 68)
    for lvl in order:
        groups = [(k, v) for k, v in by_group.items() if k[0] == lvl]
        if not groups:
            continue
        for (lv, grp), items in sorted(groups):
            print(f"\n[{lv}] {grp}")
            for it in items:
                loc = it["path"] + (f":{it['line']}" if it["line"] else "")
                print(f"  {icon[lv]} {loc}  {it['msg']}")

    print("\n" + "-" * 68)
    print(f"结果：{len(f.errors)} 个 ERROR · {len(f.warns)} 个 WARN")
    if not f.errors:
        print("✓ 没有 ERROR（WARN 请人工判断是否需要处理）")
    print("-" * 68)
    return 1 if f.errors else 0


if __name__ == "__main__":
    sys.exit(main())
