---
name: exp-feasibility-review
description: 审查一份实验方案能不能开工。对照设备清单、库存、排期、样本量和伦理状态，逐项判断假设、对照、设备材料、工时、参数量程、风险处置和伦理安全；方案没写的内容记为缺口，不当成已经满足。Use when the task is 实验方案可行性评估, versioned feasibility review, challenge-2e2c5820, or a plan must be checked against resource, price and booking contracts before anyone treats it as executable.
---

# 实验方案可行性评估

脚本负责判定，模型负责把散落的原文整理成脚本能读的结构。不要凭常识补一台设备、一个货期或一次审批。

## 先跑

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work --verify
```

然后阅读 `/app/output/result.json` 和 `/app/output/review.md`。`status` 在文件里面，进程退出码 0 只表示文件写出来了。

如果 `status=failed` 且摘要写明没有候选方案，说明原文还没落成结构。按 `references/method.md` 的字段，把方案版本和合同整理到 `/app/work/normalized/case.json`，每个数字旁边留下原文定位，再对这个目录重跑一次。重跑结果是结论；整理过程里没有出处的数字不要写。

## 判定规则

七类都要出现：假设与变量、对照、设备、材料、工时与等待、参数量程、风险处置，另加样本和伦理。

- 设备只认方案点名的型号。清单里有别的设备，不能算这个方案已经具备。
- 状态分四档：已具备、可外协、需采购、不具备。后三档不能记成通过。
- 库存少于用量时，货期进入等待；库存够则货期不进入关键路径。
- 参数值只有在单位一致、并且设备写明它测量的就是这个参数时，才和量程比较。越界是硬失败。
- 风险必须同时有触发条件和处置。“注意安全”是缺口。
- 出现人体、动物、危险试剂或个人数据时，没有已覆盖的审批状态就不能开工。
- 工时只累加步骤里写了小时数的项，公式写进结果，缺项不按 0。

`feasible` 才表示这个版本可以开工。`conditional` 必须把条件写全。`infeasible` 不能被改写成“基本可行”。

## 不要做的事

不要改脚本算出的通过/失败。不要把 PDF 文件名当成实验内容。不要生成一份原文里没有的新流程来替换被否决的方案。

## 自测

```bash
python3 /skills/weekly-skill/scripts/run_case.py --selftest
```

`examples/` 是示意，不是平台的三个正式案例。
