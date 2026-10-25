# WorkBuddy 中文交付流程

先运行 `python3 <技能目录>/scripts/run_workbuddy.py doctor`。启动器只探测已有解释器，自动选择实际具备核心依赖的环境；若没有则退出码 69 并用中文说明阻塞。不要全局安装、读取密钥或借用开发工具私有缓存。依赖缺失时按下面的隔离环境流程准备固定核心库。doctor 只证明依赖是否存在，不能替代真正运行。

## 新建

按所选生成流程准备完整 SVG，图表/表格同时写出可视预览与原生数据定义，讲稿按页面文件名放入 notes/。

```text
python3 <技能目录>/scripts/run_workbuddy.py check <项目目录> --mode quick
python3 <技能目录>/scripts/run_workbuddy.py export <项目目录> --mode quick --output <新文件.pptx> --notes --native-data
```

普通流程使用 `--mode default`，需要其规定的设计与锁定文件。只在准备好规范原生数据对象时用 `--native-data`；否则导出的是可编辑形状，不能说图表数据可编辑。

## 局部修改

```text
python3 <技能目录>/scripts/run_workbuddy.py import <原文件.pptx> --workspace <全新工作目录>
```

读取 authoring-svg-flat/authoring_summary.json 和要修改的页面，只改用户要求的对象。排序、重复和删除页面由 page_plan.json 管理，不手工复制单个 slide XML。

```text
python3 <技能目录>/scripts/run_workbuddy.py check <工作目录> --mode roundtrip
python3 <技能目录>/scripts/run_workbuddy.py export <工作目录> --mode roundtrip --output <修改后.pptx>
```

对原件记录执行前后 hash；未改页面、图表、资源与讲稿做实际比对。不能安全修改的原生对象说明具体限制，不静默重做全稿。

## 预览与交付

```text
python3 <技能目录>/scripts/run_workbuddy.py inspect <演示文件.pptx>
python3 <技能目录>/scripts/run_workbuddy.py render <项目目录> --mode quick --output <全新预览目录>
```

离线 SVG 预览使用已有 Playwright/Chromium，不需要 Flask。它只适用于资源完整且没有待内嵌图标的页面；保留原成熟预览服务供具备条件时使用。缺浏览器或权限时明确未完成，不安装、不绕过权限。

逐页检查中文缺字、溢出、遮挡、图表标签和表格内容。SVG 预览、文件结构检查、成品 PPTX 的 Office 渲染是不同证据；缺少实际 Office 渲染时不得写成已完成。修复后重新导出和预览受影响页面。

交付可编辑 PPTX，按需附讲稿与预览。中文说明页数、修改、原件保护和未完成检查。不要把英文日志直接给客户；日志仅供定位问题，技术细节转为具体中文原因和下一步。没有实际文件，不能虚构下载入口。

## 受保护环境与恢复

始终使用平台默认文件与删除保护，不设置关闭保护的环境变量；入口检测到保护被关闭会拒绝执行。导入使用全新目录，导出使用新文件名。中间构建、导入与预览工作目录为本次新建并保留，失败时可检查原因，不自动删除，也不换到其它目录继续尝试被拒绝的写入。不要对系统或输入原件放宽权限。浏览器预览明确启用 Chromium 沙箱；无法启动就保留未完成状态。

中间目录会占用额外空间。交付确认后由用户按需清理自己的项目目录，技能不静默清空历史成果。

## 付费运行环境

同一技能在客户端本地与付费云端可能使用不同环境。运行前必须实际探测；不能把本机已有库当成云端预置保证。云端没有核心库时先尝试平台允许的隔离环境准备，再实际复测。若平台禁止创建环境或访问官方 PyPI，就明确阻塞；不要求用户额外账号或手工装库，不退化成文字稿却仍称完成。

## 缺依赖时自动准备隔离环境

选择本项目中的全新运行目录，不写入技能安装目录。已有输出不覆盖，失败文件不清空。

```text
python3 <技能目录>/scripts/bootstrap_runtime.py --runtime-dir <项目目录>/<全新运行目录>
python3 <技能目录>/scripts/run_workbuddy.py --runtime <项目目录>/<全新运行目录> doctor
python3 <技能目录>/scripts/run_workbuddy.py --runtime <项目目录>/<全新运行目录> export <项目目录> --mode quick --output <新文件.pptx> --notes --native-data
```

也可用 `run_workbuddy.py --prepare <全新运行目录> <后续动作及参数>` 串联准备与执行。
准备脚本仅支持 Python 3.9–3.13，从官方 PyPI 安装 requirements-core.txt 中固定的五个核心版本。
不进行源码构建或全局缓存写入，不安装可选服务组件，不修改保护环境变量。
安装后核对模块版本、隔离路径与依赖关系。依赖检查通过之后仍必须真正导出并检查产物。

平台没有 venv/pip、禁止联网、没有匹配的二进制轮子或写入被拒时停止并报告。
不关闭任何保护，不转用全局安装，不把原来的系统 Python 结果当成本次隔离环境通过。
