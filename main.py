import asyncio
import json
import os
from pathlib import Path
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask


# =========================
# KEEP ALIVE
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Reaction roles bot is running"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# SETTINGS
# =========================

LOGIN_RETRY_SECONDS = 1800
DATA_DIR = Path("data")
PANEL_FILE = DATA_DIR / "reaction_roles_panel.json"
REACTION_ROLES_CHANNEL_ID = 1517791670391934986

ROLE_REACTIONS = {
    1517795698714611743: {
        "label": "فايف ام",
        "role_ids": [1487457268629766376],
    },
    1517795999945326622: {
        "label": "محاكي الحوادث",
        "role_ids": [1495710572023517285],
    },
    1517796106564669510: {
        "label": "Assetto Corsa",
        "role_ids": [1516370348717772971],
    },
    1517796157785509969: {
        "label": "Valorant",
        "role_ids": [1500824746596630629],
    },
    1517796072200605766: {
        "label": "فورت نايت",
        "role_ids": [1490770204341571755],
    },
    1517796050574770238: {
        "label": "روكت ليق",
        "role_ids": [1479244719543287818],
    },
    1517796255302942720: {
        "label": "Overwatch PC + PS",
        "role_ids": [1479687436455116850, 1479686969960304702],
    },
    1517797091840102461: {
        "label": "MARVEL",
        "role_ids": [1489590768757768382],
    },
}


def load_panel_message_id() -> int | None:
    try:
        with PANEL_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    message_id = data.get("message_id")
    return int(message_id) if message_id else None


def save_panel_message_id(message_id: int):
    DATA_DIR.mkdir(exist_ok=True)
    with PANEL_FILE.open("w", encoding="utf-8") as file:
        json.dump({"message_id": message_id}, file, ensure_ascii=False, indent=4)


def can_setup_roles(member: discord.Member) -> bool:
    return member.guild_permissions.manage_roles


def get_reaction_config(payload: discord.RawReactionActionEvent):
    emoji_id = payload.emoji.id
    return ROLE_REACTIONS.get(emoji_id) if emoji_id else None


def is_panel_reaction(payload: discord.RawReactionActionEvent) -> bool:
    panel_message_id = load_panel_message_id()
    return (
        panel_message_id is not None
        and payload.message_id == panel_message_id
        and payload.channel_id == REACTION_ROLES_CHANNEL_ID
    )


async def get_payload_member(payload: discord.RawReactionActionEvent):
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return None
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return None
    return member


async def update_member_roles(payload: discord.RawReactionActionEvent, add_roles: bool):
    if payload.user_id == bot.user.id or payload.guild_id is None:
        return
    if not is_panel_reaction(payload):
        return

    config = get_reaction_config(payload)
    if config is None:
        return

    member = await get_payload_member(payload)
    if member is None or member.bot:
        return

    roles = [
        member.guild.get_role(role_id)
        for role_id in config["role_ids"]
        if member.guild.get_role(role_id) is not None
    ]
    if not roles:
        return

    try:
        if add_roles:
            await member.add_roles(*roles, reason="Reaction role added")
        else:
            await member.remove_roles(*roles, reason="Reaction role removed")
    except discord.Forbidden:
        print("Missing permission or bot role is lower than one of the target roles.")
    except discord.HTTPException as exc:
        print(f"Failed to update reaction roles: {exc}")


def build_roles_embed(guild: discord.Guild):
    description_lines = [
        "اضغط على الإيموجي المناسب حتى تأخذ الرتبة.",
        "إذا شلت التفاعل، تنشال منك الرتبة تلقائيًا.",
        "",
    ]

    for emoji_id, config in ROLE_REACTIONS.items():
        emoji = bot.get_emoji(emoji_id) or f"<:{emoji_id}:{emoji_id}>"
        role_mentions = []
        for role_id in config["role_ids"]:
            role = guild.get_role(role_id)
            role_mentions.append(role.mention if role else f"`{role_id}`")
        description_lines.append(f"{emoji} {' + '.join(role_mentions)}")

    embed = discord.Embed(
        title="اخذ رول قسم",
        description="\n".join(description_lines),
        color=discord.Color.blurple(),
    )
    if guild.icon:
        embed.set_footer(text=guild.name, icon_url=guild.icon.url)
    return embed


async def add_panel_reactions(message: discord.Message):
    for emoji_id in ROLE_REACTIONS:
        emoji = bot.get_emoji(emoji_id)
        if emoji is None:
            print(f"Could not find emoji: {emoji_id}")
            continue
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException as exc:
            print(f"Could not add reaction {emoji_id}: {exc}")


async def ensure_roles_panel():
    channel = bot.get_channel(REACTION_ROLES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(REACTION_ROLES_CHANNEL_ID)
        except discord.HTTPException:
            print(f"Could not find reaction roles channel: {REACTION_ROLES_CHANNEL_ID}")
            return

    if not isinstance(channel, discord.TextChannel):
        print("Reaction roles channel is not a text channel.")
        return

    panel_message_id = load_panel_message_id()
    if panel_message_id is not None:
        try:
            panel_message = await channel.fetch_message(panel_message_id)
            await add_panel_reactions(panel_message)
            return
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            print(f"Could not fetch saved panel message: {exc}")

    panel_message = await channel.send(embed=build_roles_embed(channel.guild))
    save_panel_message_id(panel_message.id)
    await add_panel_reactions(panel_message)


@bot.command(name="roles")
@commands.guild_only()
async def send_roles_panel(ctx: commands.Context):
    if ctx.channel.id != REACTION_ROLES_CHANNEL_ID:
        return

    if not can_setup_roles(ctx.author):
        await ctx.reply("ما عندك صلاحية إدارة الرتب.", mention_author=False)
        return

    panel_message = await ctx.send(embed=build_roles_embed(ctx.guild))
    save_panel_message_id(panel_message.id)
    await add_panel_reactions(panel_message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await update_member_roles(payload, add_roles=True)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await update_member_roles(payload, add_roles=False)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await ensure_roles_panel()


keep_alive()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


async def run_discord_bot():
    while True:
        try:
            await bot.start(DISCORD_TOKEN)
            break
        except discord.HTTPException as exc:
            if getattr(exc, "status", None) == 429:
                print(
                    "Discord rate limit while logging in. "
                    f"Retrying in {LOGIN_RETRY_SECONDS} seconds."
                )
                await asyncio.sleep(LOGIN_RETRY_SECONDS)
                continue
            raise


if not DISCORD_TOKEN:
    print("DISCORD_TOKEN is missing")
else:
    asyncio.run(run_discord_bot())
