import asyncio
import os
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
    return "Salam reply bot is running"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# SETTINGS
# =========================

SALAM_CHANNEL_ID = 1480429990628560978
SALAM_TEXT = "السلام عليكم"
SALAM_REPLY = "وعليكم السلام"
LOGIN_RETRY_SECONDS = 1800


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    if (
        message.channel.id == SALAM_CHANNEL_ID
        and normalize_text(message.content) == SALAM_TEXT
    ):
        await message.channel.send(SALAM_REPLY)
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


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
