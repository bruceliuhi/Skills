# PPT 自有云服务

为「PPT制作与美化专家」提供固定的新建、导入、指定页修改、可编辑PPTX导出和逐页预览接口。轻量客户端在 `skills/ppt-presentation-expert-cloud`，完整引擎保留在本目录的 `engine/`；使用者无需在本机安装转换依赖。

接口与限额见 [API说明](API.md)，产品边界见 [产品说明](CLOUD_PRODUCT.md)。服务提供有限免费体验，不内置支付或购买权益核验。不能把匿名任务凭证当作已验证的付费身份。

## 运行组成

- `app.py`：SQLite持久化任务、随机凭证隔离、输入验证、单worker队列、过期清理、固定引擎调用。
- `limit_exec.py`：在执行子进程中设置CPU、地址空间及单文件限额；服务对整个进程组做超时终止和任务目录预算检查。
- `engine/`：完整明文转换引擎。当前API只开放已说明的核心路径，不表示所有可选功能都已对外开放。
- `Dockerfile`：固定5个Python库版本，安装LibreOffice、Poppler及中文字体。Debian镜像保持官方签名验证；不全局改用户电脑。
- `deploy/run-container.sh`：独立非root容器，1CPU、1280MiB、PID128、只读根、cap-drop、no-new-privileges、无网络，通过专用Unix socket接入Nginx。
- `deploy/ppt-service-location.inc`：独立HTTPS路径代理示例。加入现有站点时应备份，只添加自己的include，`nginx -t`成功后平滑重载。

## 部署与更新

在独立服务目录构建 `docker build -t xinghe-ppt-cloud:1.1.0 .`，核对目标域名、挂载路径和资源预算后执行启动脚本。生产更新需先确认没有正在执行的任务，保留 `/data` 持久卷，替换本服务容器后核对health与既有成果哈希。脚本默认拒绝自动覆盖同名运行容器。

容器没有公网端口和出网能力。Nginx通过专用socket连接，并覆盖X-Real-IP；客户端仍必须使用Bearer凭证读取自己的任务。输入与成果不会公开发布到网站目录，下载接口不信任任意文件路径。

当前核心云端流程、实际预览、客户端HTTPS下载、隔离与重启保留已验证。WorkBuddy市场审核、正式上架和付费Pro是独立状态；以平台页面及实际新增能力为准。不能承诺任意复杂PPT无损转换或所有Office软件像素一致。
