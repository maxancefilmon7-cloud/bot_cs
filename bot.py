import os
import re
import discord
from dotenv import load_dotenv
from urllib.parse import unquote
from analyzer import analyze
import storage

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

    # Commande !charms — affiche toutes les armes mémorisées
    if message.content.strip().lower() == "!charms":
        db = storage.get_all()
        if not db:
            await message.reply("📭 Aucune arme avec charm mémorisée pour l'instant.")
            return

        embed = discord.Embed(
            color=0xFFD700,
            description="## 🗃️  Armes avec Charm mémorisées\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )

        for weapon, info in list(db.items())[-20:]:  # 20 dernières
            name_short = weapon[:40] + "…" if len(weapon) > 40 else weapon
            val = (
                f"> 🔑 `{info['charm_name']}`\n"
                f"> 💰 Avec charm : **{info['price_with_charm']:.2f} €**\n"
            )
            if info.get("charm_standalone"):
                val += f"> 💎 Charm seul : **{info['charm_standalone']:.2f} €**\n"
            val += f"> 🕐 {info['last_updated']}"
            embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)

        embed.set_footer(text=f"CS2 Charm Analyzer  •  {len(db)} arme(s) mémorisée(s)")
        await message.reply(embed=embed)
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
