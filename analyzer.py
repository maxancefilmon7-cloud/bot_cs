import re
import discord
from bs4 import BeautifulSoup
from steam_api import SteamMarketAPI
import storage

api = SteamMarketAPI()

STEAM_FEE = 0.15

# Couleurs thème CS2
COLOR_GOLD    = 0xFFD700
COLOR_GREEN   = 0x2ECC71
COLOR_RED     = 0xE74C3C
COLOR_ORANGE  = 0xFF6B35


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


def discount_bar(pct: float, length: int = 10) -> str:
    """Barre visuelle de progression Unicode."""
    filled = round(abs(pct) / 100 * length)
    filled = min(filled, length)
    bar = "█" * filled + "░" * (length - filled)
    return f"`{bar}` {abs(pct):.1f}%"


def verdict(discount_pct: float | None) -> tuple[str, int]:
    """Retourne un emoji verdict + couleur selon l'opportunité."""
    if discount_pct is None:
        return "⬜ Neutre", COLOR_GOLD
    if discount_pct >= 30:
        return "🔥 BONNE AFFAIRE", COLOR_GREEN
    if discount_pct >= 10:
        return "✅ Intéressant", 0x27AE60
    if discount_pct >= 0:
        return "🟡 Prix marché", COLOR_GOLD
    return "🔴 Surpayé", COLOR_RED


def extract_charm_from_descriptions(descriptions: list) -> tuple[str, str] | None:
    """Extract charm info from asset descriptions.

    Steam stores charm info in a description entry with name="keychain_info".
    The charm name appears inside the HTML as:
      - title="Charm: <name>"  (regular charms)
      - title="Souvenir Charm: <name>"  (souvenir charms)
      - plain text after <br> in the same format

    Returns a tuple (display_name, market_hash_name) or None.
      - display_name: e.g. "Charm: Biomech" or "Souvenir Charm: Austin 2025 ..."
      - market_hash_name: e.g. "Charm | Biomech" or "Souvenir Charm | Austin 2025 ..."
    """
    for desc in descriptions:
        # Primary detection: the structured "keychain_info" description entry
        if desc.get("name") == "keychain_info":
            value = desc.get("value", "")
            # Try extracting from the title attribute first (most reliable)
            match = re.search(r'title="((?:Souvenir )?Charm:\s*[^"]+)"', value)
            if match:
                full_title = match.group(1).strip()
                # full_title = "Charm: Biomech" or "Souvenir Charm: Austin 2025 ..."
                display_name = full_title
                # Market hash uses " | " instead of ": "
                market_hash = full_title.replace(": ", " | ", 1)
                return display_name, market_hash
            # Fallback: extract from the visible text after <br>
            soup = BeautifulSoup(value, "html.parser")
            text = soup.get_text(separator=" ").strip()
            match = re.search(r"((?:Souvenir )?Charm:\s*.+)", text, re.IGNORECASE)
            if match:
                full_title = match.group(1).strip()
                display_name = full_title
                market_hash = full_title.replace(": ", " | ", 1)
                return display_name, market_hash
    return None


def extract_icon_url(assets: dict) -> str | None:
    """Récupère l'URL de l'image de l'item depuis les assets Steam."""
    for asset_data in assets.values():
        icon = asset_data.get("icon_url")
        if icon:
            return f"https://community.cloudflare.steamstatic.com/economy/image/{icon}/256x256"
    return None


def resale_analysis(buy_price: float) -> dict:
    return {
        "break_even": buy_price / (1 - STEAM_FEE),
        "profit_10":  buy_price * 1.10 / (1 - STEAM_FEE),
        "profit_20":  buy_price * 1.20 / (1 - STEAM_FEE),
    }


async def analyze(market_hash_name: str) -> discord.Embed:
    try:
        # 1. Prix global
        price_data = await api.get_price_overview(market_hash_name)
        if not price_data.get("success"):
            return _error_embed("Item introuvable sur le Steam Market.")

        lowest_price = parse_price_str(price_data.get("lowest_price", ""))
        median_price  = parse_price_str(price_data.get("median_price", ""))
        volume        = price_data.get("volume", "N/A")

        # 2. Listings individuels (200 listings = 2 pages de 100)
        listings_data = await api.get_all_listings(market_hash_name, pages=2)

        raw_assets = listings_data.get("assets", {})
        if not isinstance(raw_assets, dict):
            raw_assets = {}
        assets = raw_assets.get("730", {})
        if not isinstance(assets, dict):
            assets = {}
        assets = assets.get("2", {})
        if not isinstance(assets, dict):
            assets = {}

        listinginfo = listings_data.get("listinginfo", {})
        if not isinstance(listinginfo, dict):
            listinginfo = {}

        asset_prices: dict[str, float] = {}
        for linfo in listinginfo.values():
            if not isinstance(linfo, dict):
                continue
            asset_id = linfo.get("asset", {}).get("id")
            if not asset_id:
                continue
            total = (linfo.get("price", 0) + linfo.get("fee", 0)) / 100
            asset_prices[asset_id] = total

        # Regrouper les charms trouvés : {charm_display: {"market": charm_market, "prices": [...]}}
        charms_found: dict[str, dict] = {}

        for asset_id, asset_data in assets.items():
            price = asset_prices.get(asset_id)
            if price is None:
                continue
            result = extract_charm_from_descriptions(asset_data.get("descriptions", []))
            if result:
                display, market = result
                if display not in charms_found:
                    charms_found[display] = {"market": market, "prices": []}
                charms_found[display]["prices"].append(price)

        # 3. Prix standalone de chaque charm unique
        import asyncio
        for display, info in charms_found.items():
            try:
                c = await api.get_price_overview(info["market"])
                if c.get("success"):
                    info["standalone"] = parse_price_str(c.get("lowest_price", ""))
                else:
                    info["standalone"] = None
            except Exception:
                info["standalone"] = None
            await asyncio.sleep(0.5)  # anti rate-limit entre chaque lookup

        # 4. Calculs — on utilise lowest_price comme base fiable (pas la moyenne des listings)
        base_price = lowest_price  # prix minimum du marché sans distinction charm/non-charm

        # Sauvegarder chaque charm trouvé
        for display, info in charms_found.items():
            min_c = min(info["prices"])
            storage.save_charm(
                weapon=market_hash_name,
                charm_name=display,
                price_with_charm=min_c,
                price_without_charm=base_price,
                charm_standalone=info.get("standalone"),
            )

        # Verdict global basé sur le meilleur charm (celui avec le plus grand écart)
        best_disc = None
        for info in charms_found.values():
            standalone = info.get("standalone")
            min_c = min(info["prices"])
            implied = min_c - base_price
            if standalone and standalone > 0:
                disc = ((standalone - implied) / standalone) * 100
                if best_disc is None or disc > best_disc:
                    best_disc = disc

        label, color = verdict(best_disc)

        # 5. Construction de l'embed
        item_name_short = market_hash_name[:50] + "…" if len(market_hash_name) > 50 else market_hash_name
        icon_url = extract_icon_url(assets)

        embed = discord.Embed(
            color=color,
            description=(
                f"## 🎯  {item_name_short}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
        )

        if icon_url:
            embed.set_thumbnail(url=icon_url)

        # Bloc prix marché
        embed.add_field(
            name="〔 💰 MARCHÉ STEAM 〕",
            value=(
                f"> 📉  Minimum   —  {fmt(lowest_price)}\n"
                f"> 📊  Médiane   —  {fmt(median_price)}\n"
                f"> 🔄  Volume 24h — **{volume} ventes**"
            ),
            inline=False,
        )

        if charms_found:
            embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)

            total_charm_listings = sum(len(i["prices"]) for i in charms_found.values())
            embed.add_field(
                name=f"〔 🔑 {len(charms_found)} CHARM(S) DÉTECTÉ(S) — {total_charm_listings} listings 〕",
                value=f"> 🔫  Prix de base (marché)  —  {fmt(base_price)}",
                inline=False,
            )

            # Afficher chaque charm trouvé
            for display, info in charms_found.items():
                min_c = min(info["prices"])
                standalone = info.get("standalone")
                implied = min_c - base_price
                disc_pct = (((standalone - implied) / standalone) * 100
                            if standalone and standalone > 0 else None)

                val = (
                    f"> 🏷️  Arme + Charm  —  {fmt(min_c)}\n"
                    f"> 💡  Valeur charm  —  {fmt(implied)}\n"
                )
                if standalone:
                    val += f"> 💎  Charm seul    —  {fmt(standalone)}\n"
                if disc_pct is not None:
                    direction = "sous le marché ↓" if disc_pct > 0 else "au-dessus ↑"
                    val += f"> 📊  {direction}  {discount_bar(disc_pct)}\n"

                r = resale_analysis(min_c)
                val += (
                    f"> ⚖️  Revente seuil — {fmt(r['break_even'])}  "
                    f"| +10% {fmt(r['profit_10'])}"
                )

                embed.add_field(
                    name=f"✨ {display}  ({len(info['prices'])} listing{'s' if len(info['prices']) > 1 else ''})",
                    value=val,
                    inline=False,
                )

            embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
            embed.add_field(
                name="〔 🏁 VERDICT 〕",
                value=f"> {label}",
                inline=False,
            )

        else:
            embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
            embed.add_field(
                name="〔 ⚠️ AUCUN CHARM DÉTECTÉ 〕",
                value=(
                    "> Aucun Key Chain trouvé dans les 200 premiers listings.\n"
                    "> Cette arme n'a pas de charm dans les annonces actuelles."
                ),
                inline=False,
            )
            if lowest_price:
                r = resale_analysis(lowest_price)
                embed.add_field(
                    name="〔 📈 ESTIMATION REVENTE 〕",
                    value=(
                        f"> ⚖️  Seuil rentabilité  —  {fmt(r['break_even'])}\n"
                        f"> 🟢  Revente **+10%**    —  {fmt(r['profit_10'])}\n"
                        f"> 🚀  Revente **+20%**    —  {fmt(r['profit_20'])}\n"
                        f"> *après frais Steam 15%*"
                    ),
                    inline=False,
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


def _error_embed(message: str) -> discord.Embed:
    embed = discord.Embed(
        color=COLOR_RED,
        description=(
            f"## ❌  Erreur\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"> {message}"
        ),
    )
    embed.set_footer(text="CS2 Charm Analyzer  •  Steam Market")
    return embed
