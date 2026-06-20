import asyncio
import json
import os
import re
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
REACTION_ROLES_CHANNEL_ID = 1517791670391934986
EMOJI_SETUP_CHANNEL_ID = 1480429990628560978

DATA_DIR = Path("data")
PANEL_FILE = DATA_DIR / "reaction_roles_panel.json"
EMOJI_FILE = DATA_DIR / "reaction_roles_emojis.json"

GAMES = {
    "fivem": {
        "label": "فايف ام",
        "aliases": ["فايف", "فايف ام", "fivem", "five"],
        "role_ids": [1487457268629766376],
    },
    "bls": {
        "label": "محاكي الحوادث",
        "aliases": ["محاكي", "محاكي الحوادث"],
        "role_ids": [1495710572023517285],
    },
    "assetto": {
        "label": "Assetto Corsa",
        "aliases": ["اسيتو", "اسيستو", "assetto", "assito", "corsa"],
        "role_ids": [1516370348717772971],
    },
    "valorant": {
        "label": "Valorant",
        "aliases": ["فالورانت", "valorant", "valo"],
        "role_ids": [1500824746596630629],
    },
    "fortnite": {
        "label": "فورت نايت",
        "aliases": ["فورت", "فورت نايت", "fortnite"],
        "role_ids": [1490770204341571755],
    },
    "rocket": {
        "label": "روكت ليق",
        "aliases": ["روكت", "روكت ليق", "rocket", "rl"],
        "role_ids": [1479244719543287818],
    },
    "overwatch": {
        "label": "Overwatch PC + PS",
        "aliases": ["اوفر", "اوفر واتش", "overwatch", "ow"],
        "role_ids": [1479687436455116850, 1479686969960304702],
    },
    "marvel": {
        "label": "MARVEL",
        "aliases": ["مارفل", "marvel"],
        "role_ids": [1489590768757768382],
    },
}


def load_json(file: Path, default):
    try:
        with file.open("r", encoding="utf-8") as opened_file:
            return json.load(opened_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default.copy() if isinstance(default, dict) else default


def save_json(file: Path, data):
    DATA_DIR.mkdir(exist_ok=True)
    with file.open("w", encoding="utf-8") as opened_file:
        json.dump(data, opened_file, ensure_ascii=False, indent=4)


def load_panel_message_id() -> int | None:
    data = load_json(PANEL_FILE, {})
    message_id = data.get("message_id")
    return int(message_id) if message_id else None


def save_panel_message_id(message_id: int):
    save_json(PANEL_FILE, {"message_id": message_id})


def load_emojis():
    return load_json(EMOJI_FILE, {})


def save_emoji(game_key: str, emoji_data: dict):
    data = load_emojis()
    data[game_key] = emoji_data
    save_json(EMOJI_FILE, data)


def can_setup_roles(member: discord.Member) -> bool:
    return member.guild_permissions.manage_roles


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def remove_emoji_markup(text: str) -> str:
    text = re.sub(r"<a?:[A-Za-z0-9_]+:\d{15,25}>", " ", text)
    text = re.sub(r":\d{15,25}:", " ", text)
    return text


def text_before_emoji(text: str) -> str:
    match = re.search(r"<a?:[A-Za-z0-9_]+:\d{15,25}>|:\d{15,25}:", text)
    if match:
        return text[: match.start()]
    return text


def find_game_key(text: str) -> str | None:
    normalized = normalize_text(remove_emoji_markup(text_before_emoji(text)))
    for key, game in GAMES.items():
        for alias in game["aliases"]:
            if normalize_text(alias) in normalized:
                return key
    return None


def parse_emoji(text: str):
    custom_match = re.search(r"<a?:([A-Za-z0-9_]+):(\d{15,25})>", text)
    if custom_match:
        return {
            "type": "custom",
            "name": custom_match.group(1),
            "id": int(custom_match.group(2)),
        }

    raw_id_match = re.search(r":(\d{15,25}):", text)
    if raw_id_match:
        return {"type": "custom", "id": int(raw_id_match.group(1))}

    text_without_words = remove_emoji_markup(text)
    for game in GAMES.values():
        for alias in game["aliases"]:
            text_without_words = re.sub(
                re.escape(alias),
                " ",
                text_without_words,
                flags=re.IGNORECASE,
            )

    for word in text_without_words.strip().split():
        if not word.startswith("!"):
            return {"type": "unicode", "name": word}
    return None


def emoji_to_display(emoji_data: dict | None):
    if not emoji_data:
        return "بدون ايموجي"
    if emoji_data["type"] == "custom":
        emoji_id = emoji_data["id"]
        emoji = bot.get_emoji(emoji_id)
        if emoji:
            return str(emoji)
        name = emoji_data.get("name", "emoji")
        return f"<:{name}:{emoji_id}>"
    return emoji_data["name"]


def emoji_to_reaction(emoji_data: dict | None):
    if not emoji_data:
        return None
    if emoji_data["type"] == "custom":
        emoji = bot.get_emoji(emoji_data["id"])
        if emoji:
            return emoji
        if emoji_data.get("name"):
            return discord.PartialEmoji(
                name=emoji_data["name"],
                id=emoji_data["id"],
            )
        return None
    return emoji_data["name"]


def reaction_matches(payload: discord.RawReactionActionEvent, emoji_data: dict) -> bool:
    if emoji_data["type"] == "custom":
        return payload.emoji.id == emoji_data["id"]
    return payload.emoji.name == emoji_data["name"]


def get_game_from_reaction(payload: discord.RawReactionActionEvent):
    for game_key, emoji_data in load_emojis().items():
        if game_key in GAMES and reaction_matches(payload, emoji_data):
            return GAMES[game_key]
    return None


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
    if payload.guild_id is None or bot.user is None or payload.user_id == bot.user.id:
        return
    if not is_panel_reaction(payload):
        return

    game = get_game_from_reaction(payload)
    if game is None:
        return

    member = await get_payload_member(payload)
    if member is None or member.bot:
        return

    roles = [
        member.guild.get_role(role_id)
        for role_id in game["role_ids"]
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
    saved_emojis = load_emojis()
    description_lines = [
        "اضغط على الإيموجي المناسب حتى تأخذ الرتبة.",
        "إذا شلت التفاعل، تنشال منك الرتبة تلقائيًا.",
        "",
    ]

    for game_key, game in GAMES.items():
        emoji = emoji_to_display(saved_emojis.get(game_key))
        role_mentions = []
        for role_id in game["role_ids"]:
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
    for emoji_data in load_emojis().values():
        reaction = emoji_to_reaction(emoji_data)
        if reaction is None:
            print(f"Could not use emoji: {emoji_data}")
            continue
        try:
            await message.add_reaction(reaction)
        except discord.HTTPException as exc:
            print(f"Could not add reaction {emoji_data}: {exc}")


async def get_roles_panel_channel():
    channel = bot.get_channel(REACTION_ROLES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(REACTION_ROLES_CHANNEL_ID)
        except discord.HTTPException:
            print(f"Could not find reaction roles channel: {REACTION_ROLES_CHANNEL_ID}")
            return None
    if not isinstance(channel, discord.TextChannel):
        print("Reaction roles channel is not a text channel.")
        return None
    return channel


async def ensure_roles_panel():
    channel = await get_roles_panel_channel()
    if channel is None:
        return None

    panel_message_id = load_panel_message_id()
    if panel_message_id is not None:
        try:
            panel_message = await channel.fetch_message(panel_message_id)
            await panel_message.edit(embed=build_roles_embed(channel.guild))
            await add_panel_reactions(panel_message)
            return panel_message
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            print(f"Could not fetch saved panel message: {exc}")

    panel_message = await channel.send(embed=build_roles_embed(channel.guild))
    save_panel_message_id(panel_message.id)
    await add_panel_reactions(panel_message)
    return panel_message


async def refresh_roles_panel():
    panel_message = await ensure_roles_panel()
    if panel_message is None:
        return
    try:
        await panel_message.clear_reactions()
    except discord.HTTPException:
        pass
    await add_panel_reactions(panel_message)


@bot.command(name="emoji")
@commands.guild_only()
async def set_emoji_command(ctx: commands.Context, *, text: str = ""):
    await handle_emoji_setup_message(ctx.message, text)


@bot.command(name="ايموجي")
@commands.guild_only()
async def set_arabic_emoji_command(ctx: commands.Context, *, text: str = ""):
    await handle_emoji_setup_message(ctx.message, text)


async def handle_emoji_setup_message(message: discord.Message, text: str | None = None):
    if message.channel.id != EMOJI_SETUP_CHANNEL_ID:
        return
    if not isinstance(message.author, discord.Member) or not can_setup_roles(message.author):
        return

    content = text if text is not None else message.content
    game_key = find_game_key(content)
    emoji_data = parse_emoji(content)
    if not game_key or not emoji_data:
        return

    save_emoji(game_key, emoji_data)
    await refresh_roles_panel()
    await message.reply(
        f"تم حفظ إيموجي {emoji_to_display(emoji_data)} للعبة {GAMES[game_key]['label']}.",
        mention_author=False,
    )


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
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if message.channel.id == EMOJI_SETUP_CHANNEL_ID and not message.content.startswith("!"):
        await handle_emoji_setup_message(message)
    await bot.process_commands(message)


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
