"""
Slack チャンネルから週5稼働/稼働率100%の人材情報を時間帯別に要約するスクリプト

実行モード:
  MODE=daytime  : 9:00〜14:59 のメッセージを集計（毎日15:00に実行）
  MODE=nighttime: 前日0:00〜当日8:59 のメッセージを集計（毎日9:00に実行）
  MODE=test     : 時間制限なし（デバッグ用）

使い方:
  MODE=daytime python summarize_talent.py
  MODE=nighttime python summarize_talent.py
  MODE=test python summarize_talent.py

環境変数:
  SLACK_BOT_TOKEN   - Slack Bot Token (xoxb-...)
  SOURCE_CHANNEL_ID - 読み取り対象チャンネルID
  OUTPUT_CHANNEL_ID - 要約を投稿するチャンネルID
  MODE              - daytime / nighttime / test（デフォルト: daytime）
"""

import os
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

# ---- 設定 ----
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SOURCE_CHANNEL_ID = os.environ.get("SOURCE_CHANNEL_ID", "C0A8WB50TDH")
OUTPUT_CHANNEL_ID = os.environ.get("OUTPUT_CHANNEL_ID", "#週5人材")
MODE = os.environ.get("MODE", "daytime")  # daytime / nighttime / test

# 日本時間 (JST = UTC+9)
JST = timezone(timedelta(hours=9))

# ---- フィルタキーワード ----
KEYWORDS = [
    "週5", "週５", "5日/週", "稼働率100", "100%稼働", "フルタイム",
    "週5稼働", "週５稼働", "稼働率１００", "100％稼働",
]


def remove_code_blocks(text: str) -> str:
    """コードブロック（```...```）を除去する"""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    return text.strip()


def contains_keywords(text: str) -> bool:
    """週5稼働/稼働率100%に関するキーワードが含まれるか確認"""
    for kw in KEYWORDS:
        if kw in text:
            return True
    return False


def get_time_range() -> tuple[float | None, float | None, str, str]:
    """
    実行モードに応じて対象時間範囲を返す（日本時間基準）。
    戻り値: (oldest_ts, latest_ts, 対象日表示, モード説明)
    """
    now = datetime.now(JST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if MODE == "test":
        return None, None, "全期間", "テストモード"
    elif MODE == "nighttime":
        # 9:00 実行: 前日 0:00 〜 当日 8:59
        oldest = today - timedelta(days=1)  # 前日 0:00
        latest = today.replace(hour=8, minute=59, second=59)  # 当日 8:59
        label = (today - timedelta(days=1)).strftime("%Y年%m月%d日") + "〜" + today.strftime("%m月%d日")
        desc = "前日0:00〜当日8:59"
    else:
        # 15:00 実行: 当日 9:00 〜 14:59
        oldest = today.replace(hour=9, minute=0, second=0)  # 当日 9:00
        latest = today.replace(hour=14, minute=59, second=59)  # 当日 14:59
        label = today.strftime("%Y年%m月%d日")
        desc = "9:00〜14:59"

    return oldest.timestamp(), latest.timestamp(), label, desc


def fetch_messages(client: WebClient, channel_id: str, oldest: float | None, latest: float | None) -> list[dict]:
    """指定チャンネルの指定時間範囲のメッセージを取得する"""
    messages = []
    cursor = None

    while True:
        try:
            params = {
                "channel": channel_id,
                "limit": 200,
            }
            if oldest is not None:
                params["oldest"] = str(oldest)
            if latest is not None:
                params["latest"] = str(latest)
            if cursor:
                params["cursor"] = cursor

            response = client.conversations_history(**params)
            messages.extend(response["messages"])

            if not response.get("has_more"):
                break
            cursor = response["response_metadata"]["next_cursor"]

        except SlackApiError as e:
            print(f"[ERROR] メッセージ取得失敗: {e.response['error']}")
            break

    # 時系列順（古い順）にソート
    messages.sort(key=lambda m: float(m.get("ts", 0)))
    return messages


def format_summary(filtered: list[str], date_label: str, time_desc: str) -> str:
    """要約テキストを生成する"""
    header = f"*{date_label} {time_desc} の週5稼働/稼働率100% 人材情報*"

    if not filtered:
        return f"{header}\n\n該当する情報はありませんでした。"

    lines = [header, f"（{len(filtered)}件）", ""]
    for i, msg in enumerate(filtered, 1):
        lines.append(f"{i}. {msg}")
        lines.append("")

    return "\n".join(lines)


def main():
    if not SLACK_BOT_TOKEN:
        print("[ERROR] SLACK_BOT_TOKEN が設定されていません。")
        print("  .env ファイルに SLACK_BOT_TOKEN=xoxb-... を設定してください。")
        return

    client = WebClient(token=SLACK_BOT_TOKEN)

    oldest_ts, latest_ts, date_label, time_desc = get_time_range()

    print(f"モード: {MODE} / 対象: {date_label} {time_desc}")
    print(f"チャンネル {SOURCE_CHANNEL_ID} からメッセージを取得中...")
    if oldest_ts and latest_ts:
        print(f"  時間範囲: {datetime.fromtimestamp(oldest_ts, JST)} 〜 {datetime.fromtimestamp(latest_ts, JST)}")
    else:
        print("  時間範囲: 制限なし（全メッセージ）")

    messages = fetch_messages(client, SOURCE_CHANNEL_ID, oldest_ts, latest_ts)
    print(f"  {len(messages)} 件のメッセージを取得しました。")

    # フィルタリング
    filtered = []
    for msg in messages:
        text = msg.get("text", "")
        # コードブロックを除去
        clean_text = remove_code_blocks(text)
        if not clean_text:
            continue
        # キーワードチェック
        if contains_keywords(clean_text):
            filtered.append(clean_text)

    print(f"  条件に合致: {len(filtered)} 件")

    # 要約テキスト生成
    summary = format_summary(filtered, date_label, time_desc)
    print("\n" + "=" * 60)
    print(summary)
    print("=" * 60)

    # Slackへの投稿
    if MODE == "test":
        print("\n[TEST MODE] Slackへの投稿はスキップしました。")
    elif OUTPUT_CHANNEL_ID:
        try:
            client.chat_postMessage(
                channel=OUTPUT_CHANNEL_ID,
                text=summary,
            )
            print(f"\nチャンネル {OUTPUT_CHANNEL_ID} に投稿しました。")
        except SlackApiError as e:
            print(f"[ERROR] 投稿失敗: {e.response['error']}")
    else:
        print("\n（OUTPUT_CHANNEL_ID を設定すると Slack に自動投稿されます）")


if __name__ == "__main__":
    main()
