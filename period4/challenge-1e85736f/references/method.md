# 整理输入

脚本读取 `case.json`、同目录的表格、SQLite、XML 和文本。PDF 只有在运行环境有解析器时才读正文；读不到就记为未使用。

整理到 `/app/work/normalized/case.json` 时使用这些字段，名字可以不同，但不要另造一套没有出处的数字：

- 检索和资料：`documents` 或 `records`，每条有 `id`、`title`、`abstract`、`doi`、`year`、`source`。筛选条件放在 `criteria.inclusion` 和 `criteria.exclusion`。问题放在 `query`。
- 问答和审查：`paragraphs` 是 `{id, text}`，`questions` 是 `{id, text}`，审查面放在 `facets`。
- 提取：`fields` 是字段名列表，数值必须能在段落里靠近字段名读到。
- 比较：每份材料有 `condition`、`unit` 和 `measures`。
- 表格：CSV 或 `rows`。缺失标记和换算系数放在 `dictionary`。
- 数据库：SQLite 文件加一条 `query`。只接受单条只读查询。
- 写作：`sources` 是 `{id, text}`。译文是 `translations`，审稿意见是 `comments`，并且要带 `source_id`。
- 示意图：`entities` 和 `relations`。关系的 `source` 和 `target` 必须是实体的 `id`。

`output_contract` 里脚本没有算出的字段保持为 null，并写进不确定项。
