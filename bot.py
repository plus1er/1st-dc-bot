import os
import threading
import time
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import random
from datetime import datetime, timedelta

TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

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
c.execute("""CREATE TABLE IF NOT EXISTS reaction_roles (
    message_id INTEGER,
    emoji TEXT,
    role_id INTEGER
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
    "cookiefile": "cookies.txt",
}
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# guild_id -> {"title", "thumbnail", "duration", "start_time", "message", "update_task"}
now_playing = {}

def format_time(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def make_progress_bar(elapsed, duration, length=20):
    if not duration or duration <= 0:
        return "🔴 Live / unknown length"
    ratio = min(elapsed / duration, 1.0)
    filled = int(length * ratio)
    bar = "▬" * filled + "🔘" + "▬" * (length - filled - 1) if filled < length else "▬" * length + "🔘"
    return f"{bar}\n{format_time(elapsed)} / {format_time(duration)}"

def make_now_playing_embed(guild_id):
    data = now_playing.get(guild_id)
    if not data:
        return discord.Embed(title="Nothing playing")
    elapsed = time.time() - data["start_time"]
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**{data['title']}**\n\n{make_progress_bar(elapsed, data['duration'])}",
        color=discord.Color.blurple()
    )
    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])
    return embed

class MusicControls(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="⏯ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await stop_progress_updates(self.guild_id)
        await interaction.response.send_message("Stopped.", ephemeral=True)

async def progress_updater(guild_id):
    """Edits the now-playing message every few seconds to move the progress bar."""
    try:
        while guild_id in now_playing:
            data = now_playing[guild_id]
            msg = data.get("message")
            if msg is None:
                await asyncio.sleep(5)
                continue
            embed = make_now_playing_embed(guild_id)
            try:
                await msg.edit(embed=embed)
            except discord.HTTPException:
                pass
            # stop naturally once track duration passes
            if data["duration"] and time.time() - data["start_time"] >= data["duration"]:
                break
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        pass

async def stop_progress_updates(guild_id):
    data = now_playing.get(guild_id)
    if data and data.get("update_task"):
        data["update_task"].cancel()
    now_playing.pop(guild_id, None)

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
    guild_id = interaction.guild.id

    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(f"scsearch:{query}", download=False)["entries"][0]
        url = info["url"]
        title = info["title"]
        thumbnail = info.get("thumbnail")
        duration = info.get("duration")  # seconds, may be None for live streams

    # stop any previous track/updater for this guild
    if vc.is_playing():
        vc.stop()
    await stop_progress_updates(guild_id)

    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTS)
    vc.play(source)

    now_playing[guild_id] = {
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration,
        "start_time": time.time(),
        "message": None,
        "update_task": None,
    }

    embed = make_now_playing_embed(guild_id)
    view = MusicControls(guild_id)
    await interaction.followup.send(embed=embed, view=view)
    msg = await interaction.original_response()
    now_playing[guild_id]["message"] = msg
    now_playing[guild_id]["update_task"] = bot.loop.create_task(progress_updater(guild_id))

@bot.tree.command(name="stop", description="Stop playback")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await stop_progress_updates(interaction.guild.id)
        await interaction.response.send_message("Stopped.")
    else:
        await interaction.response.send_message("Nothing is playing.")

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await stop_progress_updates(interaction.guild.id)
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

# ---------- Translator ----------
from deep_translator import GoogleTranslator

@bot.tree.command(name="translate", description="Translate text")
@app_commands.describe(text="Text to translate", target="Target language code (e.g. en, es, fr)")
async def translate(interaction: discord.Interaction, text: str, target: str):
    try:
        result = GoogleTranslator(source="auto", target=target).translate(text)
        await interaction.response.send_message(f"**Translated:** {result}")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# ---------- IP Geolocator ----------
import aiohttp

@bot.tree.command(name="iplookup", description="Get geolocation info for an IP")
@app_commands.describe(ip="IP address to look up")
async def iplookup(interaction: discord.Interaction, ip: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://ip-api.com/json/{ip}") as resp:
            data = await resp.json()

    if data.get("status") == "fail":
        await interaction.followup.send(f"Lookup failed: {data.get('message')}")
        return

    embed = discord.Embed(title=f"IP Lookup: {ip}")
    embed.add_field(name="Country", value=data.get("country"), inline=True)
    embed.add_field(name="Region", value=data.get("regionName"), inline=True)
    embed.add_field(name="City", value=data.get("city"), inline=True)
    embed.add_field(name="ISP", value=data.get("isp"), inline=True)
    embed.add_field(name="Timezone", value=data.get("timezone"), inline=True)
    embed.add_field(name="Coordinates", value=f"{data.get('lat')}, {data.get('lon')}", inline=True)
    await interaction.followup.send(embed=embed)

# ---------- Fun Meter ----------
@bot.tree.command(name="gaymeter", description="Random percent meter")
async def gaymeter(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    percent = random.randint(0, 100)
    await interaction.response.send_message(f"{target.mention} is {percent}% 🏳️‍🌈")

# ---------- Reaction Roles ----------
@bot.tree.command(name="reactionrole", description="Set up a reaction role message")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(message_id="ID of the message", emoji="Emoji to react with", role="Role to assign")
async def reactionrole(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    channel = interaction.channel
    try:
        msg = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        await interaction.response.send_message("Message not found in this channel.", ephemeral=True)
        return

    await msg.add_reaction(emoji)
    c.execute("INSERT INTO reaction_roles VALUES (?, ?, ?)", (msg.id, emoji, role.id))
    conn.commit()
    await interaction.response.send_message(f"Reacting with {emoji} on that message now gives {role.mention}.", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member is None or payload.member.bot:
        return
    c.execute("SELECT role_id FROM reaction_roles WHERE message_id = ? AND emoji = ?",
              (payload.message_id, str(payload.emoji)))
    row = c.fetchone()
    if row:
        role = payload.member.guild.get_role(row[0])
        if role:
            await payload.member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload):
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return
    c.execute("SELECT role_id FROM reaction_roles WHERE message_id = ? AND emoji = ?",
              (payload.message_id, str(payload.emoji)))
    row = c.fetchone()
    if row:
        role = guild.get_role(row[0])
        if role:
            await member.remove_roles(role)

bot.run(TOKEN)
