import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():
    print(f"login: {bot.user}")
    
@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("VCに入ってね")
        return

    channel = ctx.author.voice.channel

    await channel.connect()
    await ctx.send("VC接続OK")

TOKEN = os.getenv("REC_BOT_TOKEN")

bot.run(TOKEN)