import os
import discord
from discord.ext import commands, voice_recv
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

class MySink(voice_recv.AudioSink):

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data):
        print(user, len(data.opus))

    def cleanup(self):
        pass

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

@bot.command()
async def rec(ctx):

    if not ctx.author.voice:
        await ctx.send("VCに入ってね")
        return

    channel = ctx.author.voice.channel

    vc = await channel.connect(
        cls=voice_recv.VoiceRecvClient
    )

    vc.listen(MySink())

    await ctx.send("録音開始")

TOKEN = os.getenv("REC_BOT_TOKEN")

bot.run(TOKEN)