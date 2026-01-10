#=========================
# ライブラリのインポート
#=========================
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select
import asyncio
from datetime import datetime, timedelta
import os
import json
import emoji

# Botの準備
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

#===================================
# 定数・グローバル変数・辞書の準備
#===================================
# -----リマインダー辞書の読込-----
def load_reminders():
    # reminders.jsonが存在すれば
    if os.path.exists("/mnt/reminders/reminders.json"):
        #fileオブジェクト変数に格納
        with open("/mnt/reminders/reminders.json", "r", encoding = "utf-8") as file:
            load_data = json.load(file) 
            #load_reminder関数の戻り値を設定
            return {datetime.fromisoformat(key): value for key, value in load_data.items()}
        print(f"辞書ファイルを読込完了: {datetime.now()}")
    else:
        #jsonが存在しない場合は、戻り値を空の辞書にする
        return {}

# -----辞書を定義-----
rmd_dt = {}
#jsonファイルの内容または空の辞書
reminders = load_reminders() 

#===============
# 共通処理関数
#===============
# -----辞書をjsonファイルに保存-----
def export_reminders():
    #remindersに値を代入するためグローバル宣言
    global reminders
    #jsonファイルを開く（存在しなければ作成する）
    with open("/mnt/reminders/reminders.json", "w", encoding = "utf-8") as file:
        # datetime形式をstr形式に変換してから保存
        json.dump(
            {dt.isoformat(): value for dt, value in reminders.items()}, file, ensure_ascii=False, indent=2) 
    print(f"辞書ファイルを保存完了: {datetime.now()}")

# -----辞書への予定登録処理-----
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
    export_reminders()

# -----リマインダーの削除-----
def remove_reminder(dt, idx=None):
    # idxがNoneの場合は日時全体を削除、そうでなければ指定インデックスの行を削除
    if idx is None:
        if dt in reminders:
            del reminders[dt]
            export_reminders()
            print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')}")
        return None
    else:
        removed = reminders[dt].pop(idx-1)
        # 値が空の日時全体を削除
        if not reminders[dt]:
            del reminders[dt]
        export_reminders()
        print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}")
        return removed

# 通知用ループ
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
                # 現在時刻を取得して次のゼロ秒までsleep
        now = datetime.now()
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
                    print (f"チャンネルにメッセージを送信: {datetime.now()}")
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
class ReminderSelect(View):
    # クラスの初期設定
    def __init__(self, reminders_dict):
        super().__init__()
        # remindersプロパティにreminders_dictをセット
        self.reminders = reminders_dict
        
        #削除選択リストの定義
        options = []
        for dt, values in reminders_dict.items():
            for index, v in enumerate(values, start=1):
                msg = v["msg"]
                label = f"{dt.strftime('%Y/%m/%d %H:%M')} - {msg[:50]}"
                value = f"{dt.isoformat()}|{index}"
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
        dt_str, idx_str = value.split("|")
        dt = datetime.fromisoformat(dt_str)
        idx = int(idx_str)

        # 予定の削除
        removed = remove_reminder(dt, idx)

        # 削除完了メッセージの送信
        await interaction.message.edit(
            content=f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}",
            allowed_mentions=discord.AllowedMentions.none(),
            view=None
        )

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
    print(f"ループ開始: {datetime.now()}")
    bot.loop.create_task(reminder_loop())

#===============
# コマンド定義
#===============
# /remind コマンド
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
    dt = datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M")

    # チャンネルIDの取得
    if channel:
        channel_id = channel.id
    else:
        channel_id = interaction.channel.id
    
    # add_reminder関数に渡す
    add_reminder(dt, repeat, interval, channel_id, msg)

    await interaction.response.send_message(f"{dt.strftime('%Y/%m/%d %H:%M')} にリマインダーをセットしました:saluting_face:")
    print(f"予定を追加: {reminders[dt]}")

# /reminder_list コマンド
@bot.tree.command(name="reminder_list", description="リマインダーの一覧を表示します")
async def reminder_list(interaction: discord.Interaction):
    # 空のリストを作成
    items = []

    # remindersの中身を取り出してリストに格納
    for dt, value in reminders.items():
        dt_str = dt.strftime("%Y/%m/%d %H:%M")
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

# /reminder_delete コマンド
@bot.tree.command(name="reminder_delete", description="リマインダー一覧を表示します")
async def reminder_delete(interaction: discord.Interaction):
    # リマインダーが設定されている場合、選択メニューを表示
    if reminders:
        view = ReminderSelect(reminders)
        await interaction.response.send_message("削除するリマインダーを選択", view=view)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await interaction.response.send_message("リマインダーは設定されていません")

# /poll コマンド
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
    embed = discord.Embed(title=question, description=description, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)
    
    # リアクションを追加
    message = await interaction.original_response()
    for i, opt in enumerate(options):
        if opt:
            await message.add_reaction(reactions[i])

# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))