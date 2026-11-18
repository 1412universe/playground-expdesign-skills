# 方法与输入结构

脚本只使用整理后的数字。整理时每个数字都要能指回原文件的某一段；找不到就留空，不要填一个合理值。

示意例子在 `examples/`，`example_only: true`。平台的三个正式案例不在这个目录里。

## 方案与合同（可行性、比较）

```json
{
  "case_id": "来自输入",
  "plans": [{
    "id": "A",
    "hypothesis": "原文中的假设",
    "variables": [{"name": "temperature", "unit": "C"}],
    "controls": [{"name": "blank", "blocks": "它排除的混杂"}],
    "equipment": ["与清单一致的型号"],
    "materials": [{"name": "reagent", "qty": 1, "unit": "g"}],
    "steps": [{"id": "s1", "hours": 1.5}],
    "parameters": [{"name": "temperature", "value": 60, "unit": "C"}],
    "risks": [{"trigger": "触发条件", "mitigation": "处置"}],
    "samples": {"n_required": 8},
    "cost": {"machine": 10, "material": 5},
    "evidence": ["出处定位"]
  }],
  "contracts": {
    "equipment": [{"name": "oven-X", "status": "on_hand", "measures": "temperature", "min": 20, "max": 80, "unit": "C", "booking_days": 2}],
    "materials": [{"name": "reagent", "qty_on_hand": 5, "unit": "g", "lead_time_days": 5, "status": "on_hand"}],
    "samples": {"n_available": 20},
    "ethics": {"approval_status": "not_required"}
  }
}
```

`status` 只用 `on_hand`、`outsource`、`purchase`、`unavailable`，或原文里的“已具备 / 可外协 / 需采购 / 不具备”。

工时：`occupied_hours` 是步骤 `hours` 之和。等待天数是已具备设备的 `booking_days` 与“用量超过库存”的材料货期的最大值。

## 参数（优化）

`parameters[].limits` 记录每一条界限的来源。`step` 决定网格。`history[].response` 只填表上有的响应。`budget` 缺任何一项费用字段时，脚本不计算总价。

可行域是单位一致的下界最大值到上界最小值。下界高于上界则没有建议值。

## 读数（解释）

csv 或 `measurements` 数组。列名保留原文。脚本识别 `time` / `signal` / `batch` / `channel` 这类列；认不出横轴时用行号并标明。

异常规则只在有效行不少于 5 时启用。原因栏只在异常集中于某个批次或通道、且存在干净的对照分组时出现，并写明那是共变。

## 输出

`/app/output/result.json` 含 `case_id`、`status`、`experiment_plan`、`evidence_and_risks`、`confirmations`、`sources`、`uncertainties`、`change_log`。输入里的 `output_contract` 字段会被带上；对不上的字段保持空并写进不确定项。

`runtime_seconds` 是唯一允许随运行变化的字段。
