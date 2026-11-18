---
name: exp-result-interpretation
description: 解释一张实验读数表的趋势、异常行、与批次或通道的共变、可执行的复核步骤。斜率用最小二乘，异常用中位数绝对偏差，没有共变因子时不写机理。Use when the task is 实验结果解释与异常分析, experimental result interpretation, challenge-8354c69a, or raw traces, a workbook or a csv must be tied back to rows, thresholds and a next check.
---

# 实验结果解释与异常分析

先算，再写句子。趋势、异常行和分组差异都以表里的数字为准。

## 先跑

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work --verify
```

阅读 `/app/output/result.json` 的 `series`、`anomalies` 和 `causes`。如果 `status=failed`，把工作簿或原文里的表整理成 csv 或 `measurements` 数组，列名保留原词，放到 `/app/work/normalized/` 再跑。不要预填哪一行是异常。

## 计算规则

- 斜率：`Σ((x-mean_x)*(y-mean_y)) / Σ((x-mean_x)^2)`。横轴缺失时用行号，并在结果里标明。
- 至少 5 个有效点才做异常判断。阈值是 `3 * 1.4826 * MAD`；MAD 为 0 时，只标出不等于中位数的点。
- 点数少于 5 时不叫异常，状态保持 `partial`。
- 批次或通道要同时满足：它覆盖至少 80% 的异常行，并且另有一个不少于 2 行、零异常的组。这是共变，`mechanism` 固定为空。
- 如果各组的横轴区间互不重叠，合并斜率标成与该分组混杂，不能单独当成时间效应。
- 复核步骤只指向文件、列和行号，或要求用同一横轴重跑被指出的那一组。

## 不要做的事

不要把异常行解释成原文没写的降解、污染或仪器漂移。不要为了让斜率“好看”删点。不要在点数不够时仍给一个异常名单。

## 自测

```bash
python3 /skills/weekly-skill/scripts/run_case.py --selftest
```

`examples/` 是示意，不是平台正式案例。
