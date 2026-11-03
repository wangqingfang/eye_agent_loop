@echo off
rem 干眼共病研究助手 - Windows 环境安装与检查
rem 双击运行，或由「启动研究.bat」在需要时自动调用（参数 fromlauncher）。可以重复运行，用来修复环境。
rem 步骤：1 检查本机、2 安装 uv、3 安装 Python 与依赖、4 记录机器指纹、5 环境检查与离线自检
rem 注意：本文件以 GBK 编码保存，请勿用会改成 UTF-8 的编辑器另存。
setlocal
cd /d "%~dp0"
title 干眼共病研究助手 - 安装运行环境
set "ENV_DIR=%~dp0.环境"
set "LOG=%ENV_DIR%\安装日志.txt"
set "FP=%ENV_DIR%\机器指纹.txt"
set "FROM_LAUNCHER=0"
if /i "%~1"=="fromlauncher" set "FROM_LAUNCHER=1"
if not exist "%ENV_DIR%" mkdir "%ENV_DIR%"
>> "%LOG%" echo ==== %date% %time% 开始安装 ====
set "UV_PYTHON_PREFERENCE=only-managed"

echo.
echo ==========================================
echo      干眼共病研究助手 - 安装运行环境
echo ==========================================
echo 需要联网。第一次安装约下载 500 MB，通常几分钟，请不要关闭窗口。

rem ---- 1. 检查本机 ----
echo.
echo [1/5] 检查本机
set "WINVER="
for /f "delims=" %%v in ('ver') do set "WINVER=%%v"
echo   %WINVER% %PROCESSOR_ARCHITECTURE%
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Method Head -TimeoutSec 15 -Uri 'https://pypi.org/simple/numpy/' | Out-Null; exit 0 } catch { exit 1 }" >> "%LOG%" 2>&1
if errorlevel 1 goto fail_net
echo   网络正常

rem ---- 2. 安装 uv ----
echo.
echo [2/5] 安装 uv（Python 运行环境管理工具）
call :find_uv
if defined UV goto uv_ready
echo   正在下载 uv……
powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex" >> "%LOG%" 2>&1
call :find_uv
if not defined UV goto fail_uv
:uv_ready
set "UV_VER="
for /f "delims=" %%v in ('call "%UV%" --version') do set "UV_VER=%%v"
if not defined UV_VER goto fail_uv
echo   %UV_VER%

rem ---- 3. 安装 Python 与依赖 ----
echo.
echo [3/5] 安装 Python 与依赖（按 uv.lock 锁定的版本）
set "BIND=Windows-%PROCESSOR_ARCHITECTURE%"
set "OLD_BIND="
set "OLD_DIR="
if not exist "%FP%" goto do_sync
call :read_fp
if not "%OLD_BIND%"=="%BIND%" goto rebuild
if not "%OLD_DIR%"=="%~dp0" goto rebuild
goto do_sync
:rebuild
echo   检测到更换了电脑或移动了文件夹，正在重建运行环境……
if exist "%~dp0.venv" rmdir /s /q "%~dp0.venv"
:do_sync
"%UV%" sync --frozen --no-dev --project "%~dp0." >> "%LOG%" 2>&1
if not errorlevel 1 goto sync_ok
echo   第一次尝试失败，清理后重试一次……
if exist "%~dp0.venv" rmdir /s /q "%~dp0.venv"
"%UV%" sync --frozen --no-dev --project "%~dp0." >> "%LOG%" 2>&1
if errorlevel 1 goto fail_sync
:sync_ok
if not exist "%~dp0.venv\Scripts\python.exe" goto fail_py
set "PY_VER="
for /f "delims=" %%v in ('call "%~dp0.venv\Scripts\python.exe" -V') do set "PY_VER=%%v"
echo   %PY_VER% 与依赖已安装

rem ---- 4. 记录机器指纹 ----
echo.
echo [4/5] 记录机器指纹（运行环境与本机绑定）
> "%FP%" echo BIND=%BIND%
>> "%FP%" echo DIR=%~dp0
>> "%FP%" echo OS=%WINVER%
>> "%FP%" echo UV=%UV_VER%
>> "%FP%" echo PYTHON=%PY_VER%
>> "%FP%" echo INSTALLED=%date% %time%
echo   %BIND%

rem ---- 5. 环境检查与离线自检 ----
echo.
echo [5/5] 环境检查与离线自检
echo.
"%UV%" run --frozen --no-dev --project "%~dp0." agentloop doctor
if errorlevel 1 goto fail_doctor
echo.
echo 安装完成，可以开始使用了。以后双击「启动研究.bat」即可。
echo 检查结果已保存到「环境检查报告.txt」。
set "RC=0"
goto finish

:fail_net
set "MSG=无法连接网络（pypi.org）。安装需要联网，请检查网络或代理后重试。"
goto fail
:fail_uv
set "MSG=下载或运行 uv 失败（多为网络问题，或公司电脑禁止运行 PowerShell 脚本）。"
goto fail
:fail_sync
set "MSG=下载或安装依赖失败（多为网络问题）。"
goto fail
:fail_py
set "MSG=Python 安装后无法运行。"
goto fail
:fail_doctor
set "MSG=环境检查有失败项，请按上面【失败】一行的说明处理。"
goto fail

:fail
echo.
echo 安装没有完成：%MSG%
echo 详细记录在本文件夹的「.环境\安装日志.txt」。处理后可以再次双击「安装环境.bat」重试；
echo 如果仍然不行，请把这个窗口截图，连同这个日志文件，一起发给技术同事。
>> "%LOG%" echo 安装失败：%MSG%
set "RC=1"

:finish
if "%FROM_LAUNCHER%"=="0" pause
endlocal & exit /b %RC%

rem ---- 子程序 ----
:find_uv
set "UV="
where uv >nul 2>nul && set "UV=uv"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
goto :eof

:read_fp
for /f "usebackq tokens=1,* delims==" %%a in ("%FP%") do (
  if "%%a"=="BIND" set "OLD_BIND=%%b"
  if "%%a"=="DIR" set "OLD_DIR=%%b"
)
goto :eof
