import os
import re
import discord
from dotenv import load_dotenv
from urllib.parse import unquote
from analyzer import analyze

load_dotenv()

# Regex pour détecter les liens Steam Market CS2
STEAM_URL_RE = re.compile(
    r"https?://steamcommunity\.com/market/listings/730/([^\s?#]+)"
)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"✅ Bot connecté : {client.user} (ID: {client.user.id})")
    print("En attente de liens Steam Market CS2...")


@client.event
async def on_message(message: discord.Message):
    # Ignorer les messages du bot lui-même
    if message.author == client.user:
        return

    matches = STEAM_URL_RE.findall(message.content)
    if not matches:
        return

    for raw_hash in matches:
        market_hash_name = unquote(raw_hash).rstrip("/")
        async with message.channel.typing():
            embed = await analyze(market_hash_name)
        await message.reply(embed=embed)


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("DISCORD_TOKEN manquant dans le fichier .env")

client.run(token)
