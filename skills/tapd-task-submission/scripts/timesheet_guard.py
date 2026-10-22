#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TAPD 工时登记校验器（2026-10-13 新增）
规则（用户要求）：同一登记人（owner）同一花费日期（spentdate）的工时合计，
已有 + 拟登记 之和超过上限（默认 12h）→ 提示「请与主管确认工时的合理性」，建议修改或分摊到不同日期。

用法:
  # 1) 把 get_timesheets 拉到的已有工时落盘，把拟登记的工时写成 JSON（数组或单对象）
  #    拟登记字段: owner(登记人) / spentdate(YYYY-MM-DD) / timespent(小时) / entity_type / entity_id / memo(可选)
  python timesheet_guard.py --pending "拟登记.json" --existing "已有工时.json"
  # 2) 只看某人某天现状（不校验拟登记）:
  python timesheet_guard.py --existing "已有工时.json" --owner "<当前授权账号昵称>" --date "2026-10-13"
  # 3) 自定义上限:
  python timesheet_guard.py --pending "拟登记.json" --existing "已有工时.json" --limit-hours 10
  # 4) 全周期健康检查（某用户近 2 个月所有日期的超 12h 明细）:
  #    先分页拉取: get_timesheets(owner=用户, limit=200 逐页翻) 落盘 → 再跑:
  python timesheet_guard.py --existing "全部工时.json" --owner "<当前授权账号昵称>" --since "2026-08-13" --over-only

已有工时文件兼容两种格式:
  - get_timesheets 原始返回: {"status":1,"data":[{"Timesheet":{...}}, ...]}
  - 扁平数组: [ {...}, ... ]（字段名一致即可）

退出码: 0=全部不超限（仍需按流程给用户确认后再登记）
        1=存在超限（提示修改 / 分摊；用户明确坚持原值才可放行登记）
        2=输入格式错误
"""
import argparse
import json
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_LIMIT = 12.0
VALID_ENTITY = {"story", "task", "bug"}


def load_json(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return json.loads(raw)


def flatten_timesheets(raw):
    """把 get_timesheets 返回或扁平数组统一成记录列表。"""
    if isinstance(raw, dict):
        data = raw.get("data", [])
    elif isinstance(raw, list):
        data = raw
    else:
        raise ValueError("已有工时文件格式无法识别")
    out = []
    for item in data:
        rec = item.get("Timesheet", item) if isinstance(item, dict) else None
        if not isinstance(rec, dict):
            continue
        if str(rec.get("is_delete", "0")) == "1":
            continue  # 已删除的工时不计入合计
        out.append(rec)
    return out


def to_hours(v):
    """工时字符串/数字 → float；无法解析返回 None。"""
    try:
        return float(str(v).strip().replace("h", "").replace("H", "").replace("小时", ""))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--pending", help="拟登记工时 JSON 文件（数组或单对象）；传 - 从 stdin 读")
    ap.add_argument("--existing", help="已有工时 JSON 文件（get_timesheets 落盘）；传 - 从 stdin 读")
    ap.add_argument("--owner", help="只看模式：指定登记人")
    ap.add_argument("--date", help="只看模式：指定花费日期 YYYY-MM-DD")
    ap.add_argument("--since", help="健康检查：只统计 spentdate >= 此日期（YYYY-MM-DD），如近 2 个月起点")
    ap.add_argument("--over-only", action="store_true",
                    help="健康检查：只输出超限的组合（审计模式）")
    ap.add_argument("--limit-hours", type=float, default=DEFAULT_LIMIT,
                    help="单人单日合计上限，默认 12 小时")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    if not args.existing and not args.pending:
        print("需要 --existing 和/或 --pending（详见 --help）", file=sys.stderr)
        return 2

    try:
        existing = flatten_timesheets(load_json(args.existing)) if args.existing else []
        pending = load_json(args.pending) if args.pending else []
    except (json.JSONDecodeError, ValueError, OSError) as e:
        print("输入文件解析失败：%s" % e, file=sys.stderr)
        return 2
    if isinstance(pending, dict):
        pending = [pending]

    # ---- 汇总键：(owner, spentdate)；值 = 明细列表
    buckets = defaultdict(list)

    for rec in existing:
        owner = str(rec.get("owner") or "").strip().rstrip(";")
        date = str(rec.get("spentdate") or "").strip()
        hours = to_hours(rec.get("timespent"))
        if not owner or not date or hours is None:
            continue
        buckets[(owner, date)].append({
            "来源": "已有",
            "entity_type": str(rec.get("entity_type") or ""),
            "entity_id": str(rec.get("entity_id") or ""),
            "timespent": hours,
            "memo": rec.get("memo") or "",
        })

    pending_errors = []
    for i, p in enumerate(pending, 1):
        if not isinstance(p, dict):
            pending_errors.append("第 %d 条拟登记不是对象" % i)
            continue
        owner = str(p.get("owner") or "").strip().rstrip(";")
        date = str(p.get("spentdate") or "").strip()
        hours = to_hours(p.get("timespent"))
        etype = str(p.get("entity_type") or "").strip().lower()
        if not owner or not date or hours is None:
            pending_errors.append(
                "第 %d 条拟登记缺 owner/spentdate/timespent 或工时不是数字（got owner=%r date=%r timespent=%r）"
                % (i, p.get("owner"), p.get("spentdate"), p.get("timespent")))
            continue
        if etype and etype not in VALID_ENTITY:
            pending_errors.append("第 %d 条 entity_type 应为 story/task/bug（got %r）" % (i, p.get("entity_type")))
            continue
        if hours <= 0:
            pending_errors.append("第 %d 条工时必须大于 0" % i)
            continue
        buckets[(owner, date)].append({
            "来源": "本次拟登记",
            "entity_type": etype,
            "entity_id": str(p.get("entity_id") or ""),
            "timespent": hours,
            "memo": p.get("memo") or "",
        })

    if pending_errors:
        for e in pending_errors:
            print("输入错误：%s" % e, file=sys.stderr)
        return 2

    # ---- 只看模式：过滤
    if args.owner or args.date or args.since:
        buckets = {k: v for k, v in buckets.items()
                   if (not args.owner or k[0] == args.owner)
                   and (not args.date or k[1] == args.date)
                   and (not args.since or k[1] >= args.since)}

    # ---- 输出
    results = []
    for (owner, date), items in sorted(buckets.items()):
        total = round(sum(it["timespent"] for it in items), 2)
        over = total > args.limit_hours
        results.append({
            "owner": owner, "spentdate": date, "total": total,
            "limit": args.limit_hours, "over": over, "items": items,
        })

    if args.over_only:
        results = [r for r in results if r["over"]]

    if args.format == "json":
        print(json.dumps({
            "ok": not any(r["over"] for r in results),
            "limit_hours": args.limit_hours,
            "results": results,
        }, ensure_ascii=False, indent=2))
        return 0 if not any(r["over"] for r in results) else 1

    lines = []
    lines.append("TAPD 工时登记校验（单人单日合计上限 %g h）" % args.limit_hours)
    lines.append("注：TAPD 工时接口对 Story/Task 的工时统一记为 entity_type=story，"
                 "记录显示 story 不代表对象一定是需求，实际类型以对象 ID 反查为准。")
    lines.append("=" * 52)
    if not results:
        if args.over_only:
            lines.append("✅ 审计完成：统计范围内**没有超 %g h 的「人+日期」组合**（可能本就没有工时数据，"
                         "或全部日期合计均在上限内）。" % args.limit_hours)
        else:
            lines.append("无工时记录（该范围下没有已登记或拟登记的数据）。")
    over_count = 0
    for r in sorted(results, key=lambda x: (x["owner"], x["spentdate"])):
        flag = "⚠️ 超限" if r["over"] else "✅ 正常"
        if r["over"]:
            over_count += 1
        lines.append("%s  %s  %s：%g h（上限 %g h）" % (flag, r["owner"], r["spentdate"], r["total"], r["limit"]))
        for it in r["items"]:
            lines.append("      · [%s] %s %s  %g h  %s"
                         % (it["来源"], it["entity_type"], it["entity_id"], it["timespent"], it["memo"]))
        if r["over"]:
            lines.append("      → ⚠️ 当天合计 %g h 已超 %g h 上限 —— 请与主管确认工时的合理性；"
                         "如需调整：减少本次登记工时，或分摊到其他日期（如 %s 前后顺延）。"
                         % (r["total"], r["limit"], r["spentdate"]))
    lines.append("")
    if over_count:
        lines.append("结论：有 %d 个「人+日期」组合超限 —— 醒目提示用户：请与主管确认工时的合理性；"
                     "如需调整可修改 / 分摊，用户明确坚持原值才可放行登记（须在确认页醒目展示）。" % over_count)
    else:
        lines.append("结论：全部不超限 —— 仍须按流程全量展示给用户确认后才可登记工时。")
    print("\n".join(lines))
    return 1 if over_count else 0


if __name__ == "__main__":
    sys.exit(main())
