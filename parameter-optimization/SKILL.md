---
name: exp-parameter-optimization
description: 在设备量程、材料上限和安全阈值的交集里给出可执行参数，并用已有实验点排序；域外的高响应点丢弃，没有实测响应时不预测最优值。Use when the task is 实验参数优化建议, parameter optimization under a finite domain, challenge-ec02b694, or a suggested setpoint must stay inside equipment, material and safety limits with an explicit cost.
---

# 实验参数优化建议

建议值必须落在有限可行域的网格上。脚本计算交集、网格、已观测点的排序和费用；模型只负责把手册和历史表整理成这些字段。

## 先跑

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work --verify
```

阅读 `/app/output/result.json`。如果 `status=failed`，按 `references/method.md` 把参数界限、步进、历史响应和预算整理到 `/app/work/normalized/case.json` 再跑。界限没有出处就不要填。

## 判定规则

- 可行域是陈述区间、设备量程、材料上限、安全阈值里单位一致的那些界限的交集。
- 下界高于上界时可行域为空，不给建议值，只列出冲突的界限。
- 有步进时，可执行点只能取网格点。历史最优点如果不在网格上，不能直接当成建议值。
- 域外的历史点即使响应更好也排除，并写明排除原因。
- 没有写明越大越好还是越小越好时，不排名。
- 没有落在域内的响应时，只安排初始网格，`response` 保持空，不写预测值。
- 费用只在机时、机时单价、耗材单价都有数字时计算：`per_run = hours_per_run * machine_hour_cost + consumable_cost`。缺一项就不算总价。
- `max_runs` 扣掉已有历史点数，剩余为 0 就不再追加。

## 不要做的事

不要把域外最优点改成推荐值。不要用经验补一个“通常 60 度”。不要在脚本把域判空之后再写一个折中温度。

## 自测

```bash
python3 /skills/weekly-skill/scripts/run_case.py --selftest
```

`examples/` 是示意，不是平台正式案例。
