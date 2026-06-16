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
# BOT
# =========================

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# IDS
# =========================

POINT_CHANNEL = 1497204458680090779
INTERACTION_PANEL_CHANNEL = 1497642199859593388
KEYWORD_CHANNEL = 1497911384191668254
POINTS_ACTION_LOG_CHANNEL = 1516309944129818735
SPAM_LOG_CHANNEL = 1516295642824310824

LEAVE_CHANNEL = 1490070238270718013
LEAVE_LOG_CHANNEL = 1490820000477610036
LEAVE_ROLE = 1492607429249339502

WARNING_LOG_CHANNEL = 1479608600350429194
WARNING_INPUT_CHANNEL = 1512860383461773482

HACKED_PROTECTION_CHANNEL = 1514000444349878483
HACKED_LOG_CHANNEL = 1514388692549107874
ACTIVITY_WARNING_CHANNEL = 1480389401535189065

ACTIVITY_PUNISHMENT_ROLE = 1514136578883195001
EXEMPTED_ACTIVITY_ROLE = 1514389169089020125

POINT_ROLES = {
    1477492633847857252,
    1482194383515422752,
    1480443913557905499,
}

ADMIN_ROLES = {
    1478970736717598840,
    1495873706923393205,
    1490386915629989948,
    1478971845729583276,
}

PROTECTION_EXEMPT_ROLES = POINT_ROLES | ADMIN_ROLES | {EXEMPTED_ACTIVITY_ROLE}


# =========================
# SETTINGS
# =========================

TEXT_POINTS = 12
DOUBLE_TEXT_POINTS = 24
VOICE_POINTS_EVERY_10_MINUTES = 5
DOUBLE_VOICE_POINTS_EVERY_10_MINUTES = 10
TICKET_POINTS = 25
IMAGE_POINTS = 10
TEXT_POINTS_BLOCKED_CHANNELS = {POINT_CHANNEL, KEYWORD_CHANNEL}
SPAM_MESSAGE_LIMIT_PER_SECOND = 10

WARNING_TIMEOUT_DAYS = 7
PROTECTION_BAN_HOURS = 24

MAX_MONTHLY_LEAVE = 14
MIN_LEAVE_DAYS = 3
WITHDRAW_LIMIT_SECONDS = 24 * 60 * 60


# =========================
# FILES
# =========================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

POINT_FILE = DATA_DIR / "points.json"
REQUIRE_FILE = DATA_DIR / "requirements.json"
DOUBLE_FILE = DATA_DIR / "double.json"
LEAVE_FILE = DATA_DIR / "leaves.json"
LEAVE_BALANCE_FILE = DATA_DIR / "leave_balance.json"
WARNING_FILE = DATA_DIR / "warnings.json"
TEMPBANS_FILE = DATA_DIR / "tempbans.json"
TEXT_TOGGLE_FILE = DATA_DIR / "text_points_toggle.json"


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
    if member.bot:
        return False
    if has_any_role(member, {EXEMPTED_ACTIVITY_ROLE}):
        return False
    return has_any_role(member, POINT_ROLES)


def double_active() -> bool:
    return load_json(DOUBLE_FILE, {"active": False}).get("active", False)


def add_points(user_id: int, amount: int, guild: discord.Guild | None = None, include_requirements: bool = True):
    if guild:
        member = guild.get_member(user_id)
        if not member or not is_points_member(member):
            return 0, 0

    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)
    uid = str(user_id)

    points[uid] = points.get(uid, 0) + amount
    if include_requirements:
        requirements[uid] = requirements.get(uid, 0) + amount

    save_json(POINT_FILE, points)
    save_json(REQUIRE_FILE, requirements)
    return points[uid], requirements.get(uid, 0)


def change_points_value(file: Path, user_id: int, amount: int):
    data = load_json(file)
    uid = str(user_id)
    data[uid] = max(0, data.get(uid, 0) + amount)
    save_json(file, data)
    return data[uid]


def set_points_value(file: Path, user_id: int, value: int):
    data = load_json(file)
    data[str(user_id)] = max(0, value)
    save_json(file, data)
    return data[str(user_id)]


async def send_points_action_log(
    guild: discord.Guild,
    moderator: discord.Member,
    target: discord.Member | None,
    action: str,
    amount: int | None = None,
    new_value: int | None = None,
):
    channel = guild.get_channel(POINTS_ACTION_LOG_CHANNEL) or bot.get_channel(POINTS_ACTION_LOG_CHANNEL)
    if not channel:
        return

    embed = discord.Embed(title="سجل إدارة النقاط", color=discord.Color.dark_teal(), timestamp=now_utc())
    embed.add_field(name="الإجراء", value=action, inline=True)
    embed.add_field(name="المسؤول", value=moderator.mention, inline=True)
    if target:
        embed.add_field(name="العضو", value=target.mention, inline=True)
    if amount is not None:
        embed.add_field(name="القيمة", value=f"`{amount}`", inline=True)
    if new_value is not None:
        embed.add_field(name="الرصيد بعد العملية", value=f"`{new_value}`", inline=True)

    await channel.send(embed=embed)


def get_points(user_id: int):
    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)
    uid = str(user_id)
    return points.get(uid, 0), requirements.get(uid, 0)


def parse_member_id(value: str) -> int | None:
    match = re.search(r"\d{15,25}", value)
    return int(match.group(0)) if match else None


# =========================
# LEAVES
# =========================

def reset_leave_balance_if_needed(user_id: int | str):
    balances = load_json(LEAVE_BALANCE_FILE)
    uid = str(user_id)
    current_time = now_utc()

    if uid not in balances:
        balances[uid] = {"remaining": MAX_MONTHLY_LEAVE, "last_reset": current_time.timestamp()}
        save_json(LEAVE_BALANCE_FILE, balances)
        return balances[uid]

    last_reset = datetime.datetime.fromtimestamp(balances[uid]["last_reset"], tz=datetime.timezone.utc)
    if (current_time - last_reset).days >= 30:
        balances[uid]["remaining"] = MAX_MONTHLY_LEAVE
        balances[uid]["last_reset"] = current_time.timestamp()
        save_json(LEAVE_BALANCE_FILE, balances)

    return balances[uid]


@tasks.loop(hours=12)
async def auto_reset_leaves():
    balances = load_json(LEAVE_BALANCE_FILE)
    changed = False

    for uid, data in list(balances.items()):
        last_reset = datetime.datetime.fromtimestamp(data["last_reset"], tz=datetime.timezone.utc)
        if (now_utc() - last_reset).days < 30:
            continue

        balances[uid]["remaining"] = MAX_MONTHLY_LEAVE
        balances[uid]["last_reset"] = now_utc().timestamp()
        changed = True

        try:
            user = await bot.fetch_user(int(uid))
            await user.send("✅ تم تجديد رصيد إجازاتك الشهري إلى 14 يوم.")
        except discord.HTTPException:
            pass

    if changed:
        save_json(LEAVE_BALANCE_FILE, balances)


class LeaveModal(discord.ui.Modal, title="طلب إجازة"):
    reason = discord.ui.TextInput(label="سبب الإجازة", style=discord.TextStyle.paragraph, required=True, max_length=250)
    days = discord.ui.TextInput(label="عدد الأيام", placeholder="مثال: 3", required=True, max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        if has_any_role(interaction.user, {ACTIVITY_PUNISHMENT_ROLE}):
            await interaction.response.send_message("❌ لا يمكنك طلب إجازة ولديك عقوبة عدم تفاعل نشطة.", ephemeral=True)
            return

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

        balance = reset_leave_balance_if_needed(uid)
        if days > balance["remaining"]:
            await interaction.response.send_message(f"❌ رصيدك المتبقي {balance['remaining']} يوم فقط.", ephemeral=True)
            return

        balances = load_json(LEAVE_BALANCE_FILE)
        balances[uid]["remaining"] -= days
        save_json(LEAVE_BALANCE_FILE, balances)

        leaves[uid] = {"reason": str(self.reason.value), "days": days, "created_at": now_utc().timestamp()}
        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)
        if role:
            await interaction.user.add_roles(role, reason="طلب إجازة إدارية")

        log_channel = bot.get_channel(LEAVE_LOG_CHANNEL)
        if log_channel:
            embed = discord.Embed(title="طلب إجازة جديد", color=discord.Color.green(), timestamp=now_utc())
            embed.add_field(name="الإداري", value=interaction.user.mention, inline=True)
            embed.add_field(name="المدة", value=f"{days} يوم", inline=True)
            embed.add_field(name="المتبقي", value=f"{balances[uid]['remaining']} يوم", inline=True)
            embed.add_field(name="السبب", value=str(self.reason.value), inline=False)
            await log_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ تم تسجيل الإجازة. رصيدك المتبقي: {balances[uid]['remaining']} يوم.", ephemeral=True)


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

        if now_utc().timestamp() - leaves[uid]["created_at"] >= WITHDRAW_LIMIT_SECONDS:
            await interaction.response.send_message("❌ انتهت مهلة سحب الإجازة وهي 24 ساعة.", ephemeral=True)
            return

        days = leaves[uid]["days"]
        reset_leave_balance_if_needed(uid)
        balances = load_json(LEAVE_BALANCE_FILE)
        balances[uid]["remaining"] = min(MAX_MONTHLY_LEAVE, balances[uid]["remaining"] + days)
        save_json(LEAVE_BALANCE_FILE, balances)

        del leaves[uid]
        save_json(LEAVE_FILE, leaves)

        role = interaction.guild.get_role(LEAVE_ROLE)
        if role:
            await interaction.user.remove_roles(role, reason="سحب إجازة إدارية")

        await interaction.response.send_message(f"✅ تم سحب الإجازة. رصيدك الحالي: {balances[uid]['remaining']} يوم.", ephemeral=True)


@bot.command(name="اجازه", aliases=["اجازة", "إجازة", "إجازه"])
async def leave_panel(ctx: commands.Context):
    if ctx.channel.id != LEAVE_CHANNEL:
        return

    embed = discord.Embed(
        title="لوحة الإجازات",
        description="رصيد الإداري الشهري 14 يوم. أقل إجازة 3 أيام. سحب الإجازة متاح خلال أول 24 ساعة.",
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=LeaveView())


# =========================
# POINTS PANEL
# =========================

class AddPointsModal(discord.ui.Modal, title="زيادة نقاط التفاعل"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)
    amount = discord.ui.TextInput(label="عدد النقاط", required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        try:
            amount = int(self.amount.value.strip())
        except ValueError:
            amount = None

        if not member_id or amount is None:
            await interaction.response.send_message("❌ البيانات غير صحيحة.", ephemeral=True)
            return

        member = interaction.guild.get_member(member_id)
        if not member or not is_points_member(member):
            await interaction.response.send_message("❌ العضو لا يملك إحدى رتب التفاعل المعتمدة.", ephemeral=True)
            return

        total = change_points_value(POINT_FILE, member.id, amount)
        await send_points_action_log(interaction.guild, interaction.user, member, "زيادة نقاط التفاعل", amount, total)
        await interaction.response.send_message(f"✅ تمت إضافة `{amount}` نقطة تفاعل إلى {member.mention}. الرصيد الآن: `{total}`", ephemeral=True)


class ChangeValueModal(discord.ui.Modal):
    def __init__(self, title: str, file: Path, action_name: str, multiplier: int):
        super().__init__(title=title)
        self.file = file
        self.action_name = action_name
        self.multiplier = multiplier
        self.user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)
        self.amount = discord.ui.TextInput(label="عدد النقاط", required=True, max_length=8)
        self.add_item(self.user_id)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        try:
            amount = int(self.amount.value.strip())
        except ValueError:
            amount = None

        if not member_id or amount is None or amount <= 0:
            await interaction.response.send_message("❌ البيانات غير صحيحة.", ephemeral=True)
            return

        member = interaction.guild.get_member(member_id)
        if not member:
            await interaction.response.send_message("❌ لم أجد العضو داخل السيرفر.", ephemeral=True)
            return

        signed_amount = amount * self.multiplier
        new_value = change_points_value(self.file, member.id, signed_amount)
        await send_points_action_log(interaction.guild, interaction.user, member, self.action_name, signed_amount, new_value)
        await interaction.response.send_message(
            f"✅ تم تنفيذ: **{self.action_name}** لـ {member.mention}. الرصيد الآن: `{new_value}`",
            ephemeral=True,
        )


class ResetPointsModal(discord.ui.Modal, title="تصفير نقاط عضو"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        if not member_id:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        points = load_json(POINT_FILE)
        points[str(member_id)] = 0
        save_json(POINT_FILE, points)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await send_points_action_log(interaction.guild, interaction.user, member, "تصفير نقاط التفاعل", 0, 0)
        await interaction.response.send_message(f"✅ تم تصفير نقاط التفاعل لـ {mention}.", ephemeral=True)


class SetRequirementModal(discord.ui.Modal, title="تعديل نقاط الترقية"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)
    amount = discord.ui.TextInput(label="القيمة الجديدة", required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        try:
            amount = int(self.amount.value.strip())
        except ValueError:
            amount = None

        if not member_id or amount is None:
            await interaction.response.send_message("❌ البيانات غير صحيحة.", ephemeral=True)
            return

        requirements = load_json(REQUIRE_FILE)
        requirements[str(member_id)] = amount
        save_json(REQUIRE_FILE, requirements)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await send_points_action_log(interaction.guild, interaction.user, member, "تعديل نقاط الترقية", amount, amount)
        await interaction.response.send_message(f"✅ تم تعديل نقاط الترقية لـ {mention} إلى `{amount}`.", ephemeral=True)


class ResetRequirementModal(discord.ui.Modal, title="تصفير نقاط الترقية"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        if not member_id:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        requirements = load_json(REQUIRE_FILE)
        requirements[str(member_id)] = 0
        save_json(REQUIRE_FILE, requirements)

        member = interaction.guild.get_member(member_id)
        mention = member.mention if member else f"`{member_id}`"
        await send_points_action_log(interaction.guild, interaction.user, member, "تصفير نقاط الترقية", 0, 0)
        await interaction.response.send_message(f"✅ تم تصفير نقاط الترقية لـ {mention}.", ephemeral=True)


def build_top_embed(guild: discord.Guild):
    points = load_json(POINT_FILE)
    embed = discord.Embed(title="أعلى المتفاعلين", color=discord.Color.gold(), timestamp=now_utc())

    valid_points = []
    for uid, value in points.items():
        member = guild.get_member(int(uid))
        if member and is_points_member(member):
            valid_points.append((uid, value))

    if not valid_points:
        embed.description = "لا توجد نقاط حاليًا."
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for index, (uid, pts) in enumerate(sorted(valid_points, key=lambda item: item[1], reverse=True)[:10], start=1):
        member = guild.get_member(int(uid))
        prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
        lines.append(f"{prefix} {member.mention} - `{pts}` نقطة")

    embed.description = "\n".join(lines)
    return embed


class InteractionPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="نقاطي", style=discord.ButtonStyle.primary, custom_id="points:mine", row=0)
    async def my_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        total, req = get_points(interaction.user.id)
        embed = discord.Embed(title="نقاط التفاعل والترقية", color=discord.Color.blue(), timestamp=now_utc())
        embed.add_field(name="العضو", value=interaction.user.mention, inline=False)
        embed.add_field(name="التفاعل", value=f"`{total}`", inline=True)
        embed.add_field(name="الترقية", value=f"`{req}`", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="التوب", style=discord.ButtonStyle.success, custom_id="points:top", row=0)
    async def top_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=build_top_embed(interaction.guild), ephemeral=False)

    @discord.ui.button(label="زيادة تفاعل", style=discord.ButtonStyle.secondary, custom_id="points:add_interaction", row=1)
    async def add_interaction_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("زيادة نقاط التفاعل", POINT_FILE, "زيادة نقاط التفاعل", 1))

    @discord.ui.button(label="خصم تفاعل", style=discord.ButtonStyle.danger, custom_id="points:remove_interaction", row=1)
    async def remove_interaction_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("خصم نقاط التفاعل", POINT_FILE, "خصم نقاط التفاعل", -1))

    @discord.ui.button(label="تصفير تفاعل شخص", style=discord.ButtonStyle.danger, custom_id="points:reset_interaction", row=1)
    async def reset_interaction_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetPointsModal())

    @discord.ui.button(label="زيادة ترقية", style=discord.ButtonStyle.secondary, custom_id="points:add_upgrade", row=2)
    async def add_upgrade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("زيادة نقاط الترقية", REQUIRE_FILE, "زيادة نقاط الترقية", 1))

    @discord.ui.button(label="خصم ترقية", style=discord.ButtonStyle.danger, custom_id="points:remove_upgrade", row=2)
    async def remove_upgrade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("خصم نقاط الترقية", REQUIRE_FILE, "خصم نقاط الترقية", -1))

    @discord.ui.button(label="تصفير ترقية شخص", style=discord.ButtonStyle.danger, custom_id="points:reset_upgrade", row=2)
    async def reset_upgrade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetRequirementModal())

    @discord.ui.button(label="تصفير تفاعل الكل", style=discord.ButtonStyle.danger, custom_id="points:reset_all", row=3)
    async def reset_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        points = load_json(POINT_FILE)
        for uid in list(points):
            points[uid] = 0
        save_json(POINT_FILE, points)
        await send_points_action_log(interaction.guild, interaction.user, None, "تصفير تفاعل جميع الأعضاء", 0, 0)
        await interaction.response.send_message("✅ تم تصفير نقاط التفاعل لجميع الأعضاء.", ephemeral=True)

    @discord.ui.button(label="الدبل", style=discord.ButtonStyle.secondary, custom_id="points:double", row=3)
    async def toggle_double(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        data = load_json(DOUBLE_FILE, {"active": False})
        data["active"] = not data.get("active", False)
        save_json(DOUBLE_FILE, data)
        await interaction.response.send_message(f"✅ الدبل الآن: {'مفعل' if data['active'] else 'مغلق'}.", ephemeral=True)


@bot.command(name="لوحة")
async def interaction_panel(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return

    embed = discord.Embed(
        title="لوحة إدارة التفاعل",
        description=(
            "النقاط محسوبة فقط للرتب المعتمدة:\n"
            "`1477492633847857252` - `1482194383515422752` - `1480443913557905499`"
        ),
        color=discord.Color.dark_teal(),
    )
    await ctx.send(embed=embed, view=InteractionPanel())


# =========================
# POINTS EVENTS
# =========================

voice_times: dict[str, datetime.datetime] = {}
spam_tracker: dict[int, list[float]] = {}


def should_award_text_points(user_id: int) -> bool:
    toggles = load_json(TEXT_TOGGLE_FILE)
    uid = str(user_id)
    should_count = toggles.get(uid, True)
    toggles[uid] = not should_count
    save_json(TEXT_TOGGLE_FILE, toggles)
    return should_count


async def check_spam(message: discord.Message) -> bool:
    current = now_utc().timestamp()
    timestamps = spam_tracker.setdefault(message.author.id, [])
    timestamps = [item for item in timestamps if current - item < 1]
    timestamps.append(current)
    spam_tracker[message.author.id] = timestamps

    if len(timestamps) <= SPAM_MESSAGE_LIMIT_PER_SECOND:
        return False

    channel = message.guild.get_channel(SPAM_LOG_CHANNEL) or bot.get_channel(SPAM_LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title="تنبيه سبام نقاط", color=discord.Color.red(), timestamp=now_utc())
        embed.add_field(name="العضو", value=message.author.mention, inline=True)
        embed.add_field(name="عدد الرسائل خلال ثانية", value=f"`{len(timestamps)}`", inline=True)
        embed.add_field(name="الروم", value=message.channel.mention, inline=True)
        embed.set_footer(text="تم إيقاف احتساب هذه الرسالة بسبب الاشتباه بالسبام.")
        await channel.send(embed=embed)

    return True


class RejectImageModal(discord.ui.Modal, title="سبب رفض الصورة"):
    reason = discord.ui.TextInput(label="سبب الرفض", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, target_id: int):
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction):
        target = interaction.guild.get_member(self.target_id)
        if target:
            try:
                await target.send(f"❌ تم رفض صورتك.\n**السبب:** {self.reason.value}")
            except discord.HTTPException:
                pass

        await interaction.response.send_message("✅ تم رفض الصورة وإرسال السبب للعضو في الخاص.", ephemeral=True)


class ImageReviewView(discord.ui.View):
    def __init__(self, target_id: int):
        super().__init__(timeout=None)
        self.target_id = target_id

    @discord.ui.button(label="قبول", style=discord.ButtonStyle.success, custom_id="image_review:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        target = interaction.guild.get_member(self.target_id)
        if not target or not is_points_member(target):
            await interaction.response.send_message("❌ العضو غير موجود أو لا يملك رتبة التفاعل.", ephemeral=True)
            return

        total = change_points_value(POINT_FILE, target.id, IMAGE_POINTS)
        await send_points_action_log(interaction.guild, interaction.user, target, "قبول صورة ومنح نقاط", IMAGE_POINTS, total)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ تم منح {target.mention} `{IMAGE_POINTS}` نقاط بعد قبول الصورة.",
            view=self,
        )

    @discord.ui.button(label="رفض", style=discord.ButtonStyle.danger, custom_id="image_review:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        await interaction.response.send_modal(RejectImageModal(self.target_id))


async def handle_message_points(message: discord.Message):
    if not isinstance(message.author, discord.Member) or not is_points_member(message.author):
        return

    has_image = any(
        attachment.content_type and attachment.content_type.startswith("image/")
        for attachment in message.attachments
    )

    if message.channel.id == KEYWORD_CHANNEL and has_image:
        embed = discord.Embed(
            title="مراجعة صورة للتفاعل",
            description=f"تم استلام صورة من {message.author.mention}. اختر قبول لمنحه `{IMAGE_POINTS}` نقاط أو رفض لإرسال السبب له بالخاص.",
            color=discord.Color.blurple(),
            timestamp=now_utc(),
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        await message.reply(embed=embed, view=ImageReviewView(message.author.id), mention_author=False)
        return

    if message.channel.id in TEXT_POINTS_BLOCKED_CHANNELS:
        return

    if await check_spam(message):
        return

    if not should_award_text_points(message.author.id):
        return

    text_amount = DOUBLE_TEXT_POINTS if double_active() else TEXT_POINTS
    add_points(message.author.id, text_amount, message.guild)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not is_points_member(member):
        return

    uid = str(member.id)
    if before.channel is None and after.channel is not None:
        voice_times[uid] = now_utc()
    elif before.channel is not None and after.channel is None:
        voice_times.pop(uid, None)


@tasks.loop(minutes=5)
async def award_voice_points():
    current_time = now_utc()
    amount = DOUBLE_VOICE_POINTS_EVERY_10_MINUTES if double_active() else VOICE_POINTS_EVERY_10_MINUTES

    for guild in bot.guilds:
        for channel in guild.voice_channels:
            for member in channel.members:
                if not is_points_member(member):
                    continue

                uid = str(member.id)
                if uid not in voice_times:
                    voice_times[uid] = current_time
                    continue

                elapsed = (current_time - voice_times[uid]).total_seconds() / 60
                count = int(elapsed // 10)
                if count <= 0:
                    continue

                add_points(member.id, amount * count, guild)
                voice_times[uid] += datetime.timedelta(minutes=10 * count)


# =========================
# POINT COMMANDS
# =========================

@bot.command(name="تفاعل")
async def show_points(ctx: commands.Context):
    total, req = get_points(ctx.author.id)
    embed = discord.Embed(title="نقاط التفاعل", color=discord.Color.blue(), timestamp=now_utc())
    embed.add_field(name="العضو", value=ctx.author.mention, inline=False)
    embed.add_field(name="نقاط التفاعل", value=f"`{total}`", inline=True)
    embed.add_field(name="نقاط الترقية", value=f"`{req}`", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="top")
async def top_points_command(ctx: commands.Context):
    if ctx.channel.id == INTERACTION_PANEL_CHANNEL:
        await ctx.send(embed=build_top_embed(ctx.guild))


@bot.command(name="اضف")
async def add_points_command(ctx: commands.Context, member: discord.Member, amount: int):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    total = change_points_value(POINT_FILE, member.id, amount)
    await send_points_action_log(ctx.guild, ctx.author, member, "زيادة نقاط التفاعل", amount, total)
    await ctx.send(f"✅ تم إضافة `{amount}` نقطة تفاعل إلى {member.mention}. الرصيد الآن: `{total}`")


@bot.command(name="تصفير")
async def reset_points_command(ctx: commands.Context, member: discord.Member):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    points = load_json(POINT_FILE)
    points[str(member.id)] = 0
    save_json(POINT_FILE, points)
    await send_points_action_log(ctx.guild, ctx.author, member, "تصفير نقاط التفاعل", 0, 0)
    await ctx.send(f"✅ تم تصفير نقاط التفاعل لـ {member.mention}.")


@bot.command(name="setreq")
async def set_requirement_command(ctx: commands.Context, member: discord.Member, amount: int):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    requirements = load_json(REQUIRE_FILE)
    requirements[str(member.id)] = amount
    save_json(REQUIRE_FILE, requirements)
    await send_points_action_log(ctx.guild, ctx.author, member, "تعديل نقاط الترقية", amount, amount)
    await ctx.send(f"✅ تم تعديل نقاط الترقية لـ {member.mention} إلى `{amount}`.")


@bot.command(name="resetupgrade")
async def reset_upgrade_command(ctx: commands.Context, member: discord.Member):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    requirements = load_json(REQUIRE_FILE)
    requirements[str(member.id)] = 0
    save_json(REQUIRE_FILE, requirements)
    await send_points_action_log(ctx.guild, ctx.author, member, "تصفير نقاط الترقية", 0, 0)
    await ctx.send(f"✅ تم تصفير نقاط الترقية لـ {member.mention}.")


@bot.command(name="resetall")
async def reset_all_command(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    points = load_json(POINT_FILE)
    for uid in list(points):
        points[uid] = 0
    save_json(POINT_FILE, points)
    await send_points_action_log(ctx.guild, ctx.author, None, "تصفير تفاعل جميع الأعضاء", 0, 0)
    await ctx.send("✅ تم تصفير جميع نقاط التفاعل.")


@bot.command(name="double")
async def double_on(ctx: commands.Context):
    if is_admin(ctx.author):
        save_json(DOUBLE_FILE, {"active": True})
        await ctx.send("🔥 تم تفعيل الدبل.")


@bot.command(name="doubleoff")
async def double_off(ctx: commands.Context):
    if is_admin(ctx.author):
        save_json(DOUBLE_FILE, {"active": False})
        await ctx.send("❄️ تم إيقاف الدبل.")


# =========================
# WARNINGS
# =========================

DURATION_RE = re.compile(
    r"(?P<number>\d+)\s*(?P<unit>دقيقة|دقائق|د|ساعة|ساعه|ساعات|س|يوم|ايام|أيام|d|h|m)",
    re.IGNORECASE,
)


def parse_duration(text: str):
    match = DURATION_RE.search(text)
    if not match:
        return None, text.strip()

    number = int(match.group("number"))
    unit = match.group("unit").lower()
    if unit in {"دقيقة", "دقائق", "د", "m"}:
        delta = datetime.timedelta(minutes=number)
    elif unit in {"ساعة", "ساعه", "ساعات", "س", "h"}:
        delta = datetime.timedelta(hours=number)
    else:
        delta = datetime.timedelta(days=number)

    reason = (text[: match.start()] + text[match.end() :]).strip()
    return delta, reason


def format_duration(delta: datetime.timedelta):
    total = int(delta.total_seconds())
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes:
        parts.append(f"{minutes} دقيقة")
    return " و ".join(parts) if parts else "أقل من دقيقة"


async def create_warning(guild: discord.Guild, target: discord.Member, moderator: discord.Member, reason: str, duration: datetime.timedelta, source_message_id: int | None = None):
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
    timeout_until = created_at + datetime.timedelta(days=WARNING_TIMEOUT_DAYS)

    embed = discord.Embed(title="إنذار إداري جديد", color=discord.Color.red(), timestamp=created_at)
    embed.add_field(name="العضو", value=target.mention, inline=True)
    embed.add_field(name="المسؤول", value=moderator.mention, inline=True)
    embed.add_field(name="مدة الإنذار", value=format_duration(duration), inline=True)
    embed.add_field(name="ينتهي الإنذار", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
    embed.add_field(name="التايم أوت", value=f"{WARNING_TIMEOUT_DAYS} أيام", inline=True)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.set_footer(text=f"Warning ID: {warning_id}")

    if log_channel:
        await log_channel.send(content=target.mention, embed=embed)

    try:
        await target.timeout(timeout_until, reason=f"إنذار إداري: {reason}")
    except discord.Forbidden:
        if log_channel:
            await log_channel.send(f"⚠️ لم أستطع إعطاء تايم أوت لـ {target.mention}. تأكد من صلاحية Moderate Members وترتيب رتبة البوت.")
    except discord.HTTPException:
        if log_channel:
            await log_channel.send(f"⚠️ تعذر تطبيق التايم أوت على {target.mention}.")

    return warning_id, expires_at


class WarningCreateModal(discord.ui.Modal, title="تسجيل إنذار"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)
    reason = discord.ui.TextInput(label="سبب الإنذار", style=discord.TextStyle.paragraph, required=True, max_length=300)
    duration = discord.ui.TextInput(label="مدة الإنذار", placeholder="مثال: 3 أيام أو 12 ساعة", required=True, max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        target = interaction.guild.get_member(member_id) if member_id else None
        duration, _ = parse_duration(self.duration.value)

        if not target or duration is None:
            await interaction.response.send_message("❌ تأكد من العضو والمدة.", ephemeral=True)
            return

        warning_id, expires_at = await create_warning(interaction.guild, target, interaction.user, str(self.reason.value), duration)
        await interaction.response.send_message(f"✅ تم تسجيل الإنذار `{warning_id}` لـ {target.mention}. ينتهي <t:{int(expires_at.timestamp())}:R>.", ephemeral=True)


class WarningListModal(discord.ui.Modal, title="عرض إنذارات عضو"):
    user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)

    async def on_submit(self, interaction: discord.Interaction):
        member_id = parse_member_id(self.user_id.value)
        if not member_id:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        member = interaction.guild.get_member(member_id)
        warnings = load_json(WARNING_FILE).get(str(member_id), [])
        active = [w for w in warnings if w["expires_at"] > now_utc().timestamp()]
        embed = discord.Embed(title=f"إنذارات {member.display_name if member else member_id}", color=discord.Color.orange(), timestamp=now_utc())
        embed.description = "لا توجد إنذارات فعالة." if not active else "\n".join(
            f"`{w['id']}` - {w['reason']} - ينتهي <t:{int(w['expires_at'])}:R>"
            for w in active[:10]
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WarningRemoveModal(discord.ui.Modal, title="حذف إنذار"):
    warning_id = discord.ui.TextInput(label="رقم الإنذار", required=True, max_length=12)

    async def on_submit(self, interaction: discord.Interaction):
        warning_id = self.warning_id.value.strip()
        warnings = load_json(WARNING_FILE)
        removed = False

        for uid, items in list(warnings.items()):
            before = len(items)
            warnings[uid] = [item for item in items if item["id"] != warning_id]
            removed = removed or len(warnings[uid]) != before

        save_json(WARNING_FILE, warnings)
        await interaction.response.send_message("✅ تم حذف الإنذار." if removed else "❌ لم أجد إنذار بهذا الرقم.", ephemeral=True)


class WarningPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تسجيل إنذار", style=discord.ButtonStyle.danger, custom_id="warning:create")
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningCreateModal())

    @discord.ui.button(label="عرض إنذارات", style=discord.ButtonStyle.secondary, custom_id="warning:list")
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningListModal())

    @discord.ui.button(label="حذف إنذار", style=discord.ButtonStyle.secondary, custom_id="warning:remove")
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarningRemoveModal())


@bot.command(name="لوحة_الانذارات", aliases=["لوحة_إنذارات", "لوحة_انذارات"])
async def warning_panel(ctx: commands.Context):
    if ctx.channel.id not in {WARNING_INPUT_CHANNEL, WARNING_LOG_CHANNEL} or not is_admin(ctx.author):
        return

    embed = discord.Embed(title="لوحة إدارة الإنذارات", description="تسجيل إنذار، عرض إنذارات عضو، أو حذف إنذار.", color=discord.Color.orange())
    await ctx.send(embed=embed, view=WarningPanel())


async def handle_warning_input(message: discord.Message):
    if message.channel.id != WARNING_INPUT_CHANNEL or message.content.startswith("!"):
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

    duration, reason = parse_duration(raw)
    if duration is None:
        await message.reply("❌ اكتب مدة صحيحة مثل: 3 أيام، 12 ساعة، 30 دقيقة.", mention_author=False)
        return

    warning_id, _ = await create_warning(message.guild, target, message.author, reason or "لم يتم تحديد سبب", duration, message.id)
    await message.reply(f"✅ تم تسجيل الإنذار وإرسال اللوق. رقم الإنذار: `{warning_id}`", mention_author=False)


@bot.command(name="انذارات")
async def show_warnings(ctx: commands.Context, member: discord.Member | None = None):
    if ctx.channel.id not in {WARNING_INPUT_CHANNEL, WARNING_LOG_CHANNEL} or not is_admin(ctx.author):
        return
    member = member or ctx.author
    warnings = load_json(WARNING_FILE).get(str(member.id), [])
    active = [w for w in warnings if w["expires_at"] > now_utc().timestamp()]
    embed = discord.Embed(title=f"إنذارات {member.display_name}", color=discord.Color.orange(), timestamp=now_utc())
    embed.description = "لا توجد إنذارات فعالة." if not active else "\n".join(
        f"`{w['id']}` - {w['reason']} - ينتهي <t:{int(w['expires_at'])}:R>"
        for w in active[:10]
    )
    await ctx.send(embed=embed)


@bot.command(name="حذف_انذار")
async def remove_warning_command(ctx: commands.Context, warning_id: str):
    if ctx.channel.id not in {WARNING_INPUT_CHANNEL, WARNING_LOG_CHANNEL} or not is_admin(ctx.author):
        return
    warnings = load_json(WARNING_FILE)
    removed = False
    for uid, items in list(warnings.items()):
        before = len(items)
        warnings[uid] = [item for item in items if item["id"] != warning_id]
        removed = removed or len(warnings[uid]) != before
    save_json(WARNING_FILE, warnings)
    await ctx.send("✅ تم حذف الإنذار." if removed else "❌ لم أجد إنذار بهذا الرقم.")


# =========================
# PROTECTION
# =========================

async def handle_hacked_protection(message: discord.Message):
    if message.channel.id != HACKED_PROTECTION_CHANNEL:
        return False
    if not isinstance(message.author, discord.Member) or has_any_role(message.author, PROTECTION_EXEMPT_ROLES):
        return False

    try:
        await message.delete()
    except discord.HTTPException:
        pass

    log_channel = message.guild.get_channel(HACKED_LOG_CHANNEL)
    if log_channel:
        embed = discord.Embed(title="حماية الروم المحمي", color=discord.Color.red(), timestamp=now_utc())
        embed.add_field(name="العضو", value=message.author.mention, inline=True)
        embed.add_field(name="الإجراء", value=f"حظر مؤقت {PROTECTION_BAN_HOURS} ساعة", inline=True)
        embed.add_field(name="الروم", value=message.channel.mention, inline=True)
        embed.add_field(name="المحتوى", value=message.content[:900] or "مرفق/صورة", inline=False)
        await log_channel.send(embed=embed)

    try:
        await message.author.send("تم حظرك مؤقتًا لمدة 24 ساعة بسبب الإرسال في روم محمي.")
    except discord.HTTPException:
        pass

    try:
        await message.guild.ban(message.author, reason="إرسال في روم محمي", delete_message_days=1)
        tempbans = load_json(TEMPBANS_FILE)
        tempbans[str(message.author.id)] = {
            "guild_id": message.guild.id,
            "unban_at": (now_utc() + datetime.timedelta(hours=PROTECTION_BAN_HOURS)).timestamp(),
        }
        save_json(TEMPBANS_FILE, tempbans)
    except discord.HTTPException:
        if log_channel:
            await log_channel.send(f"⚠️ لم أستطع حظر {message.author.mention}. تأكد من صلاحيات البوت.")

    return True


@tasks.loop(minutes=1)
async def check_tempbans():
    tempbans = load_json(TEMPBANS_FILE)
    if not tempbans:
        return

    current = now_utc().timestamp()
    removed = []
    for uid, data in list(tempbans.items()):
        if current < data["unban_at"]:
            continue

        guild = bot.get_guild(data["guild_id"])
        if not guild:
            continue

        try:
            user = await bot.fetch_user(int(uid))
            await guild.unban(user, reason="انتهاء الحظر المؤقت")
            removed.append(uid)
        except discord.HTTPException:
            pass

    for uid in removed:
        tempbans.pop(uid, None)
    if removed:
        save_json(TEMPBANS_FILE, tempbans)


# =========================
# EVENTS
# =========================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    protected = await handle_hacked_protection(message)
    if protected:
        return

    await handle_warning_input(message)
    await handle_message_points(message)
    await bot.process_commands(message)


@bot.event
async def on_ready():
    bot.add_view(LeaveView())
    bot.add_view(InteractionPanel())
    bot.add_view(WarningPanel())

    if not auto_reset_leaves.is_running():
        auto_reset_leaves.start()
    if not award_voice_points.is_running():
        award_voice_points.start()
    if not check_tempbans.is_running():
        check_tempbans.start()

    print(f"Logged in as {bot.user}")


# =========================
# START
# =========================

keep_alive()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("DISCORD_TOKEN is missing")
