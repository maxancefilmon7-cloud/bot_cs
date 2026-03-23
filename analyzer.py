import re
import asyncio
import discord
from steam_api import SteamMarketAPI
import storage

api = SteamMarketAPI()

STEAM_FEE = 0.15
COLOR_BLUE  = 0x5865F2
COLOR_GOLD  = 0xFFD700
COLOR_GREEN = 0x2ECC71
COLOR_RED   = 0xE74C3C


def parse_price(price_str: str) -> float:
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^\d,.]", "", price_str)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fmt(price: float) -> str:
    return f"**{price:.2f} €**"


def resale(buy: float) -> dict:
    return {
        "be":  buy / (1 - STEAM_FEE),
        "p10": buy * 1.10 / (1 - STEAM_FEE),
        "p20": buy * 1.20 / (1 - STEAM_FEE),
    }


def verdict(disc: float | None) -> str:
    if disc is None:
        return "⬜ Neutre"
    if disc >= 30:
        return "🔥 BONNE AFFAIRE"
    if disc >= 10:
        return "✅ Intéressant"
    if disc >= 0:
        return "🟡 Prix marché"
    return "🔴 Surpayé"


def extract_charm_name(descriptions: list) -> str | None:
    """
    Extrait le nom du charm depuis les descriptions d'un asset Steam.
    Cherche l'entrée avec name='keychain_info' et parse le title de l'image.
    Exemple: title="Porte-bonheur: Pistolaine" → "Pistolaine"
    """
    for desc in descriptions:
        if desc.get("name") != "keychain_info":
            continue
        value = desc.get("value", "")
        # Extraire le title de la balise <img>
        m = re.search(r'title="([^"]+)"', value)
        if not m:
            continue
        title = m.group(1).strip()
        # "Porte-bonheur: Pistolaine" → "Pistolaine"
        m2 = re.match(r"Porte-bonheur\s*(?:\(Souvenir\))?\s*:\s*(.+)", title, re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
        # Fallback: retourner le title brut
        return title
    return None


def _parse_page(data: dict, page_num: int) -> tuple[list, int]:
    """Extrait les listings et charms d'une page Steam. Retourne (charms, total_count)."""
    raw_assets = data.get("assets", {})
    assets = raw_assets.get("730", {}) if isinstance(raw_assets, dict) else {}
    assets = assets.get("2", {}) if isinstance(assets, dict) else {}

    listinginfo = data.get("listinginfo", {})
    if not isinstance(listinginfo, dict):
        listinginfo = {}

    total_count = data.get("total_count", 0)

    charms = []
    position = 1
    for linfo in listinginfo.values():
        if not isinstance(linfo, dict):
            continue
        aid = linfo.get("asset", {}).get("id")
        if not aid or aid not in assets:
            position += 1
            continue
        price = (
            linfo.get("converted_price", linfo.get("price", 0)) +
            linfo.get("converted_fee", linfo.get("fee", 0))
        ) / 100
        if price <= 0 or price > 50000:
            position += 1
            continue

        charm_name = extract_charm_name(assets[aid].get("descriptions", []))
        if charm_name:
            charms.append({
                "name": charm_name,
                "price": price,
                "page": page_num,
                "position": position,
            })
        position += 1

    return charms, total_count


async def scan(market_hash_name: str) -> discord.Embed:
    """Scanne 10 pages (100 listings) et liste tous les charms trouvés."""
    try:
        all_charms = []
        total_count = 0
        pages_scanned = 0

        for page_num in range(1, 11):
            start = (page_num - 1) * 10
            data = await api.get_page(market_hash_name, start=start)
            charms, tc = _parse_page(data, page_num)
            all_charms.extend(charms)
            if page_num == 1:
                total_count = tc
            pages_scanned += 1

            # Arrêter si on a atteint la fin des listings
            if start + 10 >= tc:
                break

            await asyncio.sleep(1.2)  # Anti rate-limit Steam

        # Sauvegarder
        for c in all_charms:
            storage.save_charm(
                weapon=market_hash_name,
                charm_name=c["name"],
                price_with_charm=c["price"],
                price_without_charm=None,
                charm_standalone=None,
                page=c["page"],
                position=c["position"],
            )

        name_short = market_hash_name[:55] + "…" if len(market_hash_name) > 55 else market_hash_name

        if not all_charms:
            embed = discord.Embed(
                color=COLOR_BLUE,
                description=(
                    f"## 🎯  {name_short}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"> 📦 {pages_scanned * 10} listings analysés ({pages_scanned} pages) • {total_count} en tout\n"
                    f"\n〔 ⚠️ Aucun porte-bonheur trouvé 〕"
                ),
            )
            embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market")
            return embed

        embed = discord.Embed(
            color=COLOR_GREEN,
            description=(
                f"## 🎯  {name_short}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"> 📦 {pages_scanned * 10} listings analysés ({pages_scanned} pages) • {total_count} en tout\n"
                f"> 🔑 **{len(all_charms)} porte-bonheur(s) trouvé(s)**"
            ),
        )

        for c in all_charms:
            embed.add_field(
                name=f"✨ {c['name']}",
                value=(
                    f"> 🏷️  Arme + porte-bonheur : {fmt(c['price'])}\n"
                    f"> 📍  Page **{c['page']}**, position **{c['position']}**"
                ),
                inline=False,
            )

        embed.set_footer(
            text="CS2 Charm Analyzer  •  Steam Market  •  Tape !analyse <nom> pour l'analyse complète",
            icon_url="https://store.steampowered.com/favicon.ico",
        )
        return embed

    except RuntimeError as e:
        return _error_embed(str(e))
    except Exception as e:
        return _error_embed(f"Erreur : {e}")


async def analyse_charm(query: str) -> discord.Embed:
    matches = storage.search_charm(query)
    if not matches:
        return _error_embed(
            f"Charm `{query}` introuvable.\n"
            "> Envoie d'abord un lien Steam Market, puis utilise `!charms`."
        )

    embed = discord.Embed(
        color=COLOR_GOLD,
        description=f"## 🔍  Analyse — `{query}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    )

    for info in matches[:5]:
        price_with = info["price_with_charm"]
        r = resale(price_with)
        pos = info.get("position", "?")

        val = (
            f"> 🏷️  Arme + charm    — {fmt(price_with)}\n"
            f"> ⚖️  Seuil rentab.  — {fmt(r['be'])}\n"
            f"> 🟢  Revente +10%  — {fmt(r['p10'])}\n"
            f"> 🚀  Revente +20%  — {fmt(r['p20'])}\n"
            f"> 📍  Page 1, position **{pos}**\n"
            f"> 🕐  {info.get('last_updated', 'N/A')}"
        )
        name_short = info["weapon"][:45] + "…" if len(info["weapon"]) > 45 else info["weapon"]
        embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)

    embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market  •  Frais Steam : 15%")
    return embed


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        color=COLOR_RED,
        description=f"## ❌  Erreur\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n> {message}",
    )
