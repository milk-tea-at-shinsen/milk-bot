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

# Botの準備
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

#=====各辞書定義=====
#---リマインダー辞書---
data_raw = load_data("reminders")
if data_raw:
    reminders = {datetime.fromisoformat(key): value for key, value in data_raw.items()}
else:
    reminders = {}

#---投票辞書---
data_raw = load_data("polls")
if data_raw:
    polls = {int(key): value for key, value in data_raw.items()}
else:
    polls = {}

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
def save_polls():
    export_data(polls, "polls")

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
def add_poll(msg_id, question, options):
    # 辞書に項目を登録
    polls[msg_id] = {
        "question": question,
        "options": options
    }

    # json保存前処理
    save_polls()

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
def remove_poll(msg_id):
    print("[start: remove_poll]")
    if msg_id in polls:
        removed = polls[msg_id]
        del polls[msg_id]
        save_polls()
        print(f"投票を削除: {removed['question']}")
        return removed
    else:
        print(f"削除対象の投票がありません")
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
async def make_poll_result(interaction, msg_id):
    print("[start: make_poll_result]")
    # 投票辞書を読み込み
    options = polls[msg_id]["options"]
    # メッセージを読み込み
    message = await interaction.channel.fetch_message(msg_id)
    # 結果用辞書を準備
    result = {}
    # 結果用辞書に結果を記録
    for i, reaction in enumerate(message.reactions):
        users = []
        display_names = []
        async for user in reaction.users():
            if user != bot.user:
                users.append(user.mention)
                display_names.append(user.display_name)
        result[i] = {
            "emoji": reaction.emoji,
            "option":options[i],
            "count":len(users),
            "users":users,
            "display_names": display_names
        }
    dt = datetime.now(JST)
    return dt, result

#---投票結果表示---
async def show_poll_result(interaction, dt, result, msg_id, mode):
    print("[start: show_poll_result]")
    # Embedの設定
    embed = discord.Embed(
        title="投票結果",
        description=polls[msg_id]["question"],
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
        row = []
        # 各ユーザーリストの同番のユーザーをrowに並べる
        for j in range(len(header)):
            if i < len(users[j]):
                row.append(users[j][i])
            # ユーザーリストを使い切っている場合は空欄を連結
            else:
                row.append("")
        # rowをまとめてrowsを作る
        rows.append(row)
    
    return header, rows

#---投票結果rows作成処理(一覧)---
def make_listed_rows(result):
    print("[start: make_listed_rows]")
    header = ["option", "users"]
    rows = []
    
    for i, value in result.items():
        for user in value["display_names"]:
            rows.append([value["option"], user])
    
    return header, rows

#---投票結果CSV作成処理---
def make_poll_csv(filename, meta, header, rows):
    print("[start: make_poll_csv]")
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # metaの書込
        for key, value in meta.items():
            writer.writerow([f"#{key}: {value}"])
        # headerの書込
        writer.writerow(header)
        # rowsの書込
        writer.writerows(rows)

#---投票結果CSV出力処理---
async def export_poll_csv(interaction, result, msg_id, dt, mode):
    print("[start: export_poll_csv]")
    meta = {
        "question": polls[msg_id]["question"],
        "status": mode,
        "collected_at": dt.strftime("%Y/%m/%d %H:%M")
    }
    
    # csv(グループ型)の作成
    header, rows = make_grouped_rows(result)
    grouped_file = f"/tmp/{dt.strftime('%Y%m%d_%H%M')}_grouped.csv"
    make_poll_csv(grouped_file, meta, header, rows)
    
    # csv(リスト型)の作成
    header, rows = make_listed_rows(result)
    listed_file = f"/tmp/{dt.strftime('%Y%m%d_%H%M')}_listed.csv"
    make_poll_csv(listed_file, meta, header, rows)
    
    # discordに送信
    await interaction.followup.send(
        content="集計結果CSV",
        files=[discord.File(grouped_file), discord.File(listed_file)]
    )

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
                placeholder="削除するリマインダーを選択",
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
class PollSelect(View):
    # クラスの初期設定
    def __init__(self, polls, mode):
        super().__init__()
        # pollsプロパティに投票辞書をセット
        self.polls = polls
        # modeプロパティに投票モードをセット
        self.mode = mode

        #選択リストの定義
        options = []
        # 投票辞書からメッセージidと項目を分離
        for msg_id, v in polls.items():
            question = v["question"]
            # 選択肢に表示される項目を設定
            label = f"{question[:50]}"
            # 選択時に格納される値を設定
            value = f"{msg_id}"
            # optionsリストに表示項目と値を格納
            options.append(discord.SelectOption(label=label, value=value))
        
        #selectUIの定義
        if options:
            select = Select(
                placeholder="集計する投票を選択",
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)
    
    # 集計処理の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        msg_id = int(interaction.data["values"][0])

        # 集計処理
        dt, result = await make_poll_result(interaction, msg_id)
        
        # 結果表示処理
        if self.mode == PollResultMode.MID_RESULT:
            mode = "mid"
        else:
            mode = "final"
        await show_poll_result(interaction, dt, result, msg_id, mode)
        
        # CSV作成処理
        await export_poll_csv(interaction, result, msg_id, dt, mode)
        
        # 投票辞書からの削除
        if self.mode == PollResultMode.FINAL_RESULT:
            remove_poll(msg_id)

#=====集計モード切替クラス=====
class PollResultMode(Enum):
    MID_RESULT = "mid_result"
    FINAL_RESULT = "final_result"

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
@bot.tree.command(name="remind", description="リマインダーをセットします")
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

    await interaction.response.send_message(f"{dt.strftime('%Y/%m/%d %H:%M')} にリマインダーをセットしました:saluting_face:")
    print(f"予定を追加: {reminders[dt]}")

#=====/reminder_list コマンド=====
@bot.tree.command(name="reminder_list", description="リマインダーの一覧を表示します")
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
        await interaction.response.send_message("リマインダーは設定されていません")

#=====/reminder_delete コマンド=====
@bot.tree.command(name="reminder_delete", description="リマインダー一覧を表示します")
async def reminder_delete(interaction: discord.Interaction):
    # リマインダーが設定されている場合、選択メニューを表示
    if reminders:
        view = ReminderSelect(reminders)
        await interaction.response.send_message("削除するリマインダーを選択", view=view)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await interaction.response.send_message("リマインダーは設定されていません")

#=====/poll コマンド=====
@bot.tree.command(name="poll", description="投票を作成します")
@app_commands.describe(
    question="質問",
    opt_1="選択肢1",
    opt_2="選択肢2",
    opt_3="選択肢3",
    opt_4="選択肢4",
    opt_5="選択肢5",
    opt_6="選択肢6",
    opt_7="選択肢7",
    opt_8="選択肢8",
    opt_9="選択肢9",
    opt_10="選択肢10",
)
async def poll(interaction: discord.Interaction,
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
    add_poll(message.id, question, options)

#=====/poll_result コマンド=====
@bot.tree.command(name="poll_result", description="投票結果を表示します")
@app_commands.describe(mode="集計モード")
@app_commands.choices(mode=[
    app_commands.Choice(name="中間集計", value="mid"),
    app_commands.Choice(name="最終結果", value="final")
])
async def poll_result(interaction: discord.Interaction, mode: str):
    if polls:
        if mode == "mid":
            view = PollSelect(polls, PollResultMode.MID_RESULT)
            await interaction.response.send_message("結果表示する投票を選択", view=view)
        elif mode == "final":
            view = PollSelect(polls, PollResultMode.FINAL_RESULT)
            await interaction.response.send_message("結果表示する投票を選択", view=view)
        else:
            await interaction.response.send_message("集計モードの指定が不正です")

    # 投票がない場合のメッセージ
    else:
        await interaction.response.send_message("投票がありません")

# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))
