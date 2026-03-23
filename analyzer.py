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

        charm_display = None   # e.g. "Charm: Biomech"
        charm_market = None    # e.g. "Charm | Biomech"
        charm_prices: list[float] = []
        no_charm_prices: list[float] = []

        for asset_id, asset_data in assets.items():
            price = asset_prices.get(asset_id)
            if price is None:
                continue
            result = extract_charm_from_descriptions(asset_data.get("descriptions", []))
            if result:
                charm_prices.append(price)
                if charm_display is None:
                    charm_display, charm_market = result
            else:
                no_charm_prices.append(price)

        # 3. Prix du charm seul
        charm_standalone: float | None = None
        if charm_market:
            try:
                c = await api.get_price_overview(charm_market)
                if c.get("success"):
                    charm_standalone = parse_price_str(c.get("lowest_price", ""))
            except Exception:
                pass

        # 4. Calculs + sauvegarde
        min_charm  = min(charm_prices)    if charm_prices    else None
        avg_base   = (sum(no_charm_prices) / len(no_charm_prices)) if no_charm_prices else None
        implied    = (min_charm - avg_base) if (min_charm and avg_base) else None
        disc_pct   = (((charm_standalone - implied) / charm_standalone) * 100
                      if (charm_standalone and implied and charm_standalone > 0) else None)

        label, color = verdict(disc_pct)

        # Sauvegarder dans la base si charm trouvé
        if charm_display and min_charm:
            storage.save_charm(
                weapon=market_hash_name,
                charm_name=charm_display,
                price_with_charm=min_charm,
                price_without_charm=avg_base,
                charm_standalone=charm_standalone,
            )

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

        if charm_display:
            embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)

            # Charm détecté
            embed.add_field(
                name="〔 🔑 CHARM DÉTECTÉ 〕",
                value=f"> ✨  `{charm_display}`",
                inline=False,
            )

            # Tableau des prix
            prix_lines = ""
            if min_charm:
                prix_lines += f"> 🏷️  Arme **+** Charm     —  {fmt(min_charm)}\n"
            if avg_base:
                prix_lines += f"> 🔫  Arme **sans** charm  —  {fmt(avg_base)}\n"
            if charm_standalone:
                prix_lines += f"> 💎  Charm seul           —  {fmt(charm_standalone)}\n"

            if prix_lines:
                embed.add_field(
                    name="〔 🧾 DÉCOMPOSITION DES PRIX 〕",
                    value=prix_lines,
                    inline=False,
                )

            # Valeur du charm
            if implied is not None:
                charm_section = f"> 💡  Valeur implicite  —  {fmt(implied)}\n"
                if disc_pct is not None:
                    direction = "sous ↓" if disc_pct > 0 else "au-dessus ↑"
                    charm_section += (
                        f"> 📊  Écart marché  —  {direction}\n"
                        f"> {discount_bar(disc_pct)}\n"
                    )
                embed.add_field(
                    name="〔 📊 ANALYSE DU CHARM 〕",
                    value=charm_section,
                    inline=False,
                )

            # Revente
            if min_charm:
                r = resale_analysis(min_charm)
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
