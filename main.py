import datetime
import json
import os
import re
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
    return "Points and promotion bot is running"


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
PROMOTION_REQUEST_CHANNEL = 1497203612432990259

POINTS_ACTION_LOG_CHANNEL = 1516309944129818735
SPAM_LOG_CHANNEL = 1516295642824310824

POINT_ROLES = {
    1482194383515422752,
    1480443913557905499,
}

IMAGE_REVIEW_ROLES = {
    1477492633847857252,
}

ADMIN_ROLES = {
    1478970736717598840,
    1495873706923393205,
    1490386915629989948,
    1478971845729583276,
}

PROMOTION_REVIEW_ROLES = {
    1478971845729583276,
    1490386915629989948,
    1505984803839676466,
}

ADMIN_RANK_ORDER = [
    1485560413146841210,
    1485549583861022802,
    1480649204593332324,
    1485551861334540378,
    1488591572042780725,
    1480818082426392637,
    1480390711651336244,
    1480391201227280535,
]


# =========================
# SETTINGS
# =========================

TEXT_POINTS = 12
DOUBLE_TEXT_POINTS = 24
VOICE_POINTS_EVERY_10_MINUTES = 5
DOUBLE_VOICE_POINTS_EVERY_10_MINUTES = 10
IMAGE_POINTS = 10

TEXT_POINTS_BLOCKED_CHANNELS = {POINT_CHANNEL, KEYWORD_CHANNEL}
SPAM_MESSAGE_LIMIT_PER_SECOND = 10


# =========================
# FILES
# =========================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

POINT_FILE = DATA_DIR / "points.json"
REQUIRE_FILE = DATA_DIR / "requirements.json"
DOUBLE_FILE = DATA_DIR / "double.json"
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
    return not member.bot and has_any_role(member, POINT_ROLES)


def can_review_images(member: discord.Member) -> bool:
    return is_admin(member) or has_any_role(member, IMAGE_REVIEW_ROLES)


def can_review_promotions(member: discord.Member) -> bool:
    return has_any_role(member, PROMOTION_REVIEW_ROLES)


def double_active() -> bool:
    return load_json(DOUBLE_FILE, {"active": False}).get("active", False)


def parse_member_id(value: str) -> int | None:
    match = re.search(r"\d{15,25}", value)
    return int(match.group(0)) if match else None


def get_guild_icon_url(guild: discord.Guild | None):
    return guild.icon.url if guild and guild.icon else None


def apply_guild_brand(embed: discord.Embed, guild: discord.Guild | None):
    icon_url = get_guild_icon_url(guild)
    if icon_url:
        embed.set_footer(text=guild.name, icon_url=icon_url)
    return embed


def get_points(user_id: int):
    points = load_json(POINT_FILE)
    requirements = load_json(REQUIRE_FILE)
    uid = str(user_id)
    return points.get(uid, 0), requirements.get(uid, 0)


def change_points_value(file: Path, user_id: int, amount: int):
    data = load_json(file)
    uid = str(user_id)
    data[uid] = max(0, data.get(uid, 0) + amount)
    save_json(file, data)
    return data[uid]


def should_award_text_points(user_id: int) -> bool:
    toggles = load_json(TEXT_TOGGLE_FILE)
    uid = str(user_id)
    should_count = toggles.get(uid, True)
    toggles[uid] = not should_count
    save_json(TEXT_TOGGLE_FILE, toggles)
    return should_count


def get_admin_rank_progress(member: discord.Member):
    current_role = None
    current_index = None
    for index, role_id in enumerate(ADMIN_RANK_ORDER):
        if any(role.id == role_id for role in member.roles):
            current_role = member.guild.get_role(role_id)
            current_index = index

    if current_index is None:
        return None, member.guild.get_role(ADMIN_RANK_ORDER[0])
    if current_index + 1 >= len(ADMIN_RANK_ORDER):
        return current_role, None
    return current_role, member.guild.get_role(ADMIN_RANK_ORDER[current_index + 1])


def build_promotion_panel_embed(guild: discord.Guild):
    embed = discord.Embed(
        title="لوحة طلب الترقية",
        description="اضغط الزر لإرسال طلب ترقية يحتوي على صورتك، نقاط الترقية، رتبتك الحالية، والرتبة المطلوبة.",
        color=discord.Color.blurple(),
    )
    return apply_guild_brand(embed, guild)


async def send_points_action_log(guild: discord.Guild, moderator: discord.Member, target: discord.Member | None, action: str, amount: int | None = None, new_value: int | None = None):
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
    apply_guild_brand(embed, guild)
    await channel.send(embed=embed)


# =========================
# POINTS PANEL
# =========================

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
        await interaction.response.send_message(f"✅ تم تنفيذ: **{self.action_name}** لـ {member.mention}. الرصيد الآن: `{new_value}`", ephemeral=True)


class ResetUserModal(discord.ui.Modal):
    def __init__(self, title: str, file: Path, action_name: str):
        super().__init__(title=title)
        self.file = file
        self.action_name = action_name
        self.user_id = discord.ui.TextInput(label="آيدي أو منشن العضو", required=True, max_length=40)
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return

        member_id = parse_member_id(self.user_id.value)
        if not member_id:
            await interaction.response.send_message("❌ آيدي العضو غير صحيح.", ephemeral=True)
            return

        data = load_json(self.file)
        data[str(member_id)] = 0
        save_json(self.file, data)
        member = interaction.guild.get_member(member_id)
        await send_points_action_log(interaction.guild, interaction.user, member, self.action_name, 0, 0)
        await interaction.response.send_message("✅ تم التصفير بنجاح.", ephemeral=True)


class InteractionPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="نقاطي", style=discord.ButtonStyle.primary, custom_id="points:mine", row=0)
    async def my_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        total, req = get_points(interaction.user.id)
        embed = discord.Embed(title="ملف التفاعل الإداري", description=f"ملخص نقاط {interaction.user.mention}.", color=discord.Color.blue(), timestamp=now_utc())
        embed.add_field(name="نقاط التفاعل", value=f"`{total}`", inline=True)
        embed.add_field(name="نقاط الترقية", value=f"`{req}`", inline=True)
        embed.add_field(name="حالة الدبل", value="`مفعل`" if double_active() else "`مغلق`", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        icon_url = get_guild_icon_url(interaction.guild)
        if icon_url:
            embed.set_author(name=interaction.guild.name, icon_url=icon_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="التوب", style=discord.ButtonStyle.success, custom_id="points:top", row=0)
    async def top_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=build_top_embed(interaction.guild), ephemeral=False)

    @discord.ui.button(label="زيادة تفاعل", style=discord.ButtonStyle.secondary, custom_id="points:add_interaction", row=1)
    async def add_interaction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("زيادة نقاط التفاعل", POINT_FILE, "زيادة نقاط التفاعل", 1))

    @discord.ui.button(label="خصم تفاعل", style=discord.ButtonStyle.danger, custom_id="points:remove_interaction", row=1)
    async def remove_interaction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("خصم نقاط التفاعل", POINT_FILE, "خصم نقاط التفاعل", -1))

    @discord.ui.button(label="تصفير تفاعل شخص", style=discord.ButtonStyle.danger, custom_id="points:reset_interaction", row=1)
    async def reset_interaction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetUserModal("تصفير نقاط التفاعل", POINT_FILE, "تصفير نقاط التفاعل"))

    @discord.ui.button(label="زيادة ترقية", style=discord.ButtonStyle.secondary, custom_id="points:add_upgrade", row=2)
    async def add_upgrade(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("زيادة نقاط الترقية", REQUIRE_FILE, "زيادة نقاط الترقية", 1))

    @discord.ui.button(label="خصم ترقية", style=discord.ButtonStyle.danger, custom_id="points:remove_upgrade", row=2)
    async def remove_upgrade(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeValueModal("خصم نقاط الترقية", REQUIRE_FILE, "خصم نقاط الترقية", -1))

    @discord.ui.button(label="تصفير ترقية شخص", style=discord.ButtonStyle.danger, custom_id="points:reset_upgrade", row=2)
    async def reset_upgrade(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetUserModal("تصفير نقاط الترقية", REQUIRE_FILE, "تصفير نقاط الترقية"))

    @discord.ui.button(label="تصفير تفاعل الكل", style=discord.ButtonStyle.danger, custom_id="points:reset_all", row=3)
    async def reset_all(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        return apply_guild_brand(embed, guild)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for index, (uid, pts) in enumerate(sorted(valid_points, key=lambda item: item[1], reverse=True)[:10], start=1):
        member = guild.get_member(int(uid))
        prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
        lines.append(f"{prefix} {member.mention} - `{pts}` نقطة")
    embed.description = "\n".join(lines)
    return apply_guild_brand(embed, guild)


@bot.command(name="لوحة")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def interaction_panel(ctx: commands.Context):
    if ctx.channel.id != INTERACTION_PANEL_CHANNEL or not is_admin(ctx.author):
        return
    embed = discord.Embed(
        title="لوحة إدارة التفاعل والترقية",
        description="إدارة نقاط التفاعل والترقية والدبل من لوحة واحدة.",
        color=discord.Color.dark_teal(),
    )
    await ctx.send(embed=apply_guild_brand(embed, ctx.guild), view=InteractionPanel())


# =========================
# IMAGE REVIEW
# =========================

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
        embed = discord.Embed(title="طلب صورة مرفوض", description=f"**سبب الرفض:** {self.reason.value}", color=discord.Color.red(), timestamp=now_utc())
        if target:
            embed.add_field(name="الإداري", value=target.mention, inline=True)
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
        if interaction.message and interaction.message.embeds and interaction.message.embeds[0].image:
            embed.set_image(url=interaction.message.embeds[0].image.url)
        await interaction.response.edit_message(embed=apply_guild_brand(embed, interaction.guild), view=None)


class ImageReviewView(discord.ui.View):
    def __init__(self, target_id: int):
        super().__init__(timeout=None)
        self.target_id = target_id

    @discord.ui.button(label="قبول", style=discord.ButtonStyle.success, custom_id="image_review:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_images(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return
        target = interaction.guild.get_member(self.target_id)
        if not target or not is_points_member(target):
            await interaction.response.send_message("❌ العضو غير موجود أو لا يملك رتبة التفاعل.", ephemeral=True)
            return
        total = change_points_value(REQUIRE_FILE, target.id, IMAGE_POINTS)
        await send_points_action_log(interaction.guild, interaction.user, target, "قبول صورة ومنح نقاط ترقية", IMAGE_POINTS, total)
        embed = discord.Embed(title="طلب صورة مقبول", description=f"✅ تم قبول صورة {target.mention}.", color=discord.Color.green(), timestamp=now_utc())
        embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
        embed.add_field(name="نقاط الترقية المضافة", value=f"`{IMAGE_POINTS}`", inline=True)
        embed.add_field(name="رصيد الترقية", value=f"`{total}`", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        if interaction.message and interaction.message.embeds and interaction.message.embeds[0].image:
            embed.set_image(url=interaction.message.embeds[0].image.url)
        await interaction.response.edit_message(embed=apply_guild_brand(embed, interaction.guild), view=None)

    @discord.ui.button(label="رفض", style=discord.ButtonStyle.danger, custom_id="image_review:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_images(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية.", ephemeral=True)
            return
        await interaction.response.send_modal(RejectImageModal(self.target_id))


# =========================
# PROMOTION REQUESTS
# =========================

class PromotionRejectModal(discord.ui.Modal, title="سبب رفض طلب الترقية"):
    reason = discord.ui.TextInput(label="سبب الرفض", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, target_id: int):
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction):
        target = interaction.guild.get_member(self.target_id)
        if target:
            try:
                await target.send(f"❌ تم رفض طلب ترقيتك.\n**السبب:** {self.reason.value}")
            except discord.HTTPException:
                pass
        embed = discord.Embed(title="طلب ترقية مرفوض", description=f"**سبب الرفض:** {self.reason.value}", color=discord.Color.red(), timestamp=now_utc())
        if target:
            embed.add_field(name="الإداري", value=target.mention, inline=True)
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=apply_guild_brand(embed, interaction.guild), view=None)


class PromotionReviewView(discord.ui.View):
    def __init__(self, target_id: int, current_role_id: int | None, next_role_id: int):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.current_role_id = current_role_id
        self.next_role_id = next_role_id

    @discord.ui.button(label="قبول الترقية", style=discord.ButtonStyle.success, custom_id="promotion:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_promotions(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية مراجعة الترقيات.", ephemeral=True)
            return
        target = interaction.guild.get_member(self.target_id)
        next_role = interaction.guild.get_role(self.next_role_id)
        current_role = interaction.guild.get_role(self.current_role_id) if self.current_role_id else None
        if not target or not next_role:
            await interaction.response.send_message("❌ تعذر العثور على العضو أو رتبة الترقية.", ephemeral=True)
            return
        try:
            await target.add_roles(next_role, reason=f"قبول طلب ترقية بواسطة {interaction.user}")
            if current_role:
                await target.remove_roles(current_role, reason="استبدال رتبة الإدارة بعد الترقية")
        except discord.Forbidden:
            await interaction.response.send_message("❌ لا أملك صلاحية تعديل رتب هذا العضو.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("❌ حدث خطأ أثناء تنفيذ الترقية.", ephemeral=True)
            return
        try:
            await target.send(f"✅ تم قبول طلب ترقيتك إلى رتبة {next_role.mention}.")
        except discord.HTTPException:
            pass
        total, req = get_points(target.id)
        embed = discord.Embed(title="طلب ترقية مقبول", description=f"✅ تم قبول ترقية {target.mention}.", color=discord.Color.green(), timestamp=now_utc())
        embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
        embed.add_field(name="الرتبة الجديدة", value=next_role.mention, inline=True)
        embed.add_field(name="نقاط الترقية", value=f"`{req}`", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.edit_message(embed=apply_guild_brand(embed, interaction.guild), view=None)

    @discord.ui.button(label="رفض الترقية", style=discord.ButtonStyle.danger, custom_id="promotion:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_promotions(interaction.user):
            await interaction.response.send_message("❌ لا تملك صلاحية مراجعة الترقيات.", ephemeral=True)
            return
        await interaction.response.send_modal(PromotionRejectModal(self.target_id))


class PromotionRequestPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="طلب ترقية", style=discord.ButtonStyle.primary, custom_id="promotion:request")
    async def request_promotion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_points_member(interaction.user):
            await interaction.response.send_message("❌ نظام طلب الترقية مخصص للرتب المعتمدة في التفاعل فقط.", ephemeral=True)
            return
        current_role, next_role = get_admin_rank_progress(interaction.user)
        if not next_role:
            await interaction.response.send_message("✅ أنت على أعلى رتبة إدارية حاليًا.", ephemeral=True)
            return
        total, req = get_points(interaction.user.id)
        embed = discord.Embed(title="طلب ترقية جديد", description=f"تم إرسال طلب ترقية من {interaction.user.mention}.", color=discord.Color.blurple(), timestamp=now_utc())
        embed.add_field(name="نقاط التفاعل", value=f"`{total}`", inline=True)
        embed.add_field(name="نقاط الترقية", value=f"`{req}`", inline=True)
        embed.add_field(name="الرتبة الحالية", value=current_role.mention if current_role else "لا توجد رتبة إدارية", inline=True)
        embed.add_field(name="الرتبة المطلوبة", value=next_role.mention, inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        apply_guild_brand(embed, interaction.guild)
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        await interaction.channel.send(embed=embed, view=PromotionReviewView(interaction.user.id, current_role.id if current_role else None, next_role.id))
        await interaction.channel.send(embed=build_promotion_panel_embed(interaction.guild), view=PromotionRequestPanel())
        await interaction.response.send_message("✅ تم إرسال طلب ترقيتك للمراجعة.", ephemeral=True)


@bot.command(name="ترقية")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def promotion_panel(ctx: commands.Context):
    if ctx.channel.id != PROMOTION_REQUEST_CHANNEL:
        return
    await ctx.send(embed=build_promotion_panel_embed(ctx.guild), view=PromotionRequestPanel())


# =========================
# POINTS EVENTS
# =========================

voice_times: dict[str, datetime.datetime] = {}
spam_tracker: dict[int, list[float]] = {}


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
        await channel.send(embed=apply_guild_brand(embed, message.guild))
    return True


async def handle_message_points(message: discord.Message):
    if not isinstance(message.author, discord.Member) or not is_points_member(message.author):
        return

    has_image = any(a.content_type and a.content_type.startswith("image/") for a in message.attachments)
    if message.channel.id == KEYWORD_CHANNEL and has_image:
        image_attachment = next((a for a in message.attachments if a.content_type and a.content_type.startswith("image/")), None)
        review_file = None
        image_url = image_attachment.url if image_attachment else None
        if image_attachment:
            extension = Path(image_attachment.filename or "image.png").suffix or ".png"
            filename = f"review_{message.id}{extension}"
            try:
                review_file = await image_attachment.to_file(filename=filename)
                image_url = f"attachment://{filename}"
            except discord.HTTPException:
                image_url = image_attachment.url
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        embed = discord.Embed(
            title="مراجعة صورة للتفاعل",
            description=f"تم استلام صورة من {message.author.mention}. اختر قبول لمنحه `{IMAGE_POINTS}` نقاط ترقية أو رفض لإرسال السبب له بالخاص.",
            color=discord.Color.blurple(),
            timestamp=now_utc(),
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        if image_url:
            embed.set_image(url=image_url)
        if review_file:
            await message.channel.send(embed=embed, view=ImageReviewView(message.author.id), file=review_file)
        else:
            await message.channel.send(embed=embed, view=ImageReviewView(message.author.id))
        return

    if message.channel.id in TEXT_POINTS_BLOCKED_CHANNELS:
        return
    if await check_spam(message):
        return
    if not should_award_text_points(message.author.id):
        return
    amount = DOUBLE_TEXT_POINTS if double_active() else TEXT_POINTS
    change_points_value(POINT_FILE, message.author.id, amount)


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
                change_points_value(POINT_FILE, member.id, amount * count)
                voice_times[uid] += datetime.timedelta(minutes=10 * count)


# =========================
# COMMANDS
# =========================

@bot.command(name="تفاعل")
async def show_points(ctx: commands.Context):
    total, req = get_points(ctx.author.id)
    embed = discord.Embed(title="ملف التفاعل الإداري", description=f"ملخص نقاط {ctx.author.mention}.", color=discord.Color.blue(), timestamp=now_utc())
    embed.add_field(name="نقاط التفاعل", value=f"`{total}`", inline=True)
    embed.add_field(name="نقاط الترقية", value=f"`{req}`", inline=True)
    embed.add_field(name="حالة الدبل", value="`مفعل`" if double_active() else "`مغلق`", inline=True)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    icon_url = get_guild_icon_url(ctx.guild)
    if icon_url:
        embed.set_author(name=ctx.guild.name, icon_url=icon_url)
    await ctx.send(embed=embed)


@bot.command(name="top")
async def top_points_command(ctx: commands.Context):
    if ctx.channel.id == INTERACTION_PANEL_CHANNEL:
        await ctx.send(embed=build_top_embed(ctx.guild))


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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    await handle_message_points(message)
    await bot.process_commands(message)


@bot.event
async def on_ready():
    bot.add_view(InteractionPanel())
    bot.add_view(PromotionRequestPanel())
    if not award_voice_points.is_running():
        award_voice_points.start()
    print(f"Logged in as {bot.user}")


keep_alive()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("DISCORD_TOKEN is missing")
