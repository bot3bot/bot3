import discord
from discord.ext import commands
import datetime
import json
import os

from flask import Flask
from threading import Thread

# =========================
# KEEP ALIVE
# =========================

app = Flask('')

@app.route('/')
def home():
    return "Bot Running"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# =========================
# BOT
# =========================

intents = discord.Intents.all()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================
# IDS
# =========================

POINT_CHANNEL = 1497204458680090779
TOP_CHANNEL = 1497642199859593388

# روم الكلمات الجديدة
KEYWORD_CHANNEL = 1497911384191668254

POINT_ROLES = [
1482194383515422752,
1480443913557905499
]

ALLOWED_ROLES = [
1478970736717598840,
1495873706923393205,
1490386915629989948,
1478971845729583276
]

# =========================
# FILES
# =========================

POINT_FILE = "points.json"
DOUBLE_FILE = "double.json"

def load_json(file):

    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump({}, f)

    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):

    with open(file, "w") as f:
        json.dump(data, f, indent=4)

# =========================
# نقاط الكتابة + كلمات صوره وتكت
# =========================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    points = load_json(POINT_FILE)
    double = load_json(DOUBLE_FILE)

    uid = str(message.author.id)

    # =====================
    # نقاط الكتابة العادية
    # =====================

    if any(r.id in POINT_ROLES for r in message.author.roles):

        add = 2

        if double.get("active"):
            add = 5

        points[uid] = points.get(uid, 0) + add

        save_json(POINT_FILE, points)

    # =====================
    # كلمات صوره وتكت
    # =====================

    if message.channel.id == KEYWORD_CHANNEL:

        text = message.content.lower()

        if "صوره" in text:

            points[uid] = points.get(uid, 0) + 10

            save_json(POINT_FILE, points)

            total = points.get(uid, 0)

            embed = discord.Embed(
                title="📸 إضافة نقاط",
                description=(
                    f"تم إضافة **10 نقاط** إلى {message.author.mention}\n\n"
                    f"📊 مجموع نقاطك الآن:\n"
                    f"**{total} نقطة**"
                ),
                color=discord.Color.green()
            )

            embed.timestamp = datetime.datetime.utcnow()

            await message.channel.send(embed=embed)

        elif "تكت" in text:

            points[uid] = points.get(uid, 0) + 25

            save_json(POINT_FILE, points)

            total = points.get(uid, 0)

            embed = discord.Embed(
                title="🎫 إضافة نقاط",
                description=(
                    f"تم إضافة **25 نقطة** إلى {message.author.mention}\n\n"
                    f"📊 مجموع نقاطك الآن:\n"
                    f"**{total} نقطة**"
                ),
                color=discord.Color.green()
            )

            embed.timestamp = datetime.datetime.utcnow()

            await message.channel.send(embed=embed)

    await bot.process_commands(message)

# =========================
# نقاط الصوت
# =========================

voice_times = {}

@bot.event
async def on_voice_state_update(member, before, after):

    if not any(r.id in POINT_ROLES for r in member.roles):
        return

    uid = str(member.id)

    if after.channel:

        voice_times[uid] = datetime.datetime.utcnow()

    elif before.channel:

        if uid in voice_times:

            start = voice_times[uid]

            mins = (
                datetime.datetime.utcnow() - start
            ).total_seconds() / 60

            count = int(mins // 5)

            if count > 0:

                points = load_json(POINT_FILE)
                double = load_json(DOUBLE_FILE)

                add = 15

                if double.get("active"):
                    add = 30

                total = add * count

                points[uid] = points.get(uid, 0) + total

                save_json(POINT_FILE, points)

            del voice_times[uid]

# =========================
# عرض نقاطك
# =========================

@bot.command(name="تفاعل")
async def show_points(ctx):

    if ctx.channel.id != POINT_CHANNEL:
        return

    points = load_json(POINT_FILE)

    uid = str(ctx.author.id)

    total = points.get(uid, 0)

    embed = discord.Embed(
        title="📊 نقاط التفاعل",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="المستخدم",
        value=ctx.author.mention,
        inline=False
    )

    embed.add_field(
        name="مجموع النقاط",
        value=f"{total} نقطة",
        inline=False
    )

    embed.timestamp = datetime.datetime.utcnow()

    await ctx.send(embed=embed)

# =========================
# TOP 3
# =========================

@bot.command(name="top")
async def top_points(ctx):

    if ctx.channel.id != TOP_CHANNEL:
        return

    points = load_json(POINT_FILE)

    if not points:
        await ctx.send("لا يوجد نقاط حالياً")
        return

    sorted_points = sorted(
        points.items(),
        key=lambda x: x[1],
        reverse=True
    )

    medals = ["🥇", "🥈", "🥉"]

    desc = ""

    for i, (uid, pts) in enumerate(sorted_points[:3]):

        member = ctx.guild.get_member(int(uid))

        if member:

            desc += (
                f"{medals[i]} "
                f"{member.mention} — "
                f"{pts} نقطة\n"
            )

    embed = discord.Embed(
        title="🏆 أعلى المتفاعلين",
        description=desc,
        color=discord.Color.gold()
    )

    embed.timestamp = datetime.datetime.utcnow()

    await ctx.send(embed=embed)

# =========================
# تصفير نقاط شخص
# =========================

@bot.command(name="تصفير")
async def reset_points(ctx, member: discord.Member):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):

        await ctx.send("❌ لا يسمح لك باستخدام الامر")
        return

    points = load_json(POINT_FILE)

    points[str(member.id)] = 0

    save_json(POINT_FILE, points)

    embed = discord.Embed(
        title="🧹 تصفير النقاط",
        description=f"تم تصفير نقاط {member.mention}",
        color=discord.Color.red()
    )

    await ctx.send(embed=embed)

# =========================
# إضافة نقاط
# =========================

@bot.command(name="اضف")
async def add_points(ctx, member: discord.Member, amount: int):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):

        await ctx.send("❌ لا يسمح لك باستخدام الامر")
        return

    points = load_json(POINT_FILE)

    uid = str(member.id)

    points[uid] = points.get(uid, 0) + amount

    save_json(POINT_FILE, points)

    embed = discord.Embed(
        title="➕ إضافة نقاط",
        description=f"تم إضافة {amount} نقطة إلى {member.mention}",
        color=discord.Color.green()
    )

    await ctx.send(embed=embed)

# =========================
# تصفير الجميع
# =========================

@bot.command(name="resetall")
async def reset_all(ctx):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):

        await ctx.send("❌ لا يسمح لك باستخدام الامر")
        return

    save_json(POINT_FILE, {})

    embed = discord.Embed(
        title="🧹 تصفير شامل",
        description="تم تصفير جميع النقاط",
        color=discord.Color.red()
    )

    await ctx.send(embed=embed)

# =========================
# دبل
# =========================

@bot.command()
async def double(ctx):

    save_json(DOUBLE_FILE, {"active": True})

    await ctx.send("🔥 تم تفعيل الدبل")

@bot.command()
async def doubleoff(ctx):

    save_json(DOUBLE_FILE, {"active": False})

    await ctx.send("❄️ تم إيقاف الدبل")

# =========================
# READY
# =========================

@bot.event
async def on_ready():

    print(f"✅ Logged in as {bot.user}")

# =========================
# START
# =========================

keep_alive()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("❌ لم يتم العثور على DISCORD_TOKEN")
