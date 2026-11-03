@echo off
rem 干眼共病研究助手 - Windows 启动文件
rem 双击运行。只负责：检查并在需要时安装运行环境、检查配置、显示菜单、调用主程序。
rem 注意：本文件以 GBK 编码保存，请勿用会改成 UTF-8 的编辑器另存。
setlocal
cd /d "%~dp0"
title 干眼共病研究助手

set "CONFIG=%~dp0配置.txt"
set "TEMPLATE=%~dp0配置模板.txt"
set "DATA_DIR=%~dp0数据"
set "RUNS_DIR=%~dp0runs"

echo.
echo ==========================================
echo           干眼共病研究助手
echo ==========================================
echo.

rem ---- 1. 检查运行环境：没有安装、换了电脑或移动了文件夹时自动安装 ----
call :find_uv
set "FP=%~dp0.环境\机器指纹.txt"
set "BIND=Windows-%PROCESSOR_ARCHITECTURE%"
set "REASON="
set "OLD_BIND="
set "OLD_DIR="
if not defined UV set "REASON=这台电脑还没有安装运行环境。"
if not defined REASON if not exist "%~dp0.venv\Scripts\python.exe" set "REASON=运行环境还没有安装完成。"
if not defined REASON if not exist "%FP%" set "REASON=运行环境还没有安装完成。"
if not defined REASON call :read_fp
if not defined REASON if not "%OLD_BIND%"=="%BIND%" set "REASON=检测到这是另一台电脑，运行环境与本机不匹配。"
if not defined REASON if not "%OLD_DIR%"=="%~dp0" set "REASON=检测到文件夹被移动过，需要重建运行环境。"
if not defined REASON goto env_ready
echo %REASON%
echo 需要联网自动安装（第一次约下载 500 MB，通常几分钟）。
set "ANS="
set /p "ANS=按回车键开始安装（输入 N 再按回车则退出）："
if /i "%ANS%"=="N" goto quit
call "%~dp0安装环境.bat" fromlauncher
if errorlevel 1 goto end
call :find_uv
echo.
echo ==========================================
echo.

:env_ready
set "UV_PYTHON_PREFERENCE=only-managed"
"%UV%" run --frozen --no-dev --project "%~dp0." agentloop doctor --quick > "%TEMP%\agentloop_quick.txt" 2>&1
if errorlevel 1 goto env_broken

rem ---- 2. 检查配置文件 ----
if exist "%CONFIG%" goto check_key
if not exist "%TEMPLATE%" goto no_template
copy /y "%TEMPLATE%" "%CONFIG%" >nul
echo 这是第一次使用，已为你创建配置文件「配置.txt」。
echo 马上会用记事本打开它：请把 API Key 粘贴到 API_KEY= 后面，保存并关闭记事本。
echo.
pause
start "" /wait notepad "%CONFIG%"

:check_key
set "APIKEY="
for /f "usebackq tokens=1,* delims==" %%a in ("%CONFIG%") do if /i "%%a"=="API_KEY" set "APIKEY=%%b"
if not defined APIKEY goto no_key

rem ---- 3. 菜单 ----
:menu
echo 请选择要做什么：
echo.
echo   1  使用模拟数据（第一次建议选这个）
echo   2  使用真实数据（数据需已放入「数据」文件夹）
echo   3  继续上次的研究
echo   0  退出
echo.
set "CHOICE="
set /p "CHOICE=请输入数字后按回车键："
echo.
if "%CHOICE%"=="1" goto run_synthetic
if "%CHOICE%"=="2" goto run_real
if "%CHOICE%"=="3" goto run_resume
if "%CHOICE%"=="0" goto quit
echo 没有这个选项，请输入 0、1、2 或 3。
echo.
goto menu

:run_synthetic
echo 正在启动。第一次运行需要联网下载组件，可能要等几分钟，请不要关闭窗口……
echo.
"%UV%" run --frozen --no-dev --project "%~dp0." agentloop run --synthetic --config "%CONFIG%"
goto after_run

:run_real
dir /b "%DATA_DIR%" 2>nul | findstr "." >nul || goto no_data
echo 正在启动。第一次运行需要联网下载组件，可能要等几分钟，请不要关闭窗口……
echo.
"%UV%" run --frozen --no-dev --project "%~dp0." agentloop run --data "%DATA_DIR%" --config "%CONFIG%"
goto after_run

:run_resume
dir /b "%RUNS_DIR%" 2>nul | findstr "." >nul || goto no_runs
echo 正在启动，请不要关闭窗口……
echo.
"%UV%" run --frozen --no-dev --project "%~dp0." agentloop resume --config "%CONFIG%"
goto after_run

:after_run
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto ok
if "%RC%"=="4" goto paused
if "%RC%"=="3" goto end
if "%RC%"=="1" goto fixable
goto failed

:ok
echo 已完成。报告已在浏览器中打开，也可以在 runs 文件夹里找到。
goto end

:paused
echo 研究已暂停，目前的报告已在浏览器中打开。之后重新双击启动、输入 3 即可接着跑。
goto end

:fixable
echo 请按上面的提示处理，然后重新双击启动、输入 3 继续，已完成的部分不会重复。
goto end

:failed
echo 运行没有成功。
echo 请把这个窗口截图，连同 runs 文件夹里最新的那个文件夹，一起发给技术同事。
echo 注意：不要发送「数据」文件夹。
goto end

:env_broken
type "%TEMP%\agentloop_quick.txt"
echo.
echo 运行环境有问题。请双击「安装环境.bat」修复，修复后再双击启动。
goto end

:no_template
echo 找不到「配置模板.txt」，文件夹可能不完整。请联系技术同事。
goto end

:no_key
echo 配置文件里还没有填写 API Key。
echo 请打开本文件夹里的「配置.txt」，把 API Key 粘贴到 API_KEY= 后面，保存后重新双击启动。
start "" notepad "%CONFIG%"
goto end

:no_data
echo 「数据」文件夹不存在或是空的。请先请技术同事把转换好的数据放进去。
echo.
goto menu

:no_runs
echo 还没有做过任何研究，无法继续。请先选择 1 或 2。
echo.
goto menu

:quit
endlocal
exit /b 0

:end
echo.
pause
endlocal
exit /b

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
