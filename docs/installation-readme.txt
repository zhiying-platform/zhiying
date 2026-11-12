知映 zhiying - 安装说明
========================

快速开始：
  双击「知映 zhiying」（桌面或开始菜单）
  -> 服务以托盘图标常驻（任务栏右下角「知」字图标），就绪后自动打开浏览器
  -> 浏览器关闭后服务继续运行，随时双击图标再打开 http://127.0.0.1:8600

退出服务：
  右键任务栏托盘的「知」图标 -> 退出（会同时停止数据库）

组件说明：
  - 完整安装：含嵌入式 PostgreSQL（知识库向量检索）
  - 精简安装：仅 md 知识积累，不装数据库

常用操作：
  停止服务：右键托盘图标退出，或运行 scripts\stop.cmd
  命令行：  scripts\zhiying-cli.cmd --help
  AI 接入： scripts\zhiying-mcp.cmd（MCP 协议）
            claude mcp add zhiying -- "安装目录\scripts\zhiying-mcp.cmd"
  重置知识库：scripts\pg-setup.cmd

数据位置：
  %APPDATA%\zhiying\（视频、知识库、数据库）
  卸载或升级重装不会删除数据

模型配置：
  首次使用在网页「设置」页填写 VLM（视觉识别）与文本模型 API Key，支持混搭不同厂商。
  B 站高清下载：在「设置」页点一次登录引导，缓存 Cookie 后即可 1080P 下载。

端口：
  网页与 API：8600（固定）
  嵌入式数据库：自动选择空闲端口（15499 起），记录在 %APPDATA%\zhiying\pg.port
  这样不会与 Docker、本机已装 PostgreSQL 等冲突。