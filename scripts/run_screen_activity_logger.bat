@echo off
setlocal

pushd "%~dp0.."
uv run python tools\screen_activity_logger\screen_activity_logger.py --config tools\screen_activity_logger\config.toml %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
