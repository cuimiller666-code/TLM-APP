$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidHomeBase = "E:\andanid"
$AndroidSdk = Join-Path $AndroidHomeBase "Android\sdk"
$FlutterRoot = Join-Path $AndroidHomeBase "flutter\3.29.2"
$JavaHome = Join-Path $AndroidHomeBase "java\17.0.13+11"
$VenvPython = Join-Path $RepoRoot ".venv-android\Scripts\python.exe"
$FletExe = Join-Path $RepoRoot ".venv-android\Scripts\flet.exe"

New-Item -ItemType Directory -Force -Path `
    $AndroidHomeBase, `
    (Join-Path $AndroidHomeBase "tmp"), `
    (Join-Path $AndroidHomeBase "pub-cache"), `
    (Join-Path $AndroidHomeBase ".gradle"), `
    $AndroidSdk | Out-Null

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:NO_COLOR = "1"
$env:FLET_CLI_NO_RICH_OUTPUT = "1"
$env:USERPROFILE = $AndroidHomeBase
$env:HOME = $AndroidHomeBase
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidSdk
$env:ANDROID_SDK_ROOT = $AndroidSdk
$env:PUB_CACHE = Join-Path $AndroidHomeBase "pub-cache"
$env:GRADLE_USER_HOME = Join-Path $AndroidHomeBase ".gradle"
$env:TEMP = Join-Path $AndroidHomeBase "tmp"
$env:TMP = Join-Path $AndroidHomeBase "tmp"
$env:FLUTTER_STORAGE_BASE_URL = "https://storage.flutter-io.cn"
$env:PUB_HOSTED_URL = "https://pub.flutter-io.cn"
$env:HTTP_PROXY = "http://127.0.0.1:7897"
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
$env:ALL_PROXY = "http://127.0.0.1:7897"
$env:GIT_CONFIG_COUNT = "2"
$env:GIT_CONFIG_KEY_0 = "http.proxy"
$env:GIT_CONFIG_VALUE_0 = "http://127.0.0.1:7897"
$env:GIT_CONFIG_KEY_1 = "https.proxy"
$env:GIT_CONFIG_VALUE_1 = "http://127.0.0.1:7897"
$env:Path = "$FlutterRoot\bin;$AndroidSdk\platform-tools;$env:Path"

if (!(Test-Path $VenvPython)) {
    python -m venv (Join-Path $RepoRoot ".venv-android")
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install "flet==0.28.3" "flet-cli==0.28.3"

$DevMode = Get-ItemProperty `
    -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" `
    -Name "AllowDevelopmentWithoutDevLicense" `
    -ErrorAction SilentlyContinue

if ($DevMode.AllowDevelopmentWithoutDevLicense -ne 1) {
    Write-Host "Windows Developer Mode is required for Flutter plugin symlinks."
    Write-Host "Opening Settings. Enable Developer Mode, then run this script again."
    Start-Process "ms-settings:developers"
    exit 2
}

$LicensesDir = Join-Path $AndroidSdk "licenses"
New-Item -ItemType Directory -Force -Path $LicensesDir | Out-Null
Set-Content -Path (Join-Path $LicensesDir "android-sdk-license") -Value @(
    "8933bad161af4178b1185d1a37fbf41ea5269c55",
    "d56f5187479451eabf01fb78af6dfcb131a6481e",
    "24333f8a63b6825ea9c5514f83c2829b004d1fee"
) -Encoding ASCII
Set-Content -Path (Join-Path $LicensesDir "android-sdk-preview-license") -Value @(
    "84831b9409646a918e30573bab4c9c91346d8abd"
) -Encoding ASCII

Set-Location $RepoRoot

$GradleProperties = Join-Path $env:GRADLE_USER_HOME "gradle.properties"
Set-Content -Path $GradleProperties -Value @(
    "org.gradle.daemon=false",
    "org.gradle.jvmargs=-Xmx4G -Dfile.encoding=UTF-8"
) -Encoding ASCII

Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -like "*TLM-APP*gradlew*" -or
        $_.CommandLine -like "*GradleDaemon*"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

$SeriousPythonBuild = Join-Path $RepoRoot "build\flutter\build\serious_python_android"
Remove-Item $SeriousPythonBuild -Recurse -Force -ErrorAction SilentlyContinue

& $FletExe build apk `
    --verbose `
    --no-rich-output `
    --arch arm64-v8a `
    --cleanup-app `
    --cleanup-packages `
    --skip-flutter-doctor
