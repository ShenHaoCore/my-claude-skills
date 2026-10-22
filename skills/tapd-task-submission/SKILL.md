---
name: tapd-task-submission
description: "为开发人员推进 TAPD Task 状态（open→progressing→done）并登记/核对工时；当用户要求「完成任务」「记工时」「提交工时」「推进任务状态」时使用。⚠️ 涉及【创建工作项】（建 Task/Story/Bug/Epic、录任务）一律先走 tapd-create-guard 的校验流程，本 skill 只做状态推进与工时登记。不用于独立管理 Story、Bug 或迭代。"
metadata:
  short-description: "推进 TAPD Task 状态并登记工时（创建工作项请走 tapd-create-guard）"
---

# TAPD 开发任务：状态推进与工时登记

**建之前走 `tapd-create-guard`，建完之后推状态、记工时走这里。**

## 一、边界

| 你要做的事 | 走哪里 |
| --- | --- |
| 创建 Epic / Feature / Story / Task / Bug | `tapd-create-guard`（校验 → 全量草稿 → 确认 → 创建 → 回执） |
| **推进状态** open → progressing → done | **本技能** |
| **登记 / 核对 / 分摊工时** | **本技能**（校验脚本用 guard 的 `timesheet_guard.py`） |
| 修改已建工作项的字段 | `tapd-create-guard`（`update_change_guard.py` + `owner_match_guard.py`） |
| 查字段候选值 / 接口参数 | 官方 `tapd-skill`（工具参数的事实源） |

两条口径约束：

- **冲突时以 guard 为准**。本技能不要求"创建级逐字段全量确认"，但这**不降低**流转前的必填项确认要求（见第三节第 4 步）。
- 用户要创建时，**不要在本技能里就地开建**，直接切到 guard；本技能不复述创建流程。

## 二、可用工具

全部走 `tapd` 官方连接器（`mcp__tapd__*`），先只读再写，长 ID 按字符串传。

| 用途 | 工具 |
| --- | --- |
| 当前账号 | `get_current_user` |
| 查需求/任务 | `get_stories_or_tasks` |
| 更新状态 / effort / remain | `update_story_or_task` |
| 查工时 / 登记 / 改工时 | `get_timesheets` / `add_timesheets` / `update_timesheets` |
| 查工作项类型、自定义字段 | `get_workitem_types` / `get_entity_custom_fields` |
| 查流转规则 / 状态中英文映射 | `get_workflows_all_transitions` / `get_workflows_status_map` |

⚠️ 早前版本引用的 `tapd_create_task` / `tapd_create_timesheet` / `tapd_get_tasks` / `tapd_discover_tools` 在当前环境**不存在**（那是 Codex 环境的工具名）。

不要改用浏览器、`curl`、其他 MCP 或直接 HTTP 请求。

## 三、状态流转（流转前必须先查必填项）

TAPD 的必填校验发生在**流转那一刻**：界面上会弹窗让你填，但**通过 MCP 流转只会抛一个不友好的报错**，既不说缺什么、也不说该填什么。所以先备齐、再让用户过一眼。

**四步，不得跳步：**

1. **取规则** —— `get_workflows_all_transitions`（`system: story`，`workitem_type_id` 按对象类型）：返回的每条流转里 **`Appendfield[].Notnull == "yes"` 的字段就是该流转的必填项**。
2. **取当前值** —— `get_stories_or_tasks` 按 `id` 回读，`fields` 带上第 1 步那些必填字段。
3. **跑校验**：

   ```bash
   # 路径按本机 skills 布局定位；无 python3 时用 python。脚本缺失见下方降级
   python3 ~/.agents/skills/tapd-task-submission/scripts/transition_guard.py --workflow "wf.json" --list
   python3 ~/.agents/skills/tapd-task-submission/scripts/transition_guard.py \
     --workflow "wf.json" --from "未开始" --to "进行中" \
     --current "item.json" --suggest '{"due":"2026-10-16"}'
   ```

   退出码 `0`＝必填齐全 / `1`＝**有缺失，不得流转** / `2`＝输入错误。输出可直接当确认表用。
   **脚本不存在时降级**：手工读 `Appendfield[].Notnull`，逐字段比对当前值，同样要出全量表。
4. **全量展示 + 等确认** → 才调 `update_story_or_task`（至少 `id`、`workspace_id`、`status`）。
   - 有值 → 标「当前值」；缺值 → **先按上下文拟建议值**并标「建议值（待你确认）」，枚举只能取该空间已配置项，拟不出标「❓ 待你给」；
   - 用户改了任何字段 → **重出整张表**再确认。

**硬约束：**

1. 必填项没备齐、或用户没确认整表 → **不得流转**。
2. 转为 `progressing` 时**必须有处理人**。
3. 流转会**自动写系统字段**（实际开始 / 完成时间）——这是正常行为，不要手工去写。
4. 需要顺带补写字段时，先跑 `tapd-create-guard` 的 `update_change_guard.py`（补空可执行、覆盖需确认），**不要用 `update_story_or_task` 直接补洞**。
5. 处理人与当前授权账号无关时，按 guard 的「人员匹配提醒」醒目提示；用户坚持才放行。

已知口径（任务类）：状态只有 未开始 / 进行中 / 已完成；「未开始→进行中」「→已完成」**必填 5 项**＝处理人 + 任务类型 + 优先级 + 预计开始 + 预计结束；到「已完成」另需登记工时。

## 四、工时登记

**顺序固定：先查 → 校验 → 全量确认 → 写入 → 复查。**

1. **先查**：`get_timesheets` 按 `owner`（+ `spentdate`）拉当天已有记录并落盘。
2. **校验**：把已有工时 + 拟登记 JSON 喂给校验器：

   ```bash
   python3 ~/.agents/skills/tapd-task-submission/scripts/timesheet_guard.py \
     --pending "拟登记.json" --existing "已有工时.json"     # 默认上限 12h，--limit-hours 可调
   ```

   退出码 `0`＝不超限 / `1`＝超限 / `2`＝输入错误。**同一登记人同一花费日期合计 >12h → 醒目提示「请与主管确认工时的合理性」**，建议减少或分摊到其他日期；用户明确坚持原值才放行。
   **脚本不存在时降级**：自己按登记人 + 花费日期汇总已有与拟登记工时，超过上限（默认 12h）同样要醒目提示并等确认。
3. **全量确认**：人 / 日期 / 工时 / 关联对象逐项列出，确认后才调 `add_timesheets`。
4. **复查（不得跳过）**：登记完成后**重新**拉该登记人在每个花费日期的**全空间**工时（不限本次对象）重跑校验——别人可能刚好同天也登了。超限则醒目提醒，调整已入库记录用 `update_timesheets` 且方案须用户确认。

字段：`entity_type`（本技能统一传 `"story"`——TAPD 工时接口对 Story/Task 都记为 story，实际类型以 ID 反查为准）、`entity_id`、`workspace_id`、`owner`、`timespent`、`spentdate`、`memo`（可选）。单条 ≤24h；同一任务 + 日期 + 人员不重复建，已存在就改。

工时日期取当前日期（时区以本机为准，国内项目通常为 `Asia/Shanghai`）。

## 五、快捷完成任务

用户说「完成任务」「提交完成」，或创建时同时要求完成时：

1. 查 `get_stories_or_tasks` 拿 `effort` / `effort_completed` / `remain` / 当前状态；查 `get_timesheets` 拿当天已有工时。
2. 定当天工时：**用户给的数 > 任务 `remain` > `effort - effort_completed`**；都拿不到才问，**不能填 0 或凭空估算**。
3. 已有同日同人记录 → 只补差额，不重复建。
4. 登记成功后调 `update_story_or_task`：`status: "done"`、`effort_completed` 为累计值、`remain: 0`，必要时传 `current_user`。
5. **先建 `open` → 记工时 → 再标 `done`**：反序会让 TAPD 在工时登记前自动补齐整条预估工时。已是 `done` 的只补当天缺的工时，不重复改状态。
6. 回执按第六节格式返回。

## 六、回执格式

```
Task「<标题>」#<id>　<原状态> → <新状态>
工时：<日期> <h>h（累计 <X>h / 预估 <Y>h）　工时记录 ID：<id>
```

失败时给 TAPD 原始错误与已尝试的步骤，不循环重试。权限不足（`403` / `permission_denied`）时按 guard 话术回复：「无法创建/更新，授权用户权限不足，有疑问请联系项目经理」。

## 七、异常与范围变化

- 实际投入超预估 → **按真实值记并说明原因**，不为了好看少填。
- 需求理解错误或范围明显扩大 → 暂停，与产品确认 Story；**不要用原 Task 偷换成新需求**。
- 字段、状态或接口路径不确定 → 查 [TAPD 任务 API](https://open.tapd.cn/document/api-doc/API%E6%96%87%E6%A1%A3/api_reference/task/)，不凭 REST 直觉猜路径。

> 任务规范（层级、必填字段、状态口径、例外情形）见 [references/tapd-task-rules.md](references/tapd-task-rules.md)。

## 附：脚本说明

本技能自带两个纯标准库校验脚本（无第三方依赖）：

| 脚本 | 用途 |
| --- | --- |
| `scripts/transition_guard.py` | 比对流转规则里的必填项与当前值，输出缺失清单 |
| `scripts/timesheet_guard.py` | 汇总单人单日工时，校验是否超过上限 |

两者都只读 JSON 文件、只写标准输出，退出码 `0/1/2` 分别表示通过 / 有问题 / 输入错误。
