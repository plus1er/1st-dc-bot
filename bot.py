import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio
from datetime import datetime, timedelta

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
c.execute("""CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    reason TEXT
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

# ---------- Music ----------
import yt_dlp

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
}
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

@bot.tree.command(name="join", description="Join your voice channel")
async def join(interaction: discord.Interaction):
    if interaction.user.voice is None:
        await interaction.response.send_message("You need to be in a voice channel.")
        return
    channel = interaction.user.voice.channel
    await channel.connect()
    await interaction.response.send_message(f"Joined {channel.name}")

@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="Song name or URL")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if interaction.guild.voice_client is None:
        if interaction.user.voice is None:
            await interaction.followup.send("Join a voice channel first.")
            return
        await interaction.user.voice.channel.connect()

    vc = interaction.guild.voice_client

    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)["entries"][0]
        url = info["url"]
        title = info["title"]

    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTS)

    if vc.is_playing():
        vc.stop()

    vc.play(source)
    await interaction.followup.send(f"Now playing: {title}")

@bot.tree.command(name="stop", description="Stop playback")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("Stopped.")
    else:
        await interaction.response.send_message("Nothing is playing.")

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("Left the voice channel.")
    else:
        await interaction.response.send_message("Not in a voice channel.")

# ---------- Moderation ----------
@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"Kicked {member.mention} — {reason}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"Banned {member.mention} — {reason}")

@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason given"):
    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await interaction.response.send_message(f"Muted {member.mention} for {minutes}m — {reason}")

@bot.tree.command(name="unmute", description="Remove timeout from a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"Unmuted {member.mention}")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    c.execute("INSERT INTO warnings (user_id, reason) VALUES (?, ?)", (member.id, reason))
    conn.commit()
    await interaction.response.send_message(f"Warned {member.mention} — {reason}")

@bot.tree.command(name="warnings", description="List a member's warnings")
async def warnings(interaction: discord.Interaction, member: discord.Member):
    c.execute("SELECT reason, id FROM warnings WHERE user_id = ?", (member.id,))
    rows = c.fetchall()
    if not rows:
        await interaction.response.send_message(f"{member.mention} has no warnings.")
        return
    text = "\n".join(f"#{rid}: {reason}" for reason, rid in rows)
    await interaction.response.send_message(f"Warnings for {member.mention}:\n{text}")

@bot.tree.command(name="clear", description="Delete a number of messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

@kick.error
@ban.error
@mute.error
@unmute.error
@warn.error
@clear.error
async def mod_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission for this.", ephemeral=True)
    else:
        raise error

bot.run(TOKEN)
