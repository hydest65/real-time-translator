# 当前架构入口

基线：桌面 **0.4.6**，2026-10-03。

| 层 | 文件 | 责任 |
| --- | --- | --- |
| 桌面进程 | `desktop/main.cjs`、`preload.cjs`、`geometry.cjs` | 透明窗口、置顶、八向缩放、限定桌面桥、本机设置保存 |
| 配置 | `desktop/cloud-config.cjs` | 统一解析、工作进程环境覆盖、主配置兼容恢复、保留已有密钥 |
| 本机服务 | `desktop/backend_worker.py`、`backend/` | 随机回环端口运行 Cloud 服务，受父进程管理，正常退出清理录音 |
| 显示 | `frontend/caption-settings.js`、`desktop-controls.js`、`desktop.css` | 字号、颜色、SRC / TR、透明度、状态图标和原生设置恢复 |
| 构建 | `scripts/build-desktop.ps1` | 云端运行组件与前端打包，输出完整便携目录和 ZIP |

渲染页面禁用 Node.js，并启用 sandbox / contextIsolation；桌面桥校验来源，不向页面返回密钥。程序与数据分开，窗口状态使用 `window.json`，显示状态使用 `display.json`，云配置使用本机 `.env`。颜色和布尔开关经主进程校验，显示选择保留字幕记录与连接。

配置恢复只在正式便携包的默认数据路径执行，保护有效主配置与部分冲突；显式指定配置和隔离测试不读取旧保存位置。Notes 生成路线已移出当前运行接口，可选离线源码路径不随 Cloud 便携包分发。

细节与历史背景见 [技术架构](TECHNICAL_ARCHITECTURE.md)，构建和操作见 [桌面说明](DESKTOP_APP.md)，配置根因见 [技术交接](technical-memory.md)。
