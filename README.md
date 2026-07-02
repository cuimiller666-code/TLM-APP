# TLM APP

实验室用 TLM 计算与计时工具，使用 Python + Flet 编写。

## 功能

- TLM 计算：选择预设后输入不同间距下的电流，自动计算 `Rc`、`Rsh`、`R²` 等结果。
- 预设管理：支持保存、编辑、删除 TLM 间距与数量预设。
- 历史记录：最多保存 1500 条测试记录。
- 图片导出：生成 16:9 PNG，包含正方形坐标图、`Rc`、`Rsh`、`R²`、导出时间和输入表格。
- 分享：支持导出图片、另存图片和系统分享。
- 计时器：首页进入计时器，可使用秒级倒计时、3/5/10/14 分钟倒计时、自定义倒计时和正计时。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install flet
flet run
```

也可以直接运行：

```powershell
python src\main.py
```

## 在 GitHub 下载 App

这个仓库包含 GitHub Actions 自动打包配置。

1. 打开仓库的 `Actions` 页面。
2. 选择 `Build downloadable apps`。
3. 点击 `Run workflow`。
4. 等待构建完成后，在页面底部 `Artifacts` 下载：
   - `TLM-APP-Android-APK`
   - `TLM-APP-Windows`
   - `TLM-APP-Linux`

如果创建 `v2.1.2` 这类 tag，Actions 会把构建结果自动发布到 GitHub Release。平时直接打开仓库的 `Releases` 页面，下载最新版本里的 `tlm-app.apk`、`TLM-APP-Windows.zip` 或 `TLM-APP-Linux.zip` 即可。

如果 Android APK 打开后白屏，优先确认下载的是最新 Release。v2.1.2 已修复移动端启动阶段提前初始化平台控件导致的白屏风险。

## CentOS 7 说明

GitHub Actions 会生成一个 Linux 桌面包，但它是在 Ubuntu runner 上构建的。CentOS 7 的系统库较旧，如果 Linux 包无法直接运行，推荐使用源码方式运行：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install flet
python src/main.py
```

CentOS 7 默认 Python 版本较旧，需要先安装 Python 3.10 或更高版本。

## 手动打包

Android APK：

```powershell
python -m pip install flet
flet build apk
```

Windows：

```powershell
python -m pip install flet
flet build windows
```

Linux：

```bash
python -m pip install flet
flet build linux
```

构建输出通常位于 `build/` 目录。
