import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio
from datetime import datetime, timedelta
import os

TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Database ----------
conn = sqlite3.connect("bot.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id INTEGER,
    message TEXT,
    remind_at TEXT
)""")
conn.commit()

# ---------- Events ----------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")
    check_reminders.start()

# ---------- Slash Commands ----------
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="remind", description="Set a reminder")
@app_commands.describe(minutes="Minutes from now", message="What to remind you about")
async def remind(interaction: discord.Interaction, minutes: int, message: str):
    remind_at = datetime.utcnow() + timedelta(minutes=minutes)
    c.execute(
        "INSERT INTO reminders (user_id, channel_id, message, remind_at) VALUES (?, ?, ?, ?)",
        (interaction.user.id, interaction.channel_id, message, remind_at.isoformat())
    )
    conn.commit()
    await interaction.response.send_message(f"Okay, I'll remind you in {minutes} minutes.")

@bot.tree.command(name="rps", description="Play rock-paper-scissors")
@app_commands.choices(choice=[
    app_commands.Choice(name="rock", value="rock"),
    app_commands.Choice(name="paper", value="paper"),
    app_commands.Choice(name="scissors", value="scissors"),
])
async def rps(interaction: discord.Interaction, choice: app_commands.Choice[str]):
    options = ["rock", "paper", "scissors"]
    bot_choice = random.choice(options)
    user_choice = choice.value

    if user_choice == bot_choice:
        result = "Tie!"
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "paper" and bot_choice == "rock") or \
         (user_choice == "scissors" and bot_choice == "paper"):
        result = "You win!"
    else:
        result = "I win!"

    await interaction.response.send_message(f"You: {user_choice} | Me: {bot_choice} → {result}")

@bot.tree.command(name="poll", description="Create a yes/no poll")
@app_commands.describe(question="The poll question")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 Poll", description=question)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

# ---------- Background task ----------
from discord.ext import tasks

@tasks.loop(seconds=30)
async def check_reminders():
    now = datetime.utcnow().isoformat()
    c.execute("SELECT id, user_id, channel_id, message FROM reminders WHERE remind_at <= ?", (now,))
    rows = c.fetchall()
    for rid, user_id, channel_id, message in rows:
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(f"<@{user_id}> ⏰ Reminder: {message}")
        c.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    conn.commit()

bot.run(TOKEN)
