import re
import asyncio
import discord
from bs4 import BeautifulSoup
from steam_api import SteamMarketAPI
import storage

api = SteamMarketAPI()

STEAM_FEE = 0.15
COLOR_GOLD   = 0xFFD700
COLOR_GREEN  = 0x2ECC71
COLOR_RED    = 0xE74C3C
COLOR_BLUE   = 0x5865F2

# Prix max acceptable pour un listing (filtre les listings fantaisistes)
MAX_LISTING_PRICE = 50_000.0


def parse_price_str(price_str: str) -> float:
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


def discount_bar(pct: float, length: int = 8) -> str:
    filled = min(round(abs(pct) / 100 * length), length)
    bar = "█" * filled + "░" * (length - filled)
    return f"`{bar}` {abs(pct):.1f}%"


def verdict(disc: float | None) -> tuple[str, int]:
    if disc is None:
        return "⬜ Neutre", COLOR_GOLD
    if disc >= 30:
        return "🔥 BONNE AFFAIRE", COLOR_GREEN
    if disc >= 10:
        return "✅ Intéressant", 0x27AE60
    if disc >= 0:
        return "🟡 Prix marché", COLOR_GOLD
    return "🔴 Surpayé", COLOR_RED


def resale(buy: float) -> dict:
    return {
        "be":  buy / (1 - STEAM_FEE),
        "p10": buy * 1.10 / (1 - STEAM_FEE),
        "p20": buy * 1.20 / (1 - STEAM_FEE),
    }


def extract_charm(descriptions: list) -> tuple[str, str] | None:
    """Retourne (display_name, market_hash_name) ou None."""
    for desc in descriptions:
        if desc.get("name") == "keychain_info":
            value = desc.get("value", "")
            m = re.search(r'title="((?:Souvenir )?Charm:\s*[^"]+)"', value)
            if m:
                display = m.group(1).strip()
                return display, display.replace(": ", " | ", 1)
            soup = BeautifulSoup(value, "html.parser")
            text = soup.get_text(separator=" ").strip()
            m = re.search(r"((?:Souvenir )?Charm:\s*.+)", text, re.IGNORECASE)
            if m:
                display = m.group(1).strip()
                return display, display.replace(": ", " | ", 1)
    return None


def extract_icon(assets: dict) -> str | None:
    for a in assets.values():
        icon = a.get("icon_url")
        if icon:
            return f"https://community.cloudflare.steamstatic.com/economy/image/{icon}/256x256"
    return None


async def _fetch_listings(market_hash_name: str) -> tuple[dict, dict, float, float, str]:
    """Retourne (assets, charms_found, lowest_price, median_price, volume)."""
    price_data = await api.get_price_overview(market_hash_name)
    if not price_data.get("success"):
        raise RuntimeError("Item introuvable sur le Steam Market.")

    lowest = parse_price_str(price_data.get("lowest_price", ""))
    median = parse_price_str(price_data.get("median_price", ""))
    volume = price_data.get("volume", "N/A")

    listings_data = await api.get_all_listings(market_hash_name, pages=2)

    raw = listings_data.get("assets", {})
    assets = raw.get("730", {}) if isinstance(raw, dict) else {}
    assets = assets.get("2", {}) if isinstance(assets, dict) else {}

    linfo_raw = listings_data.get("listinginfo", {})
    listinginfo = linfo_raw if isinstance(linfo_raw, dict) else {}

    # Construire la liste ordonnée des listings (triés par prix croissant)
    listing_list = []
    for lid, linfo in listinginfo.items():
        if not isinstance(linfo, dict):
            continue
        aid = linfo.get("asset", {}).get("id")
        if not aid:
            continue
        total = (linfo.get("price", 0) + linfo.get("fee", 0)) / 100
        # Filtrer les listings fantaisistes (> 50 000 €)
        if total > MAX_LISTING_PRICE:
            continue
        listing_list.append((aid, total))

    # Trier par prix croissant pour avoir la position réelle
    listing_list.sort(key=lambda x: x[1])

    charms_found: dict[str, dict] = {}
    for position, (aid, price) in enumerate(listing_list):
        adata = assets.get(aid)
        if not adata:
            continue
        result = extract_charm(adata.get("descriptions", []))
        if result:
            display, market = result
            page = (position // 10) + 1   # 10 items par page Steam
            pos_in_page = (position % 10) + 1
            if display not in charms_found:
                charms_found[display] = {
                    "market": market,
                    "prices": [],
                    "first_page": page,
                    "first_pos": pos_in_page,
                }
            charms_found[display]["prices"].append((price, page, pos_in_page))

    return assets, charms_found, lowest, median, volume


# ─────────────────────────────────────────────
# MODE 1 : liste rapide des charms trouvés
# ─────────────────────────────────────────────
async def scan(market_hash_name: str) -> discord.Embed:
    try:
        assets, charms_found, lowest, median, volume = await _fetch_listings(market_hash_name)

        name_short = market_hash_name[:50] + "…" if len(market_hash_name) > 50 else market_hash_name
        icon_url = extract_icon(assets)

        embed = discord.Embed(
            color=COLOR_BLUE,
            description=f"## 🎯  {name_short}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )
        if icon_url:
            embed.set_thumbnail(url=icon_url)

        embed.add_field(
            name="〔 💰 MARCHÉ STEAM 〕",
            value=(
                f"> 📉  Minimum    —  {fmt(lowest)}\n"
                f"> 📊  Médiane   —  {fmt(median)}\n"
                f"> 🔄  Volume 24h — **{volume} ventes**"
            ),
            inline=False,
        )

        if not charms_found:
            embed.add_field(
                name="〔 ⚠️ AUCUN CHARM DÉTECTÉ 〕",
                value="> Aucun Key Chain trouvé dans les 200 premiers listings.",
                inline=False,
            )
            embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market")
            return embed

        embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        total = sum(len(i["prices"]) for i in charms_found.values())
        embed.add_field(
            name=f"〔 🔑 {len(charms_found)} CHARM(S) TROUVÉ(S) — {total} listings 〕",
            value=f"> 🔫  Prix de base — {fmt(lowest)}\n> *Tape `!analyse <nom>` pour l'analyse complète*",
            inline=False,
        )

        for display, info in charms_found.items():
            prices = [p for p, _, _ in info["prices"]]
            min_c = min(prices)
            page = info["first_page"]
            pos  = info["first_pos"]
            count = len(prices)

            # Sauvegarder
            storage.save_charm(
                weapon=market_hash_name,
                charm_name=display,
                price_with_charm=min_c,
                price_without_charm=lowest,
                charm_standalone=None,
                page=page,
                position=pos,
            )

            embed.add_field(
                name=f"✨ {display}",
                value=(
                    f"> 🏷️  Prix min   — {fmt(min_c)}\n"
                    f"> 📦  {count} listing{'s' if count > 1 else ''}\n"
                    f"> 📍  Page {page}, position {pos}"
                ),
                inline=True,
            )

        embed.set_footer(
            text="CS2 Charm Analyzer  •  Steam Market  •  Frais : 15%",
            icon_url="https://store.steampowered.com/favicon.ico",
        )
        return embed

    except RuntimeError as e:
        return _error_embed(str(e))
    except Exception as e:
        return _error_embed(f"Erreur inattendue : {e}")


# ─────────────────────────────────────────────
# MODE 2 : analyse complète d'un charm précis
# ─────────────────────────────────────────────
async def analyse_charm(query: str) -> discord.Embed:
    matches = storage.search_charm(query)

    if not matches:
        return _error_embed(
            f"Charm `{query}` introuvable en base.\n"
            "> Envoie d'abord un lien Steam Market pour scanner, puis utilise `!charms` pour voir les noms exacts."
        )

    embed = discord.Embed(
        color=COLOR_GOLD,
        description=f"## 🔍  Analyse — `{query}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    )

    for info in matches[:5]:
        charm_name = info["charm_name"]
        market_hash = charm_name.replace(": ", " | ", 1)
        price_with = info["price_with_charm"]
        base = info.get("price_without_charm") or 0.0
        page = info.get("page", "?")
        pos  = info.get("position", "?")

        # Récupérer prix standalone en temps réel
        standalone = None
        try:
            c = await api.get_price_overview(market_hash)
            if c.get("success"):
                standalone = parse_price_str(c.get("lowest_price", ""))
                # Mettre à jour la base avec le prix standalone
                storage.save_charm(
                    weapon=info["weapon"],
                    charm_name=charm_name,
                    price_with_charm=price_with,
                    price_without_charm=base,
                    charm_standalone=standalone,
                    page=page if isinstance(page, int) else 0,
                    position=pos if isinstance(pos, int) else 0,
                )
        except Exception:
            pass

        implied = price_with - base if base else None
        disc_pct = (((standalone - implied) / standalone) * 100
                    if standalone and implied and standalone > 0 else None)
        label, color = verdict(disc_pct)
        r = resale(price_with)

        val = f"> 🔫  Arme de base    —  {fmt(base)}\n" if base else ""
        val += f"> 🏷️  Arme + Charm   —  {fmt(price_with)}\n"
        if implied:
            val += f"> 💡  Valeur charm   —  {fmt(implied)}\n"
        if standalone:
            val += f"> 💎  Charm seul     —  {fmt(standalone)}\n"
        if disc_pct is not None:
            direction = "sous le marché ↓" if disc_pct > 0 else "au-dessus ↑"
            val += f"> 📊  {direction}  {discount_bar(disc_pct)}\n"
        val += (
            f"> ⚖️  Seuil rentab. —  {fmt(r['be'])}\n"
            f"> 🟢  Revente +10%  —  {fmt(r['p10'])}\n"
            f"> 🚀  Revente +20%  —  {fmt(r['p20'])}\n"
            f"> 📍  Trouvé page **{page}**, position **{pos}**\n"
            f"> 🕐  {info.get('last_updated', 'N/A')}\n"
            f"> **{label}**"
        )

        name_short = info["weapon"][:45] + "…" if len(info["weapon"]) > 45 else info["weapon"]
        embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)

    embed.set_footer(
        text="CS2 Charm Analyzer  •  Steam Market  •  Frais : 15%",
        icon_url="https://store.steampowered.com/favicon.ico",
    )
    return embed


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        color=COLOR_RED,
        description=f"## ❌  Erreur\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n> {message}",
    )
