# TLM APP v2.1.11

这是当前推荐下载的 Android APK 版本。

## 下载

请下载本 Release 附件中的 `tlm-app.apk`，安装到 Android 手机。

## 本次修复

- 修复 Android 启动白屏问题。
- 修复错误的 `permission_handler` 控件导致红屏的问题。
- 修复手机端设置弹窗超出屏幕、历史记录按钮不易找到的问题。
- 修复计时器切到后台后停止计时的问题。
- 修复图片保存到 app 私有目录、文件管理器难以找到的问题。
- 修复 Android 文件选择器返回 `/document/primary:...` 导致另存失败的问题。
- 修复导出图片字体像素化问题，Android APK 加入 Pillow，导出 PNG 更清晰。
- 保留 TLM 图表功能，继续使用 Flet 0.28.3 的 `LineChart`。
- Android 打包改为 64 位 ARM，`versionCode` 为 4。

## 截图

### 首页

![首页](https://raw.githubusercontent.com/cuimiller666-code/TLM-APP/v2.1.11/docs/screenshots/home.jpg)

### 计时器

![计时器](https://raw.githubusercontent.com/cuimiller666-code/TLM-APP/v2.1.11/docs/screenshots/timer.jpg)

### TLM 结果

![TLM 结果](https://raw.githubusercontent.com/cuimiller666-code/TLM-APP/v2.1.11/docs/screenshots/tlm-result.jpg)

### 16:9 导出图片

![16:9 导出图片](https://raw.githubusercontent.com/cuimiller666-code/TLM-APP/v2.1.11/docs/screenshots/export-16x9.png)
