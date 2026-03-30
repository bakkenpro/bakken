#!/bin/bash
# cron ジョブの設定スクリプト
# 実行方法: bash cron_setup.sh

# このスクリプトがある場所
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=$(which python3 || which python)

echo "スクリプトディレクトリ: $SCRIPT_DIR"
echo "Python: $PYTHON"

# 既存の cron に追記
(crontab -l 2>/dev/null; cat <<EOF

# ---- Slack 人材情報 自動要約 ----
# 毎日13:15 に 0:00〜13:00 のメッセージを集計して投稿
15 13 * * * cd $SCRIPT_DIR && MODE=daytime $PYTHON summarize_talent.py >> $SCRIPT_DIR/cron.log 2>&1

# 毎日9:00 に 前日13:00〜24:00 のメッセージを集計して投稿
0 9 * * * cd $SCRIPT_DIR && MODE=nighttime $PYTHON summarize_talent.py >> $SCRIPT_DIR/cron.log 2>&1
EOF
) | crontab -

echo "cron ジョブを登録しました。"
echo ""
echo "確認コマンド: crontab -l"
echo "ログ確認: tail -f $SCRIPT_DIR/cron.log"
