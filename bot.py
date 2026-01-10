import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import os

# Botの準備
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Bot起動確認
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"起動しました！: {bot.user}")
    print(f"ループ開始： {datetime.datetime.now()}")
    bot.loop.create_task(reminder_loop())

# 空の辞書を定義
reminders = {}
rmd_dt = {}

# 辞書登録処理
def add_reminder(dt, repeat, interval, channel_id, msg):
    # 日時が辞書になければ辞書に行を追加
    if dt not in reminders:
        reminders[dt] = []
    # 辞書に項目を登録
    reminders[dt].append({"repeat": repeat, "interval": interval, "channel_id": channel_id, "msg": msg})

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
    dt = datetime.datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M")
    channel_id = interaction.channel.id
    add_reminder(dt, repeat, interval, channel_id, msg)

    await interaction.response.send_message(f"{dt} にリマインダーをセットしました:saluting_face:")
    print(dt)
    print(reminders[dt])

# 通知用ループ
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # 現在時刻を取得して次のゼロ秒までsleep
        now = datetime.datetime.now()
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
                    print (f"チャンネルにメッセージを送信：{datetime.datetime.now()}")
                else:
                    print(f"チャンネル取得失敗：{channel_id}")
            
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

# スラッシュコマンドのテスト
@bot.tree.command(name="ping", description="ピンポン！")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong!")

# スラッシュコマンドとプレフィックスコマンドのテスト
async def greet_common(ctx_or_interaction, target: str):
    msg = f"{target}さん、こんちわ!"
    if isinstance(ctx_or_interaction, discord.Interaction):
        await ctx_or_interaction.response.send_message(msg)
    else:
        await ctx_or_interaction.send(msg)

@bot.command(name="hello")
async def hello_prefix(ctx):
    target = ctx.author.display_name
    await greet_common(ctx, target)
    print(f"プレフィックスコマンドを実行: {datetime.datetime.now()}")

@bot.tree.command(name="hello", description="スラッシュ版のHello")
async def hello_slash(interaction: discord.Interaction):
    target = interaction.user.display_name
    await greet_common(interaction, target)
    print(f"スラッシュコマンドを実行: {datetime.datetime.now()}")

# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))