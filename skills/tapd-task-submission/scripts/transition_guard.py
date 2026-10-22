#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TAPD 状态流转「必填字段」校验器
配套技能：tapd-task-submission

作用：给定某类工作项的**工作流流转细则**（mcp__tapd__get_workflows_all_transitions 的返回）
      + 该工作项的**当前值**（mcp__tapd__get_stories_or_tasks 的返回），
      算出「某条流转要求哪些必填字段」，并逐个对照当前值，输出可直接给用户确认的全量表。

用法:
  # 列出该类型的全部流转及各自必填字段
  python transition_guard.py --workflow wf.json --list

  # 校验「未开始 → 进行中」这条流转（当前值缺失的会标出来）
  python transition_guard.py --workflow wf.json --from 未开始 --to 进行中 --current item.json

  # 若已按经验给空缺字段拟了建议值，一并带上（让脚本直接输出"全量确认表"）
  python transition_guard.py --workflow wf.json --to 进行中 --current item.json \
      --suggest '{"begin":"2026-10-14","due":"2026-10-16"}'

  # 状态名中英文对照表可覆盖（默认内置常用映射）
  python transition_guard.py --workflow wf.json --to 进行中 --current item.json --status-map sm.json

退出码: 0=该流转必填字段都有值(仍需用户确认)  1=有缺失(不得流转)  2=输入错误
"""

import argparse
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------- 状态名映射
# TAPD 用英文状态名（open/progressing/done…），这里内置常用对照；
# 实际项目可用 --status-map 覆盖（或从 get_workflows_status_map 的返回直接存成 json）。
STATUS_CN_DEFAULT = {
    "start": "开始",
    "open": "未开始",
    "planning": "规划中",
    "progressing": "进行中",
    "proceeding": "进行中",
    "resolved": "已解决",
    "verified": "已验证",
    "done": "已完成",
    "closed": "已关闭",
    "rejected": "已拒绝",
    "end": "已结束",
    "draft": "草稿",
}

# 系统级开关字段（不是业务字段，流转时由 TAPD 自己处理）
SYSTEM_FIELDS = {"enable_add_timesheet": "登记工时（系统项）"}


def cn_status(code, status_map):
    """英文状态名 → 中文；查不到就原样返回。"""
    if code is None:
        return ""
    return status_map.get(code, code)


def norm_status(raw, status_map):
    """把用户输入的中文/英文状态名统一成英文代码；识别不了就返回原值。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in status_map:
        return s
    for code, label in status_map.items():
        if s == label:
            return code
    return s


# ---------------------------------------------------------------- 载入
def load_json(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return json.loads(raw)


def load_workflow(path):
    """兼容三种形态：MCP 原始返回 / {"data":[...]} / 裸数组。返回 transitions 列表。"""
    obj = load_json(path)
    if isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise SystemExit("无法识别 workflow 结构：期望 {'data': [...]} 或裸数组")
    if isinstance(obj, list):
        return obj
    raise SystemExit("无法识别 workflow 结构：期望 {'data': [...]} 或裸数组")


def load_item(path):
    """兼容 MCP 工作项返回；返回 field -> value 的扁平字典。"""
    obj = load_json(path)
    if isinstance(obj, dict) and isinstance(obj.get("data"), list) and obj["data"]:
        row = obj["data"][0]
        if isinstance(row, dict):
            for k in ("Story", "Bug", "Task"):
                if isinstance(row.get(k), dict):
                    return row[k]
            return row
    if isinstance(obj, list) and obj:
        row = obj[0]
        if isinstance(row, dict) and isinstance(row.get("Story"), dict):
            return row["Story"]
        if isinstance(row, dict):
            return row
    if isinstance(obj, dict):
        return obj
    raise SystemExit("无法识别 current 结构：期望 MCP 工作项返回、{'Story':{...}} 或裸对象")


def is_blank(v):
    if v is None:
        return True
    s = str(v).strip()
    return s in ("", "0", "0.0", "-1", "none", "null", "nan", "-", "—", "未分类", "无")


# ---------------------------------------------------------------- 解析流转
def transition_required(tr):
    """从一条流转里拆出「业务必填」与「系统必填」。"""
    biz, sysf, optional = [], [], []
    for af in (tr.get("Appendfield") or []):
        field = af.get("FieldName") or ""
        label = SYSTEM_FIELDS.get(field) or af.get("FieldLabel") or field
        item = {
            "field": field,
            "label": label,
            "notnull": (str(af.get("Notnull") or "").strip().lower() == "yes"),
            "type": af.get("Type") or "",
            "sort": af.get("Sort") or 999,
        }
        if field in SYSTEM_FIELDS:
            sysf.append(item)
        elif item["notnull"]:
            biz.append(item)
        else:
            optional.append(item)
    biz.sort(key=lambda x: x["sort"])
    sysf.sort(key=lambda x: x["sort"])
    optional.sort(key=lambda x: x["sort"])
    return biz, sysf, optional


def find_transitions(txs, frm, to, status_map):
    out = []
    for tr in txs:
        prev = tr.get("StepPrevious")
        nxt = tr.get("StepNext")
        if frm and prev != frm and prev != cn_status(prev, status_map):
            continue
        if to and nxt != to and nxt != cn_status(nxt, status_map):
            continue
        out.append(tr)
    return out


def render_list(txs, status_map):
    lines = ["该工作项类型的全部状态流转（含各自必填字段）", "=" * 46, ""]
    for tr in txs:
        biz, sysf, _opt = transition_required(tr)
        prev = cn_status(tr.get("StepPrevious"), status_map)
        nxt = cn_status(tr.get("StepNext"), status_map)
        lines.append("· %s（%s） → %s（%s）" % (prev, tr.get("StepPrevious"), nxt, tr.get("StepNext")))
        if biz:
            lines.append("    必填：%s" % "、".join("%s(%s)" % (i["label"], i["field"]) for i in biz))
        else:
            lines.append("    必填：（无业务必填字段）")
        if sysf:
            lines.append("    系统项：%s" % "、".join(i["label"] for i in sysf))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程
def build_report(tr, item, suggest, status_map):
    biz, sysf, _opt = transition_required(tr)
    rows = []
    missing = []
    for spec in biz:
        field = spec["field"]
        cur = item.get(field)
        from_suggest = False
        if is_blank(cur) and suggest and field in suggest:
            cur = suggest[field]
            from_suggest = True
        blank = is_blank(cur)
        if blank:
            missing.append(spec)
        rows.append({
            "field": field,
            "label": spec["label"],
            "value": "" if cur is None else str(cur),
            "source": "当前值" if not from_suggest else "建议值（待你确认）",
            "status": "missing" if blank else "ok",
            "blank": blank,
        })
    return {
        "from": tr.get("StepPrevious"),
        "to": tr.get("StepNext"),
        "from_cn": cn_status(tr.get("StepPrevious"), status_map),
        "to_cn": cn_status(tr.get("StepNext"), status_map),
        "name": tr.get("Name"),
        "fields": rows,
        "system_fields": [{"field": i["field"], "label": i["label"]} for i in sysf],
        "missing": [{"field": i["field"], "label": i["label"]} for i in missing],
        "ok": not missing,
    }


def render_text(reports, status_map):
    lines = ["TAPD 状态流转必填字段校验", "=" * 46, ""]
    for r in reports:
        lines.append("流转：%s（%s） → %s（%s）" % (r["from_cn"], r["from"], r["to_cn"], r["to"]))
        lines.append("")
        lines.append("| 字段 | 标签 | 当前值 / 建议值 | 来源 | 状态 |")
        lines.append("|---|---|---|---|---|")
        for f in r["fields"]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                f["field"], f["label"], f["value"] or "（空）", f["source"],
                "✗ 缺" if f["blank"] else "✓"))
        lines.append("")
        if r["system_fields"]:
            lines.append("系统项（TAPD 自动处理）：%s" % "、".join(i["label"] for i in r["system_fields"]))
        if r["ok"]:
            lines.append("结论：该流转要求的必填字段**都有值** —— 仍须把上表全量展示给用户确认后才可流转。")
        else:
            lines.append("结论：**有 %d 项必填空缺**（%s）—— 先按经验/上下文拟建议值补上，再全量展示给用户确认；"
                         "**确认通过前不得流转**。"
                         % (len(r["missing"]), "、".join(i["label"] for i in r["missing"])))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="TAPD 状态流转必填字段校验")
    ap.add_argument("--workflow", required=True,
                    help="工作流流转细则 JSON（get_workflows_all_transitions 的返回；支持 - 读 stdin）")
    ap.add_argument("--current", help="该工作项当前值 JSON（get_stories_or_tasks 的返回）")
    ap.add_argument("--from", dest="frm", help="起始状态（中/英文名，可省略）")
    ap.add_argument("--to", help="目标状态（中/英文名）")
    ap.add_argument("--suggest", help="给空缺字段拟的建议值 JSON，如 '{\"begin\":\"2026-10-14\"}'")
    ap.add_argument("--status-map", help="状态中英文映射 JSON（可选，覆盖内置）")
    ap.add_argument("--list", action="store_true", help="列出全部流转及必填字段后退出")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    status_map = dict(STATUS_CN_DEFAULT)
    if args.status_map:
        extra = load_json(args.status_map)
        if isinstance(extra, dict):
            status_map.update({str(k): str(v) for k, v in extra.items()})

    txs = load_workflow(args.workflow)

    if args.list:
        print(render_list(txs, status_map))
        return 0

    if not args.to:
        print("需要指定 --to（目标状态），或加 --list 查看全部流转", file=sys.stderr)
        return 2

    frm = norm_status(args.frm, status_map)
    to = norm_status(args.to, status_map)
    hits = find_transitions(txs, frm, to, status_map)
    if not hits:
        print("没找到匹配的流转（from=%s to=%s）。用 --list 看看可用流转。"
              % (args.frm or "任意", args.to), file=sys.stderr)
        return 2

    item = load_item(args.current) if args.current else {}
    suggest = json.loads(args.suggest) if args.suggest else None

    reports = [build_report(tr, item, suggest, status_map) for tr in hits]

    if args.format == "json":
        print(json.dumps({"ok": all(r["ok"] for r in reports), "reports": reports},
                         ensure_ascii=False, indent=2))
    else:
        print(render_text(reports, status_map))

    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
