---
name: exp-plan-comparison
description: 用同一套字段比较多个实验方案并给出可复核的取舍。先做可行性审查，只在可行且成本每一项都有数字的方案之间按成本选择，否决理由必须引用结论或数字。Use when the task is 实验方案比较与选择, aligned plan comparison, challenge-7be76e91, or several versioned plans must be chosen among using cost, risk and resource contracts.
---

# 实验方案比较与选择

比较前先把每个版本放进同一套可行性审查。便宜但设备不在清单里的方案不能赢。

## 先跑

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work --verify
```

阅读 `/app/output/result.json` 里的 `comparison_table`、`selection_reason` 和 `rejections`。方案还是散文时，先按 `references/method.md` 整理到 `/app/work/normalized/case.json`，每个成本数字都要有定位，再跑脚本。

## 选择规则

1. 每个方案先按可行性技能的规则得出 `feasible`、`conditional` 或 `infeasible`。
2. 只有 `feasible` 且成本字典里每一项都是数字的方案进入排序。
3. 按成本升序，成本相同再比方案自带的依据条数。成本相同要写明，不能说成“更便宜”。
4. 缺成本不按 0 参与比较。没有任何方案同时可行且成本完整时，`chosen_plan_id` 为空。
5. 每个落选方案都要有一条理由，引用可行性结论或两边的成本数字。

## 不要做的事

不要因为文献里常见就改选另一个方案。不要把三份散文各写一段当比较。不要补脚本没算出来的总分。

## 自测

```bash
python3 /skills/weekly-skill/scripts/run_case.py --selftest
```

`examples/` 是示意，不是平台正式案例。
