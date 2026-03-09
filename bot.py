import asyncio
import os
from collections import deque

import discord
from discord.ext import commands
import yt_dlp

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =========================
# YTDL / FFMPEG SETTINGS
# =========================
ytdl_format_options = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": False,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Queue per guild
music_queues = {}  # {guild_id: deque([song, song, ...])}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown title")
        self.url = data.get("webpage_url", "")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()

        def extract():
            return ytdl.extract_info(url, download=not stream)

        data = await loop.run_in_executor(None, extract)

        if data is None:
            raise Exception("yt-dlp returned no data")

        if "entries" in data:
            entries = data.get("entries")
            if not entries:
                raise Exception("No search results found")
            data = entries[0]

        audio_url = data.get("url")
        if not audio_url:
            raise Exception("No audio URL found in extracted data")

        print("Extracted title:", data.get("title"))
        print("Audio URL found:", bool(audio_url))

        source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
        return cls(source, data=data)


def get_queue(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = deque()
    return music_queues[guild_id]


async def play_next(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("Queue is empty.")
        return

    song = queue.popleft()

    try:
        player = await YTDLSource.from_url(song["query"], loop=bot.loop, stream=True)
    except Exception as e:
        await ctx.send(f"Error while loading track: {e}")
        print("LOAD ERROR:", e)
        return

    def after_playing(error):
        if error:
            print(f"PLAYER ERROR: {error}")

        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"NEXT SONG ERROR: {e}")

    try:
        ctx.voice_client.play(player, after=after_playing)
        await ctx.send(f"Now playing: **{player.title}**")
    except Exception as e:
        await ctx.send(f"Playback failed: {e}")
        print("PLAYBACK ERROR:", e)


# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# =========================
# COMMANDS
# =========================
@bot.command()
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("You need to join a voice channel first.")
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
        await ctx.send(f"Moved to **{channel}**")
        return

    await channel.connect()
    await ctx.send(f"Joined **{channel}**")


@bot.command()
async def leave(ctx):
    if ctx.voice_client is None:
        await ctx.send("I'm not in a voice channel.")
        return

    get_queue(ctx.guild.id).clear()
    await ctx.voice_client.disconnect()
    await ctx.send("Disconnected.")


@bot.command()
async def play(ctx, *, query: str):
    if ctx.author.voice is None:
        await ctx.send("Join a voice channel first.")
        return

    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()

    queue = get_queue(ctx.guild.id)
    queue.append({"query": query})

    await ctx.send(f"Added: **{query}**")

    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
        await play_next(ctx)


@bot.command()
async def skip(ctx):
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        await ctx.send("Nothing is playing.")
        return

    ctx.voice_client.stop()
    await ctx.send("Skipped.")


@bot.command()
async def pause(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Paused.")


@bot.command()
async def resume(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Resumed.")


@bot.command()
async def stop(ctx):
    queue = get_queue(ctx.guild.id)
    queue.clear()

    if ctx.voice_client is not None:
        ctx.voice_client.stop()

    await ctx.send("Stopped and cleared queue.")


@bot.command(name="queue")
async def show_queue(ctx):
    q = get_queue(ctx.guild.id)

    if not q:
        await ctx.send("Queue is empty.")
        return

    lines = []
    for i, song in enumerate(q, start=1):
        lines.append(f"{i}. {song['query']}")

    await ctx.send("**Queue:**\n" + "\n".join(lines[:20]))


@bot.command()
async def testaudio(ctx):
    if ctx.author.voice is None:
        await ctx.send("Join a voice channel first.")
        return

    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()

    url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"

    source = discord.FFmpegPCMAudio(
        url,
        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        options="-vn"
    )

    ctx.voice_client.play(source)
    await ctx.send("Testing direct audio stream...")


if TOKEN is None:
    raise ValueError("TOKEN environment variable is missing.")

bot.run(TOKEN)