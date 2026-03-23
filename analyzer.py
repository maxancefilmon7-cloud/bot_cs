import re
import discord
from urllib.parse import unquote
from bs4 import BeautifulSoup
from steam_api import SteamMarketAPI

api = SteamMarketAPI()

# Frais Steam CS2 : 15% (13% Steam + 2% Valve)
STEAM_FEE = 0.15


def parse_price_str(price_str: str) -> float:
    """Convertit '12,34 €' ou '$12.34' en float."""
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^\d,.]", "", price_str)
    # Gère les formats européens (virgule décimale) et US (point décimal)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def extract_charm_from_descriptions(descriptions: list) -> str | None:
    """
    Parse les descriptions d'un asset CS2 pour trouver un Key Chain (charm).
    Steam retourne du HTML dans le champ 'value'.
    """
    for desc in descriptions:
        value = desc.get("value", "")
        if "Key Chain" in value:
            soup = BeautifulSoup(value, "html.parser")
            text = soup.get_text(separator=" ")
            match = re.search(r"Key Chain\s*:\s*(.+)", text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return None


def resale_analysis(buy_price: float) -> dict:
    """
    Calcule les seuils de revente après frais Steam.
    Le vendeur reçoit : prix_vente * (1 - STEAM_FEE)
    Pour récupérer buy_price : prix_vente = buy_price / (1 - STEAM_FEE)
    """
    break_even = buy_price / (1 - STEAM_FEE)
    profit_10 = buy_price * 1.10 / (1 - STEAM_FEE)
    profit_20 = buy_price * 1.20 / (1 - STEAM_FEE)
    return {
        "break_even": break_even,
        "profit_10": profit_10,
        "profit_20": profit_20,
    }


async def analyze(market_hash_name: str) -> discord.Embed:
    """
    Analyse complète d'un item CS2 avec charm.
    Retourne un embed Discord avec toutes les infos de prix.
    """
    try:
        # 1. Prix global de l'item
        price_data = await api.get_price_overview(market_hash_name)

        if not price_data.get("success"):
            return _error_embed("Item introuvable sur le Steam Market.")

        lowest_price = parse_price_str(price_data.get("lowest_price", ""))
        median_price = parse_price_str(price_data.get("median_price", ""))
        volume = price_data.get("volume", "N/A")

        # 2. Listings individuels pour détecter les charms
        listings_data = await api.get_listings(market_hash_name, count=30)

        assets = listings_data.get("assets", {}).get("730", {}).get("2", {})
        listinginfo = listings_data.get("listinginfo", {})

        # Associer chaque listing à son asset et son prix
        asset_prices: dict[str, float] = {}
        for lid, linfo in listinginfo.items():
            asset_id = linfo.get("asset", {}).get("id")
            if not asset_id:
                continue
            price_cents = linfo.get("price", 0)
            fee_cents = linfo.get("fee", 0)
            total_euros = (price_cents + fee_cents) / 100
            asset_prices[asset_id] = total_euros

        charm_name = None
        charm_listing_prices: list[float] = []
        no_charm_listing_prices: list[float] = []

        for asset_id, asset_data in assets.items():
            price = asset_prices.get(asset_id)
            if price is None:
                continue
            descriptions = asset_data.get("descriptions", [])
            charm = extract_charm_from_descriptions(descriptions)
            if charm:
                charm_listing_prices.append(price)
                if charm_name is None:
                    charm_name = charm
            else:
                no_charm_listing_prices.append(price)

        # 3. Prix du charm seul sur le marché
        charm_standalone: float | None = None
        if charm_name:
            try:
                charm_data = await api.get_price_overview(charm_name)
                if charm_data.get("success"):
                    charm_standalone = parse_price_str(charm_data.get("lowest_price", ""))
            except Exception:
                pass

        # 4. Construction de l'embed
        embed = discord.Embed(
            title="🔍 Analyse CS2 — Charm Market",
            description=f"**{market_hash_name}**",
            color=0xF5A623,
        )

        # Prix global
        embed.add_field(
            name="💰 Prix Steam Market (global)",
            value=(
                f"**Minimum :** {lowest_price:.2f} €\n"
                f"**Médiane :** {median_price:.2f} €\n"
                f"**Volume 24h :** {volume} ventes"
            ),
            inline=False,
        )

        # Charm détecté
        if charm_name:
            embed.add_field(
                name="🔑 Charm détecté",
                value=f"`{charm_name}`",
                inline=False,
            )

            min_with_charm = min(charm_listing_prices) if charm_listing_prices else None
            avg_no_charm = (
                sum(no_charm_listing_prices) / len(no_charm_listing_prices)
                if no_charm_listing_prices
                else None
            )

            if min_with_charm:
                embed.add_field(
                    name="🏷️ Arme + Charm (moins cher)",
                    value=f"**{min_with_charm:.2f} €**",
                    inline=True,
                )

            if avg_no_charm:
                embed.add_field(
                    name="🔫 Arme sans Charm (moy.)",
                    value=f"**{avg_no_charm:.2f} €**",
                    inline=True,
                )

            if charm_standalone:
                embed.add_field(
                    name="💎 Charm seul (marché)",
                    value=f"**{charm_standalone:.2f} €**",
                    inline=True,
                )

            # Valeur implicite du charm
            if min_with_charm and avg_no_charm:
                implied = min_with_charm - avg_no_charm
                implied_text = f"Valeur implicite du charm : **{implied:.2f} €**\n"
                if charm_standalone and charm_standalone > 0:
                    discount_pct = ((charm_standalone - implied) / charm_standalone) * 100
                    if discount_pct > 0:
                        implied_text += f"📊 Le charm est à **{discount_pct:.1f}% sous** son prix marché\n"
                    else:
                        implied_text += f"📊 Le charm est à **{abs(discount_pct):.1f}% au-dessus** de son prix marché\n"
                embed.add_field(
                    name="📊 Valeur du Charm",
                    value=implied_text,
                    inline=False,
                )

            # Estimation de revente
            if min_with_charm:
                resale = resale_analysis(min_with_charm)
                embed.add_field(
                    name="📈 Estimation de revente",
                    value=(
                        f"**Seuil rentabilité :** {resale['break_even']:.2f} €\n"
                        f"**Revente +10% :** {resale['profit_10']:.2f} €\n"
                        f"**Revente +20% :** {resale['profit_20']:.2f} €\n"
                        f"*Frais Steam déduits (15%)*"
                    ),
                    inline=False,
                )
        else:
            embed.add_field(
                name="⚠️ Aucun charm détecté",
                value=(
                    "Aucun Key Chain trouvé dans les 30 premiers listings.\n"
                    "L'item n'a peut-être pas de charm, ou il est très rare dans les annonces actuelles."
                ),
                inline=False,
            )

            # Quand même afficher l'estimation de revente sur le prix global
            if lowest_price:
                resale = resale_analysis(lowest_price)
                embed.add_field(
                    name="📈 Estimation de revente (sans charm)",
                    value=(
                        f"**Seuil rentabilité :** {resale['break_even']:.2f} €\n"
                        f"**Revente +10% :** {resale['profit_10']:.2f} €\n"
                        f"**Revente +20% :** {resale['profit_20']:.2f} €\n"
                        f"*Frais Steam déduits (15%)*"
                    ),
                    inline=False,
                )

        embed.set_footer(text="Données : Steam Market • Frais Steam CS2 : 15%")
        return embed

    except RuntimeError as e:
        return _error_embed(str(e))
    except Exception as e:
        return _error_embed(f"Erreur inattendue : {e}")


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="❌ Erreur",
        description=message,
        color=0xFF0000,
    )
