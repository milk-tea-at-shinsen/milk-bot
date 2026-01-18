#=========================
# ライブラリのインポート
#=========================
import discord
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
from google import genai
import aiohttp
import requests
from functools import wraps
import inspect
from ibm_watson import SpeechToTextV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
import ctypes
import ctypes.util
from pydub import AudioSegment, effects

#=====Botの準備=====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
print(f"Pycord version: {discord.__version__}")

if not discord.opus.is_loaded():
    try:
        # Nixpacksが設定するライブラリパスの中からlibopusを探す
        lib_path = ctypes.util.find_library('opus')
        if lib_path:
            discord.opus.load_opus(lib_path)
        else:
            # 見つからない場合の「決め打ち」パス（Nixpacksの標準的な配置）
            discord.opus.load_opus('/usr/lib/libopus.so.0')
    except Exception as e:
        print(f"Opus loading error: {e}")

#=====サービスアカウントキーの読込=====
#---Vision API---
info = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
credentials = service_account.Credentials.from_service_account_info(info)
vision_client = vision.ImageAnnotatorClient(credentials=credentials)

#---Gemini API---
gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

#---Watson STT---
WATSON_STT_API_KEY = os.getenv("WATSON_STT_API_KEY")
WATSON_STT_URL = os.getenv("WATSON_STT_URL")
authenticator = IAMAuthenticator(WATSON_STT_API_KEY)
stt = SpeechToTextV1(authenticator=authenticator)
stt.set_service_url(WATSON_STT_URL)

#===================================
# 定数・グローバル変数・辞書の準備
#===================================
#=====タイムゾーンの指定=====
JST = timezone(timedelta(hours=9), "JST")

#=====辞書読込共通処理=====
def load_data(data):
    try:
        # jsonが存在すれば
        if os.path.exists(f"/mnt/data/{data}.json"):
            # fileオブジェクト変数に格納
            with open(f"/mnt/data/{data}.json", "r", encoding = "utf-8") as file:
                print(f"loaded dict: {datetime.now(JST)} - {data}")
                return json.load(file)
        else:
            #jsonが存在しない場合は、戻り値を空の辞書にする
            print(f"dict {data}: not exist")
            return {}
    except Exception as e:
        print(f"dict {data}: load error: {e}")
        return {}
    
#=====各辞書読込前処理=====
#---統合辞書---
raw_data = load_data("all_data")
try:
    if raw_data:
        print("exist raw_data")
        all_data = {int(key): value for key, value in raw_data.items()}
        print(f"all_data: {all_data}")
        for guild_id, guild_dict in all_data.items():
            # リマインダー辞書キーのdtをdatetime型に戻す
            all_data[guild_id]["reminders"] = {datetime.fromisoformat(key): value for key, value in guild_dict["reminders"].items()}
            # 投票辞書キーのmsg_idをint型に戻す
            all_data[guild_id]["votes"] = {int(key): value for key, value in guild_dict["votes"].items()}
            # 代理投票辞書キーのmsg_idをint型に戻す
            all_data[guild_id]["proxy_votes"] = {int(key): value for key, value in guild_dict["proxy_votes"].items()}
    else:
        print("not exist raw_data")
        all_data = {}
except Exception as e:
    print(f"raw_data convert error: {e}")
    all_data = {}

print(f"dict all_data: {all_data}")

#---リマインダー辞書---
raw_data = load_data("reminders")
try:
    if raw_data:
        reminders = {datetime.fromisoformat(key): value for key, value in raw_data.items()}
    else:
        reminders = {}
except:
    reminders = {}
    
print(f"dict reminders: {reminders}")

#---投票辞書---
raw_data = load_data("votes")
if raw_data:
    votes = {int(key): value for key, value in raw_data.items()}
else:
    votes = {}
print(f"dict votes: {votes}")

#---代理投票辞書---
raw_data = load_data("proxy_votes")
try:
    if raw_data:
        proxy_votes = {int(key): value for key, value in raw_data.items()}
    else:
        proxy_votes = {}
except:
    proxy_votes = {}
    
print(f"dict proxy_votes: {proxy_votes}")

#---リスト化対象チャンネル辞書---
raw_data = load_data("make_list_channels")
try:
    if raw_data:
        make_list_channels = {key: value for key, value in raw_data.items()}
    else:
        make_list_channels = {"channels": []}
except:
    make_list_channels = {"channels": []}

print(f"dict make_list_channels: {make_list_channels}")

#---録音セッション---
rec_sessions = {}

#=====辞書プリセット処理=====
def preset_dict(guild_id):
    # 統合辞書にサーバーidが登録されていなければ、空の辞書を作成
    if guild_id not in all_data:
        print("[all_data presetting: guild: {guild_id}]")
        all_data[guild_id] = {
            "reminders": {},
            "votes": {},
            "proxy_votes": {},
            "make_list_channels": [],
            "rec_sessions": {}
        }
        save_all_data()

#===============
# 共通処理関数
#===============
#---------------
# デコレーター
#---------------
#=====スラッシュコマンドの引数整理=====
def clean_slash_options(func):
    @wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        for key, value in kwargs.items():
            if isinstance(value, discord.Option):
                kwargs[key] = None
        return await func(ctx, *args, **kwargs)
    return wrapper

#---------------
# 辞書関係
#---------------
#=====辞書をjsonファイルに保存=====
def export_data(data: dict, name: str):
    try:
        # 指定ディレクトリがなければ作成する
        os.makedirs(f"/mnt/data", exist_ok=True)
        #jsonファイルを開く（存在しなければ作成する）
        with open(f"/mnt/data/{name}.json", "w", encoding = "utf-8") as file:
            # jsonファイルを保存
            json.dump(data, file, ensure_ascii=False, indent=2)
        print(f"saved dict: {datetime.now(JST)} - {name}")
    except Exception as e:
        print(f"saving dict error: {e}")

#=====jsonファイル保存前処理=====
#---統合辞書---
def save_all_data():
    print("[start: save_all_data]")
    data_to_save = {}

    for guild_id, guild_dict in all_data.items():
        data_to_save[guild_id] = guild_dict.copy()

        # reminders辞書のdatetime型をisoformatに直してから保存
        data_to_save[guild_id]["reminders"] = {dt.isoformat(): value for dt, value in guild_dict["reminders"].items()}

    print(f"data_to_save: {data_to_save}")
    export_data(data_to_save, "all_data")

# #---リマインダー---
# def save_reminders():
#     reminders_to_save = {dt.isoformat(): value for dt, value in reminders.items()}
#     export_data(reminders_to_save, "reminders")

# #---投票---
# def save_votes():
#     export_data(votes, "votes")

# #---代理投票---
# def save_proxy_votes():
#     export_data(proxy_votes, "proxy_votes")

# #---リスト化対象チャンネル---
# def save_make_list_channels():
#     export_data(make_list_channels, "make_list_channels")

#=====辞書への登録処理=====
#---リマインダー辞書---
def add_reminder(guild_id, dt, repeat, interval, channel_id, msg):
    reminders = all_data[guild_id]["reminders"]
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
    #save_reminders()
    save_all_data()

#---投票辞書---
def add_vote(guild_id, msg_id, question, reactions, options):
    votes = all_data[guild_id]["votes"]
    # 辞書に項目を登録
    votes[msg_id] = {
        "question": question,
        "reactions": reactions,
        "options": options
    }

    # json保存前処理
    # save_votes()
    save_all_data()

#---代理投票辞書---
def add_proxy_vote(guild_id, msg_id, voter, agent_id, opt_idx):
    print("[start: add_proxy_vote]")
    proxy_votes = all_data[guild_id]["proxy_votes"]
    # msg_idが辞書になければ辞書に行を追加
    if msg_id not in proxy_votes:
        proxy_votes[msg_id] = {}
    
    # 辞書に項目を登録
    proxy_votes[msg_id][voter] = {
        "agent_id": agent_id,
        "opt_idx": opt_idx
    }

    # json保存前処理
    # save_proxy_votes()
    save_all_data()

#---リスト化対象チャンネル辞書---
def add_make_list_channel(guild_id, channel_id):
    make_list_channels = all_data[guild_id]["make_list_channels"]
    # リストに項目を登録
    if channel_id not in make_list_channels:
        make_list_channels.append(channel_id)
        print(f"make_list_channels: {make_list_channels}")

    # json保存前処理
    #save_make_list_channels()
    save_all_data()

#---録音セッション辞書---
def add_rec_session(guild_id, channel_id):
    print("[start: add_rec_session]")
    rec_sessions = all_data[guild_id]["rec_sessions"]
    # channel_idが辞書になければ辞書に行を追加
    if channel_id not in rec_sessions:
        rec_sessions[channel_id] = []

#=====辞書からの削除処理=====
#---リマインダー辞書---
def remove_reminder(guild_id, dt, idx=None):
    reminders = all_data[guild_id]["reminders"]
    # idxがNoneの場合は日時全体を削除、そうでなければ指定インデックスの行を削除
    if idx is None:
        if dt in reminders:
            removed = reminders[dt]
            del reminders[dt]
            #save_reminders()
            save_all_data()
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
            #save_reminders()
            save_all_data()
            print(f"リマインダーを削除: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}")
            return removed
        else:
            print(f"削除対象のリマインダーがありません")
            return None

#---投票辞書---
def remove_vote(guild_id, msg_id):
    print("[start: remove_vote]")
    votes = all_data[guild_id]["votes"]
    if msg_id in votes:
        removed = votes[msg_id]
        del votes[msg_id]
        #save_votes()
        save_all_data()
        print(f"投票を削除: {removed['question']}")
        return removed
    else:
        print(f"削除対象の投票がありません")
        return None
        
#---代理投票辞書---
def remove_proxy_vote(guild_id, msg_id):
    print("[start: remove_proxy_vote]")
    proxy_votes = all_data[guild_id]["proxy_votes"]
    if msg_id in proxy_votes:
        removed = proxy_votes[msg_id]
        del proxy_votes[msg_id]
        #save_proxy_votes()
        save_all_data()
        print(f"代理投票({msg_id})を削除しました")
        return removed
    else:
        print(f"削除対象の代理投票がありません")
        return None

#---リスト化対象チャンネル辞書---
def remove_make_list_channel(guild_id, channel_id, channel_name):
    print("[start: remove_make_list_channel]")
    make_list_channels = all_data[guild_id]["make_list_channels"]
    if channel_id in make_list_channels:
        make_list_channels.remove(channel_id)
        #save_make_list_channels()
        save_all_data()
        print(f"リスト化対象から削除: {channel_name}")
        return channel_name
    else:
        print(f"削除対象のチャンネルがありません")
        return None

#---録音セッション辞書---
def remove_rec_session(guild_id, channel_id, channel_name):
    print("[start: remove_rec_sessions]")
    rec_sessions = all_data[guild_id]["rec_sessions"]
    if channel_id in rec_sessions:
        del rec_sessions[channel_id]
        print(f"{channel_name}の録音セッションを終了")
        return
    else:
        print(f"{channel_name}の録音セッションがありません")
        return

#---代理投票辞書からの個別投票除外---
def cancel_proxy_vote(guild_id, msg_id, voter, agent_id):
    print("[start: cancel_proxy_vote]")
    proxy_votes = all_data[guild_id]["proxy_votes"]
    if msg_id in proxy_votes:
        # 該当する投票を取り出して投票者と代理人が一致するものを削除
        for key, value in proxy_votes[msg_id].items():
            if (key, value["agent_id"]) == (voter, agent_id):
                removed = proxy_votes[msg_id][voter]
                del proxy_votes[msg_id][voter]
                #save_proxy_votes()
                save_all_data()
                print(f"{voter}の代理投票({msg_id})をキャンセルしました")
                return removed
            else:
                print(f"キャンセル対象の代理投票がありません")
                return None
    else:
        print(f"キャンセル対象の代理投票がありません")
        return None

#=====CSV作成処理=====
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

#===============
# 個別処理関数
#===============
#---------------
# リマインダー関係
#---------------
#=====リマインダー削除=====
async def handle_remove_reminder(interaction, dt, idx):
        removed = remove_reminder(dt, idx)

        # 削除完了メッセージの送信
        await interaction.message.delete()
        await interaction.followup.send(
            content=f"リマインダーを削除したよ🫡: {dt.strftime('%Y/%m/%d %H:%M')} - {removed['msg']}",
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=True
        )

#=====通知用ループ処理===== *require modifying
async def reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # 現在時刻を取得して次のゼロ秒までsleep
        now = datetime.now(JST)
        next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait = (next_minute - now).total_seconds()
        await asyncio.sleep(wait)

        for guild_id in all_data:
            reminders = all_data[guild_id]["reminders"]
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
                        add_reminder(guild_id, dt, repeat, interval, channel_id, msg)
                
                # 処理済の予定の削除
                remove_reminder(guild_id, next_minute)

#---------------
# 投票関係
#---------------
#=====リアクションと絵文字を差し替え=====
def reaction_replace(options, reactions):
    for i, opt in enumerate(options):
        if opt:
            first_char = opt[0]
            if first_char in emoji.EMOJI_DATA and first_char not in reactions[:i]:
                # 選択肢の最初の文字が絵文字の場合、その絵文字をリアクションに差替
                reactions[i] = first_char
                # 選択肢から最初の文字を削除
                options[i] = opt[1:]
    
    # リアクションの重複があった場合はデフォルト絵文字に戻す
    default_reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    duplicate_flag = False
    if len(reactions) != len(set(reactions)):
        duplicate_flag = True
    
    while duplicate_flag is True:
        for i, reaction in enumerate(reactions):
            if reactions.count(reaction) > 1 and reaction != default_reactions[i]:
                    options[i] = reaction + options[i]
                    reactions[i] = default_reactions[i]
        if len(reactions) == len(set(reactions)):
            duplicate_flag = False

    return options, reactions

#=====投票選択肢embed作成=====
def make_poll_embed(options, reactions, question, description):
    for i, opt in enumerate(options):
        if opt:
            description += f"{reactions[i]} {opt}\n"
    embed = discord.Embed(title=question, description=description, color=discord.Color.green())
    return embed

#=====投票集計=====
async def make_vote_result(interaction, msg_id):
    print("[start: make_vote_result]")
    votes = all_data[interaction.guild.id]["votes"]
    proxy_votes = all_data[interaction.guild.id]["proxy_votes"]
    # 投票辞書を読み込み
    if msg_id in votes:
        options = votes[msg_id]["options"]
        print(f"votes: {votes}")
    else:
        options = []
    # メッセージを読み込み
    message = await interaction.channel.fetch_message(msg_id)
    # サーバー情報を読み込み
    guild = interaction.guild
    
    # 結果用辞書を準備
    result = {}
    # 結果用辞書に結果を記録
    for i, reaction in enumerate(message.reactions):
        
        # リアクション投票分
        # リアクションしたユーザーがbotでなければリストに追加
        reaction_users = [reaction_user async for reaction_user in reaction.users() if reaction_user != bot.user]
        users = [user.nick or user.display_name or user.name for user in reaction_users]
        
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
                            agent_display_name = agent.nick or agent.display_name or agent.name
                        else:
                            agent_display_name = "Unknown"

                        users.append(f"{voter}(by:{agent_display_name})")

        if options:
            result[i] = {
                "emoji": reaction.emoji,
                "option": options[i],
                "count": len(users),
                "users": users,
            }
        else:
            result[i] = {
                "emoji": reaction.emoji,
                "option": f"選択肢[{i+1}]",
                "count": len(users),
                "users": users,
            }
    dt = datetime.now(JST)
    return dt, result

#=====投票結果表示=====
async def show_vote_result(interaction, dt, result, msg_id, mode):
    print("[start: show_vote_result]")
    votes = all_data[interaction.guild.id]["votes"]
    # Embedの設定
    if msg_id in votes:
        embed = discord.Embed(
            title="集計結果",
            description=votes[msg_id]["question"],
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="集計結果",
            description="",
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
    if msg_id in votes:
        if mode == "mid":
            mode_str = "中間集計"
        else:
            mode_str = "最終結果"
    else:
        mode_str = "集計日時"
    embed.set_footer(text=f"{mode_str} - {dt.strftime('%Y/%m/%d %H:%M')}")
    # embedを表示
    if interaction.message:
        await interaction.message.edit(
            content=None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
            view=None
        )
    else:
        await interaction.followup.send(
            content=None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
        )

#=====投票結果rows作成処理(選択肢グループ)=====
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
        users.append(value["users"])
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

#=====投票結果rows作成処理(一覧)=====
def make_listed_rows(result):
    print("[start: make_listed_rows]")
    header = ["option", "users"]
    
    rows = [
        [value["option"], user]
         for key, value in result.items()
         for user in value["users"]
    ]
    
    return header, rows

#=====投票結果CSV出力処理=====
async def export_vote_csv(interaction, result, msg_id, dt, mode):
    print("[start: export_vote_csv]")
    votes = all_data[interaction.guild.id]["votes"]
    if msg_id in votes:
        meta = {
            "question": votes[msg_id]["question"],
            "status": mode,
            "collected_at": dt.strftime("%Y/%m/%d %H:%M")
        }
    else:
        meta = {"collected_at": dt.strftime("%Y/%m/%d %H:%M")}
    
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
        content="投票集計結果のCSVだよ🫡",
        files=[discord.File(grouped_file), discord.File(listed_file)]
    )

#---------------
# OCR関係
#---------------
#=====メッセージリストの作成=====
async def collect_message(channel, counts, minutes, start_msg, limit_msg):
    # 終了フラグをFalseに設定
    end_flag = False
    # 返信先メッセージをリストに格納
    messages = []
    # 返信先メッセージをhistoryの最初の位置に設定
    loop_start_msg = start_msg
    # 件数指定なしまたは1未満の場合は1を設定
    if counts is not None:
        counts = int(counts)
    if counts is None or counts < 1:
        counts = 1

    # 終了フラグが立つまでループ
    while end_flag is False:
        # historyの最初の位置より古い100件分のメッセージを取得
        msgs = [msg async for msg in channel.history(before=loop_start_msg, limit=100)]

        # 取得数が100件未満または累計が指定数以上または100件目が最終なら終了
        if len(msgs) < 100 or (len(messages) + len(msgs)) >= counts or msgs[0].id == limit_msg.id:
            end_flag = True
        else:
            loop_start_msg = msgs[0].id
        # リストに追加
        messages.extend(msgs if not end_flag else msgs[:counts - len(messages)])

    # リストを古い順にソート
    messages.sort(key=lambda m: m.created_at)

    if minutes:
        # 時間指定がある場合、取得するメッセージの範囲を計算
        start_time = start_msg.created_at
        end_time = start_time + timedelta(minutes=int(minutes))
        # メッセージのタイムスタンプが範囲内ならリストに追加
        msg_ids = [message.id for message in messages if start_time <= message.created_at <= end_time]
    else:
        msg_ids = [message.id for message in messages]

    return msg_ids
            
#=====添付画像バイナリ取得処理=====
async def get_image(channel, msg_id):
    print("[start: get_image]")
    message = await channel.fetch_message(msg_id)
    
    # 添付画像がなければNoneを返す
    if not message.attachments:
        return None

    # 画像データをcontentsに格納
    contents = []
    async with aiohttp.ClientSession() as session:
        for attachment in message.attachments:
            async with session.get(attachment.url) as resp:
                content = await resp.read()
                contents.append(content)

    return contents

#=====文字座標計算=====
#---行センター出し関数---
def get_x_center(bounding_box):
    return sum(vertice.x for vertice in bounding_box.vertices) / 4

#---列センター出し関数---
def get_y_center(bounding_box):
    return sum(vertice.y for vertice in bounding_box.vertices) / 4

#---高さ出し関数---
def get_height(bounding_box):
    return max(vertice.y for vertice in bounding_box.vertices) - min(vertice.y for vertice in bounding_box.vertices)

#=====symbol取得処理=====
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

#=====同一行列判定=====
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

#=====表整形処理=====
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

#=====OCR->CSV用データ作成処理=====
async def extract_table_from_image(image_content):
    print("[start: extract_table_from_image]")
    loop = asyncio.get_running_loop()
    image = vision.Image(content=image_content)

    # Vision APIをスレッドで実行
    response = await loop.run_in_executor(
        None,
        lambda: vision_client.document_text_detection(image=image)
    )

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

#=====重複行削除処理=====
def remove_duplicate_rows(rows):
    print("[start: remove_duplicate_rows]")
    unique_rows = []
    for row in rows:
        if row not in unique_rows:
            unique_rows.append(row)
    return unique_rows

#---------------
# リスト化関係
#---------------
async def handle_make_list(message):
    print("[start: hamdle_make_list]")
    # 改行ごとに分けてリスト化
    lines = message.content.split("\n")
    print(f"lines: {lines}")
    
    # 行頭記号リスト
    bullet = ["-", "*", "+", "•", "・", "○", "◯", "○"]
    
    # 空白を除去し、箇条書き化
    for line in lines:
        line = line.strip()
        print(f"line: {line}")
        if line[:1] in bullet:
            line = line[1:]
            print(f"line: {line}")
        if line:
            await message.channel.send(f"- {line}")
    
    await message.delete()

#---------------
# STT関係
#---------------
#=====要約用テキスト作成=====
def make_gemini_text(ctx, channel_id):
    rec_sessions = all_data[ctx.guild.id]["rec_sessions"]
    lines = [f"{item['time'].strftime('%Y/%m/%d %H:%M:%S')} {item['name']}: {item['text']}" for item in rec_sessions[channel_id]]
    text = "\n".join(lines)
    return text
    
#=====要約作成=====
def make_summery(text):
    prompt = f"""
以下は、Discordのボイスチャット会議のログです。
内容を分析し、以下のガイドラインに従って議事録を作成してください。

--- 前提条件 ---
- あなたはプロの議事録作成アシスタントです
- 会議の内容を正確に把握し、要点を簡潔にまとめてください
- 音声認識による誤認識の可能性や、話し手による言い間違いの可能性も考慮し、文脈から正しい内容を推測してください
- 出力は指定した4項目の見出しと、その内容のみとし、前置きや結びの言葉、メタ情報などは一切含めないでください
- 4項目の順番は入れ替えないでください
- 全体の文字数は、Markdown記法や空白などを含めて最大4000文字以内に収めてください

--- 出力内容 ---
#### 会議概要
- 日時、参加者を記載
#### 議題
- 会議の主なテーマを記載
#### 議事概要
- 議事内容を構造化し、要約して箇条書きで記載
#### 決定事項
- 合意・決定した事項や次回までの検討事項を記載
- 該当がない場合は「特になし」と記載

--- 出力フォーマット ---
- Markdown記法で記載してください
- 見出しのレベルは####を使用し、####の後に半角スペースを入れてください
- 箇条書きには-を使用し、-の後に半角スペースを入れてください
- コードブロック(```)は使用しないでください

--- 会議ログ ---
{text}
"""
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

#=====vcログ作成=====
def write_vc_log(ctx, channel_id, start_time):
    print("[start: write_vc_log]")
    rec_sessions = all_data[ctx.guild.id]["rec_sessions"]

    if channel_id in rec_sessions:
        sessions = rec_sessions[channel_id]
        # セッションを時間順にソート
        sessions.sort(key=lambda x: x["time"])
        
        # CSVファイル作成
        filename = f"/mnt/data/vc_log_{channel_id}_{start_time.strftime('%Y%m%d_%H%M%S')}.csv"
        meta = {
            "title": "vc_log",
            "speeched_at": start_time.strftime("%Y/%m/%d %H:%M")
        }
        header = ["time", "name", "text"]
        rows = [
            [item["time"].strftime("%Y/%m/%d %H:%M:%S"), item["name"], item["text"]]
            for item in sessions
        ]
        make_csv(filename, rows, meta, header)
        print(f"VCログを保存: {filename}")
        
        return filename

#=====録音後処理=====
async def after_recording(sink, channel: discord.TextChannel, start_time: datetime, ctx, *args):
    print("[start: after_recording]")
    rec_sessions = all_data[ctx.guild.id]["rec_sessions"]
    status_msg = await channel.send(f"{bot.user.display_name}が考え中…🤔")
    await asyncio.sleep(2)

    for user_id, audio in sink.audio_data.items():
        user = channel.guild.get_member(user_id) or await channel.guild.fetch_member(user_id)
        user_name = user.nick or user.display_name or user.name

        # userがbotなら無視
        if user.bot:
            print(f"skipping bot audio: {user_name}")
            continue
        
        # 開始時間の取得
        rel_start_time = getattr(audio, "first_packet", 0)
        if rel_start_time == 0:
            rel_start_time = getattr(audio, "timestamp", 0)
        
        user_start_time = start_time + timedelta(seconds=rel_start_time)

        try:
            # 音声変換
            audio.file.seek(0)
            raw_bytes = audio.file.read()
            seg = AudioSegment.from_raw(
                io.BytesIO(raw_bytes),
                sample_width=2,
                frame_rate=48000,
                channels=2
            )
            seg = seg.set_channels(1).set_frame_rate(16000)
            buf = io.BytesIO()
            seg.export(buf, format="wav")
            buf.seek(0)
            
            final_audio_data = buf.read()
            
            # Watson解析実行
            res = stt.recognize(
                audio=final_audio_data,
                content_type="audio/wav",
                model="ja-JP_Multimedia",
                timestamps=True
            ).get_result()
            
            print(f"res: {res}")
            
            if res and "results" in res:
                for result in res["results"]:
                    rel_start = result["alternatives"][0]["timestamps"][0][1]
                    actual_start = user_start_time + timedelta(seconds=rel_start)
                    transcript = result["alternatives"][0]["transcript"]
                    
                    print(f"DEBUG: rel_start={rel_start} (type: {type(rel_start)})", flush=True)
                    print(f"DEBUG: actual_start={actual_start}", flush=True)
                    
                    rec_sessions[channel.id].append({
                        "time": actual_start,
                        "name": user_name,
                        "text": transcript.strip()
                    })
        except Exception as e:
            print(f"error anlyzing voice from {user.nick or user.display_name or user.name}: {e}")
    
    filename = write_vc_log(ctx, channel.id, start_time)
    text = make_gemini_text(channel.id)
    summerized_text = make_summery(text)
    print(f"summerized_text: {summerized_text}")

    # embed作成
    embed = discord.Embed(
        title="VC会議摘録",
        description=summerized_text,
        color=discord.Color.purple()
    )
    # discordに送信
    await status_msg.edit(content="", embed=embed)
    await channel.send(content="VCのログを作成したよ🫡", file=discord.File(filename))
    
    # 録音セッション辞書からチャンネルIDを削除
    remove_rec_session(ctx.guild.id, channel.id, channel.name)
    
#===============
# クラス定義
#===============
#---------------
# リマインダー関係
#---------------
#=====リマインダー選択=====
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
                placeholder="リマインダーを選択",
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)
    
    # 削除処理の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=f"{bot.user.display_name}が考え中…🤔", view=None)
        value = interaction.data["values"][0]
        # 日時とインデックスを分離
        dt_str, idx_str = value.split("|")
        dt = datetime.fromisoformat(dt_str)
        idx = int(idx_str)

        # 予定の削除
        await handle_remove_reminder(interaction, dt, idx)

#---------------
# 投票関係
#---------------
#=====投票選択=====
class VoteSelect(View):
    # クラスの初期設定
    def __init__(self, guild_id, mode, voter=None, agent_id=None):
        votes = all_data[guild_id]["votes"]
        super().__init__()
        # guild_idプロパティにサーバーidをセット
        self.guild_id = guild_id
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
            select = Select(
                placeholder="投票を選択",
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)
    
    # 投票選択後処理の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        votes = all_data[self.guild_id]["votes"]
        msg_id = int(interaction.data["values"][0])

        # 代理投票
        if self.mode == VoteSelectMode.PROXY_VOTE:
            await interaction.response.edit_message(content=f"{bot.user.display_name}が考え中…🤔", view=None)
            view = VoteOptionSelect(msg_id, self.voter, self.agent_id)
            await interaction.message.edit(content="代理投票する選択肢を選んでね", view=view)
        # 代理投票キャンセル
        elif self.mode == VoteSelectMode.CANCEL_PROXY_VOTE:
            removed = cancel_proxy_vote(self.guild_id, msg_id, self.voter, self.agent_id)
            await interaction.response.edit_message(content=f"{bot.user.display_name}が考え中…🤔", view=None)
            if removed:
                await interaction.message.edit(content=f"**{self.voter}** の分の代理投票を取り消したよ🫡")
            else:
                await interaction.message.delete()
                await interaction.followup.send(content=f"⚠️取り消せる代理投票がないよ", ephemeral=True)
        # 投票選択肢追加
        elif self.mode == VoteSelectMode.ADD_OPTION:
            lim = min(5, 10 - len(votes[msg_id]["options"]))
            if lim == 0:
                await interaction.message.delete()
                await interaction.followup.send(content="️⚠️これ以上選択肢を増やせないよ", view=None, ephemeral=True)
                return
            await interaction.response.send_modal(AddOptionInput(msg_id, lim))
        # 削除
        elif self.mode == VoteSelectMode.DELETE_VOTE:
            await interaction.response.defer()
            remove_vote(self.guild_id, msg_id)
            remove_proxy_vote(self.guild_id, msg_id)
            await interaction.message.delete()
            await interaction.followup.send(content="投票を削除したよ🫡", ephemeral=True)
        # 集計
        else:
            await interaction.response.edit_message(content=f"{bot.user.display_name}が考え中…🤔", view=None)
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
                remove_vote(self.guild_id, msg_id)
                remove_proxy_vote(self.guild_id, msg_id)

#=====投票選択肢選択=====
class VoteOptionSelect(View):
    # クラスの初期設定
    def __init__(self, guild_id, msg_id, voter, agent_id):
        votes = all_data[guild_id]["votes"]
        super().__init__()
        # msg_idプロパティにメッセージIDをセット
        self.msg_id = msg_id
        # voterプロパティに投票者名をセット
        self.voter = voter
        # agentプロパティに代理人をセット
        self.agent_id = agent_id
        # guild_idプロパティにサーバーidをセット
        self.guild_id = guild_id

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
                placeholder="代理投票する選択肢を選択(複数選択可)",
                min_values = 1,
                max_values = len(options),
                options = options
            )
            select.callback = self.select_callback
            self.add_item(select)

    # 選択肢選択後の関数定義
    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=f"{bot.user.display_name}が考え中…🤔", view=None)
        guild = interaction.guild
        
        opt_idx = [int(opt_str) for opt_str in interaction.data["values"]]
        
        add_proxy_vote(self.guild_id, self.msg_id, self.voter, self.agent_id, opt_idx)
        agent = guild.get_member(self.agent_id)
        agent_display_name = agent.nick or agent.display_name or agent.name
        await interaction.message.edit(content=f"**{agent_display_name}** から **{self.voter}** の分の投票を受け付けたよ🫡")

#=====追加選択肢入力=====
class AddOptionInput(discord.ui.Modal):
    # クラスの初期設定
    def __init__(self, guild_id, msg_id, lim):
        super().__init__(title="追加する選択肢を入力してね")
        # msg_idプロパティにメッセージIDをセット
        self.msg_id = msg_id
        # limプロパティに選択肢追加上限をセット
        self.lim = lim
        # guild_idプロパティにサーバーidをセット
        self.guild_id = guild_id
        
        # ModalUIの定義
        self.inputs = []
        for i in range(self.lim):
            text = discord.ui.InputText(
                label=f"選択肢{i+1}",
                required=(i == 0)
            )
            self.inputs.append(text)
            self.add_item(text)

    # 選択肢入力後の処理
    async def callback(self, interaction: discord.Interaction):
        print("[start: on submit]")
        votes = all_data[self.guild_id]["votes"]
        await interaction.response.defer()
        await interaction.message.edit(content=f"{bot.user.display_name}が考え中…🤔", view=None)
        # 追加選択肢をリスト化
        add_options = [add_opt.value for add_opt in self.inputs if add_opt.value.strip()]
        # 辞書の内容を取得
        options = votes[self.msg_id]["options"]
        reactions = votes[self.msg_id]["reactions"]
        
        # リアクションリストを更新
        add_reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][len(options) : len(options) + len(add_options)]
        add_options, add_reactions = reaction_replace(add_options, add_reactions)

        # 選択肢リストを更新
        options.extend(add_options)
        reactions.extend(add_reactions)

        # embedを書き換え
        question = votes[self.msg_id]["question"]
        description = ""
        embed = make_poll_embed(options, reactions, question, description)

        # embedを表示
        message = await interaction.channel.fetch_message(self.msg_id)
        await message.edit(embed=embed)
        # リアクションを追加
        for i in range(len(add_options)):
            await message.add_reaction(add_reactions[i])
        
        await interaction.message.edit(content=f"投票に選択肢を追加したよ🫡\n{message.jump_url}")

        # 辞書の更新
        add_vote(self.guild_id, self.msg_id, question, reactions, options)

#=====投票選択モード切替=====
class VoteSelectMode(Enum):
    MID_RESULT = "mid_result"
    FINAL_RESULT = "final_result"
    PROXY_VOTE = "proxy_vote"
    CANCEL_PROXY_VOTE = "cancel_proxy_vote"
    ADD_OPTION = "add_option"
    DELETE_VOTE = "delete_vote"

#====================
# イベントハンドラ
#====================
# Bot起動時処理
@bot.event
async def on_ready():
    print(f"Bot started: {bot.user}")

    # 統合辞書に登録されていないサーバーの場合は辞書を初期化
    for guild in bot.guilds:
        preset_dict(guild.id)
    
    # リマインダーループの開始
    print(f"[start loop: {datetime.now(JST)}]")
    bot.loop.create_task(reminder_loop())

# 新規サーバー導入時処理
@bot.event
async def on_guild_join():
    print("[start: on_guild_join]")
    # 統合辞書に登録されていないサーバーの場合は辞書を初期化
    for guild in bot.guilds:
        preset_dict(guild.id)

#  メッセージ受信時処理
@bot.event
async def on_message(message): 
    print("[start: on_message]")
    # Botのメッセージは無視
    if message.author.bot:
        return
    if message.guild is None:
        print("message.guild is None")
        return
    make_list_channels = all_data[message.guild.id]["make_list_channels"]
    rec_sessions = all_data[message.guild.id]["rec_sessions"]
    # コマンドは実行して終了
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return
    # メッセージがリスト化対象チャンネルに投稿された場合、リスト化処理を行う
    print(f"message.channel.id: {message.channel.id}")
    print(f"make_list_channels: {make_list_channels}")
    if message.channel.id in make_list_channels:
        await handle_make_list(message)
    # 録音実施中かつ、メッセージが録音実行チャンネルに投稿された場合は録音ログに追加
    vc = message.guild.voice_client
    ts = message.created_at.astimezone(JST)
    if vc and vc.recording and message.channel.id in rec_sessions:
        rec_sessions[message.channel.id].append({
            "time": ts,
            "name": message.author.nick or message.author.display_name or message.author.name,
            "text": message.content.strip()
        })
    # その他のコマンドは実行
    await bot.process_commands(message)

#===============
# コマンド定義
#===============
#---------------
# 統合辞書移行関係
#---------------
#=====move_dict コマンド=====
@bot.command()
async def move_dict(ctx):
    guild_id = ctx.guild.id
    all_data[ctx.guild.id] = {}
    if reminders:
        all_data[guild_id]["reminders"] = reminders
    else:
        all_data[guild_id]["reminders"] = {}
    print(f'reminders: {reminders}')
    print(f'all_data[guild_id]["reminders"]: {all_data[guild_id]["reminders"]}')
    
    if votes:
        all_data[guild_id]["votes"] = votes
    else:
        all_data[guild_id]["votes"] = {}
    print(f'votes: {votes}')
    print(f'all_data[guild_id]["votes"]: {all_data[guild_id]["votes"]}')

    if proxy_votes:
        all_data[guild_id]["proxy_votes"] = proxy_votes
    else:
        all_data[guild_id]["proxy_votes"] = {}
    print(f'proxy_votes: {proxy_votes}')
    print(f'all_data[guild_id]["proxy_votes"]: {all_data[guild_id]["proxy_votes"]}')

    if make_list_channels:
        all_data[guild_id]["make_list_channels"] = make_list_channels["channels"] or []
    else:
        all_data[guild_id]["make_list_channels"] = []
    print(f'make_list_channels: {make_list_channels}')
    print(f'all_data[guild_id]["make_list_channels"]: {all_data[guild_id]["make_list_channels"]}')

    if rec_sessions:
        all_data[guild_id]["rec_sessions"] = rec_sessions
    else:
        all_data[guild_id]["rec_sessions"] = {}
    
    print(f"all_data: {all_data}")
    save_all_data()

    await ctx.message.delete()
    await ctx.send(f"統合辞書への移行が完了したよ🫡")

#---------------
# リマインダー関係
#---------------
#=====/remind コマンド=====
@bot.slash_command(name="remind", description="リマインダーをセットするよ")
@clean_slash_options
async def remind(
    ctx: discord.ApplicationContext,
    date: discord.Option(str, description="日付(yyyy/mm/dd)"),
    time: discord.Option(str, description="時刻(hh:mm)"),
    msg: discord.Option(str, description="内容"),
    channel: discord.Option(discord.TextChannel, description="通知するチャンネル", required=False),
    repeat: discord.Option(str, description="繰り返し単位", 
        choices=[
            discord.OptionChoice(name="日", value="day"),
            discord.OptionChoice(name="時間", value="hour"),
            discord.OptionChoice(name="分", value="minute")
        ],
        required=False
    ),
    interval: discord.Option(int, description="繰り返し間隔", default=0)
):
    reminders = all_data[ctx.guild.id]["reminders"]
    print(f"channel: {channel}")
    # 文字列引数からdatatime型に変換
    dt = datetime.strptime(f"{date} {time}", "%Y/%m/%d %H:%M").replace(tzinfo=JST)

    # チャンネルIDの取得
    if channel:
        channel_id = channel.id
    else:
        channel_id = ctx.channel.id
    
    # 過去時刻チェック
    if dt < datetime.now(JST):
        await ctx.interaction.response.send_message("️⚠️設定時刻が過去の日時だよ", ephemeral=True)
        return
    
    # add_reminder関数に渡す
    add_reminder(ctx.guild.id, dt, repeat, interval, channel_id, msg)

    await ctx.interaction.response.send_message(
        content=f"**{dt.strftime('%Y/%m/%d %H:%M')}** にリマインダーをセットしたよ🫡",
        ephemeral=True)
    print(f"予定を追加: {reminders[dt]}")

#=====/reminder_list コマンド=====
@bot.slash_command(name="reminder_list", description="リマインダーの一覧を表示するよ")
async def reminder_list(ctx: discord.ApplicationContext):
    reminders = all_data[ctx.guild.id]["reminders"]
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
        await ctx.interaction.response.send_message(embed=embed)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await ctx.interaction.response.send_message("⚠️設定されているリマインダーがないよ", ephemeral=True)

#=====/reminder_delete コマンド=====
@bot.slash_command(name="reminder_delete", description="リマインダーを削除するよ")
async def reminder_delete(ctx: discord.ApplicationContext):
    reminders = all_data[ctx.guild.id]["reminders"]
    # リマインダーが設定されている場合、選択メニューを表示
    if reminders:
        view = ReminderSelect(reminders)
        await ctx.interaction.response.send_message("削除するリマインダーを選んでね", view=view)
    # リマインダーが設定されていない場合のメッセージ
    else:
        await ctx.interaction.response.send_message("⚠️設定されているリマインダーがないよ", ephemeral=True)

#---------------
# 投票関係
#---------------
#=====/vote コマンド=====
@bot.slash_command(name="vote", description="投票を作成するよ")
@clean_slash_options
async def vote(ctx: discord.ApplicationContext,
    question: discord.Option(description="質問を書いてね"),
    opt_1: discord.Option(str,description="1番目の選択肢を書いてね"),
    opt_2: discord.Option(str,description="2番目の選択肢を書いてね", required=False),
    opt_3: discord.Option(str,description="3番目の選択肢を書いてね", required=False),
    opt_4: discord.Option(str,description="4番目の選択肢を書いてね", required=False),
    opt_5: discord.Option(str,description="5番目の選択肢を書いてね", required=False),
    opt_6: discord.Option(str,description="6番目の選択肢を書いてね", required=False),
    opt_7: discord.Option(str,description="7番目の選択肢を書いてね", required=False),
    opt_8: discord.Option(str,description="8番目の選択肢を書いてね", required=False),
    opt_9: discord.Option(str,description="9番目の選択肢を書いてね", required=False),
    opt_10: discord.Option(str,description="10番目の選択肢を書いてね", required=False)
): 
    # 選択肢をリストに格納
    raw_opts = [opt_1, opt_2, opt_3, opt_4, opt_5, opt_6, opt_7, opt_8, opt_9, opt_10]
    opts = [opt for opt in raw_opts if not isinstance(opt, discord.Option)]
    options = [opt for opt in opts if opt and opt.strip()]
    # リアクションリスト
    reacts = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    reactions = reacts[:len(options)]
    # 選択肢の1文字目が絵文字ならリアクションリストを置き換え
    options, reactions = reaction_replace(options, reactions)
    # 選択肢表示を初期化
    description = ""

    # Embedで出力
    embed = make_poll_embed(options, reactions, question, description)
    await ctx.interaction.response.send_message(embed=embed)
    
    # リアクションを追加
    message = await ctx.interaction.original_response()
    for i in range(len(options)):
        await message.add_reaction(reactions[i])
    
    # 辞書に保存
    add_vote(ctx.guild.id, message.id, question, reactions, options)

#=====/vote_add_option コマンド=====
@bot.slash_command(name="vote_add_option", description="投票に選択肢を追加するよ")
async def vote_add_option(ctx: discord.ApplicationContext):
    votes = all_data[ctx.guild.id]["votes"]
    if votes:
        view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.ADD_OPTION, voter=None, agent_id=None)
        await ctx.interaction.response.send_message("選択肢を追加する投票を選んでね", view=view)
    # 投票がない場合のメッセージ
    else:
        await ctx.interaction.response.send_message("⚠️実施中の投票がないよ", ephemeral=True)

#=====/vote_result コマンド=====
@bot.slash_command(name="vote_result", description="投票結果を表示するよ")
async def vote_result(
    ctx: discord.ApplicationContext,
    mode: str = discord.Option(description="集計モード",
        choices = [
            discord.OptionChoice(name="中間集計", value="mid"),
            discord.OptionChoice(name="最終結果", value="final")
        ]
    )
):
    votes = all_data[ctx.guild.id]["votes"]
    if votes:
        if mode == "mid":
            view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.MID_RESULT, voter=None, agent_id=None)
            await ctx.interaction.response.send_message("どの投票結果を表示するか選んでね", view=view)
        elif mode == "final":
            view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.FINAL_RESULT, voter=None, agent_id=None)
            await ctx.interaction.response.send_message("どの投票結果を表示するか選んでね", view=view)
        else:
            await ctx.interaction.response.send_message("⚠️選択モードの指定がまちがってるよ", ephemeral=True)

    # 投票がない場合のメッセージ
    else:
        await ctx.interaction.response.send_message("⚠️集計できる投票がないよ", ephemeral=True)

#=====/proxy_vote コマンド=====
@bot.slash_command(name="proxy_vote", description="本人の代わりに代理投票するよ")
async def proxy_vote(ctx: discord.ApplicationContext, voter: str = discord.Option(description="投票する本人の名前を書いてね")):
    votes = all_data[ctx.guild.id]["votes"]
    if votes:
        agent_id = ctx.interaction.user.id
        view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.PROXY_VOTE, voter=voter, agent_id=agent_id)
        await ctx.interaction.response.send_message("どの投票に代理投票するか選んでね", view=view)
    else:
        await ctx.interaction.response.send_message("⚠️代理投票できる投票がないよ", ephemeral=True)

#=====/cancel_proxy コマンド=====
@bot.slash_command(name="cancel_proxy", description="投票済みの代理投票を取り消すよ")
async def cancel_proxy(ctx: discord.ApplicationContext, voter: str = discord.Option(description="投票者名")):
    votes = all_data[ctx.guild.id]["votes"]
    if votes:
        agent_id = ctx.interaction.user.id
        view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.CANCEL_PROXY_VOTE, voter=voter, agent_id=agent_id)
        await ctx.interaction.response.send_message("代理投票を取り消しする投票を選んでね", view=view)
    else:
        await ctx.interaction.response.send_message("⚠️取り消しできる投票がないよ", ephemeral=True)

#=====!delete_vote コマンド====
@bot.command()
async def delete_vote(ctx):
    votes = all_data[ctx.guild.id]["votes"]
    if votes:
        view = VoteSelect(guild_id=ctx.guild.id, mode=VoteSelectMode.DELETE_VOTE, voter=None, agent_id=None)
        await ctx.message.delete()
        await ctx.send("どの投票を削除するか選んでね", view=view)
    else:
        await ctx.send("⚠️取り消しできる投票がないよ")

#=====context_reaction_count コマンド=====
@bot.message_command(name="context_reaction_count")
async def context_reaction_count(ctx: discord.ApplicationContext, message: discord.Message):
    if not message.reactions:
        await ctx.interaction.response.send_message(content="️⚠️リアクションがついてないよ", ephemeral=True)
        return

    await ctx.interaction.response.defer()
    print(message)
    msg_id = message.id
    
    dt, result = await make_vote_result(ctx, msg_id)
    # 結果表示処理
    await show_vote_result(ctx, dt, result, msg_id, "mid")
    # CSV作成処理
    await export_vote_csv(ctx, result, msg_id, dt, "mid")

#---------------
# メンバーリスト関係
#---------------
#=====/export_members コマンド=====
@bot.slash_command(name="export_members", description="サーバーのメンバーリストを出力するよ")
async def export_members(ctx: discord.ApplicationContext):
    await ctx.interaction.response.defer()
    guild = ctx.interaction.guild
    
    filename = f"/tmp/members_list_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.csv"
    meta = {
        "# members_at": guild.name,
        "# collected_at": datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    }
    header = ["user_id", "user_name", "display_name", "is_bot"]
    rows = [[member.id, member.name, member.nick or member.display_name or member.name, member.bot] async for member in guild.fetch_members(limit=None)]
    
    make_csv(filename, rows, meta, header)
    
    # discordに送信
    await ctx.interaction.followup.send(
        content="メンバー一覧のCSVだよ🫡",
        file=discord.File(filename)
    )

#---------------
# OCR関係
#---------------
#=====/table_ocr コマンド=====
@bot.slash_command(name="table_ocr", description="表の画像からCSVを作成するよ")
@clean_slash_options
async def table_ocr(
    ctx: discord.ApplicationContext,
    counts: discord.Option(str, description="時間指定(分)", required=False),
    minutes: discord.Option(str, description="件数指定(件)", required=False)
):
    await ctx.interaction.response.defer()

    # チャンネルの最新メッセージを取得
    start_msg_id = ctx.interaction.channel.last_message_id
    start_msg = await ctx.interaction.channel.fetch_message(start_msg_id)
    # チャンネルの一番古いメッセージを取得
    msgs = [msg async for msg in ctx.interaction.channel.history(limit=1, oldest_first=True)]
    limit_msg = msgs[0]

    # 指定した範囲のメッセージを取得
    msg_ids = await collect_message(ctx.interaction.channel, counts, minutes, start_msg, limit_msg)

    # メッセージから画像データを取得してリストに格納
    all_contents = []
    for msg_id in msg_ids:
        contents = await get_image(ctx.interaction.channel, msg_id)
        if contents:
            all_contents.extend(contents)

    # visionからテキストを受け取ってCSV用に整形
    temp_rows = []
    for content in all_contents:
        rows = await extract_table_from_image(content)
        temp_rows.extend(rows)

    # 重複行を削除
    rows = remove_duplicate_rows(temp_rows)
    
    # csv作成処理
    filename = f"/tmp/ocr_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.csv"
    make_csv(filename, rows)
    
    # CSVを出力
    await ctx.interaction.followup.send(
        content="OCR結果のCSVだよ🫡",
        file=discord.File(filename)
    )

#=====context_ocr コマンド=====
@bot.message_command(name="context_ocr")
async def context_ocr(ctx: discord.ApplicationContext, message: discord.Message):

    if not message.attachments:
        await ctx.interaction.response.send_message(content="⚠️画像が添付されてないよ", ephemeral=True)
        return

    await ctx.interaction.response.defer()

    # 画像ごとにOCR処理を実行してtemp_rowsに格納
    temp_rows = []
    for attachment in message.attachments:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                content = await resp.read()
    
        # visionからテキストを受け取ってCSV用に整形
        temp_rows.extend(await extract_table_from_image(content))
    print(f"temp_rows:{temp_rows}")
    # 重複行を削除
    rows = remove_duplicate_rows(temp_rows)
    print(f"rows:{rows}")
    
    # csv作成処理
    filename = f"/tmp/ocr_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.csv"
    make_csv(filename, rows)
    
    # CSVを出力
    await ctx.interaction.followup.send(
        content="OCR結果のCSVだよ🫡",
        file=discord.File(filename)
    )

#---------------
# リスト化関係
#---------------
#=====add_listed_ch コマンド=====
@bot.command()
async def add_listed_ch(ctx):
    # コマンド実行チャンネルを取得
    channel_id = ctx.channel.id
    channel_name = ctx.channel.name

    # リスト化対象チャンネル辞書に登録
    add_make_list_channel(ctx.guild.id, channel_id)
    
    await ctx.message.delete()
    await ctx.send(f"{channel_name}をリスト化対象にしたよ🫡\n今後は改行ごとに別の項目としてリスト化されるよ\nリストから削除する場合は、ロングタップ(PCの場合は右クリック)して、アプリ→**remove_from_list**で削除できるよ\n---")

#=====remove_listed_ch コマンド=====
@bot.command()
async def remove_listed_ch(ctx):
    # コマンド実行チャンネルを取得
    channel_id = ctx.channel.id
    channel_name = ctx.channel.name

    # リスト化対象チャンネル辞書から削除
    remove_ch = remove_make_list_channel(ctx.guild.id, channel_id, channel_name)
    
    if remove_ch:
        await ctx.message.delete()
        await ctx.send(f"{channel_name}をリスト化対象から削除したよ🫡")
    else:
        await ctx.message.delete()
        await ctx.send(content=f"⚠️{channel_name}はリスト化対象ではないよ")

#=====remove_from_list コマンド=====
@bot.message_command(name="remove_from_list")
async def remove_from_list(ctx: discord.ApplicationContext, message: discord.Message):
    make_list_channels = all_data[ctx.guild.id]["make_list_channels"]
    # リスト化対象チャンネル内なら項目を削除
    if message.channel.id in make_list_channels:
        await message.delete()
        await ctx.interaction.response.send_message(content=f"{message.content}を削除したよ🫡", ephemeral=True)
    # リスト化対象チャンネル以外ならエラーを返す
    else:
        await ctx.interaction.response.send_message(content=f"️⚠️リストの項目以外は削除できないよ", ephemeral=True)

#---------------
# STT関係
#---------------
#=====recstart コマンド=====
@bot.command(name="recstart")
async def recstart(ctx):
    # コマンド実行者がvc参加中の場合
    if ctx.author.voice:
        # botが既にvc参加していればエラーメッセージを返す
        if ctx.voice_client and ctx.voice_client.recording:
            await ctx.message.delete()
            return await ctx.send("⚠️いまは録音中だよ")
        # そうでなければコマンド実行者が参加中のvcに接続する
        else:
            channel = ctx.author.voice.channel
            await ctx.message.delete()
            await channel.connect()
            vc = ctx.voice_client

    # コマンド実行者がvc参加していなければエラーメッセージを返す
    else:
        await ctx.message.delete()
        return await ctx.send("⚠️先にボイスチャンネルに参加してね")

    start_time = datetime.now(JST)

    # 録音開始
    vc.start_recording(
        discord.sinks.WaveSink(),
        after_recording,
        channel,
        start_time
    )

    # 録音セッション辞書にチャンネルIDを追加
    add_rec_session(ctx.guild.id, ctx.channel.id)

    await ctx.send("⏺録音を開始したよ🫡")

#=====recstop コマンド=====
@bot.command(name="recstop")
async def recstop(ctx):
    vc = ctx.voice_client
    # botがvcに参加している場合
    if vc:
        if vc.recording:
            await ctx.message.delete()
            vc.stop_recording()
            await vc.disconnect()
        else:
            await ctx.message.delete()
            await ctx.send("⚠️いまは録音してないよ")

# Botを起動
bot.run(os.getenv("DISCORD_TOKEN"))