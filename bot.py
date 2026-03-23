import os
import re
import discord
from dotenv import load_dotenv
from urllib.parse import unquote
from analyzer import scan, analyse_charm
import storage

load_dotenv()

STEAM_URL_RE = re.compile(
    r"https?://steamcommunity\.com/market/listings/730/([^\s?#]+)"
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"✅ Bot connecté : {client.user} (ID: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    content = message.content.strip()

    # ── /info ──────────────────────────────────────────
    if content.lower() == "/info":
        embed = discord.Embed(
            color=0x5865F2,
            description=(
                "## 👋  Bonjour Dieu du sexe !\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Voici toutes mes commandes :"
            ),
        )
        embed.add_field(
            name="🔗  Lien Steam Market",
            value="> Envoie directement un lien Steam Market CS2\n"
                  "> → Je liste toutes les armes avec charms et leurs prix",
            inline=False,
        )
        embed.add_field(
            name="🔍  `!analyse <nom du charm>`",
            value="> Analyse complète d'un charm mémorisé :\n"
                  "> valeur du charm, bonne affaire ou non, estimation revente",
            inline=False,
        )
        embed.add_field(
            name="📋  `!charms`",
            value="> Affiche toutes les armes avec charms mémorisées",
            inline=False,
        )
        embed.add_field(
            name="ℹ️  `/info`",
            value="> Affiche ce menu d'aide",
            inline=False,
        )
        embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market")
        await message.reply(embed=embed)
        return

    # ── !charms ────────────────────────────────────────
    if content.lower() == "!charms":
        db = storage.get_all()
        if not db:
            await message.reply("📭 Aucune arme avec charm mémorisée pour l'instant.")
            return

        embed = discord.Embed(
            color=0xFFD700,
            description=f"## 🗃️  Armes mémorisées ({len(db)})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )
        for weapon, info in list(db.items())[-20:]:
            name_short = weapon[:40] + "…" if len(weapon) > 40 else weapon
            val = (
                f"> 🔑 `{info['charm_name']}`\n"
                f"> 💰 Prix avec charm : {info['price_with_charm']:.2f} €\n"
                f"> 🕐 {info['last_updated']}"
            )
            embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)

        embed.set_footer(text="CS2 Charm Analyzer  •  Tape !analyse <charm> pour l'analyse complète")
        await message.reply(embed=embed)
        return

    # ── !analyse <charm> ───────────────────────────────
    if content.lower().startswith("!analyse "):
        charm_name = content[9:].strip()
        if not charm_name:
            await message.reply("Usage : `!analyse <nom du charm>`")
            return
        async with message.channel.typing():
            embed = await analyse_charm(charm_name)
        await message.reply(embed=embed)
        return

    # ── Lien Steam Market ──────────────────────────────
    matches = STEAM_URL_RE.findall(content)
    if matches:
        for raw_hash in matches:
            market_hash_name = unquote(raw_hash).rstrip("/")
            async with message.channel.typing():
                embed = await scan(market_hash_name)
            await message.reply(embed=embed)


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("DISCORD_TOKEN manquant dans le fichier .env")

client.run(token)
