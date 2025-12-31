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

# /remind コマンド
@bot.tree.command(name="remind", description="リマインダーをセットします")
@app_commands.describe(
    date="日付(yyyy/mm/dd)",
    time="時刻(hh:mm)",
    
    msg="リマインド内容"
)
async def remind(interaction: discord.Interaction, date: str, time: str, msg: str):
    dt = datetime.datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M")

    if dt not in reminders:
        reminders[dt] = []
        reminders[dt].append((interaction.channel.id, msg))

    await interaction.response.send_message(f"{dt} にリマインダーをセットしました:saluting_face:")

# 通知用ループ
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now()
        next_minute = (now + datetime.timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait = (next_minute - now).total_seconds()
        await asyncio.sleep(wait)
        print (f"毎分ゼロ秒に辞書と照合：{datetime.datetime.now()}")

        if next_minute in reminders:
            for channel_id, msg in reminders[next_minute]:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"{msg}")
                    print (f"チャンネルにメッセージを送信：{datetime.datetime.now()}")
                else:
                    print(f"チャンネル取得失敗：{channel_id}")
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