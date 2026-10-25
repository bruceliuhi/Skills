# PPT任务接口 v1

正式接口根路径：`https://www.tuokexing.net/ppt-service/v1`。

`GET /health`返回服务状态和实际限额。`POST /sessions {}`建立隔离会话，返回随机token、client_id和expires_at。后续请求使用 `Authorization: Bearer <token>`；token必须保密，不记录在应用输出或业务日志中。服务不验证WorkBuddy购买状态，当前会话用于有限免费体验。

## 创建任务

`POST /jobs`返回202、任务id与status_url。只接受以下操作：

```json
{"operation":"create","pages":[{"svg":"完整SVG","notes":"中文逐页讲稿"}]}
```

```json
{"operation":"import","pptx_base64":"用户明确选中的PPTX内容"}
```

```json
{"operation":"edit","parent_job_id":"同一会话下已成功任务id","changes":[{"page":2,"find":"唯一原文字","replace":"新文字"}]}
```

高级局部设计修改可把单个change改为 `{"page":2,"svg":"对应页完整SVG"}`。不可与find/replace混用，不能跨客户端读取原任务。

## 查询与下载

`GET /jobs/<id>`的status为queued/running/succeeded/failed。成功结果列出artifacts，每项含name、bytes、sha256与下载URL。下载需同一Bearer凭证，接口为 `GET /jobs/<id>/artifacts/<name>`。客户端必须核验长度和哈希，再交付文件。

成果含可编辑PPTX、PDF、逐页PNG和中文检查JSON。导入/修改另可返回逐页编辑源；修改任务带未改组件保护报告。失败结果明确error，不返回伪造成功文件。

## 约束

- 新建1–12页；导入1–30页、原PPTX10MB；请求总正文20MB。
- 单页SVG800KB、宽高100–4096、面积不超过900万像素。
- PPTX画布1–36英寸；预览长边最多2000像素。
- 每凭证每日10次任务、最多2个等待任务；服务单worker、队列上限6。
- 任务与输入24小时后清理；会话30天有效。
- 单处理步骤120秒、CPU90秒、地址空间1100MiB、单文件64MiB；工作目录200MiB预算校验。容器额外提供资源边界。
- 不接受宏、OLE对象、外部素材引用、脚本、文件URL或任意命令；错误请求不会跳过校验。
