import asyncio
import logging
import json
import os
from datetime import datetime, date, timezone
import discord
from discord.ext import commands
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except ImportError:
    pass  # dotenv optional in container if env vars provided directly

# Load secrets from environment
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")
CHANNEL_ID = int(CHANNEL_ID_RAW) if CHANNEL_ID_RAW and CHANNEL_ID_RAW.isdigit() else 0

# Data persistence location
# If DATA_DIR env var is set (used in container), store file inside that directory.
DATA_DIR = os.getenv("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    DATA_FILE = os.path.join(DATA_DIR, "submissions_data.json")
else:
    DATA_FILE = "submissions_data.json"

# Structure: { "YYYY-MM-DD": [user_id, ...] }
submissions_by_day: dict[str, set[int]] = {}

def _today_key() -> str:
    return date.today().isoformat()  # server local date

def load_data():
    if os.path.isfile(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for k, v in raw.items():
                submissions_by_day[k] = set(v)
            logging.info(f"Loaded submission history for {len(submissions_by_day)} day(s)")
        except Exception as e:
            logging.exception("Failed to load data file: %s", e)

def save_data():
    try:
        serializable = {k: sorted(list(v)) for k, v in submissions_by_day.items()}
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        logging.exception("Failed to save data: %s", e)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Requires enabling in Developer Portal
intents.guilds = True
intents.messages = True
# Members intent (privileged) – set True only if enabled in Developer Portal.
ENABLE_MEMBERS_INTENT = False  # set True ONLY if enabled in Developer Portal
if ENABLE_MEMBERS_INTENT:
    intents.members = True  # Needed to list guild members for non‑submitted report

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
discord.utils.setup_logging(level=logging.INFO)

bot = commands.Bot(command_prefix="!", intents=intents)

# Simple health HTTP server on port 7890 (optional for container)
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "7890"))
_health_started = False

async def start_health_server():
    global _health_started
    if _health_started:
        return
    _health_started = True
    from aiohttp import web
    app = web.Application()
    async def health(_request):
        return web.json_response({
            "status": "ok",
            "guilds": len(bot.guilds),
            "channel_id": CHANNEL_ID,
            "day": _today_key(),
        })
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_PORT)
    await site.start()
    logging.info(f"Health server started on :{HEALTH_PORT}")

async def _heartbeat():
    last_day = _today_key()
    while True:
        try:
            await asyncio.sleep(30)
            chan = bot.get_channel(CHANNEL_ID)
            # Day rollover detection
            current = _today_key()
            if current != last_day:
                logging.info(f"Date changed {last_day} -> {current}. Starting new day tracking.")
                last_day = current
                submissions_by_day.setdefault(current, set())
                save_data()
            logging.info(
                f"Heartbeat: day={current} submissions_today={len(submissions_by_day.get(current, set()))} channel_resolved={'yes' if chan else 'no'}"
            )
        except Exception as e:
            logging.exception("Heartbeat error: %s", e)

@bot.event
async def on_ready():
    if not TOKEN:
        logging.error("DISCORD_TOKEN not set. Set it in environment or .env file.")
    if CHANNEL_ID == 0:
        logging.warning("CHANNEL_ID missing or invalid. Set CHANNEL_ID env var.")
    print(f"✅ Logged in as {bot.user}")
    print(f"🏰 Connected to {len(bot.guilds)} servers:")
    for guild in bot.guilds:
        print(f"  - {guild.name} (ID: {guild.id})")
    print(f"🔧 Bot permissions can be checked at: https://discord.com/developers/applications/{bot.user.id}/bot")
    # Start heartbeat background task once
    if not any(t.get_name() == 'heartbeat' for t in asyncio.all_tasks()):
        bot.loop.create_task(_heartbeat(), name='heartbeat')
    # Start health server
    await start_health_server()

    # Attempt a one‑time test message (ignore failures)
    chan = bot.get_channel(CHANNEL_ID)
    if chan:
        try:
            await chan.send("👋 Bot online (diagnostic message). If you see this, messages should work.")
        except discord.Forbidden:
            print("⚠️ Bot lacks permission to send messages in target channel.")
        except Exception as e:
            print(f"⚠️ Failed to send diagnostic message: {e}")
    else:
        print("⚠️ Could not resolve CHANNEL_ID. Double‑check the ID and that the bot can VIEW the channel.")

    # Load data after bot is fully ready
    load_data()
    # Ensure today key exists
    submissions_by_day.setdefault(_today_key(), set())

@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author == bot.user:
        return

    # Debug: Print all messages to console
    print(f"[EVENT] Message in channel {message.channel.id} author={message.author} content={message.content[:80]!r}")
    
    # TEMPORARY: Work in ALL channels to find the right one
    if True:  # Work in all channels temporarily
        print(f"✅ Processing message in channel {message.channel.id}")

        # If this is a test command, show channel info
        if message.content.startswith("!test"):
            await message.channel.send(f"🤖 Bot is working! Channel ID: {message.channel.id}")
            # Still allow command processing afterwards
        spreadsheet_detected = False

        # Check for file attachments
        for attachment in message.attachments:
            if attachment.filename.endswith(('.xlsx', '.xls', '.csv', '.ods')):
                spreadsheet_detected = True
                print(f"📎 File attachment detected: {attachment.filename}")
                break

        # Check for Google Sheets links
        if not spreadsheet_detected and message.content:
            google_sheets_keywords = [
                'docs.google.com/spreadsheets',
                'sheets.google.com',
                'drive.google.com'
            ]

            for keyword in google_sheets_keywords:
                if keyword in message.content.lower():
                    spreadsheet_detected = True
                    print(f"🔗 Google Sheets link detected with keyword: {keyword}")
                    break

        # Send confirmation if spreadsheet was detected
        if spreadsheet_detected:
            # Record submission
            today_key = _today_key()
            submissions_by_day.setdefault(today_key, set()).add(message.author.id)
            save_data()
            print(f"📊 Sending confirmation for {message.author.name}")
            try:
                await message.channel.send(
                    f"✅ Spreadsheet received from {message.author.mention}"
                )
            except discord.Forbidden:
                print("⚠️ Missing permission to send message in this channel.")
        else:
            print(f"❌ No spreadsheet detected in message: {message.content[:100]}...")

    # Process commands after custom logic
    await bot.process_commands(message)

@bot.event
async def on_connect():
    print("🔌 on_connect fired – gateway connection established.")

@bot.event
async def on_resumed():
    print("♻️ Session resumed.")

@bot.event
async def on_guild_join(guild: discord.Guild):
    print(f"➕ Joined guild {guild.name} ({guild.id})")

@bot.event
async def on_error(event_method, *args, **kwargs):
    logging.exception("Unhandled exception in %s", event_method)

@bot.command(name='debug')
async def debug_info(ctx):
    """Get debug information about the bot"""
    embed = discord.Embed(title="🔧 Bot Debug Info", color=0x00ff00)
    embed.add_field(name="Bot User", value=f"{bot.user.name}#{bot.user.discriminator}", inline=True)
    embed.add_field(name="Current Channel", value=f"{ctx.channel.name} ({ctx.channel.id})", inline=True)
    embed.add_field(name="Current Server", value=f"{ctx.guild.name} ({ctx.guild.id})", inline=True)
    embed.add_field(name="Target Channel ID", value=str(CHANNEL_ID), inline=True)
    embed.add_field(name="Message Content Intent", value="✅ Enabled", inline=True)
    embed.add_field(name="Bot Permissions", value=f"Read: ✅\nSend: ✅\nView: ✅", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='test')
async def test_bot(ctx):
    """Test if bot is working in this channel"""
    await ctx.send(f"🤖 Bot is working! Channel ID: {ctx.channel.id}")

def _get_today_sets(guild: discord.Guild):
    today_ids = submissions_by_day.get(_today_key(), set())
    # Collect eligible member ids (exclude bots)
    member_ids = {m.id for m in guild.members if not m.bot}
    submitted = today_ids & member_ids
    not_submitted = member_ids - submitted
    return submitted, not_submitted

@bot.command(name='submissions')
async def report_submissions(ctx):
    """Show who HAS submitted today."""
    if ctx.channel.id != CHANNEL_ID:
        return
    submitted, _ = _get_today_sets(ctx.guild)
    if not submitted:
        await ctx.send("❌ No submissions received today.")
        return
    lines = []
    for uid in sorted(submitted):
        user = ctx.guild.get_member(uid)
        lines.append(f"✅ {user.display_name if user else uid}")
    embed = discord.Embed(
        title="📊 Submitted Today",
        description="\n".join(lines),
        color=0x00ff00,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Total submitted: {len(submitted)}")
    await ctx.send(embed=embed)

@bot.command(name='notsubmitted')
async def report_not_submitted(ctx):
    """Show who has NOT submitted today."""
    if ctx.channel.id != CHANNEL_ID:
        return
    submitted, not_submitted = _get_today_sets(ctx.guild)
    if not not_submitted:
        await ctx.send("✅ Everyone has submitted today!")
        return
    lines = []
    for uid in sorted(not_submitted):
        user = ctx.guild.get_member(uid)
        lines.append(f"❌ {user.display_name if user else uid}")
    embed = discord.Embed(
        title="🕒 Not Yet Submitted Today",
        description="\n".join(lines),
        color=0xFFAA00,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Pending: {len(not_submitted)} | Submitted: {len(submitted)}")
    await ctx.send(embed=embed)

@bot.command(name='dailyreport')
async def daily_report(ctx):
    """Combined report: submitted + not submitted."""
    if ctx.channel.id != CHANNEL_ID:
        return
    submitted, not_submitted = _get_today_sets(ctx.guild)
    desc_parts = []
    if submitted:
        desc_parts.append("**Submitted:**\n" + "\n".join(
            f"✅ {ctx.guild.get_member(uid).display_name}" for uid in sorted(submitted)
            if ctx.guild.get_member(uid)
        ))
    else:
        desc_parts.append("No submissions yet.")
    if not_submitted:
        desc_parts.append("\n**Not Submitted:**\n" + "\n".join(
            f"❌ {ctx.guild.get_member(uid).display_name}" for uid in sorted(not_submitted)
            if ctx.guild.get_member(uid)
        ))
    else:
        desc_parts.append("\nEveryone has submitted ✅")
    embed = discord.Embed(
        title=f"Daily Report – {_today_key()}",
        description="\n".join(desc_parts),
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Submitted: {len(submitted)} | Pending: {len(not_submitted)} | Total: {len(submitted)+len(not_submitted)}")
    await ctx.send(embed=embed)

@bot.command(name='clear_submissions')
async def clear_submissions(ctx):
    """Admin: clear today's submission list."""
    if ctx.channel.id != CHANNEL_ID:
        return
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to clear submissions.")
        return
    submissions_by_day[_today_key()] = set()
    save_data()
    await ctx.send("🗑️ Cleared today's submission list.")

bot.run(TOKEN)
