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

# Stocke les liens en attente du nombre de pages : {user_id: market_hash_name}
pending: dict[int, str] = {}


@client.event
async def on_ready():
    print(f"✅ Bot connecté : {client.user} (ID: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    content = message.content.strip()
    uid = message.author.id

    # ── Réponse au nombre de pages demandé ─────────────
    if uid in pending:
        if content.isdigit():
            pages = max(1, int(content))
            market_hash_name = pending.pop(uid)
            import math
            est = math.ceil(pages / 10) * 4
            await message.reply(f"⏳ Analyse de **{pages} page(s)** en cours... (~{est}s)")
            async with message.channel.typing():
                embed = await scan(market_hash_name, pages=pages)
            await message.reply(embed=embed)
            return
        elif content.lower() in ("annuler", "cancel", "non", "/cancel"):
            pending.pop(uid)
            await message.reply("❌ Analyse annulée.")
            return
        else:
            await message.reply("Réponds avec un **nombre** de pages (ex: `5`) ou `annuler`.")
            return

    # ── /cancel ─────────────────────────────────────────
    if content.lower() == "/cancel":
        if uid in pending:
            pending.pop(uid)
            await message.reply("❌ Analyse annulée.")
        else:
            await message.reply("Aucune analyse en cours.")
        return

    # ── /info ───────────────────────────────────────────
    if content.lower() == "/info":
        embed = discord.Embed(
            color=0x5865F2,
            description=(
                "## 👋  Bonjour Seigneur du caca !\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Voici toutes mes commandes :"
            ),
        )
        embed.add_field(
            name="🔗  Lien Steam Market",
            value="> Envoie un lien → je te demande combien de pages analyser",
            inline=False,
        )
        embed.add_field(
            name="🔍  `!analyse <nom du charm>`",
            value="> Analyse complète d'un charm mémorisé",
            inline=False,
        )
        embed.add_field(
            name="📋  `!charms`",
            value="> Liste tous les charms mémorisés",
            inline=False,
        )
        embed.add_field(
            name="ℹ️  `/info`",
            value="> Affiche ce menu",
            inline=False,
        )
        embed.add_field(
            name="❌  `/cancel`",
            value="> Annule la recherche en cours",
            inline=False,
        )
        embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market")
        await message.reply(embed=embed)
        return

    # ── !charms ─────────────────────────────────────────
    if content.lower() == "!charms":
        entries = storage.get_all()
        if not entries:
            await message.reply("📭 Aucun charm mémorisé pour l'instant.")
            return
        embed = discord.Embed(
            color=0xFFD700,
            description=f"## 🗃️  Charms mémorisés ({len(entries)})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )
        for info in entries[-20:]:
            name_short = info["weapon"][:35] + "…" if len(info["weapon"]) > 35 else info["weapon"]
            val = (
                f"> 🔑 `{info['charm_name']}`\n"
                f"> 💰 {info['price_with_charm']:.2f} €  •  📍 Page {info.get('page','?')}, pos {info.get('position','?')}\n"
                f"> 🕐 {info['last_updated']}"
            )
            embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)
        embed.set_footer(text="Tape !analyse <charm> pour l'analyse complète")
        await message.reply(embed=embed)
        return

    # ── !analyse <charm> ────────────────────────────────
    if content.lower().startswith("!analyse "):
        charm_name = content[9:].strip()
        if not charm_name:
            await message.reply("Usage : `!analyse <nom du charm>`")
            return
        async with message.channel.typing():
            embed = await analyse_charm(charm_name)
        await message.reply(embed=embed)
        return

    # ── Lien Steam Market → demande le nombre de pages ──
    matches = STEAM_URL_RE.findall(content)
    if matches:
        market_hash_name = unquote(matches[0]).rstrip("/")
        pending[uid] = market_hash_name
        await message.reply(
            f"🔗 Lien reçu : **{market_hash_name[:60]}**\n\n"
            f"Combien de pages veux-tu analyser ? *(1 page = 10 listings)*"
        )


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("DISCORD_TOKEN manquant dans le fichier .env")

client.run(token)
