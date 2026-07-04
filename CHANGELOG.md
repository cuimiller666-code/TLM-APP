# 更新日志

## v2.1.13 - 2026-07-05

### 发布说明

- 改用 GitHub CLI 在 Actions 内创建 GitHub Release 并上传 Android APK，避免 Release action 卡住。
- 版本号更新为 `versionName 2.1.13`、`versionCode 6`。

## v2.1.12 - 2026-07-05

### 发布说明

- 在 README 和 GitHub Release 详情中补充软件用途：面向 B1500 TLM 测试后的手机端 `Rc`、`Rsh`、`LT`、`ρc` 计算、拟合和结果导出。
- Release 详情页加入首页、计时器、TLM 结果和 16:9 导出图片截图。
- 版本号更新为 `versionName 2.1.12`、`versionCode 5`。

## v2.1.11 - 2026-07-05

### 修复

- 修复 Android 启动白屏和运行时红屏问题。
- 修复 Android 手机端设置弹窗超出屏幕、历史记录按钮不易找到的问题。
- 修复计时器切到后台后停止计时的问题。
- 修复导出图片保存到 app 私有目录、文件管理器难以找到的问题。
- 修复 Android 文件选择器返回 `/document/primary:...` 导致另存失败的问题。
- 修复导出图片字体像素化问题，Android APK 加入 Pillow 以生成更清晰的 PNG。
- 修复 Android 64 位架构打包参数，使用 `arm64-v8a` 和 `android-arm64`。

### 改进

- 图片优先保存到手机可见的 `1aTLM` 目录，失败时尝试 Android 可见媒体目录。
- GitHub Release 改为聚焦 Android APK。
- 版本号更新为 `versionName 2.1.11`、`versionCode 4`。

## v2.1.6 - 2026-07-03

- 修复 Release 中 Android APK 文件名不稳定的问题。

## v2.1.0 - 2026-07-03

- 新增首页、TLM 计算页和实验计时器。
- 新增 16:9 图片导出。
- 新增历史记录和预设管理。
