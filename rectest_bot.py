import discord
from discord.ext import commands
import discord.ext.voice_recv as voice_recv
from dotenv import load_dotenv
import os

load_dotenv()

#=====Botの準備=====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
print(f"Pycord version: {discord.__version__}")

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

class TestSink(voice_recv.AudioSink):
    def __init__(self):
        super().__init__()

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data):
        if user is None:
            return

        print(
            f"VOICE: {user} | pcm={len(data.pcm)} bytes"
        )

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("VCに入ってね")

    channel = ctx.author.voice.channel

    vc = await channel.connect(
        cls=voice_recv.VoiceRecvClient
    )

    sink = TestSink()

    vc.listen(sink)

    await ctx.send("録音開始テスト")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        ctx.voice_client.stop_listening()
        await ctx.voice_client.disconnect()

    await ctx.send("切断したよ")

bot.run(os.getenv("DISCORD_TOKEN"))