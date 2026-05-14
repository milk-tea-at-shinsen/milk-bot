import os

import discord
from discord.ext import commands

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

TOKEN = os.getenv("REC_BOT_TOKEN")

bot.run(TOKEN)