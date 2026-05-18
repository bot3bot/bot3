import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# كود عشان البوت ما يطفي في Render
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run)
    t.start()

# إعدادات البوت
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command()
async def ping(ctx):
    await ctx.send("Pong! 🏓")

keep_alive()
# حط التوكن حق بوتك هنا بين العلامتين ""
bot.run("YOUR_TOKEN_HERE")