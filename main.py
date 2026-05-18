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
KEYWORD_CHANNEL = 1497911384191668254

LEAVE_CHANNEL = 1490070238270718013
LEAVE_LOG_CHANNEL = 1490820000477610036
LEAVE_ROLE = 1492607429249339502

BLOCKED_CHANNELS = [
    1497203612432990259,
    1497204458680090779
]

POINT_ROLES = [
    1482194383515422752,
    1480443913557905499,
    1477492633847857252
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
REQUIRE_FILE = "requirements.json"
LEAVE_FILE = "leaves.json"

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
# نظام الإجازات
# =========================

class LeaveModal(discord.ui.Modal, title="طلب إجازة"):

    reason = discord.ui.TextInput(
        label="سبب الإجازة",
        required=True,
        max_length=200
    )

    days = discord.ui.TextInput(
        label="كم يوم",
        required=True,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):

        try:
            days = int(self.days.value)
        except:
            await interaction.response.send_message(
                "❌ عدد الأيام غير صحيح",
                ephemeral=True
            )
            return

        leaves = load_json(LEAVE_FILE)

        uid = str(interaction.user.id)

        now = datetime.datetime.utcnow().timestamp()

        leaves[uid] = {
            "reason": self.reason.value,
            "days": days,
            "time": now
        }

        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)

        if role:
            await interaction.user.add_roles(role)

        log_channel = bot.get_channel(LEAVE_LOG_CHANNEL)

        if log_channel:

            embed = discord.Embed(
                title="📋 طلب إجازة جديد",
                color=discord.Color.green()
            )

            embed.description = (
                f"👤 المستخدم : {interaction.user.mention}\n\n"
                f"📝 السبب : {self.reason.value}\n\n"
                f"📅 عدد الأيام : {days}"
            )

            embed.timestamp = datetime.datetime.utcnow()

            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            "✅ تم تسجيل الإجازة بنجاح",
            ephemeral=True
        )

class LeaveView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="طلب إجازة",
        style=discord.ButtonStyle.green
    )
    async def request_leave(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            LeaveModal()
        )

    @discord.ui.button(
        label="سحب الإجازة",
        style=discord.ButtonStyle.red
    )
    async def remove_leave(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        leaves = load_json(LEAVE_FILE)

        uid = str(interaction.user.id)

        if uid not in leaves:

            await interaction.response.send_message(
                "❌ ليس لديك إجازة",
                ephemeral=True
            )
            return

        leave_time = leaves[uid]["time"]

        now = datetime.datetime.utcnow().timestamp()

        passed = now - leave_time

        if passed >= 86400:

            await interaction.response.send_message(
                "❌ انتهت مدة سحب الإجازة (24 ساعة)",
                ephemeral=True
            )
            return

        del leaves[uid]

        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)

        if role:
            await interaction.user.remove_roles(role)

        log_channel = bot.get_channel(LEAVE_LOG_CHANNEL)

        if log_channel:

            embed = discord.Embed(
                title="📌 سحب إجازة",
                color=discord.Color.red()
            )

            embed.description = (
                f"👤 المستخدم : {interaction.user.mention}\n\n"
                f"✅ تم سحب الإجازة بنجاح"
            )

            embed.timestamp = datetime.datetime.utcnow()

            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            "✅ تم سحب الإجازة",
            ephemeral=True
        )

# =========================
# أمر لوحة الإجازات
# =========================

@bot.command(name="اجازه")
async def leave_panel(ctx):

    if ctx.channel.id != LEAVE_CHANNEL:
        return

    embed = discord.Embed(
        title="📋 نظام الإجازات",
        description=(
            "اضغط على الزر المناسب\n\n"
            "🟢 طلب إجازة\n"
            "🔴 سحب الإجازة"
        ),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=LeaveView()
    )

# =========================
# نقاط الكتابة
# =========================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    points = load_json(POINT_FILE)
    double = load_json(DOUBLE_FILE)

    uid = str(message.author.id)

    if (
        any(r.id in POINT_ROLES for r in message.author.roles)
        and message.channel.id not in BLOCKED_CHANNELS
    ):

        add = 2

        if double.get("active"):
            add = 5

        points[uid] = points.get(uid, 0) + add

        save_json(POINT_FILE, points)

    if message.channel.id == KEYWORD_CHANNEL:

        text = message.content.lower()

        if "صوره" in text:

            points[uid] = points.get(uid, 0) + 10

            save_json(POINT_FILE, points)

        elif "تكت" in text:

            points[uid] = points.get(uid, 0) + 25

            save_json(POINT_FILE, points)

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
# عرض التفاعل
# =========================

@bot.command(name="تفاعل")
async def show_points(ctx):

    if ctx.channel.id != POINT_CHANNEL:
        return

    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)

    uid = str(ctx.author.id)

    total_points = points.get(uid, 0)

    required_points = requirements.get(uid, 1000)

    remaining = required_points - total_points

    if remaining < 0:
        remaining = 0

    embed = discord.Embed(
        title="📊 نظام التفاعل",
        color=discord.Color.blue()
    )

    embed.description = (
        f"👤 المستخدم : {ctx.author.mention}\n\n"
        f"📈 نقاط التفاعل الحالية : {total_points}\n\n"
        f"🎯 نقاط الترقية المطلوبة : {required_points}\n\n"
        f"📌 المتبقي للترقية : {remaining}"
    )

    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    embed.timestamp = datetime.datetime.utcnow()

    await ctx.send(embed=embed)

# =========================
# TOP
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

    await ctx.send(embed=embed)

# =========================
# تصفير نقاط شخص
# =========================

@bot.command(name="تصفير")
async def reset_points(ctx, member: discord.Member):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):
        return

    points = load_json(POINT_FILE)

    points[str(member.id)] = 0

    save_json(POINT_FILE, points)

    await ctx.send(
        f"✅ تم تصفير نقاط التفاعل لـ {member.mention}"
    )

# =========================
# إضافة نقاط
# =========================

@bot.command(name="اضف")
async def add_points(ctx, member: discord.Member, amount: int):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):
        return

    points = load_json(POINT_FILE)

    uid = str(member.id)

    points[uid] = points.get(uid, 0) + amount

    save_json(POINT_FILE, points)

    await ctx.send(
        f"✅ تم إضافة {amount} نقطة إلى {member.mention}"
    )

# =========================
# تعديل متطلب الترقية
# =========================

@bot.command(name="setreq")
async def set_requirement(ctx, member: discord.Member, amount: int):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):
        return

    requirements = load_json(REQUIRE_FILE)

    requirements[str(member.id)] = amount

    save_json(REQUIRE_FILE, requirements)

    await ctx.send(
        f"✅ تم تحديد متطلب الترقية لـ {member.mention} إلى {amount}"
    )

# =========================
# تصفير متطلب الترقية
# =========================

@bot.command(name="resetupgrade")
async def reset_upgrade(ctx, member: discord.Member):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):
        return

    requirements = load_json(REQUIRE_FILE)

    requirements[str(member.id)] = 1000

    save_json(REQUIRE_FILE, requirements)

    await ctx.send(
        f"✅ تم تصفير متطلب الترقية لـ {member.mention}"
    )

# =========================
# تصفير جميع نقاط التفاعل
# =========================

@bot.command(name="resetall")
async def reset_all(ctx):

    if ctx.channel.id != TOP_CHANNEL:
        return

    if not any(r.id in ALLOWED_ROLES for r in ctx.author.roles):
        return

    points = load_json(POINT_FILE)

    for user_id in points:
        points[user_id] = 0

    save_json(POINT_FILE, points)

    await ctx.send(
        "✅ تم تصفير جميع نقاط التفاعل فقط"
    )

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

    bot.add_view(LeaveView())

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
