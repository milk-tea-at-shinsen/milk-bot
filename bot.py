#=========================
# ライブラリのインポート
#=========================
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select
import asyncio
from datetime import datetime, timedelta, timezone
import os
import json
import emoji
from enum import Enum
import csv, io
from google.cloud import vision
from google.oauth2 import service_account
import aiohttp

# Botの準備
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# サービスアカウントキーの読込
info = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
credentials = service_account.Credentials.from_service_account_info(info)
client = vision.ImageAnnotatorClient(credentials=credentials)

#===================================
# 定数・グローバル変数・辞書の準備
#===================================

#=====タイムゾーンの指定=====
JST = timezone(timedelta(hours=9), "JST")

#=====辞書読込共通処理=====
def load_data(data):
    # reminders.jsonが存在すれば
    if os.path.exists(f"/mnt/data/{data}.json"):
        #fileオブジェクト変数に格納
        with open(f"/mnt/data/{data}.json", "r", encoding = "utf-8") as file:
            print(f"辞書ファイルを読込完了: {datetime.now(JST)} - {data}")
            return json.load(file)
    else:
        #jsonが存在しない場合は、戻り値を空の辞書にする
        return {}

#=====各辞書読込前処理=====
#---リマインダー辞書---
data_raw = load_data("reminders")
if data_raw:
    reminders = {datetime.fromisoformat(key): value for key, value in data_raw.items()}
else:
    reminders = {}
print(f"dict reminders: {reminders}")

#---投票辞書---
data_raw = load_data("votes")
if data_raw:
    votes = {int(key): value for key, value in data_raw.items()}
else:
    votes = {}
print(f"dict votes: {votes}")

#---代理投票辞書---
data_raw = load_data("proxy_votes")
if data_raw:
    msg_id, values = next(iter(data_raw.items()))
    if "option" in values:
        proxy_votes = {}
    else:
        proxy_votes = {int(key): value for key, value in data_raw.items()}
else:
    proxy_votes = {}
print(f"dict proxy_votes: {proxy_votes}")


#===============
# 共通処理関数
#===============
#=====辞書をjsonファイルに保存=====
def export_data(data: dict, name: str):
    # 指定ディレクトリがなければ作成する
    os.makedirs(f"/mnt/data", exist_ok=True)
    #jsonファイルを開く（存在しなければ作成する）
    with open(f"/mnt/data/{name}.json", "w", encoding = "utf-8") as file:
        # jsonファイルを保存
        json.dump(data, file, ensure_ascii=False, indent=2) 
    print(f"辞書ファイルを保存完了: {datetime.now(JST)} - {name}")

#=====jsonファイル保存前処理=====
#---リマインダー---
def save_reminders():
    reminders_to_save = {dt.isoformat(): value for dt, value in reminders.items()}
    export_data(reminders_to_save, "reminders")

#---投票---
def save_votes():
    export_data(votes, "votes")

#---投票---
def save_proxy_votes():
    export_data(proxy_votes, "proxy_votes")
    
#=====辞書への登録処理=====
#---リマインダー---
def add_reminder(dt, repeat, interval, channel_id, msg):
    # 日時が辞書になければ辞書に行を追加
    if dt not in reminders:
        reminders[dt] = []
    # 辞書に項目を登録
    reminders[dt].append(
        {"repeat": repeat,
         "interval": interval,
         "channel_id": channel_id,
         "msg": msg}
    )
    # json保存前処理
    save_reminders()

#---投票---
def add_vote(msg_id, question, reactions, options):
    # 辞書に項目を登録
    votes[msg_id] = {
        "question": question,
        "reactions": reactions,
        "options": options
    }

    # json保存前処理
    save_votes()

#---代理投票---
def add_proxy_votes(msg_id, voter, agent_id, opt_idx):
    print("[start: add_proxy_votes]")
    # msg_idが辞書になければ辞書に行を追加
    if msg_id not in proxy_votes:
        proxy_votes[msg_id] = {}
    
    # 辞書に項目を登録
    proxy_votes[msg_id][voter] = {
        "agent_id": agent_id,
        "opt_idx": opt_idx
    }

    # json保存前処理
    save_proxy_votes()

#=====辞書からの削除処理=====
#---リマインダー---
def remove_reminder(dt, idx=None):
    # idxがNoneの場合は日時全体を削除、そうでなければ指定インデックスの行を削除
    if idx is None:
        if dt in reminders:
            removed = reminders[dt]
            del reminders[dt]
            save_reminders()
            print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')}")
            return removed
        else:
            print(f"削除対象のリマインダーがありません")
            return None
    else:
        if dt in reminders and 0 <= (idx-1) < len(reminders[dt]):
            removed = reminders[dt].pop(idx-1)
            # 値が空の日時全体を削除
            if not reminders[dt]:
                del reminders[dt]
            save_reminders()
            print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}")
            return removed
        else:
            print(f"削除対象のリマインダーがありません")
            return None

#---投票---
def remove_vote(msg_id):
    print("[start: remove_vote]")
    if msg_id in votes:
        removed = votes[msg_id]
        del votes[msg_id]
        save_votes()
        print(f"投票を削除: {removed['question']}")
        return removed
    else:
        print(f"削除対象の投票がありません")
        return None
        
#---代理投票---
def remove_proxy_vote(msg_id):
    print("[start: remove_proxy_vote]")
    if msg_id in proxy_votes:
        removed = proxy_votes[msg_id]
        del proxy_votes[msg_id]
        save_proxy_votes()
        print(f"代理投票({msg_id})を削除しました")
        return removed
    else:
        print(f"削除対象の代理投票がありません")
        return None

#---代理投票(個別投票キャンセル)---
def cancel_proxy_vote(msg_id, voter, agent_id):
    print("[start: cancel_proxy_vote]")
    if msg_id in proxy_votes:
        # 該当する投票を取り出して投票者と代理人が一致するものを削除
        for key, value in proxy_votes[msg_id].items():
            if (key, value["agent_id"]) == (voter, agent_id):
                removed = proxy_votes[msg_id][voter]
                del proxy_votes[msg_id][voter]
                print(f"{voter}の代理投票({msg_id})をキャンセルしました")
                return removed
            else:
                print(f"キャンセル対象の代理投票がありません")
                return None

#=====UI選択後の処理=====
#---リマインダー削除---
async def handle_remove_reminder(interaction, dt, idx):
        removed = remove_reminder(dt, idx)

        # 削除完了メッセージの送信
        await interaction.message.edit(
            content=f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}",
            allowed_mentions=discord.AllowedMentions.none(),
            view=None
        )

#---投票集計---
async def make_vote_result(interaction, msg_id):
    print("[start: make_vote_result]")
    # 投票辞書を読み込み
    options = votes[msg_id]["options"]
    # メッセージを読み込み
    message = await interaction.channel.fetch_message(msg_id)
    # サーバー情報を読み込み
    guild = interaction.guild
    
    # 結果用辞書を準備
    result = {}
    # 結果用辞書に結果を記録
    for i, reaction in enumerate(message.reactions):
        #users = []
        #display_names = []
        
        # リアクション投票分
        # リアクションしたユーザーがbotでなければリストに追加
        reaction_users = [reaction_user async for reaction_user in reaction.users() if reaction_user != bot.user]
        users = [user.mention for user in reaction_users]
        display_names = [user.display_name for user in reaction_users]
        
        # 代理投票分
        if msg_id in proxy_votes:
            # 投票者の投票内容を確認し該当する選択肢のものがあればリストに追加
            for voter, values in proxy_votes[msg_id].items():
                for opt_idx in values["opt_idx"]:
                    if opt_idx == i:
                        agent_id = values["agent_id"]
                        # 代理人のidから代理人を検索
                        agent = guild.get_member(agent_id)
                        # 代理人が最近のキャッシュに見つからなければサーバー情報から検索
                        if agent is None:
                            try:
                                agent = await guild.fetch_member(agent_id)
                            # それでも見つからない場合はNoneを表示
                            except:
                                agent = None
                        if agent:
                            agent_display_name = agent.display_name
                        else:
                            agent_display_name = "None"
                        
                        users.append(f"{voter}(by{agent_display_name})")
                        display_names.append(f"{voter}(by{agent_display_name})")
            
        result[i] = {
            "emoji": reaction.emoji,
            "option": options[i],
            "count": len(users),
            "users": users,
            "display_names": display_names
        }
    dt = datetime.now(JST)
    return dt, result

#---投票結果表示---
async def show_vote_result(interaction, dt, result, msg_id, mode):
    print("[start: show_vote_result]")
    # Embedの設定
    embed = discord.Embed(
        title="投票結果",
        description=votes[msg_id]["question"],
        color=discord.Color.green()
    )
    # 投票結果からフィールドを作成
    for i in result:
        emoji = result[i]["emoji"]
        option = result[i]["option"]
        count = result[i]["count"]
        users = result[i]["users"]
        user_list = ", ".join(users) if users else "なし"
        embed.add_field(name=f"{emoji} {option} - {count}人", value=f"メンバー: {user_list}", inline=False)
    # フッター
    if mode == "mid":
        mode_str = "中間集計"
    else:
        mode_str = "最終結果"
    embed.set_footer(text=f"{mode_str} - {dt.strftime('%Y/%m/%d %H:%M')}")
    # embedを表示
    await interaction.message.edit(
        content=None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions.none(),
        view=None
    )

#---投票結果rows作成処理(選択肢グループ)---
def make_grouped_rows(result):
    print("[start: make_grouprd_rows]")
    # 空のリストを用意
    header = []
    rows = []
    users = []
    max_users = 0
    
    # 選択肢リストと選択肢ごとのユーザーリストを作成
    # resultをキー(インデックス)と値に分離
    for i, value in result.items():
        # 選択肢を連結
        header.append(value["option"])
        # 選択肢ごとの選択肢を連結
        if value.get("display_names") is None:
            users.append(value["users"])
        else:
            users.append(value["display_names"])
        # ユーザーの最大値を取得
        if len(value["users"]) > max_users:
            max_users = len(value["users"])
    
    # ユーザーリストの行列を入れ替え
    for i in range(max_users):
        # rowをリセット
        #row = []
        # 各ユーザーリストの同番のユーザーをrowに並べる, 存在しない場合は空文字を追加
        row = [users[j][i] if i < len(users[j]) else "" for j in range(len(header))]
        # rowをまとめてrowsを作る
        rows.append(row)
    
    return header, rows

#---投票結果rows作成処理(一覧)---
def make_listed_rows(result):
    print("[start: make_listed_rows]")
    header = ["option", "users"]
    
    rows = [
        [value["option"], user]
         for key, value in result.items()
         for user in value["display_names"]
    ]
    
    return header, rows

#---CSV作成処理---
def make_csv(filename, rows, meta=None, header=None):
    print("[start: make_csv]")
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        # metaの書込
        if meta:
            for key, value in meta.items():
                writer.writerow([f"#{key}: {value}"])
        # headerの書込
        if header:
            writer.writerow(header)
        # rowsの書込
        writer.writerows(rows)

#---投票結果CSV出力処理---
async def export_vote_csv(interaction, result, msg_id, dt, mode):
    print("[start: export_vote_csv]")
    meta = {
        "question": votes[msg_id]["question"],
        "status": mode,
        "collected_at": dt.strftime("%Y/%m/%d %H:%M")
    }
    
    # csv(グループ型)の作成
    header, rows = make_grouped_rows(result)
    grouped_file = f"/tmp/{dt.strftime('%Y%m%d_%H%M')}_grouped.csv"
    make_csv(grouped_file, rows, meta, header)
    
    # csv(リスト型)の作成
    header, rows = make_listed_rows(result)
    listed_file = f"/tmp/{dt.strftime('%Y%m%d_%H%M')}_listed.csv"
    make_csv(listed_file, rows, meta, header)
    
    # discordに送信
    await interaction.followup.send(
        content="投票集計結果のCSVだよ(\*`･ω･)ゞ",
        files=[discord.File(grouped_file), discord.File(listed_file)]
    )

#=====OCR関係の処理=====
#---画像取得メッセージリストの作成---
async def collect_message(channel, counts, minutes, start_msg, limit_msg, direction):
        # 終了フラグをFalseに設定
        end_flag = False
        # 返信先メッセージをリストに格納
        messages = [start_msg]
        # 返信先メッセージをhistoryの最初の位置に設定
        loop_start_msg = start_msg.id
        # 件数指定なしまたは1未満の場合は1を設定
        if counts is None or counts < 1:
            counts = 1

        # 終了フラグが立つまでループ
        while end_flag is False:
            if direction == "forward":
                # historyの最初の位置より新しい100件分のメッセージを取得
                m = await channel.history(after=loop_start_msg, limit=100).flatten()
            else: # direction == "backward"
                # historyの最初の位置より古い100件分のメッセージを取得
                m = await channel.history(before=loop_start_msg, limit=100).flatten()

            # 取得数が100件未満または累計が指定数以上なら終了
            if len(m) < 100 or (len(messages) + len(m)) >= counts:
                end_flag = True
            # 終端メッセージに到達していたら終了、そうでなければ次のスタートを設定
            else:
                if direction == "forward":
                    if m[0].id == limit_msg.id:
                        end_flag = True
                    else:
                        loop_start_msg = m[0].id
                else: # direction == "backward"
                    if m[-1].id == limit_msg.id:
                        end_flag = True
                    else:
                        loop_start_msg = m[-1].id
            # リストに追加
            messages.extend(m if not end_flag else m[:counts - len(messages)])

        # リストを古い順にソート
        messages.sort(key=lambda msg: msg.created_at)
        # 件数でフィルタ
        messages = messages[:counts]

        if minutes:
            # 時間指定がある場合、取得するメッセージの範囲を計算
            if direction == "forward":
                start_time = start_msg.created_at
                end_time = start_time + timedelta(minutes=int(minutes))
            else: # direction == "backward"
                end_time = start_msg.created_at
                start_time = end_time - timedelta(minutes=int(minutes))
            # メッセージのタイムスタンプが範囲内ならリストに追加
            msg_ids = [msg.id for msg in messages if start_time <= msg.created_at <= end_time]

            return msg_ids

#---行センター出し関数---
def get_x_center(bounding_box):
    return sum(vertice.x for vertice in bounding_box.vertices) / 4

#---列センター出し関数---
def get_y_center(bounding_box):
    return sum(vertice.y for vertice in bounding_box.vertices) / 4

#---高さ出し関数---
def get_height(bounding_box):
    return max(vertice.y for vertice in bounding_box.vertices) - min(vertice.y for vertice in bounding_box.vertices)

#---symbol取得処理---
def get_symbols(response):
    print("[start: get_symbols]")
    symbols = [{
            "symbol": symbol.text,
            "x": get_x_center(symbol.bounding_box),
            "y": get_y_center(symbol.bounding_box),
            "height": get_height(symbol.bounding_box)
        }
        for page in response.full_text_annotation.pages
        for block in page.blocks
        for paragraph in block.paragraphs
        for word in paragraph.words
        for symbol in word.symbols
    ]
    return symbols

#---行作成処理---
def cluster_lines(symbols, avr_height):
    print("[start: cluster_lines]")
    # symbolをy座標でソート
    symbols.sort(key=lambda symbol: symbol["y"])
    # y座標で同一行を判定
    line = []
    line_y = None
    lines = []
    for symbol in symbols:
        # 最初の行のy座標を設定
        if line_y is None:
            line_y =symbol["y"]
        # 行のy座標範囲内ならlineに追加
        if abs(symbol["y"] - line_y) < avr_height:
            line.append(symbol)
            line_y = (line_y + symbol["y"]) / 2
        # 行のy座標範囲外ならlinesにlineを追加してlineをリセット
        else:
            line.sort(key=lambda symbol: symbol["x"])
            lines.append(line)
            line = [symbol]
            line_y = symbol["y"]
    # 最終行をlinesに追加
    if line:
        line.sort(key=lambda symbol: symbol["x"])
        lines.append(line)
    return lines

#---列項目作成処理---
def cluster_rows(lines, avr_height):
    print("[start: cluster_rows]")
    # x座標で単語を判定
    word = []
    row = []
    rows = []
    prev_x = None
    for line in lines:
        for symbol in line:
            if prev_x is None:
                prev_x = symbol["x"]
            if (symbol["x"] - prev_x) < avr_height * 2:
                word.append(symbol["symbol"])
                prev_x = symbol["x"]
            else:
                row.append("".join(word))
                word = [symbol["symbol"]]
                prev_x = symbol["x"]
        # 最終単語をrowに追加して、rowをrowsに追加
        if word:
            row.append("".join(word))
            rows.append(row)
            word = []
            row = []
            prev_x = None
    return rows

#---最頻列数を取得---
def get_mode_columns(rows):
    col_counts = [len(row) for row in rows]
    return max(set(col_counts), key=col_counts.count)

#---表本体抽出処理---
def extract_table_body(rows):
    print("[start: extract_table_body]")

    mode_columns = get_mode_columns(rows)
    table_body = [row for row in rows if len(row) + 1 >= mode_columns]
    return table_body

#---OCR->CSV用データ整形処理---
def extract_table_from_image(image_content):
    image = vision.Image(content=image_content)
    response = client.document_text_detection(image=image)

    # symbolsを取得
    symbols = get_symbols(response)

    # 文字が存在しなかった場合
    if not symbols:
        return []
    else:
        # 文字の高さの平均を計算
        avr_height = sum(symbol["height"] for symbol in symbols) / len(symbols) 
        
        lines = cluster_lines(symbols, avr_height)
        rows = cluster_rows(lines, avr_height)
        rows = extract_table_body(rows)
        return rows

#---重複行削除処理---
def remove_duplicate_rows(rows):
    print("[start: remove_duplicate_rows]")
    unique_rows = []
    for row in rows:
        if row not in unique_rows:
            unique_rows.append(row)
    return unique_rows
    
#=====通知用ループ処理=====
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # 現在時刻を取得して次のゼロ秒までsleep
        now = datetime.now(JST)
        next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait = (next_minute - now).total_seconds()
        await asyncio.sleep(wait)

        # 辞書に該当時刻が登録されていた場合
        if next_minute in reminders:
            # 該当行を取り出してラベル付きリストに代入し値を取り出す
            for rmd_dt in reminders[next_minute]:
                channel_id = rmd_dt["channel_id"]
                repeat = rmd_dt["repeat"]
                interval = rmd_dt["interval"]
                msg = rmd_dt["msg"]
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"{msg}")
                    print (f"チャンネルにメッセージを送信: {datetime.now(JST)}")
                else:
                    print(f"チャンネル取得失敗: {channel_id}")
            
                # 繰り返し予定の登録
                if repeat:
                    if repeat == "day":
                        dt = next_minute + timedelta(days=interval)
                    elif repeat == "hour":
                        dt = next_minute + timedelta(hours=interval)
                    elif repeat == "minute":
                        dt = next_minute + timedelta(minutes=interval)
                    add_reminder(dt, repeat, interval, channel_id, msg)
            
            # 処理済の予定の削除
            remove_reminder(next_minute)

#===============
# クラス定義
#===============
#=====リマインダー選択UIクラス=====
class ReminderSelect(View):
    # クラスの初期設定
    def __init__(self, reminders):
        super().__init__()
        # remindersプロパティにリマインダー辞書をセット
        self.reminders = reminders
        
        #選択リストの定義
        options = []
        # リマインダー辞書から日時と項目を分離
        for dt, values in reminders.items():
            # 同一日時内の項目区別用インデックスを作成
            for index, v in enumerate(values, start=1):
                msg = v["msg"]
                # 選択肢に表示される項目を設定
                label = f"{dt.strftime('%Y/%m/%d %H:%M')} - {msg[:50]}"
                # 選択時に格納される値を設定
                value = f"{dt.isoformat()}|{index}"
                # optionsリストに表示項目と値を格納
                options.append(discord.SelectOption(label=label, value=value))
        
        #selectUIの定義
        if options:
            select = Select(
                placeholder="削除するリマインダーを選んでね",
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)
    
    # 削除処理の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        # 日時とインデックスを分離
        dt_str, idx_str = value.split("|")
        dt = datetime.fromisoformat(dt_str)
        idx = int(idx_str)

        # 予定の削除
        await handle_remove_reminder(interaction, dt, idx)

#=====投票選択UIクラス=====
class VoteSelect(View):
    # クラスの初期設定
    def __init__(self, votes, mode, voter=None, agent_id=None):
        super().__init__()
        # votesプロパティに投票辞書をセット
        self.votes = votes
        # modeプロパティに投票モードをセット
        self.mode = mode
        # voterプロパティに投票者名をセット
        self.voter = voter
        # agentプロパティに代理人をセット
        self.agent_id = agent_id

        #選択リストの定義
        options = []
        # 投票辞書からメッセージidと項目を分離
        for msg_id, v in votes.items():
            question = v["question"]
            # 選択肢に表示される項目を設定
            label = f"{question[:50]}"
            # 選択時に格納される値を設定
            value = f"{msg_id}"
            # optionsリストに表示項目と値を格納
            options.append(discord.SelectOption(label=label, value=value))
        
        #selectUIの定義
        if options:
            if mode == VoteSelectMode.PROXY_VOTE:
                select = Select(
                    placeholder="代理投票する投票を選んでね",
                    options = options
                )
            else:
                select = Select(
                    placeholder="集計する投票を選んでね",
                    options = options
                )
            select.callback = self.select_callback
            self.add_item(select)
    
    # 投票選択後処理の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        msg_id = int(interaction.data["values"][0])

        # 代理投票と集計で処理を分岐
        if self.mode == VoteSelectMode.PROXY_VOTE:
            # 代理投票処理
            view = VoteOptionSelect(msg_id, self.voter, self.agent_id)
            await interaction.followup.send("代理投票する選択肢を選んでね", view=view)
        # 代理投票キャンセル
        elif self.mode == VoteSelectMode.CANCEL_PROXY_VOTE:
            removed = cancel_proxy_vote(msg_id, self.voter, self.agent_id)
            if removed:
                await interaction.followup.send(f"**{self.voter}** の分の代理投票を取り消したよ(\*`･ω･)ゞ")
            else:
                await interaction.followup.send(f"取り消せる代理投票がないみたい(´･ω･`)")
        else:
            # 集計処理
            dt, result = await make_vote_result(interaction, msg_id)
            
            # 結果表示処理
            if self.mode == VoteSelectMode.MID_RESULT:
                mode = "mid"
            else:
                mode = "final"
            await show_vote_result(interaction, dt, result, msg_id, mode)
            
            # CSV作成処理
            await export_vote_csv(interaction, result, msg_id, dt, mode)
            
            # 投票辞書からの削除
            if self.mode == VoteSelectMode.FINAL_RESULT:
                remove_vote(msg_id)
                remove_proxy_vote(msg_id)

#=====投票選択肢選択UIクラス=====
class VoteOptionSelect(View):
    # クラスの初期設定
    def __init__(self, msg_id, voter, agent_id):
        super().__init__()
        # votesプロパティに投票辞書をセット
        self.votes = votes
        # msg_idプロパティにメッセージIDをセット
        self.msg_id = msg_id
        # voterプロパティに投票者名をセット
        self.voter = voter
        # agentプロパティに代理人をセット
        self.agent_id = agent_id

        #選択リストの定義
        options = []
        # 投票辞書からメッセージidと項目を分離
        for i, (reaction, opt) in enumerate(zip(votes[msg_id]["reactions"], votes[msg_id]["options"])):
            option = opt or ""
            # 選択肢に表示される項目を設定
            label = f"{reaction} {option[:50]}"
            # 選択時に格納される値を設定
            value = str(i)
            
            # optionsリストに表示項目と値を格納
            if option != "":
                options.append(discord.SelectOption(label=label, value=value))
        
        # selectUIの定義
        if options:
            select = Select(
                placeholder="代理投票する選択肢を選んでね",
                min_values = 1,
                max_values = len(options),
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)

    # 選択肢選択後の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        
        opt_idx = [int(opt_str) for opt_str in interaction.data["values"]]
        
        add_proxy_votes(self.msg_id, self.voter, self.agent_id, opt_idx)
        agent = guild.get_member(self.agent_id)
        agent_display_name = agent.display_name
        await interaction.followup.send(f"**{agent_display_name}** から **{self.voter}** の分の投票を受け付けたよ(\*`･ω･)ゞ")

#=====集計モード切替クラス=====
class VoteSelectMode(Enum):
    MID_RESULT = "mid_result"
    FINAL_RESULT = "final_result"
    PROXY_VOTE = "proxy_vote"
    CANCEL_PROXY_VOTE = "cancel_proxy_vote"

#====================
# イベントハンドラ
#====================
# Bot起動確認
@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    print(f"Botを起動: {bot.user}")
    print(f"同期されたコマンド: {[cmd.name for cmd in synced]}")
    
    # リマインダーループの開始
    print(f"ループ開始: {datetime.now(JST)}")
    bot.loop.create_task(reminder_loop())

#===============
# コマンド定義
#===============
#=====/remind コマンド=====
@bot.tree.command(name="remind", description="リマインダーをセットするよ")
@app_commands.describe(
    date="日付(yyyy/mm/dd)",
    time="時刻(hh:mm)",
    channel="通知するチャンネル",
    repeat="繰り返し単位",
    interval="繰り返し間隔",
    msg="内容"
)
@app_commands.choices(repeat=[
    app_commands.Choice(name="日", value="day"),
    app_commands.Choice(name="時間", value="hour"),
    app_commands.Choice(name="分", value="minute")
])
async def remind(interaction: discord.Interaction, date: str, time: str, msg: str, channel: discord.TextChannel = None, repeat: str = None, interval: int = 0):
    # 文字列引数からdatatime型に変換
    dt = datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M").replace(tzinfo=JST)

    # チャンネルIDの取得
    if channel:
        channel_id = channel.id
    else:
        channel_id = interaction.channel.id
    
    # add_reminder関数に渡す
    add_reminder(dt, repeat, interval, channel_id, msg)

    await interaction.response.send_message(f"**{dt.strftime('%Y/%m/%d %H:%M')}** にリマインダーをセットしたよ(\*`･ω･)ゞ")
    print(f"予定を追加: {reminders[dt]}")

#=====/reminder_list コマンド=====
@bot.tree.command(name="reminder_list", description="リマインダーの一覧を表示するよ")
async def reminder_list(interaction: discord.Interaction):
    # 空のリストを作成
    items = []

    # remindersの中身を取り出してリストに格納
    for dt, value in reminders.items():
        dt_str = dt.strftime("%Y/%m/%d %H:%M")
        # 同一日時の予定をrmd_dtに分解
        for rmd_dt in value:
            channel = bot.get_channel(rmd_dt["channel_id"])
            if channel:
                mention = channel.mention
            else:
                mention = f"ID: {rmd_dt['channel_id']}"
            items.append((dt_str, mention, rmd_dt["msg"]))

    # リマインダー一覧をEmbedで表示        
    if items:
        embed = discord.Embed(title="リマインダー一覧", color=discord.Color.blue())
        for dt_txt, mention, msg in items:
            embed.add_field(name=dt_txt, value=f"{mention} - {msg}", inline=False)
        await interaction.response.send_message(embed=embed)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await interaction.response.send_message("設定されているリマインダーがないみたい(´･ω･`)")

#=====/reminder_delete コマンド=====
@bot.tree.command(name="reminder_delete", description="リマインダーを削除するよ")
async def reminder_delete(interaction: discord.Interaction):
    # リマインダーが設定されている場合、選択メニューを表示
    if reminders:
        view = ReminderSelect(reminders)
        await interaction.response.send_message("削除するリマインダーを選んでね", view=view)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await interaction.response.send_message("設定されているリマインダーがないみたい(´･ω･`)")

#=====/vote コマンド=====
@bot.tree.command(name="vote", description="投票を作成するよ")
@app_commands.describe(
    question="質問を書いてね",
    opt_1="1番目の選択肢を書いてね",
    opt_2="2番目の選択肢を書いてね",
    opt_3="3番目の選択肢を書いてね",
    opt_4="4番目の選択肢を書いてね",
    opt_5="5番目の選択肢を書いてね",
    opt_6="6番目の選択肢を書いてね",
    opt_7="7番目の選択肢を書いてね",
    opt_8="8番目の選択肢を書いてね",
    opt_9="9番目の選択肢を書いてね",
    opt_10="10番目の選択肢を書いてね",
)
async def vote(interaction: discord.Interaction,
     question: str, opt_1: str, opt_2: str=None, opt_3: str=None, opt_4: str=None, opt_5: str=None,
     opt_6: str=None, opt_7: str=None, opt_8: str=None, opt_9: str=None, opt_10: str=None): 
    # 選択肢をリストに格納
    options = [opt_1, opt_2, opt_3, opt_4, opt_5, opt_6, opt_7, opt_8, opt_9, opt_10]
    # リアクションリスト
    reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    # 選択肢表示を初期化
    description = ""

    for i, opt in enumerate(options):
        if opt:
            first_char = opt[0]
            if first_char in emoji.EMOJI_DATA:
                # 選択肢の最初の文字が絵文字の場合、その絵文字をリアクションに差替
                reactions[i] = first_char
                # 選択肢から最初の文字を削除
                o = opt[1:]
                options[i] = o

    # Embedで出力
    for i, opt in enumerate(options):
        if opt:
            description += f"{reactions[i]} {opt}\n"
    embed = discord.Embed(title=question, description=description, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)
    
    # リアクションを追加
    message = await interaction.original_response()
    for i, opt in enumerate(options):
        if opt:
            await message.add_reaction(reactions[i])
    
    # 辞書に保存
    add_vote(message.id, question, reactions, options)

#=====/vote_result コマンド=====
@bot.tree.command(name="vote_result", description="投票結果を表示するよ")
@app_commands.describe(mode="集計モード")
@app_commands.choices(mode=[
    app_commands.Choice(name="中間集計", value="mid"),
    app_commands.Choice(name="最終結果", value="final")
])
async def vote_result(interaction: discord.Interaction, mode: str):
    if votes:
        if mode == "mid":
            view = VoteSelect(votes=votes, mode=VoteSelectMode.MID_RESULT, voter=None, agent_id=None)
            await interaction.response.send_message("どの投票結果を表示するか選んでね", view=view)
        elif mode == "final":
            view = VoteSelect(votes=votes, mode=VoteSelectMode.FINAL_RESULT, voter=None, agent_id=None)
            await interaction.response.send_message("どの投票結果を表示するか選んでね", view=view)
        else:
            await interaction.response.send_message("選択モードの指定がおかしいみたい(´･ω･`)")

    # 投票がない場合のメッセージ
    else:
        await interaction.response.send_message("集計できる投票がないみたい(´･ω･`)")

#=====/proxy_vote コマンド=====
@bot.tree.command(name="proxy_vote", description="本人の代わりに代理投票するよ")
@app_commands.describe(voter = "投票する本人の名前を書いてね")
async def proxy_vote(interaction: discord.Interaction, voter: str):
    if votes:
        agent_id = interaction.user.id
        view = VoteSelect(votes=votes, mode=VoteSelectMode.PROXY_VOTE, voter=voter, agent_id=agent_id)
        await interaction.response.send_message("どの投票に代理投票するか選んでね", view=view)
    else:
        await interaction.response.send_message("代理投票できる投票がないみたい(´･ω･`)")

#=====/cancel_proxy コマンド=====
@bot.tree.command(name="cancel_proxy", description="投票済みの代理投票を取り消すよ")
@app_commands.describe(voter = "投票者名")
async def cancel_proxy(interaction: discord.Interaction, voter: str):
    if votes:
        agent_id = interaction.user.id
        view = VoteSelect(votes=votes, mode=VoteSelectMode.CANCEL_PROXY_VOTE, voter=voter, agent_id=agent_id)
        await interaction.response.send_message("代理投票を取り消しする投票を選んでね", view=view)
    else:
        await interaction.response.send_message("取り消しできる投票がないみたい(´･ω･`)")

#=====/export_members コマンド=====
@bot.tree.command(name="export_members", description="サーバーのメンバーリストを出力するよ")
async def export_members(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    
    filename = f"/tmp/members_list_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.csv"
    meta = {
        "members_at": guild.name,
        "collected_at": datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    }
    header = ["user_id", "display_name"]
    rows = [[member.id, member.display_name] async for member in guild.fetch_members(limit=None)]
    
    make_csv(filename, rows, meta, header)
    
    # discordに送信
    await interaction.followup.send(
        content="メンバー一覧のCSVだよ(\*`･ω･)ゞ",
        file=discord.File(filename)
    )

#=====/table_ocr コマンド=====
@bot.tree.command(name="table_ocr", description="表の画像からCSVを作成するよ")
@app_commands.describe(minutes = "時間指定(分)", counts = "件数指定(件)")
async def table_ocr(interaction: discord.Interaction, minutes: str = None, counts: str = None):
    await interaction.response.defer()

    # 返信コマンド実行時
    if interaction.data.resolved.messages:
        # 返信先のメッセージの情報を取得
        start_msg_id = next(iter(interaction.data.resolved.messages.values()), None)
        start_msg = await interaction.channel.fetch_message(start_msg_id)
        # チャンネルの最新メッセージを取得
        limit_msg = await interaction.channel.fetch_message(interaction.channel.last_message_id)

        msg_ids = collect_message(interaction.channel, counts, minutes, start_msg, limit_msg, "forward")

    # 単独コマンド入力時
    else:
        # チャンネルの最新メッセージを取得
        start_msg = await interaction.channel.fetch_message(interaction.channel.last_message_id)
        # チャンネルの一番古いメッセージを取得
        limit_msg = await interaction.channel.history(after=None, limit=1).flatten()
        limit_msg = limit_msg[0]

        msg_ids = collect_message(interaction.channel, counts, minutes, start_msg, limit_msg, "backward")

#=====context_ocr コマンド=====
@bot.tree.context_menu(name="context_ocr")
async def context_ocr(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer()
    
    if not message.attachments:
        await interaction.response.send("画像が添付されてないよ(´･ω･`)")
        return

    # 画像ごとにOCR処理を実行してtemp_rowsに格納
    temp_rows = []
    for i, attachment in enumerate(message.attachments):
        attachment = message.attachments[i]

        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                content = await resp.read()
    
        # visionからテキストを受け取ってCSV用に整形
        temp_rows.extend(extract_table_from_image(content))
    print(f"temp_rows:{temp_rows}")
    # 重複行を削除
    rows = remove_duplicate_rows(temp_rows)
    print(f"rows:{rows}")
    
    # csv作成処理
    filename = f"/tmp/ocr_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.csv"
    make_csv(filename, rows)
    
    # CSVを出力
    await interaction.followup.send(
        content="OCR結果のCSVだよ(\*`･ω･)ゞ",
        file=discord.File(filename)
    )
    
# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))
