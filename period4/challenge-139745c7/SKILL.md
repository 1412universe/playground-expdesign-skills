---
name: corpus-index
description: 完成「科研文件智能检索」。只使用给定材料，缺失就留空，不补造文献、数字、审批或图。Use when the task is 科研文件智能检索, index, or challenge challenge-139745c7.
---

# 科研文件智能检索

脚本负责能从给定材料直接算清的部分。模型负责把散落的 PDF、表格和题录整理成脚本能读的结构。不要把常识补成实验结果。

## 先跑

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work --verify
```

然后阅读 `/app/output/result.json` 和 `/app/output/review.md`。`status` 在文件里面。进程退出码 0 只表示文件写出来了。

如果 `status=failed` 且摘要写明缺少结构，按 `references/method.md` 把材料整理到 `/app/work/normalized/case.json`。每个数字、题录和句子旁边留下原文定位，再对这个目录重跑一次。重跑结果是结论。整理时没有出处的内容不要写。

## 本题规则

- 为给出的文件建立索引，并保留别名和版本说明。
- 版本指向的记录如果不在材料里，就记缺口，不新建那条记录。

## 不要做的事

不要改脚本已经算出的数字、空值和排除决定。不要把文件名当成实验内容。不要生成一份材料里没有的文献、曲线或章节来填满输出。

## 自测

```bash
python3 /skills/weekly-skill/scripts/run_case.py --selftest
```

`examples/` 是示意，不是平台的三个正式案例。
