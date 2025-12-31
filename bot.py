#====================
# ライブラリのインポート
#====================
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select
import asyncio
import datetime
from datetime import datetime
import os
import json

# Botの準備
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

#==============================
# 定数・グローバル変数・辞書の準備
#==============================
# リマインダー辞書の読込
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

# 辞書を定義
rmd_dt = {}
#jsonファイルの内容または空の辞書
reminders = load_reminders() 

#===============
# 共通処理関数
#===============
# 辞書をjsonファイルに保存
def export_reminders():
    #remindersに値を代入するためグローバル宣言
    global reminders
    #jsonファイルを開く（存在しなければ作成する）
    with open("/mnt/reminders/reminders.json", "w", encoding = "utf-8") as file:
        # datetime形式をstr形式に変換してから保存
        json.dump({dt.isoformat(): value for dt, value in reminders.items()}, file, ensure_ascii=False, indent=2) 
    print(f"辞書ファイルを保存完了: {datetime.now()}")

# 辞書登録処理
def add_reminder(dt, repeat, interval, channel_id, msg):
    # 日時が辞書になければ辞書に行を追加
    if dt not in reminders:
        reminders[dt] = []
    # 辞書に項目を登録
    reminders[dt].append({"repeat": repeat, "interval": interval, "channel_id": channel_id, "msg": msg})
    export_reminders()

# リマインダーの削除
def remove_reminder(dt, idx):
    removed = reminders[dt].pop(idx-1)
    # 値が空の辞書の行を削除
    if not reminders[dt]:
        del reminders[dt]
    export_reminders()
    return removed

# 通知用ループ
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # 現在時刻を取得して次のゼロ秒までsleep
        now = datetime.now()
        next_minute = (now + datetime.timedelta(minutes=1)).replace(second=0, microsecond=0)
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
                        dt = next_minute + datetime.timedelta(days=interval)
                    elif repeat == "hour":
                        dt = next_minute + datetime.timedelta(hours=interval)
                    elif repeat == "minute":
                        dt = next_minute + datetime.timedelta(minutes=interval)
                    add_reminder(dt, repeat, interval, channel_id, msg)
            
            # 処理済の予定の削除
            del reminders[next_minute]
            export_reminders()
            print(f"{next_minute}の予定を削除")

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
            view=None
        )
        print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}")

#===============
# イベントハンドラ
#===============
# Bot起動確認
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Botを起動: {bot.user}")
    
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
    repeat="繰り返し単位",
    interval="繰り返し間隔",
    msg="リマインド内容"
)
@app_commands.choices(repeat=[
    app_commands.Choice(name="日", value="day"),
    app_commands.Choice(name="時間", value="hour"),
    app_commands.Choice(name="分", value="minute")
])
async def remind(interaction: discord.Interaction, date: str, time: str, msg: str, repeat: str = None, interval: int = 0):
    # 文字列引数からdatatime型に変換
    dt = datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M")
    channel_id = interaction.channel.id
    # add_reminder関数に渡す
    add_reminder(dt, repeat, interval, channel_id, msg)

    await interaction.response.send_message(f"{dt.strftime("%Y/%m/%d %H:%M")} にリマインダーをセットしました:saluting_face:")
    print(f"予定を追加: {reminders[dt]}")

# リマインダー一覧の表示
@bot.tree.command(name="reminder_list", description="リマインダーの一覧を表示します")
async def reminder_list(interaction: discord.Interaction):
    # 空のリストを作成
    items = []
    # remindersの中身を取り出してリストに格納
    for dt, value in reminders.items():
        dt_str = dt.strftime("%Y/%m/%d %H:%M")
        for rmd_dt in value:
            items.append((dt_str, rmd_dt["msg"]))
            
    if items:
        embed = discord.Embed(title="リマインダー一覧", color=discord.Color.blue())
        for dt_txt, msg in items:
            embed.add_field(name=dt_txt, value=msg, inline=False)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("リマインダーは設定されていません")

# 削除メニューの呼び出しコマンド
@bot.tree.command(name="reminder_delete", description="リマインダー一覧を表示します")
async def reminder_delete(interaction: discord.Interaction):
    if reminders:
        view = ReminderSelect(reminders)
        await interaction.response.send_message("削除するリマインダーを選択", view=view)
    else:
        await interaction.response.send_message("リマインダーは設定されていません")

# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))
