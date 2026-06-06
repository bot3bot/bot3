import datetime
import json
import os
import re
import uuid
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands, tasks
from flask import Flask


# =========================
# KEEP ALIVE
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Admin bot is running"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================
# BOT CONFIG
# =========================

intents = discord.Intents.all()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# CHANNELS / ROLES
# =========================

# التفاعل
POINT_CHANNEL = 1497204458680090779
INTERACTION_PANEL_CHANNEL = 1497642199859593388
KEYWORD_CHANNEL = 1497911384191668254

# الإجازات
LEAVE_CHANNEL = 1490070238270718013
LEAVE_LOG_CHANNEL = 1490820000477610036
LEAVE_ROLE = 1492607429249339502

# الإنذارات
WARNING_LOG_CHANNEL = 1479608600350429194
WARNING_INPUT_CHANNEL = 1512860383461773482
WARNING_TIMEOUT_DAYS = 7

BLOCKED_CHANNELS = {
    1497203612432990259,
    1497204458680090779,
}

POINT_ROLES = {
    1482194383515422752,
    1480443913557905499,
    1477492633847857252,
}

ADMIN_ROLES = {
    1478970736717598840,
    1495873706923393205,
    1490386915629989948,
    1478971845729583276,
}

TEXT_POINTS = 10
DOUBLE_TEXT_POINTS = 15
VOICE_POINTS_EVERY_5_MINUTES = 15
DOUBLE_VOICE_POINTS_EVERY_5_MINUTES = 20
TICKET_POINTS = 25
IMAGE_POINTS = 10


# =========================
# FILES
# =========================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

POINT_FILE = DATA_DIR / "points.json"
DOUBLE_FILE = DATA_DIR / "double.json"
REQUIRE_FILE = DATA_DIR / "requirements.json"
LEAVE_FILE = DATA_DIR / "leaves.json"
LEAVE_BALANCE_FILE = DATA_DIR / "leave_balance.json"
WARNING_FILE = DATA_DIR / "warnings.json"


def load_json(file: Path, default=None):
    if default is None:
        default = {}

    if not file.exists():
        save_json(file, default)
        return default.copy() if isinstance(default, dict) else default

    try:
        with file.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default.copy() if isinstance(default, dict) else default


def save_json(file: Path, data):
    file.parent.mkdir(exist_ok=True)
    with file.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def has_any_role(member: discord.Member, role_ids: set[int]) -> bool:
    return any(role.id in role_ids for role in getattr(member, "roles", []))


def is_admin(member: discord.Member) -> bool:
    return has_any_role(member, ADMIN_ROLES)


def is_points_member(member: discord.Member) -> bool:
    return has_any_role(member, POINT_ROLES)


def add_points_to_user(user_id: int, amount: int, include_requirements: bool = True):
    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)

    uid = str(user_id)
    points[uid] = points.get(uid, 0) + amount

    if include_requirements:
        requirements[uid] = requirements.get(uid, 0) + amount

    save_json(POINT_FILE, points)
    save_json(REQUIRE_FILE, requirements)

    return points[uid], requirements.get(uid, 0)


def get_user_points(user_id: int):
    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)
    uid = str(user_id)
    return points.get(uid, 0), requirements.get(uid, 0)


def get_double_amount(text_amount: int, voice_amount: int):
    double = load_json(DOUBLE_FILE, {"active": False})
    if double.get("active"):
        return 5 if text_amount == 2 else 30
    return text_amount if text_amount == 2 else voice_amount


# =========================
# LEAVES
# =========================

MAX_MONTHLY_LEAVE = 14
MIN_LEAVE_DAYS = 3
WITHDRAW_LIMIT_SECONDS = 24 * 60 * 60


def reset_user_balance_if_needed(user_id: int | str):
    balances = load_json(LEAVE_BALANCE_FILE)
    uid = str(user_id)
    current_time = now_utc()

    if uid not in balances:
        balances[uid] = {
            "remaining": MAX_MONTHLY_LEAVE,
            "last_reset": current_time.timestamp(),
        }
        save_json(LEAVE_BALANCE_FILE, balances)
        return balances[uid]

    last_reset = datetime.datetime.fromtimestamp(
        balances[uid]["last_reset"],
        tz=datetime.timezone.utc,
    )

    if (current_time - last_reset).days >= 30:
        balances[uid]["remaining"] = MAX_MONTHLY_LEAVE
        balances[uid]["last_reset"] = current_time.timestamp()
        save_json(LEAVE_BALANCE_FILE, balances)

    return balances[uid]


@tasks.loop(hours=12)
async def auto_reset_leaves():
    balances = load_json(LEAVE_BALANCE_FILE)
    current_time = now_utc()
    changed = False

    for uid, data in balances.items():
        last_reset = datetime.datetime.fromtimestamp(
            data["last_reset"],
            tz=datetime.timezone.utc,
        )

        if (current_time - last_reset).days >= 30:
            balances[uid]["remaining"] = MAX_MONTHLY_LEAVE
            balances[uid]["last_reset"] = current_time.timestamp()
            changed = True

            try:
                user = await bot.fetch_user(int(uid))
                await user.send("✅ تم تجديد رصيد إجازاتك الشهري إلى 14 يوم.")
            except discord.HTTPException:
                pass

    if changed:
        save_json(LEAVE_BALANCE_FILE, balances)


class LeaveModal(discord.ui.Modal, title="طلب إجازة"):
    reason = discord.ui.TextInput(
        label="سبب الإجازة",
        placeholder="اكتب السبب باختصار",
        required=True,
        max_length=200,
    )
    days = discord.ui.TextInput(
        label="عدد الأيام",
        placeholder="مثال: 3",
        required=True,
        max_length=2,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            days = int(self.days.value)
        except ValueError:
            await interaction.response.send_message("❌ عدد الأيام غير صحيح.", ephemeral=True)
            return

        if days < MIN_LEAVE_DAYS:
            await interaction.response.send_message("❌ أقل مدة للإجازة هي 3 أيام.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        leaves = load_json(LEAVE_FILE)

        if uid in leaves:
            await interaction.response.send_message("❌ لديك إجازة مسجلة حاليًا.", ephemeral=True)
            return

        balance = reset_user_balance_if_needed(uid)
        if days > balance["remaining"]:
            await interaction.response.send_message(
                f"❌ رصيدك المتبقي {balance['remaining']} يوم فقط.",
                ephemeral=True,
            )
            return

        balances = load_json(LEAVE_BALANCE_FILE)
        balances[uid]["remaining"] -= days
        save_json(LEAVE_BALANCE_FILE, balances)

        leaves[uid] = {
            "reason": str(self.reason.value),
            "days": days,
            "created_at": now_utc().timestamp(),
        }
        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)
        if role:
            await interaction.user.add_roles(role, reason="تسجيل إجازة إدارية")

        log_channel = bot.get_channel(LEAVE_LOG_CHANNEL)
        if log_channel:
            embed = discord.Embed(
                title="طلب إجازة جديد",
                color=discord.Color.green(),
                timestamp=now_utc(),
            )
            embed.add_field(name="الإداري", value=interaction.user.mention, inline=True)
            embed.add_field(name="المدة", value=f"{days} يوم", inline=True)
            embed.add_field(name="الرصيد المتبقي", value=f"{balances[uid]['remaining']} يوم", inline=True)
            embed.add_field(name="السبب", value=str(self.reason.value), inline=False)
            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ تم تسجيل الإجازة. رصيدك المتبقي: {balances[uid]['remaining']} يوم.",
            ephemeral=True,
        )


class LeaveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="طلب إجازة", style=discord.ButtonStyle.green, custom_id="leave:request")
    async def request_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LeaveModal())

    @discord.ui.button(label="سحب الإجازة", style=discord.ButtonStyle.red, custom_id="leave:withdraw")
    async def withdraw_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        leaves = load_json(LEAVE_FILE)

        if uid not in leaves:
            await interaction.response.send_message("❌ لا توجد إجازة مسجلة عليك.", ephemeral=True)
            return

        passed = now_utc().timestamp() - leaves[uid]["created_at"]
        if passed >= WITHDRAW_LIMIT_SECONDS:
            await interaction.response.send_message("❌ انتهت مهلة سحب الإجازة وهي 24 ساعة.", ephemeral=True)
            return

        days = leaves[uid]["days"]
        balances = load_json(LEAVE_BALANCE_FILE)
        reset_user_balance_if_needed(uid)
        balances = load_json(LEAVE_BALANCE_FILE)
        balances[uid]["remaining"] = min(MAX_MONTHLY_LEAVE, balances[uid]["remaining"] + days)
        save_json(LEAVE_BALANCE_FILE, balances)

        del leaves[uid]
        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)
        if role:
            await interaction.user.remove_roles(role, reason="سحب الإجازة الإدارية")

        log_channel = bot.get_channel(LEAVE_LOG_CHANNEL)
        if log_channel:
            embed = discord.Embed(
                title="سحب إجازة",
                color=discord.Color.red(),
                timestamp=now_utc(),
                description=f"تم سحب إجازة {interaction.user.mention}. الرصيد الحالي: {balances[uid]['remaining']} يوم.",
            )
            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ تم سحب الإجازة. رصيدك الحالي: {balances[uid]['remaining']} يوم.",
            ephemeral=True,
        )


@bot.command(name="اجازه", aliases=["اجازة", "إجازة", "إجازه"])
async def leave_panel(ctx: commands.Context):
    if ctx.channel.id != LEAVE_CHANNEL:
        return

    embed = discord.Embed(
        title="نظام الإجازات",
        description=(
            "رصيد كل إداري: 14 يوم شهريًا\n"
            "أقل طلب إجازة: 3 أيام\n"
            "يمكن سحب الإجازة خلال أول 24 ساعة فقط."
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=LeaveView())


# =========================
# INTERACTION PANEL
# =========================

class AddPointsModal(discord.ui.Modal, title="إضافة نقاط"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)
    amount = discord.ui.TextInput(label="عدد النقاط", required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
            amount = int(self.amount.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ الآيدي أو عدد النقاط غير صحيح.", ephemeral=True)
            return

        member = interaction.guild.get_member(member_id)
        if not member:
            await interaction.response.send_message("❌ لم أجد العضو داخل السيرفر.", ephemeral=True)
            return

        total, req = add_points_to_user(member.id, amount)
        await interaction.response.send_message(
            f"✅ تم إضافة {amount} نقطة إلى {member.mention}. التفاعل: {total} | الترقية: {req}",
            ephemeral=True,
        )


class SetRequirementModal(discord.ui.Modal, title="تعديل نقاط الترقية"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)
    amount = discord.ui.TextInput(label="القيمة الجديدة", required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
            amount = int(self.amount.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ الآيدي أو القيمة غير صحيحة.", ephemeral=True)
            return

        requirements = load_json(REQUIRE_FILE)
        requirements[str(member_id)] = amount
        save_json(REQUIRE_FILE, requirements)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await interaction.response.send_message(
            f"✅ تم تعديل نقاط الترقية لـ {mention} إلى {amount}.",
            ephemeral=True,
        )


class ResetUserPointsModal(discord.ui.Modal, title="تصفير نقاط عضو"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ الآيدي غير صحيح.", ephemeral=True)
            return

        points = load_json(POINT_FILE)
        points[str(member_id)] = 0
        save_json(POINT_FILE, points)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await interaction.response.send_message(f"✅ تم تصفير نقاط التفاعل لـ {mention}.", ephemeral=True)


class ResetRequirementModal(discord.ui.Modal, title="تصفير نقاط الترقية"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ الآيدي غير صحيح.", ephemeral=True)
            return

        requirements = load_json(REQUIRE_FILE)
        requirements[str(member_id)] = 0
        save_json(REQUIRE_FILE, requirements)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await interaction.response.send_message(f"✅ تم تصفير نقاط الترقية لـ {mention}.", ephemeral=True)


class InteractionPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="نقاطي", style=discord.ButtonStyle.primary, custom_id="points:mine", row=0)
    async def my_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        total, req = get_user_points(interaction.user.id)
        embed = discord.Embed(title="نقاط التفاعل", color=discord.Color.blue(), timestamp=now_utc())
        embed.add_field(name="الإداري", value=interaction.user.mention, inline=False)
        embed.add_field(name="نقاط التفاعل", value=str(total), inline=True)
        embed.add_field(name="نقاط الترقية", value=str(req), inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="التوب", style=discord.ButtonStyle.success, custom_id="points:top", row=0)
    async def top_points_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=build_top_embed(interaction.guild), ephemeral=False)

    @discord.ui.button(label="إضافة نقاط", style=discord.ButtonStyle.secondary, custom_id="points:add", row=1)
    async def add_points_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddPointsModal())

    @discord.ui.button(label="تصفير عضو", style=discord.ButtonStyle.danger, custom_id="points:reset_user", row=1)
    async def reset_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetUserPointsModal())

    @discord.ui.button(label="تعديل ترقية", style=discord.ButtonStyle.secondary, custom_id="points:setreq", row=2)
    async def set_req_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetRequirementModal())

    @discord.ui.button(label="تصفير ترقية", style=discord.ButtonStyle.danger, custom_id="points:reset_req", row=2)
    async def reset_req_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetRequirementModal())

    @discord.ui.button(label="تصفير الكل", style=discord.ButtonStyle.danger, custom_id="points:reset_all", row=3)
    async def reset_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        points = load_json(POINT_FILE)
        for user_id in points:
            points[user_id] = 0
        save_json(POINT_FILE, points)
        await interaction.response.send_message("✅ تم تصفير جميع نقاط التفاعل فقط.", ephemeral=True)

    @discord.ui.button(label="تشغيل/إيقاف الدبل", style=discord.ButtonStyle.danger, custom_id="points:double", row=3)
    async def toggle_double(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        double = load_json(DOUBLE_FILE, {"active": False})
        double["active"] = not double.get("active", False)
        save_json(DOUBLE_FILE, double)

        status = "مفعل" if double["active"] else "مغلق"
        await interaction.response.send_message(f"✅ الدبل الآن: {status}.", ephemeral=True)


def build_top_embed(guild: discord.Guild):
    points = load_json(POINT_FILE)
    embed = discord.Embed(title="أعلى المتفاعلين", color=discord.Color.gold(), timestamp=now_utc())

    if not points:
        embed.description = "لا توجد نقاط حاليًا."
        return embed

    sorted_points = sorted(points.items(), key=lambda item: item[1], reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []

    for index, (uid, pts) in enumerate(sorted_points, start=1):
        member = guild.get_member(int(uid))
        name = member.mention if member else f"`{uid}`"
        prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
        lines.append(f"{prefix} {name} - {pts} نقطة")

    embed.description = "\n".join(lines)
    return embed


@bot.command(name="لوحة")
async def interaction_panel(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL:
        return

    if not is_admin(ctx.author):
        return

    embed = discord.Embed(
        title="لوحة إدارة التفاعل",
        description="إدارة نقاط التفاعل والترقية والتوب والدبل من هنا.",
        color=discord.Color.dark_teal(),
    )
    await ctx.send(embed=embed, view=InteractionPanel())


# =========================
# POINTS
# =========================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    await handle_warning_input(message)
    await handle_message_points(message)
    await bot.process_commands(message)


async def handle_message_points(message: discord.Message):
    if not isinstance(message.author, discord.Member):
        return

    double_active = load_json(DOUBLE_FILE, {"active": False}).get("active")
    text_amount = DOUBLE_TEXT_POINTS if double_active else TEXT_POINTS
    add_points_to_user(message.author.id, text_amount)

    if message.channel.id != KEYWORD_CHANNEL:
        return

    content = message.content.strip().lower()
    has_image = any(
        attachment.content_type and attachment.content_type.startswith("image/")
        for attachment in message.attachments
    )

    keyword_amount = 0
    keyword_name = None

    if "تكت" in content or "ticket" in content:
        keyword_amount = TICKET_POINTS
        keyword_name = "تكت"
    elif "صوره" in content or "صورة" in content or has_image:
        keyword_amount = IMAGE_POINTS
        keyword_name = "صورة"

    if keyword_amount:
        total, req = add_points_to_user(message.author.id, keyword_amount)
        await message.reply(
            (
                f"✅ تم تسجيل {keyword_name} واحتساب النقاط بنجاح.\n"
                f"**النقاط المضافة:** `{keyword_amount}`\n"
                f"**مجموع نقاطك:** `{total}`"
            ),
            mention_author=False,
        )


voice_times: dict[str, datetime.datetime] = {}


@tasks.loop(minutes=5)
async def award_voice_points():
    double_active = load_json(DOUBLE_FILE, {"active": False}).get("active")
    amount = DOUBLE_VOICE_POINTS_EVERY_5_MINUTES if double_active else VOICE_POINTS_EVERY_5_MINUTES
    current_time = now_utc()

    for guild in bot.guilds:
        for channel in guild.voice_channels:
            for member in channel.members:
                if member.bot:
                    continue

                uid = str(member.id)
                if uid not in voice_times:
                    voice_times[uid] = current_time
                    continue

                elapsed_minutes = (current_time - voice_times[uid]).total_seconds() / 60
                count = int(elapsed_minutes // 5)
                if count <= 0:
                    continue

                add_points_to_user(member.id, amount * count)
                voice_times[uid] = voice_times[uid] + datetime.timedelta(minutes=5 * count)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    uid = str(member.id)

    if before.channel is None and after.channel is not None:
        voice_times[uid] = now_utc()
        return

    if before.channel is not None and after.channel is None and uid in voice_times:
        minutes = (now_utc() - voice_times[uid]).total_seconds() / 60
        count = int(minutes // 5)

        if count > 0:
            double_active = load_json(DOUBLE_FILE, {"active": False}).get("active")
            amount = DOUBLE_VOICE_POINTS_EVERY_5_MINUTES if double_active else VOICE_POINTS_EVERY_5_MINUTES
            add_points_to_user(member.id, amount * count)

        del voice_times[uid]


@bot.command(name="تفاعل")
async def show_points(ctx: commands.Context):
    if ctx.channel.id != POINT_CHANNEL:
        return

    total, req = get_user_points(ctx.author.id)
    embed = discord.Embed(title="نظام التفاعل", color=discord.Color.blue(), timestamp=now_utc())
    embed.add_field(name="الإداري", value=ctx.author.mention, inline=False)
    embed.add_field(name="نقاط التفاعل", value=str(total), inline=True)
    embed.add_field(name="نقاط الترقية", value=str(req), inline=True)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="top")
async def top_points(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL:
        return
    await ctx.send(embed=build_top_embed(ctx.guild))


@bot.command(name="تصفير")
async def reset_points(ctx: commands.Context, member: discord.Member):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    points = load_json(POINT_FILE)
    points[str(member.id)] = 0
    save_json(POINT_FILE, points)
    await ctx.send(f"✅ تم تصفير نقاط التفاعل لـ {member.mention}.")


@bot.command(name="اضف")
async def add_points(ctx: commands.Context, member: discord.Member, amount: int):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    total, req = add_points_to_user(member.id, amount)
    await ctx.send(f"✅ تم إضافة {amount} نقطة إلى {member.mention}. التفاعل: {total} | الترقية: {req}")


@bot.command(name="setreq")
async def set_requirement(ctx: commands.Context, member: discord.Member, amount: int):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    requirements = load_json(REQUIRE_FILE)
    requirements[str(member.id)] = amount
    save_json(REQUIRE_FILE, requirements)
    await ctx.send(f"✅ تم تعديل نقاط الترقية لـ {member.mention} إلى {amount}.")


@bot.command(name="resetupgrade")
async def reset_upgrade(ctx: commands.Context, member: discord.Member):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    requirements = load_json(REQUIRE_FILE)
    requirements[str(member.id)] = 0
    save_json(REQUIRE_FILE, requirements)
    await ctx.send(f"✅ تم تصفير نقاط الترقية لـ {member.mention}.")


@bot.command(name="resetall")
async def reset_all(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    points = load_json(POINT_FILE)
    for user_id in points:
        points[user_id] = 0
    save_json(POINT_FILE, points)
    await ctx.send("✅ تم تصفير جميع نقاط التفاعل فقط.")


@bot.command(name="double")
async def double_on(ctx: commands.Context):
    if not is_admin(ctx.author):
        return
    save_json(DOUBLE_FILE, {"active": True})
    await ctx.send("🔥 تم تفعيل الدبل.")


@bot.command(name="doubleoff")
async def double_off(ctx: commands.Context):
    if not is_admin(ctx.author):
        return
    save_json(DOUBLE_FILE, {"active": False})
    await ctx.send("❄️ تم إيقاف الدبل.")


# =========================
# WARNINGS
# =========================

DURATION_RE = re.compile(
    r"(?P<number>\d+)\s*(?P<unit>دقيقة|دقائق|د|ساعة|ساعه|ساعات|س|يوم|ايام|أيام|d|h|m)",
    re.IGNORECASE,
)


def parse_duration_and_reason(raw_text: str):
    match = DURATION_RE.search(raw_text)
    if not match:
        return None, raw_text.strip()

    number = int(match.group("number"))
    unit = match.group("unit").lower()

    if unit in {"دقيقة", "دقائق", "د", "m"}:
        delta = datetime.timedelta(minutes=number)
    elif unit in {"ساعة", "ساعه", "ساعات", "س", "h"}:
        delta = datetime.timedelta(hours=number)
    else:
        delta = datetime.timedelta(days=number)

    reason = (raw_text[: match.start()] + raw_text[match.end() :]).strip()
    return delta, reason


def format_duration(delta: datetime.timedelta):
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes:
        parts.append(f"{minutes} دقيقة")
    return " و ".join(parts) if parts else "أقل من دقيقة"


async def create_warning(
    guild: discord.Guild,
    target: discord.Member,
    moderator: discord.Member,
    reason: str,
    duration: datetime.timedelta,
    source_message_id: int | None = None,
):
    warning_id = uuid.uuid4().hex[:8]
    created_at = now_utc()
    expires_at = created_at + duration

    warnings = load_json(WARNING_FILE)
    warnings.setdefault(str(target.id), []).append(
        {
            "id": warning_id,
            "user_id": target.id,
            "moderator_id": moderator.id,
            "reason": reason,
            "created_at": created_at.timestamp(),
            "expires_at": expires_at.timestamp(),
            "source_message_id": source_message_id,
        }
    )
    save_json(WARNING_FILE, warnings)

    log_channel = guild.get_channel(WARNING_LOG_CHANNEL) or bot.get_channel(WARNING_LOG_CHANNEL)
    embed = discord.Embed(
        title="إنذار إداري جديد",
        color=discord.Color.orange(),
        timestamp=created_at,
    )
    embed.add_field(name="العضو", value=target.mention, inline=True)
    embed.add_field(name="المسؤول", value=moderator.mention, inline=True)
    embed.add_field(name="المدة", value=format_duration(duration), inline=True)
    embed.add_field(name="ينتهي", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.set_footer(text=f"Warning ID: {warning_id}")

    if log_channel:
        await log_channel.send(content=target.mention, embed=embed)

    timeout_until = created_at + datetime.timedelta(days=WARNING_TIMEOUT_DAYS)
    try:
        await target.timeout(
            timeout_until,
            reason=f"إنذار إداري لمدة {format_duration(duration)} - {reason}",
        )
    except discord.Forbidden:
        if log_channel:
            await log_channel.send(f"⚠️ لم أستطع إعطاء تايم أوت لـ {target.mention} بسبب نقص صلاحيات البوت.")
    except discord.HTTPException:
        if log_channel:
            await log_channel.send(f"⚠️ تعذر تطبيق التايم أوت على {target.mention}.")

    return warning_id, expires_at


class WarningCreateModal(discord.ui.Modal, title="تسجيل إنذار"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)
    reason = discord.ui.TextInput(label="سبب الإنذار", style=discord.TextStyle.paragraph, required=True, max_length=300)
    duration = discord.ui.TextInput(label="مدة الإنذار", placeholder="مثال: 3 أيام أو 12 ساعة", required=True, max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        target = interaction.guild.get_member(member_id)
        if not target:
            await interaction.response.send_message("❌ لم أجد العضو داخل السيرفر.", ephemeral=True)
            return

        duration, _ = parse_duration_and_reason(self.duration.value.strip())
        if duration is None:
            await interaction.response.send_message("❌ اكتب مدة صحيحة مثل: 3 أيام، 12 ساعة، 30 دقيقة.", ephemeral=True)
            return

        warning_id, expires_at = await create_warning(
            interaction.guild,
            target,
            interaction.user,
            str(self.reason.value),
            duration,
        )
        await interaction.response.send_message(
            f"✅ تم تسجيل الإنذار `{warning_id}` لـ {target.mention}. ينتهي <t:{int(expires_at.timestamp())}:R>.",
            ephemeral=True,
        )


class WarningListModal(discord.ui.Modal, title="عرض إنذارات عضو"):
    user_id = discord.ui.TextInput(label="آيدي العضو", required=True, max_length=25)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        try:
            member_id = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        member = interaction.guild.get_member(member_id)
        warnings = load_json(WARNING_FILE).get(str(member_id), [])
        active_warnings = [w for w in warnings if w["expires_at"] > now_utc().timestamp()]

        title_name = member.display_name if member else str(member_id)
        embed = discord.Embed(title=f"إنذارات {title_name}", color=discord.Color.orange(), timestamp=now_utc())
        if not active_warnings:
            embed.description = "لا توجد إنذارات فعالة."
        else:
            embed.description = "\n".join(
                f"`{w['id']}` - {w['reason']} - ينتهي <t:{int(w['expires_at'])}:R>"
                for w in active_warnings[:10]
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class WarningRemoveModal(discord.ui.Modal, title="حذف إنذار"):
    warning_id = discord.ui.TextInput(label="رقم الإنذار", required=True, max_length=12)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        warning_id = self.warning_id.value.strip()
        warnings = load_json(WARNING_FILE)
        removed = False

        for uid, items in warnings.items():
            original_len = len(items)
            warnings[uid] = [item for item in items if item["id"] != warning_id]
            if len(warnings[uid]) != original_len:
                removed = True

        save_json(WARNING_FILE, warnings)
        await interaction.response.send_message(
            "✅ تم حذف الإنذار." if removed else "❌ لم أجد إنذار بهذا الرقم.",
            ephemeral=True,
        )


class WarningPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تسجيل إنذار", style=discord.ButtonStyle.danger, custom_id="warnings:create", row=0)
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningCreateModal())

    @discord.ui.button(label="عرض إنذارات", style=discord.ButtonStyle.secondary, custom_id="warnings:list", row=0)
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningListModal())

    @discord.ui.button(label="حذف إنذار", style=discord.ButtonStyle.secondary, custom_id="warnings:remove", row=0)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningRemoveModal())


@bot.command(name="لوحة_الانذارات", aliases=["لوحة_إنذارات", "لوحة_انذارات"])
async def warning_panel(ctx: commands.Context):
    if ctx.channel.id not in {WARNING_INPUT_CHANNEL, WARNING_LOG_CHANNEL}:
        return
    if not is_admin(ctx.author):
        return

    embed = discord.Embed(
        title="لوحة إدارة الإنذارات",
        description="سجل إنذار، اعرض إنذارات عضو، أو احذف إنذار من خلال الأزرار.",
        color=discord.Color.orange(),
    )
    await ctx.send(embed=embed, view=WarningPanel())


async def handle_warning_input(message: discord.Message):
    if message.channel.id != WARNING_INPUT_CHANNEL:
        return

    if message.content.startswith(tuple(bot.command_prefix)):
        return

    if not is_admin(message.author):
        await message.reply("❌ الإنذارات للأدمن فقط.", mention_author=False)
        return

    if not message.mentions:
        await message.reply("❌ منشن العضو ثم اكتب السبب والمدة. مثال: @user تأخير دوام 3 أيام", mention_author=False)
        return

    target = message.mentions[0]
    raw = message.content
    for mention in message.mentions:
        raw = raw.replace(mention.mention, "").replace(f"<@!{mention.id}>", "")

    duration, reason = parse_duration_and_reason(raw)
    if duration is None:
        await message.reply("❌ اكتب مدة الإنذار مثل: 3 أيام، 12 ساعة، 30 دقيقة.", mention_author=False)
        return

    if not reason:
        reason = "لم يتم تحديد سبب"

    warning_id, expires_at = await create_warning(
        message.guild,
        target,
        message.author,
        reason,
        duration,
        source_message_id=message.id,
    )

    await message.reply(f"✅ تم تسجيل الإنذار وإرساله. رقم الإنذار: `{warning_id}`", mention_author=False)


@bot.command(name="انذارات")
async def show_warnings(ctx: commands.Context, member: discord.Member | None = None):
    if ctx.channel.id not in {WARNING_LOG_CHANNEL, WARNING_INPUT_CHANNEL}:
        return
    if not is_admin(ctx.author):
        return

    member = member or ctx.author
    warnings = load_json(WARNING_FILE).get(str(member.id), [])
    active_warnings = [w for w in warnings if w["expires_at"] > now_utc().timestamp()]

    embed = discord.Embed(title=f"إنذارات {member.display_name}", color=discord.Color.orange(), timestamp=now_utc())
    if not active_warnings:
        embed.description = "لا توجد إنذارات فعالة."
    else:
        embed.description = "\n".join(
            f"`{w['id']}` - {w['reason']} - ينتهي <t:{int(w['expires_at'])}:R>"
            for w in active_warnings[:10]
        )

    await ctx.send(embed=embed)


@bot.command(name="حذف_انذار")
async def remove_warning(ctx: commands.Context, warning_id: str):
    if ctx.channel.id not in {WARNING_LOG_CHANNEL, WARNING_INPUT_CHANNEL}:
        return
    if not is_admin(ctx.author):
        return

    warnings = load_json(WARNING_FILE)
    removed = False

    for uid, items in warnings.items():
        original_len = len(items)
        warnings[uid] = [item for item in items if item["id"] != warning_id]
        if len(warnings[uid]) != original_len:
            removed = True

    save_json(WARNING_FILE, warnings)
    await ctx.send("✅ تم حذف الإنذار." if removed else "❌ لم أجد إنذار بهذا الرقم.")


# =========================
# READY / START
# =========================

@bot.event
async def on_ready():
    bot.add_view(LeaveView())
    bot.add_view(InteractionPanel())
    bot.add_view(WarningPanel())

    if not auto_reset_leaves.is_running():
        auto_reset_leaves.start()

    if not award_voice_points.is_running():
        award_voice_points.start()

    print(f"Logged in as {bot.user}")


keep_alive()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("DISCORD_TOKEN is missing")
