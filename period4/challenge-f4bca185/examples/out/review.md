# 记录

- case_id: example
- status: success
- mode: table/clean

示意输出，不是平台正式案例，不能当作正式答案。

## 结论

清洗 3 行，保留 3 行，缺失单元格 0 个未填补，重复组 0 个。

## 不确定项

- 缺失和无效值保持为空，没有用均值或 0 填补。

## 留痕

- 只标记缺失、去掉完全重复的行，并按字典中的换算系数转换。（{'rows_in': 3, 'rows_out': 3, 'missing_cells': 0, 'duplicate_groups': 0, 'conversions': 0, 'imputed_cells': 0}）
