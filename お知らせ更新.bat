@echo off
chcp 65001 > nul
setlocal

REM ============================================================
REM  トップページ「最新のお知らせ」自動更新バット
REM    1) PSR/MyKomon から既存の最新日付以降の差分だけを取得
REM    2) サイトをビルド
REM    3) 変更があれば commit して origin/main へ push（自動デプロイ）
REM
REM  使い方: このファイルをダブルクリックするだけ
REM ============================================================

cd /d "%~dp0"

REM --- python / py のどちらかを使う ---
where python > nul 2>&1
if %errorlevel%==0 (
    set "PY=python"
) else (
    set "PY=py"
)

echo.
echo === [1/3] お知らせの差分を取得します ===
%PY% scripts\update_home_notices.py --incremental
if errorlevel 1 (
    echo.
    echo [中止] お知らせの取得に失敗しました。.env の MYKOMON_ID / MYKOMON_PASSWORD やネット接続を確認してください。
    pause
    exit /b 1
)

echo.
echo === [2/3] サイトをビルドします ===
%PY% scripts\build.py
if errorlevel 1 (
    echo.
    echo [中止] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo === [3/3] 変更を確認します ===
git diff --quiet -- src/data/home_notices.json
if %errorlevel%==0 (
    echo 新しいお知らせはありませんでした。何も反映せず終了します。
    pause
    exit /b 0
)

echo 新しいお知らせがあります。git に反映します。
git add src/data/home_notices.json
git commit -m "お知らせ: 最新の差分を自動更新"
if errorlevel 1 (
    echo.
    echo [中止] commit に失敗しました。
    pause
    exit /b 1
)

git push origin main
if errorlevel 1 (
    echo.
    echo [中止] push に失敗しました。手動で「git push origin main」を実行してください。
    pause
    exit /b 1
)

echo.
echo === 完了 === origin/main へ反映しました。数分後にサイトへ公開されます。
pause
endlocal
