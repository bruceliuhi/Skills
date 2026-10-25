# 原生图表与表格

保持可见SVG与数据定义同步。图表不是截图：元数据生成PowerPoint原生图表及嵌入工作簿；表格生成可编辑单元格。内置chart.svg/table.svg是结构样例，数字和文字必须替换为本次用户资料。

## 共同结构

完整可见图形在 `<g id="业务对象键" data-pptx-bounds="x y w h" data-pptx-replace-with="chart或table">` 内。一个直接子 `<metadata type="application/json">` 提供对象的x/y/width/height/name与全部数据。可见图形、标签、刻度和JSON要一致，不能只改其中一处。

服务在工作副本同步数据对象指纹，并继续执行真实语义/质量检查；同步指纹不代表数据正确，不能用它掩盖图文不一致。自由设计的可见SVG是主要表达，JSON是对应投影；不要无故改成JSON优先来绕过检查。

## 常用图表

柱图 `type: column`、条形 `bar`、折线 `line`、面积 `area`、饼图 `pie`、环图 `doughnut` 使用 `categories` 和 `series:[{name,values}]`。每个序列值数量与类别相同，必须是有限数值；缺失值不能当零，百分比和金额先统一口径。

图表框位置使用明确x/y/width/height。`data_labels`可设置show_value、position、font_size、font_family、color；柱图值标签常用outside_end。轴口径在 `axes.category` 和 `axes.value`，包含kind/position/minimum/maximum/major_unit/major_gridlines等。刻度和坐标应与可见图形一致，不能截断纵轴夸大差异。

`style`写colors、font_family、axis_font_size、chart_area_fill、plot_area_fill、text_color、axis_color、grid_color。建议明确背景、线色和文字色，避免不同渲染器默认差异。原生语义支持范围比这份常用示例宽，但未经本次数据与预览验证的高级组合/特殊图表不能承诺成功；用户需要时先完成实际验证。

## 原生表格

兼容数据schema使用技术标识 `ppt-master.semantic-table.v2`（仅格式字段）。`columns`为标题、`rows`为正文，列数一致；`column_widths`与`row_heights`明确各列/行权重。`style`写font_family/font_size/header_font_size/border_color/border_width/band_row。`defaults.cell`给统一fill/color/valign/padding。

文本单元格可为字符串，或带text/fill/color/align/valign/bold/font_size的对象。金额/数字列使用 `align:"r"`，不是只在SVG上右对齐。所有表头、正文、汇总行及样式必须在JSON中，原生导出不会保留JSON之外的表格文字。

合并只用矩形row_span/col_span，覆盖格明确为merge_continuation；不能重叠或越界。长表拆页，避免生成几百行无法阅读的单页。

## 修改边界

当前云端的指定页修改保留原图表、工作簿、讲稿和非修改页组件，主要用于文字与可保留对象的版式调整。要改数值/表格结构/讲稿，重新根据明确材料生成版本，并向用户说明这是新建版本；不能伪称旧复杂PPT完全无损。
