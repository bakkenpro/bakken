"""
Slack チャンネルから週5稼働/稼働率100%の人材情報を時間帯別に要約するスクリプト

実行モード:
  MODE=daytime  : 0:00〜13:00 のメッセージを集計（毎日13:15に実行）
  MODE=nighttime: 13:00〜24:00 のメッセージを集計（翌日9:00に実行）

使い方:
  MODE=daytime python summarize_talent.py
  MODE=nighttime python summarize_talent.py

環境変数:
  SLACK_BOT_TOKEN   - Slack Bot Token (xoxb-...)
  SOURCE_CHANNEL_ID - 読み取り対象チャンネルID
  OUTPUT_CHANNEL_ID - 要約を投稿するチャンネルID
  MODE              - daytime または nighttime（デフォルト: daytime）
"""

import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

# ---- 設定 ----
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SOURCE_CHANNEL_ID = os.environ.get("SOURCE_CHANNEL_ID", "C0A8WB50TDH")
OUTPUT_CHANNEL_ID = os.environ.get("OUTPUT_CHANNEL_ID", "#週5人材")
MODE = os.environ.get("MODE", "daytime")  # daytime or nighttime


def remove_code_blocks(text: str) -> str:
    """コードブロック（```...```）を除去する"""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    return text.strip()


def normalize_text(text: str) -> str:
    """改行を正規化（連続する改行を1つに）"""
    # 3つ以上の改行を2つに
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 各行の前後の空白を削除
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines)


def is_full_time_talent(text: str) -> bool:
    """
    【稼働可能時間数】が「160時間」または「100%」を含むかチェック
    """
    # 【稼働可能時間数】の行を探す
    match = re.search(r"【稼働可能時間数】(.+?)(?:\n|$)", text)
    if not match:
        return False
    
    work_hours = match.group(1)
    
    # 160時間 or 100% をチェック（全角/半角両対応）
    if re.search(r"160\s*時間|１６０\s*時間", work_hours):
        return True
    if re.search(r"100\s*%|100\s*％|１００\s*%|１００\s*％", work_hours):
        return True
    
    return False


def extract_talent_blocks(text: str) -> list[str]:
    """
    メッセージから人材情報ブロックを抽出する
    <推薦用>> から始まり、次の <推薦用>> または末尾まで
    """
    # コードブロックを除去
    text = remove_code_blocks(text)
    
    if not text:
        return []
    
    # <推薦用>> で分割
    blocks = re.split(r"<推薦用>>", text)
    
    talent_blocks = []
    for block in blocks[1:]:  # 最初の空要素をスキップ
        block = block.strip()
        if block and "【氏名】" in block:
            talent_blocks.append(block)
    
    # <推薦用>> がない場合、【氏名】で始まるブロックを探す
    if not talent_blocks and "【氏名】" in text:
        # 【氏名】で分割して各ブロックを取得
        blocks = re.split(r"(?=【氏名】)", text)
        for block in blocks:
            block = block.strip()
            if block and "【氏名】" in block:
                talent_blocks.append(block)
    
    return talent_blocks


def format_talent_block(block: str) -> str:
    """人材情報ブロックのフォーマットを整える（改行を1つに）"""
    # 連続する改行を1つに
    block = re.sub(r"\n{2,}", "\n", block)
    # 各行の前後の空白を削除
    lines = [line.strip() for line in block.split("\n") if line.strip()]
    return "\n".join(lines)


def get_time_range() -> tuple[float, float, str, str]:
    """
    実行モードに応じて対象時間範囲を返す。
    戻り値: (oldest_ts, latest_ts, 対象日表示, モード説明)
    """
    now = datetime.now()

    if MODE == "nighttime":
        # 9:00 実行: 前日13:00〜24:00
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        oldest = (base - timedelta(days=1)).replace(hour=13, minute=0, second=0)
        latest = base  # 前日24:00 = 当日0:00
        label = (base - timedelta(days=1)).strftime("%Y年%m月%d日")
        desc = "13:00〜24:00"
    else:
        # 13:15 実行: 当日0:00〜13:00
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        oldest = base
        latest = base.replace(hour=13, minute=0, second=0)
        label = base.strftime("%Y年%m月%d日")
        desc = "0:00〜13:00"

    return oldest.timestamp(), latest.timestamp(), label, desc


def fetch_messages(client: WebClient, channel_id: str, oldest: float, latest: float) -> list[dict]:
    """指定チャンネルの指定時間範囲のメッセージを取得する"""
    messages = []
    cursor = None

    while True:
        try:
            response = client.conversations_history(
                channel=channel_id,
                oldest=str(oldest),
                latest=str(latest),
                limit=200,
                cursor=cursor,
            )
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

    lines = [header, f"（{len(filtered)}名）", ""]
    
    for i, talent in enumerate(filtered, 1):
        # 各人材情報の前に番号を付ける
        formatted = format_talent_block(talent)
        lines.append(f"【{i}人目】")
        lines.append(formatted)
        lines.append("")  # 人材間は2行空ける（appendで1行 + ここで1行）
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

    messages = fetch_messages(client, SOURCE_CHANNEL_ID, oldest_ts, latest_ts)
    print(f"  {len(messages)} 件のメッセージを取得しました。")

    # 人材情報を抽出・フィルタリング
    filtered = []
    seen = set()  # 重複チェック用
    
    for msg in messages:
        text = msg.get("text", "")
        talent_blocks = extract_talent_blocks(text)
        
        for block in talent_blocks:
            # 【稼働可能時間数】が160時間/100%かチェック
            if is_full_time_talent(block):
                # 【氏名】で重複チェック
                name_match = re.search(r"【氏名】(.+?)(?:\n|$)", block)
                if name_match:
                    name = name_match.group(1).strip()
                    if name not in seen:
                        seen.add(name)
                        filtered.append(block)

    print(f"  条件に合致: {len(filtered)} 名")

    # 要約テキスト生成
    summary = format_summary(filtered, date_label, time_desc)
    print("\n" + "=" * 60)
    print(summary)
    print("=" * 60)

    # Slackへの投稿
    if OUTPUT_CHANNEL_ID:
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
