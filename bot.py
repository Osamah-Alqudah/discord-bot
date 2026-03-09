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
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

ffmpeg_options = {
    "options": "-vn"
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Queue per guild
music_queues = {}   # {guild_id: deque([song, song, ...])}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown title")
        self.url = data.get("webpage_url", "")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()

        data = await loop.run_in_executor(
            None,
            lambda: ytdl.extract_info(url, download=not stream)
        )

        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
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
    player = await YTDLSource.from_url(song["query"], loop=bot.loop, stream=True)

    def after_playing(error):
        if error:
            print(f"Player error: {error}")

        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Next song error: {e}")

    ctx.voice_client.play(player, after=after_playing)
    await ctx.send(f"Now playing: **{player.title}**")


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

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        await ctx.send(f"Added to queue: **{query}**")
        return

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


@bot.command()
async def queue(ctx):
    q = get_queue(ctx.guild.id)

    if not q:
        await ctx.send("Queue is empty.")
        return

    lines = []
    for i, song in enumerate(q, start=1):
        lines.append(f"{i}. {song['query']}")

    await ctx.send("**Queue:**\n" + "\n".join(lines[:20]))


bot.run(TOKEN)
