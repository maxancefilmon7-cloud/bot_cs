import re
import asyncio
import discord
from bs4 import BeautifulSoup
from steam_api import SteamMarketAPI
import storage

api = SteamMarketAPI()

STEAM_FEE = 0.15
COLOR_GOLD  = 0xFFD700
COLOR_GREEN = 0x2ECC71
COLOR_RED   = 0xE74C3C
COLOR_BLUE  = 0x5865F2

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
    return f"`{'█' * filled}{'░' * (length - filled)}` {abs(pct):.1f}%"


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
            # Chercher dans l'attribut title (le plus fiable)
            m = re.search(r'title="((?:Souvenir )?Charm:\s*[^"]+)"', value)
            if m:
                display = m.group(1).strip()
                return display, display.replace(": ", " | ", 1)
            # Fallback: texte visible
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


async def _fetch_charms(market_hash_name: str):
    """
    Retourne:
      - assets (dict)
      - charms_found: {display: {"market": str, "listings": [(price, page, pos)]}}
      - lowest, median, volume
    """
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

    listinginfo = listings_data.get("listinginfo", {})
    if not isinstance(listinginfo, dict):
        listinginfo = {}

    # Construire la liste triée par prix croissant
    listing_list = []
    for linfo in listinginfo.values():
        if not isinstance(linfo, dict):
            continue
        aid = linfo.get("asset", {}).get("id")
        if not aid or aid not in assets:
            continue  # Ignorer si l'asset n'existe pas dans la réponse
        total = (linfo.get("price", 0) + linfo.get("fee", 0)) / 100
        if total <= 0 or total > MAX_LISTING_PRICE:
            continue
        listing_list.append((aid, total))

    listing_list.sort(key=lambda x: x[1])

    charms_found: dict[str, dict] = {}
    for position, (aid, price) in enumerate(listing_list):
        adata = assets[aid]
        result = extract_charm(adata.get("descriptions", []))
        if not result:
            continue
        display, market = result
        page = (position // 10) + 1
        pos_in_page = (position % 10) + 1
        if display not in charms_found:
            charms_found[display] = {"market": market, "listings": []}
        charms_found[display]["listings"].append((price, page, pos_in_page))

    return assets, charms_found, lowest, median, volume


# ─────────────────────────────────────────────────────
# MODE 1 : scan — liste des charms avec prix exacts
# ─────────────────────────────────────────────────────
async def scan(market_hash_name: str) -> discord.Embed:
    try:
        assets, charms_found, lowest, median, volume = await _fetch_charms(market_hash_name)

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
        total = sum(len(i["listings"]) for i in charms_found.values())
        embed.add_field(
            name=f"〔 🔑 {len(charms_found)} CHARM(S) TROUVÉ(S) — {total} listings 〕",
            value=f"> 🔫  Prix arme seule — {fmt(lowest)}\n> *Tape `!analyse <nom>` pour l'analyse complète*",
            inline=False,
        )

        for display, info in charms_found.items():
            listings = info["listings"]  # [(price, page, pos), ...]
            page0, pos0 = listings[0][1], listings[0][2]

            # Récupérer le prix standalone du charm maintenant
            standalone = None
            try:
                c = await api.get_price_overview(info["market"])
                if c.get("success"):
                    standalone = parse_price_str(c.get("lowest_price", ""))
            except Exception:
                pass
            await asyncio.sleep(0.3)

            # Sauvegarder
            min_price = min(p for p, _, _ in listings)
            storage.save_charm(
                weapon=market_hash_name,
                charm_name=display,
                price_with_charm=min_price,
                price_without_charm=lowest,
                charm_standalone=standalone,
                page=page0,
                position=pos0,
            )

            # Afficher chaque listing individuel
            lines = ""
            if standalone:
                lines += f"> 💎 Prix du charm (marché) : **{standalone:.2f} €**\n"
            else:
                lines += f"> 💎 Prix du charm : *introuvable*\n"
            lines += "\n"
            for price, pg, ps in listings[:6]:
                lines += f"> 🏷️ **{price:.2f} €** *(arme+charm)*  —  page {pg}, pos. {ps}\n"
            if len(listings) > 6:
                lines += f"> *...et {len(listings)-6} autre(s) listing(s)*\n"

            embed.add_field(name=f"✨ {display}", value=lines, inline=False)

        embed.set_footer(
            text="CS2 Charm Analyzer  •  Steam Market  •  Frais Steam : 15%",
            icon_url="https://store.steampowered.com/favicon.ico",
        )
        return embed

    except RuntimeError as e:
        return _error_embed(str(e))
    except Exception as e:
        return _error_embed(f"Erreur inattendue : {e}")


# ─────────────────────────────────────────────────────
# MODE 2 : analyse complète d'un charm
# ─────────────────────────────────────────────────────
async def analyse_charm(query: str) -> discord.Embed:
    matches = storage.search_charm(query)
    if not matches:
        return _error_embed(
            f"Charm `{query}` introuvable.\n"
            "> Envoie d'abord un lien Steam Market, puis utilise `!charms` pour voir les noms."
        )

    embed = discord.Embed(
        color=COLOR_GOLD,
        description=f"## 🔍  Analyse — `{query}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    )

    for info in matches[:5]:
        charm_name  = info["charm_name"]
        market_hash = charm_name.replace(": ", " | ", 1)
        price_with  = info["price_with_charm"]
        base        = info.get("price_without_charm") or 0.0
        page        = info.get("page", "?")
        pos         = info.get("position", "?")

        standalone = info.get("charm_standalone")
        try:
            c = await api.get_price_overview(market_hash)
            if c.get("success"):
                standalone = parse_price_str(c.get("lowest_price", ""))
        except Exception:
            pass

        implied  = price_with - base if base else None
        disc_pct = (((standalone - implied) / standalone) * 100
                    if standalone and implied and standalone > 0 else None)
        label, _ = verdict(disc_pct)
        r = resale(price_with)

        val  = f"> 🔫  Arme seule      —  **{base:.2f} €**\n" if base else ""
        val += f"> 🏷️  Arme + Charm   —  **{price_with:.2f} €**\n"
        if implied and implied > 0:
            val += f"> 💡  Valeur charm   —  **{implied:.2f} €** *(différence)*\n"
        if standalone:
            val += f"> 💎  Charm seul     —  **{standalone:.2f} €** *(marché)*\n"
        if disc_pct is not None:
            direction = "sous le marché ↓" if disc_pct > 0 else "au-dessus ↑"
            val += f"> 📊  {direction}  {discount_bar(disc_pct)}\n"
        val += (
            f"> ⚖️  Seuil rentab.  —  **{r['be']:.2f} €**\n"
            f"> 🟢  Revente +10%  —  **{r['p10']:.2f} €**\n"
            f"> 🚀  Revente +20%  —  **{r['p20']:.2f} €**\n"
            f"> 📍  Trouvé page **{page}**, position **{pos}**\n"
            f"> 🕐  {info.get('last_updated', 'N/A')}\n"
            f"> **{label}**"
        )
        name_short = info["weapon"][:45] + "…" if len(info["weapon"]) > 45 else info["weapon"]
        embed.add_field(name=f"🔫 {name_short}", value=val, inline=False)

    embed.set_footer(
        text="CS2 Charm Analyzer  •  Steam Market  •  Frais Steam : 15%",
        icon_url="https://store.steampowered.com/favicon.ico",
    )
    return embed


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        color=COLOR_RED,
        description=f"## ❌  Erreur\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n> {message}",
    )
