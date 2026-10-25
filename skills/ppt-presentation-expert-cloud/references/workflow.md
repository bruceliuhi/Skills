# 从材料到真实文件

## 本地工作区

在用户允许的工作区建立本次独立目录。凭证文件建议放在工作区之外的私密位置或专用 `.ppt-cloud-credential.json`；脚本强制0600且不打印token。不要将其放入交付、Git、技能包或截图。

项目结构为 `svg_output/01_cover.svg`、`02_content.svg`等顺序页与 `notes/01_cover.md` 等同名讲稿。只上传这两处明确文件，不递归扫描其他目录。

以下命令中路径均替换为实际绝对路径；先确定脚本所在目录，不假定当前目录。命令只调用包内脚本。

```bash
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" health
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" create --project "<本次项目>" --receipt "<新建回执.json>"
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" wait --job "<返回任务编号>"
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" download --job "<任务编号>" --out "<尚不存在的成果目录>"
```

首次提交自动创建随机隔离凭证，无需注册其他平台。`status`随时查询原任务；等待超时不表示任务失败。回执含输入哈希，下载记录含所有真实成果哈希。

## 导入已有PPTX

```bash
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" import --pptx "<用户选中的原文件.pptx>" --receipt "<新回执.json>"
```

等待并下载后会得到原PPTX、逐页可用SVG、预览和检查报告。读取用户指定页，结合预览理解原版式。不要在导入前假设所有图片、公式或复杂对象都能安全重建。

## 指定页文字修改

建立新的修改JSON文件：

```json
[{"page":2,"find":"原页面上的唯一完整文字","replace":"用户要求的新文字"}]
```

```bash
python3 scripts/ppt_cloud.py --credential "<私密凭证路径>" edit --parent "<已成功原任务编号>" --changes "<修改.json>" --receipt "<新回执.json>"
```

页码从1起。原文必须唯一匹配；若匹配失败，读取导出的该页SVG与预览再定位，不做全文件盲替换。新任务会校验未改组件与原件保护。

## 指定页设计修改

基于导入得到的对应页完整SVG，在工作副本局部调整版式；保留原生对象的身份与引用。JSON项可使用 `{"page":2,"svg":"该页完整SVG文本"}`，与 `find/replace`互斥。服务不能保证任意复杂对象可重建；检查拒绝时保留原件，不删除原对象以绕过。

## 交付确认

结果包含 `deck.pptx`、`preview.pdf`、`page-*.png`、`report.json`；修改任务另有 `preservation.json`。PNG是预览，PPTX才是可编辑成果。请逐页查看，不只数文件。新建图表与表格核对原生对象数量和数据，讲稿核对页数。预览由LibreOffice转PDF生成，PowerPoint/WPS的个别字体效果可能不同。

服务限制或失败须如实说明。不能把未通过的任务改称成功，不能请求用户关闭系统安全设置。任务与材料24小时保留，凭证30天有效，过期后使用新的凭证文件建立会话。
