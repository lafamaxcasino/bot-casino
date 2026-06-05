import discord
from discord.ext import commands, tasks
import json
import os
import random
import asyncio
import time
from datetime import datetime, timedelta

# ─── Configuration ───────────────────────────────────────────────────────────

PREFIX = "%"
DATA_FILE = "data.json"

# XP config
XP_PER_MESSAGE = (3, 10)
XP_PER_MINUTE_VOCAL = 2
XP_MESSAGE_COOLDOWN = 90

# Couleurs embed
COLOR_GOLD    = 0xF1C40F
COLOR_GREEN   = 0x2ECC71
COLOR_RED     = 0xE74C3C
COLOR_BLUE    = 0x3498DB
COLOR_PURPLE  = 0x9B59B6
COLOR_ORANGE  = 0xE67E22
COLOR_DARK    = 0x2C2F33
COLOR_CASINO  = 0xFF6B35
COLOR_TEAL    = 0x1ABC9C

# Niveaux → rôles
LEVEL_ROLES = {
    5:   "Débutant du casino",
    15:  "Aventurier du casino",
    30:  "Vétéran du casino",
    50:  "Expert du casino",
    100: "Légende du casino",
}

def xp_for_level(level: int) -> int:
    return int(100 * (level ** 1.7))

STARTING_COINS = 100

SHOP_ITEMS = {
    "role_perso": {
        "name": "🎨 Rôle Personnalisé",
        "description": "Un rôle avec la couleur et le nom de votre choix.",
        "price": 8000,
        "emoji": "🎨",
    },
    "xp_boost_1h": {
        "name": "⚡ Boost XP (1h)",
        "description": "Double votre gain d'XP pendant 1 heure.",
        "price": 1200,
        "emoji": "⚡",
    },
    "shield": {
        "name": "🛡️ Bouclier",
        "description": "Protège vos coins lors du prochain vol.",
        "price": 600,
        "emoji": "🛡️",
    },
    "lucky_charm": {
        "name": "🍀 Porte-bonheur",
        "description": "Augmente vos chances au casino pendant 24h (+5%).",
        "price": 2000,
        "emoji": "🍀",
    },
    "daily_bonus": {
        "name": "🎁 Bonus Journalier x2",
        "description": "Double votre prochain %daily.",
        "price": 900,
        "emoji": "🎁",
    },
    "vip_pass": {
        "name": "💎 Pass VIP",
        "description": "Réduit tous vos cooldowns de 50% pendant 6h.",
        "price": 3500,
        "emoji": "💎",
    },
    "insurance": {
        "name": "🔒 Assurance Casino",
        "description": "Remboursement de 50% sur votre prochaine perte au casino.",
        "price": 1500,
        "emoji": "🔒",
    },
}

# ─── Cartes visuelles ─────────────────────────────────────────────────────────
# Rendu ASCII multi-ligne d'une carte à jouer

SUIT_COLORS = {"♠": "♠", "♣": "♣", "♥": "♥", "♦": "♦"}

def render_card(rank: str, suit: str) -> list[str]:
    """Retourne une carte ASCII sous forme de liste de lignes."""
    r = rank.ljust(2)
    rb = rank.rjust(2)
    s = suit
    return [
        "┌─────┐",
        f"│{r}   │",
        f"│  {s}  │",
        f"│   {rb}│",
        "└─────┘",
    ]

def render_card_back() -> list[str]:
    return [
        "┌─────┐",
        "│░░░░░│",
        "│░░░░░│",
        "│░░░░░│",
        "└─────┘",
    ]

def render_hand(cards: list[str], hide_last: bool = False) -> str:
    """Assemble plusieurs cartes côte à côte en ASCII."""
    rendered = []
    for i, card in enumerate(cards):
        rank = card[:-1]
        suit = card[-1]
        if hide_last and i == len(cards) - 1:
            rendered.append(render_card_back())
        else:
            rendered.append(render_card(rank, suit))
    # Coller côte à côte
    lines = []
    for row in range(5):
        lines.append("  ".join(c[row] for c in rendered))
    return "```\n" + "\n".join(lines) + "\n```"

# ─── Data helpers ─────────────────────────────────────────────────────────────

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "xp": 0,
            "level": 0,
            "coins": STARTING_COINS,
            "last_message_xp": 0,
            "last_daily": 0,
            "last_work": 0,
            "last_crime": 0,
            "last_rob": 0,
            "last_cadeau": 0,
            "inventory": [],
            "xp_boost_until": 0,
            "lucky_charm_until": 0,
            "shield": False,
            "daily_bonus_x2": False,
            "vocal_start": 0,
            "casino_wins": 0,
            "casino_losses": 0,
            "total_earned": STARTING_COINS,
            "vip_until": 0,
            "insurance": False,
            "streak_daily": 0,
            "last_daily_streak": 0,
            "total_games_played": 0,
            # Banque
            "bank": 0,
            # Prêt
            "loan_amount": 0,
            "loan_due": 0,
            # Investissement
            "invest_amount": 0,
            "invest_due": 0,
            # Historique (10 dernières transactions)
            "history": [],
            # Palmarès
            "best_jackpot": 0,
            "best_rob": 0,
        }
    defaults = {
        "vip_until": 0, "insurance": False,
        "streak_daily": 0, "last_daily_streak": 0,
        "total_games_played": 0, "total_earned": STARTING_COINS,
        "bank": 0, "loan_amount": 0, "loan_due": 0,
        "invest_amount": 0, "invest_due": 0,
        "history": [], "best_jackpot": 0, "best_rob": 0,
        "last_cadeau": 0,
    }
    for k, v in defaults.items():
        if k not in data[uid]:
            data[uid][k] = v
    return data[uid]

def add_history(user: dict, label: str, amount: int):
    entry = {"label": label, "amount": amount, "ts": int(time.time())}
    user["history"].insert(0, entry)
    user["history"] = user["history"][:10]

def compute_level(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        xp -= xp_for_level(level + 1)
        level += 1
    return level

def xp_progress(xp: int, level: int) -> tuple:
    for l in range(level):
        xp -= xp_for_level(l + 1)
    needed = xp_for_level(level + 1)
    return xp, needed

def get_cooldown_mult(user: dict) -> float:
    if user.get("vip_until", 0) > time.time():
        return 0.5
    return 1.0

def make_progress_bar(current: int, total: int, length: int = 18) -> str:
    filled = int(length * current / total) if total else length
    bar = "▰" * filled + "▱" * (length - filled)
    return f"`{bar}`"

def format_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s2 = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s2:02d}s"

def parse_bet(user: dict, arg: str) -> int | None:
    if arg.lower() in ("all", "tout"):
        return user["coins"]
    try:
        v = int(arg)
        return v if v > 0 else None
    except:
        return None

# ─── Bot setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

vocal_sessions: dict[int, float] = {}

# État global pour le marché noir
blackmarket_state = {
    "last_refresh": 0,
    "items": [],
    "stocks": {},
}

BLACKMARKET_POOL = [
    {"key": "xp_boost_1h",  "name": "⚡ Boost XP",       "base_price": 1200, "emoji": "⚡"},
    {"key": "shield",        "name": "🛡️ Bouclier",       "base_price": 600,  "emoji": "🛡️"},
    {"key": "lucky_charm",   "name": "🍀 Porte-bonheur",  "base_price": 2000, "emoji": "🍀"},
    {"key": "daily_bonus",   "name": "🎁 Bonus Daily x2", "base_price": 900,  "emoji": "🎁"},
    {"key": "vip_pass",      "name": "💎 Pass VIP",        "base_price": 3500, "emoji": "💎"},
    {"key": "insurance",     "name": "🔒 Assurance",       "base_price": 1500, "emoji": "🔒"},
]

def refresh_blackmarket():
    now = time.time()
    if now - blackmarket_state["last_refresh"] < 21600:  # 6h
        return
    chosen = random.sample(BLACKMARKET_POOL, k=random.randint(3, 5))
    blackmarket_state["items"] = []
    blackmarket_state["stocks"] = {}
    for item in chosen:
        discount = random.randint(20, 50)
        price = int(item["base_price"] * (1 - discount / 100))
        stock = random.randint(1, 5)
        blackmarket_state["items"].append({
            "key": item["key"],
            "name": item["name"],
            "emoji": item["emoji"],
            "price": price,
            "discount": discount,
        })
        blackmarket_state["stocks"][item["key"]] = stock
    blackmarket_state["last_refresh"] = now

# ─── Events ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté !")
    if not vocal_xp_loop.is_running():
        vocal_xp_loop.start()
    if not check_loans_loop.is_running():
        check_loans_loop.start()
    if not check_invest_loop.is_running():
        check_invest_loop.start()

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    data = load_data()
    user = get_user(data, message.author.id)
    now = time.time()

    if now - user["last_message_xp"] >= XP_MESSAGE_COOLDOWN:
        gain = random.randint(*XP_PER_MESSAGE)
        if user.get("xp_boost_until", 0) > now:
            gain *= 2
        user["xp"] += gain
        user["last_message_xp"] = now
        new_level = compute_level(user["xp"])
        if new_level > user["level"]:
            user["level"] = new_level
            save_data(data)
            await handle_level_up(message.author, message.guild, new_level, message.channel)
        else:
            save_data(data)
    else:
        save_data(data)

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return
    if before.channel is None and after.channel is not None:
        vocal_sessions[member.id] = time.time()
    elif before.channel is not None and after.channel is None:
        if member.id in vocal_sessions:
            del vocal_sessions[member.id]

@tasks.loop(minutes=1)
async def vocal_xp_loop():
    data = load_data()
    now = time.time()
    for uid, start in list(vocal_sessions.items()):
        user = get_user(data, uid)
        gain = XP_PER_MINUTE_VOCAL
        if user.get("xp_boost_until", 0) > now:
            gain *= 2
        user["xp"] += gain
        new_level = compute_level(user["xp"])
        if new_level > user["level"]:
            user["level"] = new_level
            for guild in bot.guilds:
                member = guild.get_member(uid)
                if member:
                    await handle_level_up(member, guild, new_level, None)
    save_data(data)

@tasks.loop(minutes=10)
async def check_loans_loop():
    """Pénalise les joueurs qui n'ont pas remboursé leur prêt à temps."""
    data = load_data()
    now = time.time()
    for uid, udata in data.items():
        if udata.get("loan_amount", 0) > 0 and udata.get("loan_due", 0) < now:
            penalty = int(udata["loan_amount"] * 1.5)
            udata["coins"] = max(0, udata["coins"] - penalty)
            udata["loan_amount"] = 0
            udata["loan_due"] = 0
            add_history(udata, "💸 Pénalité prêt impayé", -penalty)
    save_data(data)

@tasks.loop(minutes=5)
async def check_invest_loop():
    """Résout les investissements arrivés à échéance."""
    data = load_data()
    now = time.time()
    for uid, udata in data.items():
        if udata.get("invest_amount", 0) > 0 and udata.get("invest_due", 0) <= now:
            amt = udata["invest_amount"]
            mult = random.uniform(-0.30, 0.80)
            gain = int(amt * mult)
            udata["coins"] += amt + gain
            if gain >= 0:
                udata["total_earned"] = udata.get("total_earned", 0) + gain
                add_history(udata, f"📈 Investissement +{gain:,}", gain)
            else:
                add_history(udata, f"📉 Investissement {gain:,}", gain)
            udata["invest_amount"] = 0
            udata["invest_due"] = 0
    save_data(data)

async def handle_level_up(member, guild, new_level: int, channel):
    role_name = LEVEL_ROLES.get(new_level)
    role_msg = ""
    if role_name:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            for rn in LEVEL_ROLES.values():
                old_role = discord.utils.get(guild.roles, name=rn)
                if old_role and old_role in member.roles:
                    try:
                        await member.remove_roles(old_role)
                    except:
                        pass
            try:
                await member.add_roles(role)
                role_msg = f"\n🏅 Rôle débloqué : **{role_name}**"
            except:
                role_msg = f"\n⚠️ Rôle **{role_name}** introuvable"

    embed = discord.Embed(
        title="⬆️ Niveau Supérieur !",
        description=f"Félicitations {member.mention} !\nTu passes au **niveau {new_level}** !{role_msg}",
        color=COLOR_GOLD
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Continue comme ça ! 🎰")
    if channel:
        await channel.send(embed=embed)
    else:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                await ch.send(embed=embed)
                break

# ─── Help ─────────────────────────────────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🎰  CasinoBot — Aide",
        description="Préfixe : `%` — Toutes les commandes disponibles",
        color=COLOR_CASINO
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    embed.add_field(name="📊  Profil & XP", value=(
        "`%profil [@user]` • Voir un profil\n"
        "`%classement` • Top 10 XP\n"
        "`%richesse` • Top 10 coins\n"
        "`%stats` • Statistiques détaillées\n"
        "`%palmares` • Records du serveur\n"
        "`%historique` • Tes 10 dernières transactions\n"
        "`%cooldowns` • Voir tes cooldowns"
    ), inline=True)
    embed.add_field(name="💰  Économie", value=(
        "`%daily` • Bonus journalier (24h)\n"
        "`%work` • Travailler (45min)\n"
        "`%crime` • Crime risqué (90min)\n"
        "`%rob @user` • Voler (3h)\n"
        "`%transfer @user <montant>` • Transférer\n"
        "`%cadeau @user <montant>` • Offrir sans taxe\n"
        "`%solde` • Voir tes coins\n"
        "`%banque <dep|ret|solde> [montant]` • Banque\n"
        "`%pret <montant>` • Emprunter des coins\n"
        "`%rembourser` • Rembourser ton prêt\n"
        "`%investir <montant>` • Investir (6h)"
    ), inline=True)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    embed.add_field(name="🎰  Casino", value=(
        "`%slot <mise>` • Machine à sous\n"
        "`%coinflip <mise> <pile|face>` • Pile ou face\n"
        "`%blackjack <mise>` • Blackjack\n"
        "`%roulette <mise> <choix>` • Roulette\n"
        "`%dice <mise>` • Duel de dés\n"
        "`%crash <mise>` • Crash\n"
        "`%plinko <mise>` • Plinko\n"
        "`%highlow <mise>` • Plus haut / Plus bas\n"
        "`%poker <mise>` • Video Poker"
    ), inline=True)
    embed.add_field(name="🎮  Mini-jeux", value=(
        "`%trivia` • Culture générale\n"
        "`%quiz <catégorie>` • Quiz par catégorie\n"
        "`%rps @user <mise>` • Pierre-Feuille-Ciseaux\n"
        "`%duel @user <mise>` • Duel\n"
        "`%duel_poker @user <mise>` • Poker duel\n"
        "`%mines <mise> <nb_mines>` • Démineur\n"
        "`%course` • Course de chevaux\n"
        "`%wordgame` • Jeu de mots\n"
        "`%memory` • Mémorisation"
    ), inline=True)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    embed.add_field(name="🛒  Shop & Marché", value=(
        "`%shop` • Boutique officielle\n"
        "`%buy <item>` • Acheter\n"
        "`%inventaire` • Mon inventaire\n"
        "`%use <item>` • Utiliser un item\n"
        "`%blackmarket` • Marché noir (refresh 6h)\n"
        "`%objectif` • Objectifs journaliers"
    ), inline=False)
    embed.set_footer(text="💡 Utilise %profil pour voir ton niveau et ta progression")
    await ctx.send(embed=embed)

# ─── Profil & Stats ───────────────────────────────────────────────────────────

@bot.command(name="profil")
async def profil(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = load_data()
    user = get_user(data, member.id)
    save_data(data)
    level = compute_level(user["xp"])
    current_xp, needed_xp = xp_progress(user["xp"], level)
    bar = make_progress_bar(current_xp, needed_xp)
    pct = int(current_xp / needed_xp * 100) if needed_xp else 100
    next_role_level = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
    next_role_info = f"**{LEVEL_ROLES[next_role_level]}** — Niv. {next_role_level}" if next_role_level else "🏆 Rang maximum !"

    wins = user.get("casino_wins", 0)
    losses = user.get("casino_losses", 0)
    total = wins + losses
    wr = f"{int(wins/total*100)}%" if total else "N/A"

    badges = []
    now = time.time()
    if user.get("xp_boost_until", 0) > now: badges.append("⚡ Boost XP")
    if user.get("lucky_charm_until", 0) > now: badges.append("🍀 Chance+")
    if user.get("shield"): badges.append("🛡️ Bouclier")
    if user.get("vip_until", 0) > now: badges.append("💎 VIP")
    if user.get("insurance"): badges.append("🔒 Assurance")

    embed = discord.Embed(title=f"🎰  Profil de {member.display_name}", color=COLOR_GOLD)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📊 Niveau", value=f"**{level}**", inline=True)
    embed.add_field(name="⭐ XP Total", value=f"**{user['xp']:,}**", inline=True)
    embed.add_field(name="💰 Coins", value=f"**{user['coins']:,}** 🪙", inline=True)
    embed.add_field(name="🏦 Banque", value=f"**{user.get('bank',0):,}** 🪙", inline=True)
    embed.add_field(
        name=f"Progression  {pct}%",
        value=f"{bar}\n`{current_xp:,} / {needed_xp:,} XP`",
        inline=False
    )
    embed.add_field(name="🎯 Prochain rôle", value=next_role_info, inline=True)
    embed.add_field(name="🎲 Streak daily", value=f"**{user.get('streak_daily',0)}** jours 🔥", inline=True)
    embed.add_field(
        name="🎰 Casino",
        value=f"✅ {wins}W  ❌ {losses}L  📊 {wr} WR",
        inline=False
    )
    if badges:
        embed.add_field(name="✨ Actifs", value="  ".join(badges), inline=False)
    embed.set_footer(text=f"Membre depuis le début • {user.get('total_games_played',0)} parties jouées")
    await ctx.send(embed=embed)

@bot.command(name="stats")
async def stats(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = load_data()
    user = get_user(data, member.id)
    save_data(data)

    wins = user.get("casino_wins", 0)
    losses = user.get("casino_losses", 0)
    total = wins + losses
    wr = f"{int(wins/total*100)}%" if total else "N/A"

    embed = discord.Embed(title=f"📈  Statistiques — {member.display_name}", color=COLOR_BLUE)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏆 Victoires casino", value=f"**{wins:,}**", inline=True)
    embed.add_field(name="💔 Défaites casino", value=f"**{losses:,}**", inline=True)
    embed.add_field(name="📊 Win Rate", value=f"**{wr}**", inline=True)
    embed.add_field(name="🎮 Parties jouées", value=f"**{user.get('total_games_played',0):,}**", inline=True)
    embed.add_field(name="💵 Total gagné (vie)", value=f"**{user.get('total_earned',0):,}** 🪙", inline=True)
    embed.add_field(name="🔥 Streak daily", value=f"**{user.get('streak_daily',0)}** jours", inline=True)
    embed.add_field(name="🏅 Meilleur jackpot", value=f"**{user.get('best_jackpot',0):,}** 🪙", inline=True)
    embed.add_field(name="🦹 Meilleur rob", value=f"**{user.get('best_rob',0):,}** 🪙", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="solde", aliases=["balance", "coins"])
async def solde(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    embed = discord.Embed(
        title="💳  Solde",
        description=f"{ctx.author.mention}\n# {user['coins']:,} 🪙",
        color=COLOR_GREEN
    )
    embed.add_field(name="🏦 Banque", value=f"**{user.get('bank',0):,}** 🪙", inline=True)
    embed.add_field(name="💎 Total", value=f"**{user['coins'] + user.get('bank',0):,}** 🪙", inline=True)
    embed.set_footer(text="Utilise %daily, %work ou %crime pour gagner plus !")
    await ctx.send(embed=embed)

@bot.command(name="classement", aliases=["top", "leaderboard"])
async def classement(ctx):
    data = load_data()
    scores = [(int(uid), d["xp"], compute_level(d["xp"])) for uid, d in data.items()]
    scores.sort(key=lambda x: x[1], reverse=True)
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    lines = []
    for i, (uid, xp, lvl) in enumerate(scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"User#{uid}"
        lines.append(f"{medals[i]}  **{name}**  —  Niv. **{lvl}**  •  `{xp:,} XP`")
    embed = discord.Embed(
        title="🏆  Classement XP",
        description="\n".join(lines) if lines else "Aucune donnée.",
        color=COLOR_GOLD
    )
    embed.set_footer(text="Envoie des messages et reste en vocal pour grimper !")
    await ctx.send(embed=embed)

@bot.command(name="richesse")
async def richesse(ctx):
    data = load_data()
    scores = [(int(uid), d["coins"] + d.get("bank", 0)) for uid, d in data.items()]
    scores.sort(key=lambda x: x[1], reverse=True)
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    lines = []
    for i, (uid, coins) in enumerate(scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"User#{uid}"
        lines.append(f"{medals[i]}  **{name}**  —  `{coins:,} 🪙`")
    embed = discord.Embed(
        title="💰  Classement Richesse",
        description="\n".join(lines) if lines else "Aucune donnée.",
        color=COLOR_GREEN
    )
    await ctx.send(embed=embed)

@bot.command(name="palmares")
async def palmares(ctx):
    """Records historiques du serveur."""
    data = load_data()
    best_streak = (0, "—")
    best_jackpot = (0, "—")
    best_rob = (0, "—")
    best_games = (0, "—")

    for uid, udata in data.items():
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User#{uid}"
        if udata.get("streak_daily", 0) > best_streak[0]:
            best_streak = (udata["streak_daily"], name)
        if udata.get("best_jackpot", 0) > best_jackpot[0]:
            best_jackpot = (udata["best_jackpot"], name)
        if udata.get("best_rob", 0) > best_rob[0]:
            best_rob = (udata["best_rob"], name)
        if udata.get("total_games_played", 0) > best_games[0]:
            best_games = (udata["total_games_played"], name)

    embed = discord.Embed(title="🏆  Palmarès du Serveur", color=COLOR_GOLD)
    embed.add_field(name="🔥 Plus grand streak daily", value=f"**{best_streak[1]}** — {best_streak[0]} jours", inline=False)
    embed.add_field(name="💰 Plus gros jackpot", value=f"**{best_jackpot[1]}** — {best_jackpot[0]:,} 🪙", inline=False)
    embed.add_field(name="🦹 Plus gros vol", value=f"**{best_rob[1]}** — {best_rob[0]:,} 🪙", inline=False)
    embed.add_field(name="🎮 Plus de parties jouées", value=f"**{best_games[1]}** — {best_games[0]:,} parties", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="historique", aliases=["history"])
async def historique(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    hist = user.get("history", [])
    if not hist:
        return await ctx.send(embed=discord.Embed(
            title="📋  Historique",
            description="Aucune transaction enregistrée.",
            color=COLOR_BLUE
        ))
    lines = []
    for entry in hist:
        ts = datetime.fromtimestamp(entry["ts"]).strftime("%d/%m %H:%M")
        sign = "+" if entry["amount"] >= 0 else ""
        lines.append(f"`{ts}`  {entry['label']}  **{sign}{entry['amount']:,}** 🪙")
    embed = discord.Embed(
        title=f"📋  Historique de {ctx.author.display_name}",
        description="\n".join(lines),
        color=COLOR_BLUE
    )
    await ctx.send(embed=embed)

@bot.command(name="cooldowns", aliases=["cd"])
async def cooldowns(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    now = time.time()
    mult = get_cooldown_mult(user)

    def cd_status(last: float, cooldown_base: float) -> str:
        cd = cooldown_base * mult
        remaining = cd - (now - last)
        if remaining <= 0:
            return "✅ Disponible !"
        return f"⏳ {format_time(remaining)}"

    embed = discord.Embed(title=f"⏱️  Cooldowns de {ctx.author.display_name}", color=COLOR_BLUE)
    if user.get("vip_until", 0) > now:
        embed.description = "💎 **VIP actif** — cooldowns réduits de 50% !"
    embed.add_field(name="🎁 Daily", value=cd_status(user["last_daily"], 86400), inline=True)
    embed.add_field(name="💼 Work", value=cd_status(user["last_work"], 2700), inline=True)
    embed.add_field(name="🚔 Crime", value=cd_status(user["last_crime"], 5400), inline=True)
    embed.add_field(name="🦹 Rob", value=cd_status(user.get("last_rob", 0), 10800), inline=True)
    embed.add_field(name="🎁 Cadeau", value=cd_status(user.get("last_cadeau", 0), 43200), inline=True)
    await ctx.send(embed=embed)

@bot.command(name="objectif", aliases=["objectifs", "daily_quest"])
async def objectif(ctx):
    """Objectifs journaliers personnels."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    now = time.time()

    # Générer des objectifs basés sur un seed quotidien
    day_seed = int(now // 86400)
    rng = random.Random(day_seed + ctx.author.id)

    goals = [
        {"label": "🎮 Jouer 3 parties de casino", "key": "total_games_played", "target": user.get("total_games_played", 0) + 3, "reward": 150},
        {"label": "🏆 Gagner 2 parties de casino", "key": "casino_wins", "target": user.get("casino_wins", 0) + 2, "reward": 200},
        {"label": "💼 Utiliser %work", "key": "last_work", "target": now - 2700, "reward": 100},
    ]
    chosen = rng.sample(goals, k=2)

    embed = discord.Embed(
        title="🎯  Objectifs Journaliers",
        description="Complète ces objectifs pour gagner des bonus !",
        color=COLOR_TEAL
    )
    for g in chosen:
        embed.add_field(
            name=g["label"],
            value=f"Récompense : **{g['reward']} 🪙**\n*(Suivi automatique dans `%stats`)*",
            inline=False
        )
    embed.set_footer(text="Les objectifs se renouvellent chaque jour à minuit.")
    await ctx.send(embed=embed)

# ─── Argent ───────────────────────────────────────────────────────────────────

@bot.command(name="daily")
async def daily(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 86400 * get_cooldown_mult(user)
    if now - user["last_daily"] < cooldown:
        remaining = cooldown - (now - user["last_daily"])
        embed = discord.Embed(
            title="⏳  Daily déjà récupéré",
            description=f"Reviens dans **{format_time(remaining)}** !",
            color=COLOR_RED
        )
        embed.set_footer(text=f"Streak actuel : {user.get('streak_daily',0)} jours 🔥")
        return await ctx.send(embed=embed)

    streak = user.get("streak_daily", 0)
    last_streak = user.get("last_daily_streak", 0)
    if now - last_streak < 172800:
        streak += 1
    else:
        streak = 1
    user["streak_daily"] = streak
    user["last_daily_streak"] = now

    base = random.randint(80, 180)
    streak_bonus = min(streak * 5, 100)
    amount = base + streak_bonus

    if user.get("daily_bonus_x2"):
        amount *= 2
        user["daily_bonus_x2"] = False

    user["coins"] += amount
    user["total_earned"] = user.get("total_earned", 0) + amount
    user["last_daily"] = now
    add_history(user, "🎁 Daily", amount)
    save_data(data)

    embed = discord.Embed(title="🎁  Daily récupéré !", color=COLOR_GREEN)
    embed.add_field(name="💰 Gains", value=f"**+{amount:,}** 🪙", inline=True)
    embed.add_field(name="🔥 Streak", value=f"**{streak}** jours", inline=True)
    embed.add_field(name="📈 Bonus streak", value=f"+**{streak_bonus}** 🪙", inline=True)
    embed.set_footer(text=f"Reviens demain pour maintenir ton streak ! | Total : {user['coins']:,} 🪙")
    await ctx.send(embed=embed)

@bot.command(name="work")
async def work(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 2700 * get_cooldown_mult(user)
    if now - user["last_work"] < cooldown:
        remaining = cooldown - (now - user["last_work"])
        return await ctx.send(embed=discord.Embed(
            title="⏳  Tu travailles déjà !",
            description=f"Repose-toi encore **{format_time(remaining)}**.",
            color=COLOR_RED
        ))
    jobs = [
        ("🍕", "Livreur de pizzas", 30, 80),
        ("💻", "Développeur freelance", 50, 140),
        ("🎸", "Musicien de rue", 20, 60),
        ("🚕", "Chauffeur VTC", 40, 100),
        ("🧹", "Agent d'entretien", 25, 70),
        ("📦", "Livreur colis", 35, 90),
        ("🍔", "Serveur fast-food", 25, 75),
        ("🌿", "Jardinier", 30, 85),
        ("📸", "Photographe", 40, 120),
        ("🔧", "Plombier", 50, 130),
    ]
    emoji, job, mn, mx = random.choice(jobs)
    amount = random.randint(mn, mx)
    user["coins"] += amount
    user["total_earned"] = user.get("total_earned", 0) + amount
    user["last_work"] = now
    add_history(user, f"{emoji} Work: {job}", amount)
    save_data(data)
    embed = discord.Embed(
        title=f"{emoji}  Tu as travaillé !",
        description=f"**{job}** — Beau boulot !",
        color=COLOR_BLUE
    )
    embed.add_field(name="💰 Salaire", value=f"**+{amount:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    embed.set_footer(text="Cooldown : 45 minutes")
    await ctx.send(embed=embed)

@bot.command(name="crime")
async def crime(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 5400 * get_cooldown_mult(user)
    if now - user["last_crime"] < cooldown:
        remaining = cooldown - (now - user["last_crime"])
        return await ctx.send(embed=discord.Embed(
            title="⏳  Les flics te surveillent !",
            description=f"Attends **{format_time(remaining)}** avant de recommencer.",
            color=COLOR_RED
        ))
    user["last_crime"] = now
    if random.random() < 0.40:
        fine = random.randint(80, 300)
        user["coins"] = max(0, user["coins"] - fine)
        add_history(user, "🚔 Crime raté — amende", -fine)
        save_data(data)
        return await ctx.send(embed=discord.Embed(
            title="🚔  Arrêté !",
            description=f"La police t'a rattrapé. Amende de **{fine:,}** 🪙.",
            color=COLOR_RED
        ))
    crimes = [
        ("🏦", "Braquage de banque", 150, 450),
        ("💎", "Vol de bijoux", 120, 380),
        ("🎭", "Arnaque en ligne", 100, 300),
        ("🖥️", "Piratage informatique", 130, 400),
        ("🚗", "Vol de voiture", 110, 350),
    ]
    e, name, mn, mx = random.choice(crimes)
    amount = random.randint(mn, mx)
    user["coins"] += amount
    user["total_earned"] = user.get("total_earned", 0) + amount
    add_history(user, f"{e} Crime: {name}", amount)
    save_data(data)
    embed = discord.Embed(
        title=f"{e}  Crime réussi !",
        description=f"**{name}** — Tu t'en es sorti !",
        color=COLOR_ORANGE
    )
    embed.add_field(name="💰 Butin", value=f"**+{amount:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    embed.set_footer(text="Cooldown : 90 minutes • Risque : 40%")
    await ctx.send(embed=embed)

@bot.command(name="rob")
async def rob(ctx, target: discord.Member):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    robber = get_user(data, ctx.author.id)
    victim = get_user(data, target.id)
    now = time.time()
    cooldown = 10800 * get_cooldown_mult(robber)
    if now - robber.get("last_rob", 0) < cooldown:
        remaining = cooldown - (now - robber["last_rob"])
        return await ctx.send(embed=discord.Embed(
            title="⏳  Trop risqué !",
            description=f"Attends **{format_time(remaining)}** avant de voler à nouveau.",
            color=COLOR_RED
        ))
    if victim.get("shield"):
        victim["shield"] = False
        robber["last_rob"] = now
        save_data(data)
        return await ctx.send(embed=discord.Embed(
            title="🛡️  Bouclier activé !",
            description=f"{target.display_name} était protégé. Ta tentative a échoué !",
            color=COLOR_BLUE
        ))
    if victim["coins"] < 100:
        return await ctx.send(embed=discord.Embed(
            description=f"💸 {target.display_name} n'a pas assez de coins.",
            color=COLOR_RED
        ))
    robber["last_rob"] = now
    if random.random() < 0.45:
        fine = random.randint(60, 250)
        robber["coins"] = max(0, robber["coins"] - fine)
        add_history(robber, f"🚔 Rob raté sur {target.display_name}", -fine)
        save_data(data)
        return await ctx.send(embed=discord.Embed(
            title="🚔  Pris la main dans le sac !",
            description=f"{ctx.author.mention} s'est fait attraper. Amende : **{fine:,}** 🪙.",
            color=COLOR_RED
        ))
    stolen = random.randint(80, min(400, victim["coins"] // 3))
    victim["coins"] -= stolen
    robber["coins"] += stolen
    if stolen > robber.get("best_rob", 0):
        robber["best_rob"] = stolen
    add_history(robber, f"🦹 Rob sur {target.display_name}", stolen)
    add_history(victim, f"😱 Volé par {ctx.author.display_name}", -stolen)
    save_data(data)
    embed = discord.Embed(
        title="🦹  Vol réussi !",
        description=f"{ctx.author.mention} vole **{stolen:,}** 🪙 à {target.mention} !",
        color=COLOR_ORANGE
    )
    await ctx.send(embed=embed)

@bot.command(name="transfer", aliases=["donner", "give"])
async def transfer(ctx, target: discord.Member, amount: str = "0"):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    sender = get_user(data, ctx.author.id)
    receiver = get_user(data, target.id)
    try:
        amt = int(amount)
    except:
        return await ctx.send(embed=discord.Embed(description="❌ Montant invalide.", color=COLOR_RED))
    if amt <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Montant doit être positif.", color=COLOR_RED))
    if amt > sender["coins"]:
        return await ctx.send(embed=discord.Embed(description=f"❌ Tu n'as que **{sender['coins']:,}** 🪙.", color=COLOR_RED))
    tax = max(1, int(amt * 0.05))
    net = amt - tax
    sender["coins"] -= amt
    receiver["coins"] += net
    add_history(sender, f"📤 Transfert → {target.display_name}", -amt)
    add_history(receiver, f"📥 Reçu de {ctx.author.display_name}", net)
    save_data(data)
    embed = discord.Embed(title="💸  Transfert effectué", color=COLOR_GREEN)
    embed.add_field(name="📤 Envoyé", value=f"**{amt:,}** 🪙", inline=True)
    embed.add_field(name="📥 Reçu", value=f"**{net:,}** 🪙", inline=True)
    embed.add_field(name="🏦 Taxe (5%)", value=f"**{tax:,}** 🪙", inline=True)
    embed.set_footer(text=f"{ctx.author.display_name} → {target.display_name}")
    await ctx.send(embed=embed)

@bot.command(name="cadeau")
async def cadeau(ctx, target: discord.Member, amount: str = "0"):
    """Offrir des coins sans taxe — cooldown 12h, max 500 🪙."""
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    sender = get_user(data, ctx.author.id)
    receiver = get_user(data, target.id)
    now = time.time()
    cooldown = 43200 * get_cooldown_mult(sender)
    if now - sender.get("last_cadeau", 0) < cooldown:
        remaining = cooldown - (now - sender["last_cadeau"])
        return await ctx.send(embed=discord.Embed(
            title="⏳  Cadeau déjà envoyé !",
            description=f"Attends **{format_time(remaining)}**.",
            color=COLOR_RED
        ))
    try:
        amt = min(int(amount), 500)
    except:
        return await ctx.send(embed=discord.Embed(description="❌ Montant invalide.", color=COLOR_RED))
    if amt <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Montant doit être positif.", color=COLOR_RED))
    if amt > sender["coins"]:
        return await ctx.send(embed=discord.Embed(description=f"❌ Tu n'as que **{sender['coins']:,}** 🪙.", color=COLOR_RED))
    sender["coins"] -= amt
    receiver["coins"] += amt
    sender["last_cadeau"] = now
    add_history(sender, f"🎁 Cadeau → {target.display_name}", -amt)
    add_history(receiver, f"🎁 Cadeau de {ctx.author.display_name}", amt)
    save_data(data)
    embed = discord.Embed(
        title="🎁  Cadeau envoyé !",
        description=f"{ctx.author.mention} offre **{amt:,}** 🪙 à {target.mention} sans taxe !",
        color=COLOR_GREEN
    )
    embed.set_footer(text="Cooldown : 12h • Maximum : 500 🪙")
    await ctx.send(embed=embed)

# ─── Banque ───────────────────────────────────────────────────────────────────

@bot.command(name="banque", aliases=["bank"])
async def banque(ctx, action: str = "solde", amount: str = "0"):
    """Banque sécurisée — les coins en banque ne peuvent pas être volés."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    action = action.lower()

    if action in ("solde", "s", "balance"):
        embed = discord.Embed(title="🏦  Banque", color=COLOR_BLUE)
        embed.add_field(name="💰 Portefeuille", value=f"**{user['coins']:,}** 🪙", inline=True)
        embed.add_field(name="🏦 Banque", value=f"**{user.get('bank', 0):,}** 🪙", inline=True)
        embed.add_field(name="💎 Total", value=f"**{user['coins'] + user.get('bank', 0):,}** 🪙", inline=True)
        embed.set_footer(text="Les coins en banque sont protégés des vols !")
        save_data(data)
        return await ctx.send(embed=embed)

    try:
        amt = int(amount) if amount.lower() not in ("all","tout") else (user["coins"] if action in ("dep","deposer","deposit") else user.get("bank", 0))
    except:
        return await ctx.send(embed=discord.Embed(description="❌ Montant invalide.", color=COLOR_RED))

    if amt <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Montant doit être positif.", color=COLOR_RED))

    if action in ("dep", "deposer", "deposit", "d"):
        if amt > user["coins"]:
            return await ctx.send(embed=discord.Embed(description=f"❌ Tu n'as que **{user['coins']:,}** 🪙.", color=COLOR_RED))
        user["coins"] -= amt
        user["bank"] = user.get("bank", 0) + amt
        add_history(user, "🏦 Dépôt banque", -amt)
        save_data(data)
        embed = discord.Embed(title="🏦  Dépôt effectué", color=COLOR_GREEN)
        embed.add_field(name="📥 Déposé", value=f"**{amt:,}** 🪙", inline=True)
        embed.add_field(name="🏦 Solde banque", value=f"**{user['bank']:,}** 🪙", inline=True)
        return await ctx.send(embed=embed)

    elif action in ("ret", "retirer", "withdraw", "r"):
        bank_bal = user.get("bank", 0)
        if amt > bank_bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ Tu n'as que **{bank_bal:,}** 🪙 en banque.", color=COLOR_RED))
        user["bank"] = bank_bal - amt
        user["coins"] += amt
        add_history(user, "🏦 Retrait banque", amt)
        save_data(data)
        embed = discord.Embed(title="🏦  Retrait effectué", color=COLOR_GREEN)
        embed.add_field(name="📤 Retiré", value=f"**{amt:,}** 🪙", inline=True)
        embed.add_field(name="💰 Portefeuille", value=f"**{user['coins']:,}** 🪙", inline=True)
        return await ctx.send(embed=embed)

    else:
        return await ctx.send(embed=discord.Embed(
            description="❌ Usage : `%banque <dep|ret|solde> [montant]`",
            color=COLOR_RED
        ))

@bot.command(name="pret", aliases=["loan", "emprunter"])
async def pret(ctx, amount: str = "0"):
    """Emprunter des coins avec 20% d'intérêts — à rembourser en 24h."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()

    if user.get("loan_amount", 0) > 0:
        due_str = format_time(max(0, user["loan_due"] - now))
        return await ctx.send(embed=discord.Embed(
            title="❌  Prêt en cours",
            description=f"Tu as déjà un prêt de **{user['loan_amount']:,}** 🪙 en cours.\nRembourse avec `%rembourser` — il reste **{due_str}**.",
            color=COLOR_RED
        ))

    try:
        amt = int(amount)
    except:
        return await ctx.send(embed=discord.Embed(description="❌ Montant invalide.", color=COLOR_RED))

    max_loan = 1000
    if amt <= 0 or amt > max_loan:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Tu peux emprunter entre **1** et **{max_loan:,}** 🪙.",
            color=COLOR_RED
        ))

    interest = int(amt * 0.20)
    total_due = amt + interest
    user["coins"] += amt
    user["loan_amount"] = total_due
    user["loan_due"] = now + 86400
    add_history(user, f"🏦 Prêt reçu", amt)
    save_data(data)

    embed = discord.Embed(title="🏦  Prêt accordé !", color=COLOR_ORANGE)
    embed.add_field(name="💰 Reçu", value=f"**{amt:,}** 🪙", inline=True)
    embed.add_field(name="📈 Intérêts (20%)", value=f"**{interest:,}** 🪙", inline=True)
    embed.add_field(name="💸 À rembourser", value=f"**{total_due:,}** 🪙", inline=True)
    embed.set_footer(text="⚠️ Remboursement obligatoire sous 24h — pénalité x1.5 si défaut !")
    await ctx.send(embed=embed)

@bot.command(name="rembourser", aliases=["repay", "remboursement"])
async def rembourser(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()

    if user.get("loan_amount", 0) <= 0:
        return await ctx.send(embed=discord.Embed(description="✅ Tu n'as aucun prêt en cours.", color=COLOR_GREEN))

    due = user["loan_amount"]
    if user["coins"] < due:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Il te faut **{due:,}** 🪙 pour rembourser. Tu n'en as que **{user['coins']:,}**.",
            color=COLOR_RED
        ))

    user["coins"] -= due
    user["loan_amount"] = 0
    user["loan_due"] = 0
    add_history(user, "🏦 Prêt remboursé", -due)
    save_data(data)

    embed = discord.Embed(title="✅  Prêt remboursé !", color=COLOR_GREEN)
    embed.add_field(name="💸 Payé", value=f"**{due:,}** 🪙", inline=True)
    embed.add_field(name="💰 Solde restant", value=f"**{user['coins']:,}** 🪙", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="investir", aliases=["invest"])
async def investir(ctx, amount: str = "0"):
    """Investir des coins — résultat après 6h (−30% à +80%)."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()

    if user.get("invest_amount", 0) > 0:
        remaining = max(0, user["invest_due"] - now)
        return await ctx.send(embed=discord.Embed(
            title="📈  Investissement en cours",
            description=f"Tu as déjà **{user['invest_amount']:,}** 🪙 investis.\nRésultat dans **{format_time(remaining)}**.",
            color=COLOR_ORANGE
        ))

    bet = parse_bet(user, amount)
    if not bet or bet < 50:
        return await ctx.send(embed=discord.Embed(description="❌ Minimum d'investissement : **50** 🪙.", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))

    user["coins"] -= bet
    user["invest_amount"] = bet
    user["invest_due"] = now + 21600  # 6h
    add_history(user, "📈 Investissement placé", -bet)
    save_data(data)

    embed = discord.Embed(title="📈  Investissement lancé !", color=COLOR_TEAL)
    embed.add_field(name="💰 Investi", value=f"**{bet:,}** 🪙", inline=True)
    embed.add_field(name="⏱️ Retour", value="Dans **6 heures**", inline=True)
    embed.add_field(name="📊 Rendement possible", value="Entre **−30%** et **+80%**", inline=True)
    embed.set_footer(text="Le résultat sera automatiquement crédité dans 6h !")
    await ctx.send(embed=embed)

# ─── Casino helpers ────────────────────────────────────────────────────────────

# ─── Casino ───────────────────────────────────────────────────────────────────

@bot.command(name="slot", aliases=["slots"])
async def slot(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : **10** 🪙. Usage : `%slot <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Tu n'as pas assez de coins.", color=COLOR_RED))
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
    weights = [22, 20, 17, 13, 10, 8, 6, 4]
    reels = random.choices(symbols, weights=weights, k=3)
    result_str = "  ".join(reels)
    user["total_games_played"] = user.get("total_games_played", 0) + 1

    if reels[0] == reels[1] == reels[2]:
        mult_map = {"7️⃣": 20, "💎": 10, "⭐": 7, "🔔": 5}
        mult = mult_map.get(reels[0], 3)
        win = bet * mult
        gain = win - bet
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        if gain > user.get("best_jackpot", 0):
            user["best_jackpot"] = gain
        add_history(user, f"🎰 Slot JACKPOT x{mult}", gain)
        embed = discord.Embed(title="🎰  JACKPOT !", description=f"╔══════════════╗\n║  {result_str}  ║\n╚══════════════╝", color=COLOR_GOLD)
        embed.add_field(name="🎉 Multiplicateur", value=f"x**{mult}**", inline=True)
        embed.add_field(name="💰 Gains", value=f"+**{gain:,}** 🪙", inline=True)
        embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        embed = discord.Embed(title="🎰  Deux identiques !", description=f"╔══════════════╗\n║  {result_str}  ║\n╚══════════════╝", color=COLOR_BLUE)
        embed.add_field(name="🤝 Résultat", value="Mise récupérée", inline=True)
        embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🎰 Slot perdu", -bet)
        embed = discord.Embed(title="🎰  Perdu !", description=f"╔══════════════╗\n║  {result_str}  ║\n╚══════════════╝", color=COLOR_RED)
        embed.add_field(name="❌ Perte", value=f"-**{bet:,}** 🪙", inline=True)
        embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

@bot.command(name="coinflip", aliases=["cf", "flip"])
async def coinflip(ctx, mise: str = "0", choix: str = "pile"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : 10. Usage : `%coinflip <mise> <pile|face>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    choix = choix.lower()
    if choix not in ("pile", "face"):
        return await ctx.send(embed=discord.Embed(description="❌ Choisis `pile` ou `face`.", color=COLOR_RED))
    result = random.choice(["pile", "face"])
    user["total_games_played"] = user.get("total_games_played", 0) + 1
    if result == choix:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        add_history(user, "🪙 Coinflip gagné", bet)
        embed = discord.Embed(title="🪙  Pile ou Face", description=f"La pièce tombe sur **{result.upper()}** !", color=COLOR_GREEN)
        embed.add_field(name="✅ Gagné !", value=f"+**{bet:,}** 🪙", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🪙 Coinflip perdu", -bet)
        embed = discord.Embed(title="🪙  Pile ou Face", description=f"La pièce tombe sur **{result.upper()}** !", color=COLOR_RED)
        embed.add_field(name="❌ Perdu !", value=f"-**{bet:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

@bot.command(name="blackjack", aliases=["bj"])
async def blackjack(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : 10. Usage : `%blackjack <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    user["total_games_played"] = user.get("total_games_played", 0) + 1

    def card_value(card):
        rank = card[:-1]
        if rank in ("J", "Q", "K"): return 10
        if rank == "A": return 11
        return int(rank)

    def hand_value(hand):
        val = sum(card_value(c) for c in hand)
        aces = sum(1 for c in hand if c[:-1] == "A")
        while val > 21 and aces:
            val -= 10; aces -= 1
        return val

    suits = "♠♥♦♣"
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    deck = [r+s for r in ranks for s in suits]
    random.shuffle(deck)

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    def make_embed(hide_dealer=True):
        pv = hand_value(player)
        embed = discord.Embed(title="🃏  Blackjack", color=COLOR_DARK)
        embed.add_field(
            name=f"🧑 Toi  ({pv})",
            value=render_hand(player),
            inline=False
        )
        if hide_dealer:
            embed.add_field(
                name="🤵 Croupier  (?)",
                value=render_hand([dealer[0], "?♠"], hide_last=True),
                inline=False
            )
        else:
            dv = hand_value(dealer)
            embed.add_field(
                name=f"🤵 Croupier  ({dv})",
                value=render_hand(dealer),
                inline=False
            )
        embed.add_field(name="💰 Mise", value=f"**{bet:,}** 🪙", inline=True)
        if hide_dealer:
            embed.set_footer(text="Tape  hit (h)  pour tirer  •  stand (s)  pour rester")
        return embed

    await ctx.send(embed=make_embed())

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ("hit","stand","h","s")

    while True:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("⏳ Temps écoulé. Stand automatique.")
            break
        if resp.content.lower() in ("stand","s"):
            break
        player.append(deck.pop())
        if hand_value(player) > 21:
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            add_history(user, "🃏 Blackjack bust", -bet)
            save_data(data)
            e = make_embed(False)
            e.color = COLOR_RED
            e.title = "🃏  Bust !"
            e.add_field(name="❌ Résultat", value=f"Perdu **{bet:,}** 🪙", inline=False)
            return await ctx.send(embed=e)
        await ctx.send(embed=make_embed())

    while hand_value(dealer) < 17:
        dealer.append(deck.pop())

    pv, dv = hand_value(player), hand_value(dealer)
    e = make_embed(False)
    if dv > 21 or pv > dv:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        add_history(user, "🃏 Blackjack gagné", bet)
        e.color = COLOR_GREEN
        e.add_field(name="🎉 Victoire !", value=f"+**{bet:,}** 🪙", inline=True)
    elif pv == dv:
        e.color = COLOR_BLUE
        e.add_field(name="🤝 Égalité", value="Mise remboursée", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🃏 Blackjack perdu", -bet)
        e.color = COLOR_RED
        e.add_field(name="❌ Défaite", value=f"-**{bet:,}** 🪙", inline=True)
    e.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=e)

@bot.command(name="roulette")
async def roulette(ctx, mise: str = "0", choix: str = "rouge"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Usage : `%roulette <mise> <rouge|noir|pair|impair|0-36>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    user["total_games_played"] = user.get("total_games_played", 0) + 1
    num = random.randint(0, 36)
    rouges = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    if num in rouges:
        color_str = "🔴 Rouge"
        color_val = COLOR_RED
    elif num == 0:
        color_str = "🟢 Zéro"
        color_val = COLOR_GREEN
    else:
        color_str = "⚫ Noir"
        color_val = COLOR_DARK

    win = False; mult = 1
    c = choix.lower()
    if c in ("rouge","red") and num in rouges: win=True; mult=2
    elif c in ("noir","black") and num not in rouges and num!=0: win=True; mult=2
    elif c in ("pair","even") and num%2==0 and num!=0: win=True; mult=2
    elif c in ("impair","odd") and num%2!=0: win=True; mult=2
    else:
        try:
            n = int(c)
            if n == num: win=True; mult=36
        except: pass

    embed = discord.Embed(title="🎡  Roulette", color=color_val)
    embed.add_field(name="🎯 Résultat", value=f"**{num}** — {color_str}", inline=True)
    embed.add_field(name="🎲 Pari", value=f"**{choix}**", inline=True)
    if win:
        gain = bet * (mult - 1)
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        add_history(user, f"🎡 Roulette gagné x{mult}", gain)
        embed.add_field(name="🎉 Gagné !", value=f"+**{gain:,}** 🪙  (x{mult})", inline=False)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🎡 Roulette perdu", -bet)
        embed.add_field(name="❌ Perdu !", value=f"-**{bet:,}** 🪙", inline=False)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

@bot.command(name="dice", aliases=["de"])
async def dice(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Usage : `%dice <mise>` — Fais plus de 7 avec deux dés !", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    user["total_games_played"] = user.get("total_games_played", 0) + 1
    dice_faces = ["⚀","⚁","⚂","⚃","⚄","⚅"]
    d1, d2 = random.randint(1,6), random.randint(1,6)
    total = d1 + d2
    embed = discord.Embed(title="🎲  Lancer de dés", color=COLOR_BLUE)
    embed.add_field(name="Dés", value=f"{dice_faces[d1-1]}  {dice_faces[d2-1]}  =  **{total}**", inline=False)
    if total > 7:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        add_history(user, "🎲 Dice gagné", bet)
        embed.color = COLOR_GREEN
        embed.add_field(name="🎉 Gagné !", value=f"+**{bet:,}** 🪙", inline=True)
    elif total == 7:
        embed.color = COLOR_BLUE
        embed.add_field(name="🤝 Égalité", value="Mise remboursée", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🎲 Dice perdu", -bet)
        embed.color = COLOR_RED
        embed.add_field(name="❌ Perdu !", value=f"-**{bet:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

# ─── CRASH (corrigé) ──────────────────────────────────────────────────────────

@bot.command(name="crash")
async def crash(ctx, mise: str = "0"):
    """Jeu de crash : le multiplicateur monte, cashout avant le crash !"""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : **10** 🪙. Usage : `%crash <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))

    user["total_games_played"] = user.get("total_games_played", 0) + 1

    r = random.random()
    if r < 0.40:
        crash_at = round(random.uniform(1.0, 1.5), 2)
    elif r < 0.65:
        crash_at = round(random.uniform(1.5, 2.5), 2)
    elif r < 0.82:
        crash_at = round(random.uniform(2.5, 5.0), 2)
    elif r < 0.94:
        crash_at = round(random.uniform(5.0, 10.0), 2)
    else:
        crash_at = round(random.uniform(10.0, 50.0), 2)

    def make_crash_embed(mult: float, crashed: bool = False):
        val = int(bet * mult)
        if crashed:
            e = discord.Embed(title="💥  CRASH !", color=COLOR_RED)
        else:
            e = discord.Embed(title="📈  Crash — En cours...", color=COLOR_CASINO)
        # Barre de progression visuelle
        safe_pct = min(int((mult - 1) / (crash_at - 1) * 16), 16) if crash_at > 1 else 16
        bar = "🟩" * safe_pct + "🟥" * (16 - safe_pct) if not crashed else "🟥" * 16
        e.add_field(name="📊 Multiplicateur", value=f"**x{mult:.2f}** {'💥' if crashed else '🚀'}", inline=True)
        e.add_field(name="💰 Valeur actuelle", value=f"**{val:,}** 🪙", inline=True)
        e.add_field(name="💵 Mise", value=f"**{bet:,}** 🪙", inline=True)
        e.add_field(name="📉 Risque", value=bar, inline=False)
        if not crashed:
            e.set_footer(text="Tape  stop  pour encaisser !")
        return e

    msg = await ctx.send(embed=make_crash_embed(1.0))

    current_mult = 1.0
    step = 0.10
    cashed_out = False
    stop_mult = None

    # ── BOUCLE CORRIGÉE ──
    # On avance d'abord le mult, puis on écoute le stop pendant le tick.
    while True:
        # 1. Avancer le multiplicateur
        current_mult = round(current_mult + step, 2)
        step = round(step * 1.06, 3)

        # 2. Vérifier le crash AVANT d'afficher
        if current_mult >= crash_at:
            current_mult = crash_at
            await msg.edit(embed=make_crash_embed(current_mult, crashed=True))
            break

        # 3. Mettre à jour l'embed avec la vraie valeur
        await msg.edit(embed=make_crash_embed(current_mult))

        # 4. Écouter le stop pendant 1.5 secondes
        try:
            await asyncio.wait_for(
                bot.wait_for(
                    "message",
                    check=lambda m: (
                        m.author == ctx.author and
                        m.channel == ctx.channel and
                        m.content.strip().lower() in ("stop", "cashout", "encaisser", "cash")
                    )
                ),
                timeout=1.5
            )
            cashed_out = True
            stop_mult = current_mult  # ✅ mult déjà à jour, valeur correcte
            break
        except asyncio.TimeoutError:
            pass

    # Résultat
    if cashed_out:
        win = int(bet * stop_mult)
        gain = win - bet
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        add_history(user, f"📈 Crash cashout x{stop_mult:.2f}", gain)
        result_embed = discord.Embed(
            title="💸  Cashout !",
            description=f"Tu as encaissé à **x{stop_mult:.2f}** !\n*Le crash était à x{crash_at:.2f}*",
            color=COLOR_GREEN
        )
        result_embed.add_field(name="💰 Gains", value=f"+**{gain:,}** 🪙", inline=True)
        result_embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    else:
        if user.get("insurance"):
            refund = bet // 2
            user["coins"] = max(0, user["coins"] - bet + refund)
            user["insurance"] = False
            add_history(user, f"💥 Crash x{crash_at:.2f} (assurance)", -(bet - refund))
            result_embed = discord.Embed(
                title="💥  Crash !",
                description=f"Crash à **x{crash_at:.2f}** !\n🔒 Assurance activée — remboursement partiel.",
                color=COLOR_ORANGE
            )
            result_embed.add_field(name="❌ Perte nette", value=f"-**{bet - refund:,}** 🪙", inline=True)
            result_embed.add_field(name="🔒 Remboursé", value=f"+**{refund:,}** 🪙", inline=True)
        else:
            user["coins"] = max(0, user["coins"] - bet)
            add_history(user, f"💥 Crash x{crash_at:.2f}", -bet)
            result_embed = discord.Embed(
                title="💥  CRASH !",
                description=f"Le marché s'est effondré à **x{crash_at:.2f}** ! 📉",
                color=COLOR_RED
            )
            result_embed.add_field(name="❌ Perte", value=f"-**{bet:,}** 🪙", inline=True)
        user["casino_losses"] += 1
        result_embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)

    save_data(data)
    await msg.edit(embed=result_embed)

# ─── PLINKO (nouveau) ─────────────────────────────────────────────────────────

@bot.command(name="plinko")
async def plinko(ctx, mise: str = "0"):
    """La bille tombe dans des cases avec des multiplicateurs aléatoires."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : **10** 🪙. Usage : `%plinko <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))

    user["total_games_played"] = user.get("total_games_played", 0) + 1

    # Multiplicateurs par slot (9 slots, distribution en cloche)
    multipliers = [0.2, 0.5, 1.0, 1.5, 3.0, 1.5, 1.0, 0.5, 0.2]
    weights     = [3,   7,   12,  18,  20,  18,  12,  7,   3  ]

    # Simuler la chute : 8 niveaux, gauche ou droite
    pos = 4  # position centrale (0-8)
    path = []
    for _ in range(8):
        move = random.choice([-1, 1])
        pos = max(0, min(8, pos + move))
        path.append("↙" if move == -1 else "↘")

    slot = random.choices(range(9), weights=weights, k=1)[0]
    mult = multipliers[slot]

    # Affichage du plateau
    board_top    = "┌───┬───┬───┬───┬───┬───┬───┬───┬───┐"
    board_mults  = "│" + "│".join(f"{m:.1f}".center(3) for m in multipliers) + "│"
    board_bottom = "└───┴───┴───┴───┴───┴───┴───┴───┴───┘"
    ball_row     = " ".join("🔴" if i == slot else " · " for i in range(9))
    path_str     = "  ".join(path)

    board_display = f"```\n{board_top}\n{board_mults}\n{board_bottom}\n{ball_row}\n```"

    gain = int(bet * mult) - bet
    if gain > 0:
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        add_history(user, f"🎯 Plinko x{mult}", gain)
        color = COLOR_GREEN if mult >= 1.0 else COLOR_ORANGE
    elif gain == 0:
        color = COLOR_BLUE
    else:
        user["coins"] = max(0, user["coins"] + gain)
        user["casino_losses"] += 1
        add_history(user, f"🎯 Plinko x{mult}", gain)
        color = COLOR_RED

    embed = discord.Embed(title="🎯  Plinko", color=color)
    embed.add_field(name="🎪 Plateau", value=board_display, inline=False)
    embed.add_field(name="🔴 Chemin", value=f"`{path_str}`", inline=False)
    embed.add_field(name="📊 Multiplicateur", value=f"**x{mult}**", inline=True)
    sign = "+" if gain >= 0 else ""
    embed.add_field(name="💰 Résultat", value=f"**{sign}{gain:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

# ─── HIGHLOW (nouveau) ────────────────────────────────────────────────────────

@bot.command(name="highlow", aliases=["hl"])
async def highlow(ctx, mise: str = "0"):
    """Devine si la prochaine carte est plus haute ou plus basse."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : **10** 🪙. Usage : `%highlow <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))

    user["total_games_played"] = user.get("total_games_played", 0) + 1

    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits_list = ["♠","♥","♦","♣"]
    rank_vals = {r: i for i, r in enumerate(ranks)}

    current_card = random.choice(ranks) + random.choice(suits_list)
    current_rank = current_card[:-1]
    current_val = rank_vals[current_rank]
    mult = 1.0
    round_num = 0

    def make_hl_embed(current: str, mult: float, round_n: int):
        e = discord.Embed(title="🃏  High or Low", color=COLOR_CASINO)
        e.add_field(name="🃏 Carte actuelle", value=render_hand([current]), inline=False)
        e.add_field(name="🎯 Multiplicateur actuel", value=f"**x{mult:.2f}**", inline=True)
        e.add_field(name="💰 Valeur si cashout", value=f"**{int(bet * mult):,}** 🪙", inline=True)
        e.add_field(name="🔄 Round", value=f"**{round_n}**", inline=True)
        e.set_footer(text="Tape  haut  /  bas  pour jouer  •  stop  pour encaisser")
        return e

    msg = await ctx.send(embed=make_hl_embed(current_card, mult, round_num))

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and \
               m.content.strip().lower() in ("haut","bas","h","b","high","low","stop","s")

    while True:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            break

        inp = resp.content.strip().lower()
        if inp in ("stop","s"):
            break

        next_card = random.choice(ranks) + random.choice(suits_list)
        next_rank = next_card[:-1]
        next_val = rank_vals[next_rank]

        if inp in ("haut","h","high"):
            win = next_val > current_val
        else:
            win = next_val < current_val

        if next_val == current_val:
            await ctx.send(embed=discord.Embed(
                description=f"🃏 Égalité ! (**{next_card}**) — Aucun changement.",
                color=COLOR_BLUE
            ))
            current_card, current_rank, current_val = next_card, next_rank, next_val
            continue

        if win:
            mult = round(mult * 1.5, 2)
            round_num += 1
            current_card, current_rank, current_val = next_card, next_rank, next_val
            await ctx.send(embed=discord.Embed(
                description=f"✅ **{next_card}** — Bonne réponse ! Mult → **x{mult:.2f}**\n*(Tape `stop` pour encaisser ou continue !)*",
                color=COLOR_GREEN
            ))
            msg = await ctx.send(embed=make_hl_embed(current_card, mult, round_num))
        else:
            # Perdu
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            add_history(user, "🃏 HighLow perdu", -bet)
            save_data(data)
            return await ctx.send(embed=discord.Embed(
                title="❌  Perdu !",
                description=f"La carte était **{next_card}**.\nPerte de **{bet:,}** 🪙.",
                color=COLOR_RED
            ).add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True))

    # Cashout
    gain = int(bet * mult) - bet
    user["coins"] += gain
    user["casino_wins"] += 1
    user["total_earned"] = user.get("total_earned", 0) + gain
    add_history(user, f"🃏 HighLow x{mult:.2f}", gain)
    save_data(data)
    embed = discord.Embed(title="💸  Cashout HighLow !", color=COLOR_GREEN)
    embed.add_field(name="📊 Mult final", value=f"**x{mult:.2f}**", inline=True)
    embed.add_field(name="💰 Gains", value=f"+**{gain:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    await ctx.send(embed=embed)

# ─── VIDEO POKER (nouveau) ────────────────────────────────────────────────────

def poker_hand_name(hand: list[str]) -> tuple[str, int]:
    """Identifie la main de poker et retourne (nom, multiplicateur)."""
    rank_order = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":11,"Q":12,"K":13,"A":14}
    ranks = [c[:-1] for c in hand]
    suits = [c[-1] for c in hand]
    vals = sorted([rank_order[r] for r in ranks])
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    freq = sorted(counts.values(), reverse=True)
    flush = len(set(suits)) == 1
    straight = vals == list(range(vals[0], vals[0]+5))
    # Royal flush
    if flush and vals == [10,11,12,13,14]:
        return "🌟 Royal Flush", 50
    if flush and straight:
        return "🎴 Quinte Flush", 25
    if freq[0] == 4:
        return "4️⃣ Carré", 10
    if freq[0] == 3 and freq[1] == 2:
        return "🏠 Full House", 6
    if flush:
        return "♠ Flush", 5
    if straight:
        return "➡️ Suite", 4
    if freq[0] == 3:
        return "3️⃣ Brelan", 3
    if freq[0] == 2 and freq[1] == 2:
        return "2️⃣ Double Paire", 2
    if freq[0] == 2:
        # Paire valide si J, Q, K ou A
        pair_rank = [r for r, c in counts.items() if c == 2][0]
        if rank_order[pair_rank] >= 11:
            return "👥 Paire (J+)", 1
    return "❌ Rien", 0

@bot.command(name="poker")
async def poker(ctx, mise: str = "0"):
    """Video Poker — 5 cartes, garde celles que tu veux, une relance."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : **10** 🪙. Usage : `%poker <mise>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))

    user["total_games_played"] = user.get("total_games_played", 0) + 1

    suits_list = ["♠","♥","♦","♣"]
    ranks_list = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck = [r+s for r in ranks_list for s in suits_list]
    random.shuffle(deck)

    hand = [deck.pop() for _ in range(5)]

    # Paiement
    pay_table = (
        "```\n"
        "🌟 Royal Flush    → x50\n"
        "🎴 Quinte Flush   → x25\n"
        "4️⃣ Carré          → x10\n"
        "🏠 Full House     → x6\n"
        "♠  Flush          → x5\n"
        "➡️  Suite          → x4\n"
        "3️⃣ Brelan         → x3\n"
        "2️⃣ Double Paire   → x2\n"
        "👥 Paire (J+)     → x1\n"
        "❌ Rien           → perte\n"
        "```"
    )

    embed = discord.Embed(title="🃏  Video Poker", color=COLOR_CASINO)
    embed.add_field(name="🂠 Ta main", value=render_hand(hand), inline=False)
    embed.add_field(name="💰 Mise", value=f"**{bet:,}** 🪙", inline=True)
    embed.add_field(name="📋 Gains", value=pay_table, inline=False)
    embed.set_footer(text="Tape les numéros des cartes à GARDER (ex: 1 3 5) ou 'none' pour tout relancer")
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        resp = await bot.wait_for("message", check=check, timeout=45)
    except asyncio.TimeoutError:
        return await ctx.send(embed=discord.Embed(description="⏳ Temps écoulé !", color=COLOR_RED))

    content = resp.content.strip().lower()
    if content == "none":
        keep_indices = []
    else:
        try:
            keep_indices = [int(x)-1 for x in content.split() if x.isdigit() and 1 <= int(x) <= 5]
        except:
            keep_indices = []

    # Relance
    new_hand = []
    for i in range(5):
        if i in keep_indices:
            new_hand.append(hand[i])
        else:
            new_hand.append(deck.pop())

    hand_name, mult = poker_hand_name(new_hand)

    if mult > 0:
        gain = bet * mult
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        if gain > user.get("best_jackpot", 0):
            user["best_jackpot"] = gain
        add_history(user, f"🃏 Poker {hand_name}", gain)
        color = COLOR_GREEN
        result_txt = f"+**{gain:,}** 🪙  (x{mult})"
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        add_history(user, "🃏 Poker rien", -bet)
        color = COLOR_RED
        result_txt = f"-**{bet:,}** 🪙"

    save_data(data)
    result = discord.Embed(title=f"🃏  Video Poker — {hand_name}", color=color)
    result.add_field(name="🂠 Main finale", value=render_hand(new_hand), inline=False)
    result.add_field(name="🏆 Résultat", value=result_txt, inline=True)
    result.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    await ctx.send(embed=result)

# ─── DUEL POKER (nouveau) ─────────────────────────────────────────────────────

@bot.command(name="duel_poker", aliases=["duelpokser", "pokervspoker"])
async def duel_poker(ctx, target: discord.Member, mise: str = "0"):
    """Duel de poker — meilleure main gagne."""
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    challenger = get_user(data, ctx.author.id)
    opponent = get_user(data, target.id)
    bet = parse_bet(challenger, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : 10. Usage : `%duel_poker @user <mise>`", color=COLOR_RED))
    if bet > challenger["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Tu n'as pas assez de coins.", color=COLOR_RED))
    if bet > opponent["coins"]:
        return await ctx.send(embed=discord.Embed(description=f"❌ {target.display_name} n'a pas assez de coins.", color=COLOR_RED))

    embed = discord.Embed(
        title="🃏  Duel Poker",
        description=f"{target.mention}, {ctx.author.mention} te défie pour **{bet:,}** 🪙 !\nAcceptes-tu ? Réponds `oui` ou `non`.",
        color=COLOR_ORANGE
    )
    await ctx.send(embed=embed)
    def check_a(m): return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non")
    try:
        r = await bot.wait_for("message", check=check_a, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send(embed=discord.Embed(description="⏳ Défi expiré.", color=COLOR_RED))
    if r.content.lower() == "non":
        return await ctx.send(embed=discord.Embed(description="❌ Défi refusé.", color=COLOR_RED))

    suits_list = ["♠","♥","♦","♣"]
    ranks_list = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck = [r+s for r in ranks_list for s in suits_list]
    random.shuffle(deck)

    hand1 = [deck.pop() for _ in range(5)]
    hand2 = [deck.pop() for _ in range(5)]

    _, mult1 = poker_hand_name(hand1)
    name1, _ = poker_hand_name(hand1)
    _, mult2 = poker_hand_name(hand2)
    name2, _ = poker_hand_name(hand2)

    result = discord.Embed(title="🃏  Résultat Duel Poker", color=COLOR_CASINO)
    result.add_field(name=f"🧑 {ctx.author.display_name}  —  {name1}", value=render_hand(hand1), inline=False)
    result.add_field(name=f"🧑 {target.display_name}  —  {name2}", value=render_hand(hand2), inline=False)

    if mult1 > mult2:
        challenger["coins"] += bet
        opponent["coins"] = max(0, opponent["coins"] - bet)
        challenger["casino_wins"] += 1
        result.color = COLOR_GREEN
        result.add_field(name="🏆 Vainqueur !", value=f"{ctx.author.mention} remporte **{bet:,}** 🪙 !", inline=False)
    elif mult2 > mult1:
        opponent["coins"] += bet
        challenger["coins"] = max(0, challenger["coins"] - bet)
        opponent["casino_wins"] += 1
        result.color = COLOR_RED
        result.add_field(name="🏆 Vainqueur !", value=f"{target.mention} remporte **{bet:,}** 🪙 !", inline=False)
    else:
        result.color = COLOR_BLUE
        result.add_field(name="🤝 Égalité !", value="Mises remboursées.", inline=False)

    save_data(data)
    await ctx.send(embed=result)

# ─── Mini-jeux ────────────────────────────────────────────────────────────────

TRIVIA_QUESTIONS = [
    {"q":"Quelle est la capitale de l'Australie ?","a":"canberra","choices":["Sydney","Melbourne","Canberra","Brisbane"]},
    {"q":"Combien de côtés a un hexagone ?","a":"6","choices":["5","6","7","8"]},
    {"q":"Quel élément chimique a le symbole 'Au' ?","a":"or","choices":["Argent","Or","Cuivre","Aluminium"]},
    {"q":"En quelle année l'homme a-t-il marché sur la Lune ?","a":"1969","choices":["1965","1967","1969","1971"]},
    {"q":"Quel est le plus grand océan du monde ?","a":"pacifique","choices":["Atlantique","Indien","Pacifique","Arctique"]},
    {"q":"Qui a peint la Joconde ?","a":"léonard de vinci","choices":["Michel-Ange","Raphaël","Léonard de Vinci","Botticelli"]},
    {"q":"Quelle est la devise de la France ?","a":"liberté égalité fraternité","choices":["Honneur et Patrie","Liberté Égalité Fraternité","Force et Honneur","Dieu et Mon Droit"]},
    {"q":"Quel pays a la plus grande superficie du monde ?","a":"russie","choices":["Canada","États-Unis","Russie","Chine"]},
    {"q":"Combien de planètes compte notre système solaire ?","a":"8","choices":["7","8","9","10"]},
    {"q":"Quel est le symbole chimique de l'eau ?","a":"h2o","choices":["H2O","CO2","O2","H2"]},
    {"q":"Quelle est la monnaie du Japon ?","a":"yen","choices":["Yuan","Won","Yen","Baht"]},
    {"q":"Qui a écrit Roméo et Juliette ?","a":"shakespeare","choices":["Molière","Shakespeare","Hugo","Dickens"]},
    {"q":"Quelle est la planète la plus proche du Soleil ?","a":"mercure","choices":["Vénus","Mercure","Mars","Terre"]},
    {"q":"En quelle année a été fondée Paris ?","a":"52","choices":["52 av. J.C","476","987","1066"]},
    {"q":"Combien d'os le corps humain adulte possède-t-il ?","a":"206","choices":["186","206","226","256"]},
]

QUIZ_CATEGORIES = {
    "sport": [
        {"q":"Combien de joueurs dans une équipe de foot ?","a":"11","choices":["9","10","11","12"]},
        {"q":"Dans quel sport utilise-t-on un volant ?","a":"badminton","choices":["Tennis","Badminton","Squash","Ping-pong"]},
        {"q":"Combien de sets pour gagner à Roland-Garros (hommes) ?","a":"3","choices":["2","3","4","5"]},
        {"q":"Quel pays a remporté la Coupe du Monde 2018 ?","a":"france","choices":["Brésil","Allemagne","France","Croatie"]},
    ],
    "cinema": [
        {"q":"Qui réalise les films de la saga 'Avengers: Endgame' ?","a":"russo","choices":["Nolan","Spielberg","Russo","Scott"]},
        {"q":"Dans quel film apparaît le personnage 'Forrest Gump' ?","a":"forrest gump","choices":["Cast Away","Forrest Gump","Rain Man","Big"]},
        {"q":"Quel acteur joue Iron Man ?","a":"robert downey jr","choices":["Chris Evans","Robert Downey Jr","Mark Ruffalo","Chris Hemsworth"]},
        {"q":"Quel studio a créé le film 'Toy Story' ?","a":"pixar","choices":["DreamWorks","Pixar","Disney","Sony"]},
    ],
    "science": [
        {"q":"Quelle planète est la plus grande du système solaire ?","a":"jupiter","choices":["Saturne","Jupiter","Neptune","Uranus"]},
        {"q":"Quel est le plus petit os du corps humain ?","a":"étrier","choices":["Phalange","Étrier","Coccyx","Radius"]},
        {"q":"À quelle température l'eau bout-elle (°C) ?","a":"100","choices":["90","95","100","110"]},
        {"q":"Quel gaz les plantes absorbent-elles ?","a":"co2","choices":["O2","H2","CO2","N2"]},
    ],
    "histoire": [
        {"q":"En quelle année a débuté la Première Guerre Mondiale ?","a":"1914","choices":["1910","1912","1914","1916"]},
        {"q":"Qui était le premier président des États-Unis ?","a":"washington","choices":["Lincoln","Jefferson","Washington","Adams"]},
        {"q":"Quelle révolution eut lieu en 1789 ?","a":"française","choices":["Américaine","Française","Russe","Industrielle"]},
        {"q":"Quel mur est tombé en 1989 ?","a":"berlin","choices":["Chine","Berlin","Hadrien","Mexique"]},
    ],
}

@bot.command(name="trivia")
async def trivia(ctx):
    q = random.choice(TRIVIA_QUESTIONS)
    reward_coins = random.randint(40, 150)
    embed = discord.Embed(title="🧠  Trivia", description=f"**{q['q']}**", color=COLOR_BLUE)
    choices_str = "\n".join(f"**{i+1}.** {c}" for i,c in enumerate(q["choices"]))
    embed.add_field(name="Choix", value=choices_str, inline=False)
    embed.set_footer(text=f"Réponds avec le numéro (1-4) — ⏳ 20 secondes — Récompense : {reward_coins} 🪙 + 20 XP")
    await ctx.send(embed=embed)

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel: return False
        try:
            idx = int(m.content.strip()) - 1
            return 0 <= idx < len(q["choices"])
        except:
            return any(m.content.strip().lower() in c.lower() for c in q["choices"])

    try:
        resp = await bot.wait_for("message", check=check, timeout=20)
    except asyncio.TimeoutError:
        return await ctx.send(embed=discord.Embed(description=f"⏳ Temps écoulé ! La réponse était **{q['a'].title()}**.", color=COLOR_RED))

    ans = resp.content.strip().lower()
    try:
        idx = int(ans) - 1
        given = q["choices"][idx].lower()
    except:
        given = ans

    if q["a"].lower() in given or given in q["a"].lower():
        data = load_data()
        user = get_user(data, ctx.author.id)
        user["coins"] += reward_coins
        user["xp"] += 20
        user["total_earned"] = user.get("total_earned", 0) + reward_coins
        add_history(user, "🧠 Trivia gagné", reward_coins)
        save_data(data)
        embed = discord.Embed(title="✅  Bonne réponse !", color=COLOR_GREEN)
        embed.add_field(name="💰 Gains", value=f"+**{reward_coins}** 🪙", inline=True)
        embed.add_field(name="⭐ XP", value="+**20** XP", inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send(embed=discord.Embed(
            title="❌  Mauvaise réponse !",
            description=f"La bonne réponse était : **{q['a'].title()}**",
            color=COLOR_RED
        ))

@bot.command(name="quiz")
async def quiz(ctx, category: str = ""):
    """Quiz par catégorie : sport, cinema, science, histoire."""
    cat = category.lower()
    if cat not in QUIZ_CATEGORIES:
        cats = ", ".join(f"`{c}`" for c in QUIZ_CATEGORIES)
        return await ctx.send(embed=discord.Embed(
            title="🧠  Quiz",
            description=f"Choisis une catégorie : {cats}\nUsage : `%quiz <catégorie>`",
            color=COLOR_BLUE
        ))
    q = random.choice(QUIZ_CATEGORIES[cat])
    reward_coins = random.randint(60, 200)
    cat_emojis = {"sport":"⚽","cinema":"🎬","science":"🔬","histoire":"📜"}
    embed = discord.Embed(
        title=f"{cat_emojis.get(cat,'🧠')}  Quiz — {cat.title()}",
        description=f"**{q['q']}**",
        color=COLOR_PURPLE
    )
    choices_str = "\n".join(f"**{i+1}.** {c}" for i,c in enumerate(q["choices"]))
    embed.add_field(name="Choix", value=choices_str, inline=False)
    embed.set_footer(text=f"⏳ 20 secondes — Récompense : {reward_coins} 🪙 + 30 XP")
    await ctx.send(embed=embed)

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel: return False
        try:
            idx = int(m.content.strip()) - 1
            return 0 <= idx < len(q["choices"])
        except:
            return any(m.content.strip().lower() in c.lower() for c in q["choices"])

    try:
        resp = await bot.wait_for("message", check=check, timeout=20)
    except asyncio.TimeoutError:
        return await ctx.send(embed=discord.Embed(description=f"⏳ Temps écoulé ! La réponse : **{q['a'].title()}**.", color=COLOR_RED))

    ans = resp.content.strip().lower()
    try:
        idx = int(ans) - 1
        given = q["choices"][idx].lower()
    except:
        given = ans

    if q["a"].lower() in given or given in q["a"].lower():
        data = load_data()
        user = get_user(data, ctx.author.id)
        user["coins"] += reward_coins
        user["xp"] += 30
        user["total_earned"] = user.get("total_earned", 0) + reward_coins
        add_history(user, f"🧠 Quiz {cat} gagné", reward_coins)
        save_data(data)
        embed = discord.Embed(title="✅  Bonne réponse !", color=COLOR_GREEN)
        embed.add_field(name="💰 Gains", value=f"+**{reward_coins}** 🪙", inline=True)
        embed.add_field(name="⭐ XP", value="+**30** XP", inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send(embed=discord.Embed(
            title="❌  Mauvaise réponse !",
            description=f"La bonne réponse était : **{q['a'].title()}**",
            color=COLOR_RED
        ))

@bot.command(name="rps")
async def rps(ctx, target: discord.Member, mise: str = "0"):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    challenger = get_user(data, ctx.author.id)
    opponent = get_user(data, target.id)
    bet = parse_bet(challenger, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : 10. Usage : `%rps @user <mise>`", color=COLOR_RED))
    if bet > challenger["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Tu n'as pas assez de coins.", color=COLOR_RED))
    if bet > opponent["coins"]:
        return await ctx.send(embed=discord.Embed(description=f"❌ {target.display_name} n'a pas assez de coins.", color=COLOR_RED))

    embed = discord.Embed(
        title="✊  Pierre-Feuille-Ciseaux",
        description=f"{target.mention}, {ctx.author.mention} te défie pour **{bet:,}** 🪙 !\nAcceptes-tu ? Réponds `oui` ou `non`.",
        color=COLOR_ORANGE
    )
    await ctx.send(embed=embed)

    def check_accept(m):
        return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non","yes","no")
    try:
        resp = await bot.wait_for("message", check=check_accept, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send(embed=discord.Embed(description="⏳ Défi expiré.", color=COLOR_RED))
    if resp.content.lower() in ("non","no"):
        return await ctx.send(embed=discord.Embed(description="❌ Défi refusé.", color=COLOR_RED))

    choices_map = {"pierre":"🪨","feuille":"📄","ciseaux":"✂️","p":"🪨","f":"📄","c":"✂️"}
    wins_map = {"pierre":"ciseaux","feuille":"pierre","ciseaux":"feuille"}

    async def get_choice(player):
        try:
            await player.send("🎮 **RPS** — Choisis : `pierre`, `feuille` ou `ciseaux`")
            def dm_check(m): return m.author == player and isinstance(m.channel, discord.DMChannel) and m.content.lower() in choices_map
            r = await bot.wait_for("message", check=dm_check, timeout=30)
            return r.content.lower()
        except:
            return None

    await ctx.send(embed=discord.Embed(description="📩 Vérifiez vos DMs pour choisir !", color=COLOR_BLUE))
    c1 = await get_choice(ctx.author)
    c2 = await get_choice(target)
    if not c1 or not c2:
        return await ctx.send(embed=discord.Embed(description="⏳ L'un des joueurs n'a pas répondu à temps.", color=COLOR_RED))

    c1n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c1,c1)
    c2n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c2,c2)
    e1, e2 = choices_map[c1], choices_map[c2]

    result_embed = discord.Embed(title="✊  Résultat RPS", color=COLOR_BLUE)
    result_embed.add_field(name=ctx.author.display_name, value=e1, inline=True)
    result_embed.add_field(name="VS", value="⚔️", inline=True)
    result_embed.add_field(name=target.display_name, value=e2, inline=True)

    if c1n == c2n:
        result_embed.add_field(name="🤝 Résultat", value="Égalité ! Mise remboursée.", inline=False)
    elif wins_map[c1n] == c2n:
        challenger["coins"] += bet; opponent["coins"] = max(0, opponent["coins"] - bet)
        challenger["casino_wins"] += 1
        result_embed.color = COLOR_GREEN
        result_embed.add_field(name="🏆 Victoire !", value=f"{ctx.author.mention} gagne **{bet:,}** 🪙 !", inline=False)
    else:
        opponent["coins"] += bet; challenger["coins"] = max(0, challenger["coins"] - bet)
        opponent["casino_wins"] += 1
        result_embed.color = COLOR_RED
        result_embed.add_field(name="🏆 Victoire !", value=f"{target.mention} gagne **{bet:,}** 🪙 !", inline=False)
    save_data(data)
    await ctx.send(embed=result_embed)

@bot.command(name="duel")
async def duel(ctx, target: discord.Member, mise: str = "0"):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send(embed=discord.Embed(description="❌ Cible invalide.", color=COLOR_RED))
    data = load_data()
    challenger = get_user(data, ctx.author.id)
    opponent = get_user(data, target.id)
    bet = parse_bet(challenger, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Mise minimum : 10. Usage : `%duel @user <mise>`", color=COLOR_RED))
    if bet > challenger["coins"]: return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    if bet > opponent["coins"]: return await ctx.send(embed=discord.Embed(description=f"❌ {target.display_name} n'a pas assez de coins.", color=COLOR_RED))

    embed = discord.Embed(
        title="⚔️  Défi lancé !",
        description=f"{target.mention}, {ctx.author.mention} te défie pour **{bet:,}** 🪙 !\nRéponds `oui` ou `non`.",
        color=COLOR_ORANGE
    )
    await ctx.send(embed=embed)
    def check_a(m): return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non")
    try:
        r = await bot.wait_for("message", check=check_a, timeout=30)
    except asyncio.TimeoutError: return await ctx.send(embed=discord.Embed(description="⏳ Défi expiré.", color=COLOR_RED))
    if r.content.lower() == "non": return await ctx.send(embed=discord.Embed(description="❌ Défi refusé.", color=COLOR_RED))

    await asyncio.sleep(1)
    r1, r2 = random.randint(1,100), random.randint(1,100)
    while r1 == r2:
        r1, r2 = random.randint(1,100), random.randint(1,100)

    result_embed = discord.Embed(title="⚔️  Résultat du Duel", color=COLOR_BLUE)
    result_embed.add_field(name=ctx.author.display_name, value=f"🎲 **{r1}**", inline=True)
    result_embed.add_field(name="VS", value="⚡", inline=True)
    result_embed.add_field(name=target.display_name, value=f"🎲 **{r2}**", inline=True)

    if r1 > r2:
        challenger["coins"] += bet; opponent["coins"] = max(0, opponent["coins"] - bet)
        result_embed.color = COLOR_GREEN
        result_embed.add_field(name="🏆 Vainqueur !", value=f"{ctx.author.mention} remporte **{bet:,}** 🪙 !", inline=False)
    else:
        opponent["coins"] += bet; challenger["coins"] = max(0, challenger["coins"] - bet)
        result_embed.color = COLOR_RED
        result_embed.add_field(name="🏆 Vainqueur !", value=f"{target.mention} remporte **{bet:,}** 🪙 !", inline=False)
    save_data(data)
    await ctx.send(embed=result_embed)

@bot.command(name="mines")
async def mines(ctx, mise: str = "0", cases: int = 3):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send(embed=discord.Embed(description="❌ Usage : `%mines <mise> <nb_mines 1-8>`", color=COLOR_RED))
    if bet > user["coins"]:
        return await ctx.send(embed=discord.Embed(description="❌ Pas assez de coins.", color=COLOR_RED))
    cases = max(1, min(8, cases))
    user["total_games_played"] = user.get("total_games_played", 0) + 1
    total = 9
    mine_positions = random.sample(range(total), cases)
    revealed = []
    mult = 1.0

    def grid_display():
        rows = []
        for row in range(3):
            line = ""
            for col in range(3):
                i = row * 3 + col
                num = str(i+1).center(3)
                if i in revealed:
                    line += "💣  " if i in mine_positions else "💎  "
                else:
                    line += f"[{num}]"
            rows.append(line.strip())
        return "\n".join(rows)

    def make_mines_embed(status="playing"):
        color = COLOR_CASINO if status == "playing" else (COLOR_GREEN if status == "win" else COLOR_RED)
        e = discord.Embed(title=f"💣  Mines  ({cases} {'mine' if cases == 1 else 'mines'})", color=color)
        e.add_field(name="Grille", value=f"```\n{grid_display()}\n```", inline=False)
        e.add_field(name="💰 Mise", value=f"**{bet:,}** 🪙", inline=True)
        e.add_field(name="📊 Multiplicateur", value=f"**x{mult:.2f}**", inline=True)
        e.add_field(name="💵 Valeur actuelle", value=f"**{int(bet * mult):,}** 🪙", inline=True)
        if status == "playing":
            e.set_footer(text="Tape un numéro (1-9) pour révéler | 'stop' pour encaisser")
        return e

    await ctx.send(embed=make_mines_embed())

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel:
            return False
        content = m.content.strip().lower()
        if content in ("stop", "encaisser", "cash"):
            return True
        try:
            v = int(content)
            return 1 <= v <= 9
        except:
            return False

    while len(revealed) < total - cases:
        try:
            resp = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            break

        content = resp.content.strip().lower()
        if content in ("stop", "encaisser", "cash"):
            break

        idx = int(content) - 1
        if idx in revealed:
            await ctx.send(embed=discord.Embed(description="⚠️ Case déjà révélée !", color=COLOR_ORANGE))
            continue

        revealed.append(idx)

        if idx in mine_positions:
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            for m_idx in mine_positions:
                if m_idx not in revealed:
                    revealed.append(m_idx)
            add_history(user, "💣 Mines — boom !", -bet)
            save_data(data)
            e = make_mines_embed("lose")
            e.add_field(name="💥 MINE !", value=f"Perdu **{bet:,}** 🪙", inline=False)
            return await ctx.send(embed=e)

        safe = total - cases
        mult = round(1 + (len(revealed) / safe) * (cases * 0.85), 2)
        await ctx.send(embed=make_mines_embed())

    win = int(bet * mult)
    gain = win - bet
    user["coins"] += gain
    if gain >= 0:
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        add_history(user, f"💣 Mines cashout x{mult:.2f}", gain)
    save_data(data)
    e = make_mines_embed("win")
    e.add_field(name="💸 Encaissé !", value=f"x{mult:.2f} → **+{gain:,}** 🪙", inline=False)
    await ctx.send(embed=e)

@bot.command(name="course")
async def course(ctx):
    horses = ["🐴 Éclair", "🦄 Pégase", "🐎 Tornado", "🏇 Foudre", "🌟 Météore"]
    odds = [2.5, 3.0, 2.0, 4.0, 5.0]
    embed = discord.Embed(
        title="🏇  Course de Chevaux",
        description="Pariez sur votre cheval ! Vous avez **30 secondes**.",
        color=COLOR_ORANGE
    )
    for i, (h, o) in enumerate(zip(horses, odds)):
        embed.add_field(name=f"{i+1}. {h}", value=f"Cote : **x{o}**", inline=True)
    embed.set_footer(text="Format : <numéro> <mise> — ex: 2 500")
    await ctx.send(embed=embed)

    bets: dict[int, tuple] = {}

    def check(m):
        if m.channel != ctx.channel or m.author.bot: return False
        parts = m.content.strip().split()
        if len(parts) == 2:
            try: return 1 <= int(parts[0]) <= len(horses) and int(parts[1]) >= 10
            except: pass
        return False

    deadline = time.time() + 30
    await ctx.send(embed=discord.Embed(description="⏳ **30 secondes** pour parier !", color=COLOR_BLUE))

    while time.time() < deadline:
        remaining = max(0, deadline - time.time())
        try:
            resp = await bot.wait_for("message", check=check, timeout=remaining)
        except asyncio.TimeoutError:
            break
        parts = resp.content.strip().split()
        horse_idx, bet_amt = int(parts[0]) - 1, int(parts[1])
        data = load_data()
        user = get_user(data, resp.author.id)
        if bet_amt > user["coins"]:
            await ctx.send(embed=discord.Embed(description=f"❌ {resp.author.mention} n'a pas assez de coins.", color=COLOR_RED))
            continue
        bets[resp.author.id] = (horse_idx, bet_amt)
        await ctx.send(embed=discord.Embed(
            description=f"✅ {resp.author.mention} mise **{bet_amt:,}** 🪙 sur **{horses[horse_idx]}** !",
            color=COLOR_GREEN
        ))
        save_data(data)

    if not bets:
        return await ctx.send(embed=discord.Embed(description="🏇 Aucun pari — course annulée.", color=COLOR_RED))

    await ctx.send(embed=discord.Embed(description="🏁 **La course commence !**", color=COLOR_ORANGE))
    await asyncio.sleep(3)
    winner_idx = random.randint(0, len(horses) - 1)

    result_embed = discord.Embed(
        title="🏆  Résultat de la course",
        description=f"**{horses[winner_idx]}** remporte la course !",
        color=COLOR_GOLD
    )
    data = load_data()
    for uid, (hidx, bet_amt) in bets.items():
        user = get_user(data, uid)
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else str(uid)
        if hidx == winner_idx:
            win = int(bet_amt * odds[winner_idx])
            gain = win - bet_amt
            user["coins"] += gain
            user["casino_wins"] += 1
            user["total_earned"] = user.get("total_earned", 0) + gain
            add_history(user, f"🏇 Course gagnée ({horses[winner_idx]})", gain)
            result_embed.add_field(name=f"🎉 {name}", value=f"+**{gain:,}** 🪙", inline=True)
        else:
            user["coins"] = max(0, user["coins"] - bet_amt)
            user["casino_losses"] += 1
            add_history(user, f"🏇 Course perdue", -bet_amt)
            result_embed.add_field(name=f"❌ {name}", value=f"-**{bet_amt:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=result_embed)

# ─── MEMORY (nouveau) ─────────────────────────────────────────────────────────

@bot.command(name="memory")
async def memory(ctx):
    """Mémorise une séquence d'emojis qui s'allonge à chaque round."""
    emojis = ["🍎","🍌","🍇","🍓","🍑","🍒","🍋","🍉"]
    sequence = []
    score = 0

    embed = discord.Embed(
        title="🧠  Memory",
        description="Mémorise la séquence et réponds avec les **numéros** dans l'ordre !\nEx : `1 3 2 4`",
        color=COLOR_PURPLE
    )
    embed.set_footer(text="Chaque round ajoute un emoji. Récompense : 20 🪙 × rounds réussis")
    await ctx.send(embed=embed)
    await asyncio.sleep(2)

    for round_n in range(1, 7):
        new_emoji = random.choice(emojis)
        sequence.append(new_emoji)
        indexed = " ".join(f"**{i+1}**={e}" for i, e in enumerate(emojis))
        seq_display = "  ".join(sequence)

        # Montre la séquence
        show = discord.Embed(
            title=f"🧠  Round {round_n} — Mémorise !",
            description=f"```\n{seq_display}\n```",
            color=COLOR_PURPLE
        )
        show.add_field(name="Référence", value=indexed, inline=False)
        msg = await ctx.send(embed=show)
        await asyncio.sleep(max(2, 4 - round_n * 0.3))

        # Cache la séquence
        hide = discord.Embed(
            title=f"🧠  Round {round_n} — À toi !",
            description="La séquence est cachée. Tape les numéros dans l'ordre.",
            color=COLOR_CASINO
        )
        hide.add_field(name="Référence", value=indexed, inline=False)
        await msg.edit(embed=hide)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            resp = await bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            break

        try:
            given = [int(x)-1 for x in resp.content.strip().split()]
            expected = [emojis.index(e) for e in sequence]
        except:
            break

        if given == expected:
            score += 1
            await ctx.send(embed=discord.Embed(description=f"✅ **Round {round_n} réussi !** Continue...", color=COLOR_GREEN))
            await asyncio.sleep(1)
        else:
            break

    reward = score * 20
    data = load_data()
    user = get_user(data, ctx.author.id)
    user["coins"] += reward
    user["xp"] += score * 5
    user["total_earned"] = user.get("total_earned", 0) + reward
    if reward > 0:
        add_history(user, f"🧠 Memory {score} rounds", reward)
    save_data(data)

    result = discord.Embed(
        title="🧠  Memory — Terminé !",
        description=f"Tu as réussi **{score}** round(s) !",
        color=COLOR_GREEN if score >= 3 else COLOR_ORANGE
    )
    result.add_field(name="💰 Gains", value=f"+**{reward}** 🪙", inline=True)
    result.add_field(name="⭐ XP", value=f"+**{score*5}** XP", inline=True)
    await ctx.send(embed=result)

WORDGAME_WORDS = [
    ("PYTHON", "🐍 Langage de programmation célèbre"),
    ("CASINO", "🎰 Lieu de jeux d'argent"),
    ("DISCORD", "💬 Application de messagerie"),
    ("TRESOR", "💎 Richesse cachée"),
    ("JACKPOT", "🎰 Gros lot au casino"),
    ("DIAMANT", "💎 Pierre précieuse"),
    ("ROBOT", "🤖 Machine autonome"),
    ("PIRATE", "🏴‍☠️ Voleur des mers"),
    ("GALAXIE", "🌌 Ensemble d'étoiles"),
    ("VOLCAN", "🌋 Montagne qui crache du feu"),
]

@bot.command(name="wordgame", aliases=["mot", "pendu"])
async def wordgame(ctx):
    word, hint = random.choice(WORDGAME_WORDS)
    reward = len(word) * 20
    xp_reward = len(word) * 5

    hidden = ["_"] * len(word)
    guessed = []
    lives = 6
    hangman_stages = ["😊","😐","😟","😰","😨","😱","💀"]

    def display():
        return " ".join(hidden)

    def make_embed():
        e = discord.Embed(title="🔤  Jeu de Mots", color=COLOR_PURPLE)
        e.add_field(name="Mot", value=f"```\n{display()}\n```", inline=False)
        e.add_field(name="💡 Indice", value=hint, inline=True)
        e.add_field(name=f"{hangman_stages[6-lives]} Vies", value=f"**{lives}/6**", inline=True)
        if guessed:
            e.add_field(name="🔡 Lettres essayées", value=" ".join(sorted(guessed)), inline=False)
        e.set_footer(text=f"Réponds avec une lettre ou le mot complet | Récompense : {reward} 🪙")
        return e

    await ctx.send(embed=make_embed())

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and len(m.content.strip()) >= 1

    while lives > 0 and "_" in hidden:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=discord.Embed(
                description=f"⏳ Temps écoulé ! Le mot était **{word}**.",
                color=COLOR_RED
            ))

        guess = resp.content.strip().upper()

        if guess == word:
            hidden = list(word)
            break

        if len(guess) == 1 and guess.isalpha():
            if guess in guessed:
                await ctx.send(embed=discord.Embed(description=f"⚠️ Tu as déjà essayé **{guess}** !", color=COLOR_ORANGE))
                continue
            guessed.append(guess)
            if guess in word:
                for i, c in enumerate(word):
                    if c == guess:
                        hidden[i] = guess
            else:
                lives -= 1
            await ctx.send(embed=make_embed())
        else:
            await ctx.send(embed=discord.Embed(description="⚠️ Envoie une seule lettre ou le mot complet.", color=COLOR_ORANGE))

    if "_" not in hidden:
        data = load_data()
        user = get_user(data, ctx.author.id)
        user["coins"] += reward
        user["xp"] += xp_reward
        user["total_earned"] = user.get("total_earned", 0) + reward
        add_history(user, f"🔤 WordGame gagné ({word})", reward)
        save_data(data)
        embed = discord.Embed(title="✅  Bravo !", description=f"Le mot était **{word}** !", color=COLOR_GREEN)
        embed.add_field(name="💰 Gains", value=f"+**{reward}** 🪙", inline=True)
        embed.add_field(name="⭐ XP", value=f"+**{xp_reward}** XP", inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send(embed=discord.Embed(
            title="💀  Perdu !",
            description=f"Le mot était **{word}**. Plus de vies !",
            color=COLOR_RED
        ))

# ─── MARCHÉ NOIR (nouveau) ────────────────────────────────────────────────────

@bot.command(name="blackmarket", aliases=["marche", "marchenoir"])
async def blackmarket_cmd(ctx):
    """Marché noir — items à prix réduit, stock limité, refresh toutes les 6h."""
    refresh_blackmarket()
    now = time.time()
    next_refresh = blackmarket_state["last_refresh"] + 21600 - now

    embed = discord.Embed(
        title="🕵️  Marché Noir",
        description=f"Stock limité ! Prochain refresh dans **{format_time(next_refresh)}**\nAchète avec `%bm <numéro>`",
        color=0x1A1A2E
    )
    for i, item in enumerate(blackmarket_state["items"]):
        stock = blackmarket_state["stocks"].get(item["key"], 0)
        embed.add_field(
            name=f"**{i+1}.** {item['emoji']} {item['name']}",
            value=f"Prix : **{item['price']:,}** 🪙  (-{item['discount']}%)\nStock : **{stock}** restant(s)",
            inline=False
        )
    embed.set_footer(text="⚠️ Ces items ne sont pas disponibles en boutique officielle !")
    await ctx.send(embed=embed)

@bot.command(name="bm")
async def bm_buy(ctx, numero: int = 0):
    """Acheter un item au marché noir."""
    refresh_blackmarket()
    items = blackmarket_state["items"]
    if numero < 1 or numero > len(items):
        return await ctx.send(embed=discord.Embed(description=f"❌ Numéro invalide. Utilise `%blackmarket` pour voir les items.", color=COLOR_RED))

    item = items[numero - 1]
    stock = blackmarket_state["stocks"].get(item["key"], 0)
    if stock <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Cet item est en rupture de stock !", color=COLOR_RED))

    data = load_data()
    user = get_user(data, ctx.author.id)
    if user["coins"] < item["price"]:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Pas assez de coins. Il te faut **{item['price']:,}** 🪙.",
            color=COLOR_RED
        ))

    user["coins"] -= item["price"]
    user["inventory"].append(item["key"])
    blackmarket_state["stocks"][item["key"]] = stock - 1
    add_history(user, f"🕵️ Marché Noir: {item['name']}", -item["price"])
    save_data(data)

    embed = discord.Embed(
        title="✅  Achat au Marché Noir !",
        description=f"Tu as acheté **{item['emoji']} {item['name']}** pour **{item['price']:,}** 🪙 !",
        color=COLOR_GREEN
    )
    embed.set_footer(text=f"Utilise %use {item['key']} pour l'activer")
    await ctx.send(embed=embed)

# ─── Shop ─────────────────────────────────────────────────────────────────────

@bot.command(name="shop", aliases=["magasin"])
async def shop(ctx):
    embed = discord.Embed(
        title="🛒  Boutique",
        description="Dépense tes coins pour des avantages exclusifs !",
        color=COLOR_PURPLE
    )
    for key, item in SHOP_ITEMS.items():
        embed.add_field(
            name=f"{item['emoji']}  {item['name']}  —  **{item['price']:,} 🪙**",
            value=f"{item['description']}\n`%buy {key}`",
            inline=False
        )
    embed.set_footer(text="Utilise %buy <clé> pour acheter • %inventaire pour voir tes items • %blackmarket pour le marché noir")
    await ctx.send(embed=embed)

@bot.command(name="buy", aliases=["acheter"])
async def buy(ctx, item_key: str = ""):
    if item_key not in SHOP_ITEMS:
        return await ctx.send(embed=discord.Embed(description="❌ Item invalide. Utilise `%shop` pour voir les items.", color=COLOR_RED))
    item = SHOP_ITEMS[item_key]
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user["coins"] < item["price"]:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Pas assez de coins. Il te faut **{item['price']:,}** 🪙, tu as **{user['coins']:,}** 🪙.",
            color=COLOR_RED
        ))

    if item_key == "role_perso":
        await ctx.send(embed=discord.Embed(description="🎨 Quel nom veux-tu pour ton rôle ? *(30 secondes)*", color=COLOR_PURPLE))
        def check_name(m): return m.author == ctx.author and m.channel == ctx.channel
        try:
            rn = await bot.wait_for("message", check=check_name, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=discord.Embed(description="⏳ Temps écoulé.", color=COLOR_RED))
        await ctx.send(embed=discord.Embed(description="🎨 Quelle couleur ? (ex: `#FF5733` ou `rouge`, `bleu`, `vert`, `violet`, `orange`)", color=COLOR_PURPLE))
        color_names = {"rouge":0xFF0000,"bleu":0x0000FF,"vert":0x00FF00,"violet":0x800080,"orange":0xFF8C00,"jaune":0xFFFF00,"rose":0xFF69B4}
        try:
            rc = await bot.wait_for("message", check=check_name, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=discord.Embed(description="⏳ Temps écoulé.", color=COLOR_RED))
        color_input = rc.content.strip().lower()
        if color_input in color_names:
            color = discord.Color(color_names[color_input])
        else:
            try:
                color = discord.Color(int(color_input.replace("#",""), 16))
            except:
                color = discord.Color.random()
        try:
            role = await ctx.guild.create_role(name=rn.content.strip()[:50], color=color, reason=f"Shop — {ctx.author}")
            await ctx.author.add_roles(role)
            user["coins"] -= item["price"]
            save_data(data)
            embed = discord.Embed(title="✅  Rôle créé !", description=f"Le rôle **{role.name}** a été créé et attribué !", color=color)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            return await ctx.send(embed=discord.Embed(description="❌ Je n'ai pas la permission de créer des rôles.", color=COLOR_RED))
    else:
        user["coins"] -= item["price"]
        user["inventory"].append(item_key)
        add_history(user, f"🛒 Achat: {item['name']}", -item["price"])
        save_data(data)
        embed = discord.Embed(
            title="✅  Achat réussi !",
            description=f"Tu as acheté **{item['name']}** !",
            color=COLOR_GREEN
        )
        embed.set_footer(text=f"Utilise %use {item_key} pour l'activer")
        await ctx.send(embed=embed)

@bot.command(name="inventaire", aliases=["inv", "inventory"])
async def inventaire(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    if not user["inventory"]:
        return await ctx.send(embed=discord.Embed(
            title="🎒  Inventaire",
            description="Ton inventaire est vide.\nAchète des items avec `%shop` ou `%blackmarket` !",
            color=COLOR_PURPLE
        ))
    embed = discord.Embed(title=f"🎒  Inventaire de {ctx.author.display_name}", color=COLOR_PURPLE)
    counts: dict[str,int] = {}
    for i in user["inventory"]:
        counts[i] = counts.get(i,0) + 1
    for k, cnt in counts.items():
        item = SHOP_ITEMS.get(k, {"name": k, "emoji": "❓"})
        embed.add_field(
            name=f"{item['emoji']}  {item['name']}  ×{cnt}",
            value=f"`%use {k}`",
            inline=True
        )
    await ctx.send(embed=embed)

@bot.command(name="use", aliases=["utiliser"])
async def use(ctx, item_key: str = ""):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if item_key not in user["inventory"]:
        return await ctx.send(embed=discord.Embed(description="❌ Tu ne possèdes pas cet item.", color=COLOR_RED))
    now = time.time()
    if item_key == "xp_boost_1h":
        user["xp_boost_until"] = now + 3600
        msg = "⚡ **Boost XP x2** activé pour **1 heure** !"
        color = COLOR_GOLD
    elif item_key == "shield":
        user["shield"] = True
        msg = "🛡️ **Bouclier** activé ! Tu es protégé contre le prochain vol."
        color = COLOR_BLUE
    elif item_key == "lucky_charm":
        user["lucky_charm_until"] = now + 86400
        msg = "🍀 **Porte-bonheur** activé pour **24h** ! (+5% chance au casino)"
        color = COLOR_GREEN
    elif item_key == "daily_bonus":
        user["daily_bonus_x2"] = True
        msg = "🎁 Ton prochain `%daily` sera **doublé** !"
        color = COLOR_ORANGE
    elif item_key == "vip_pass":
        user["vip_until"] = now + 21600
        msg = "💎 **Pass VIP** activé pour **6h** ! Tous tes cooldowns sont réduits de 50%."
        color = COLOR_PURPLE
    elif item_key == "insurance":
        user["insurance"] = True
        msg = "🔒 **Assurance Casino** activée ! Ta prochaine perte au crash sera remboursée à 50%."
        color = COLOR_BLUE
    else:
        return await ctx.send(embed=discord.Embed(description="❌ Cet item ne peut pas être utilisé manuellement.", color=COLOR_RED))
    user["inventory"].remove(item_key)
    save_data(data)
    await ctx.send(embed=discord.Embed(description=msg, color=color))

# ─── Error handler ────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(description=f"❌ Argument manquant. Tape `%help` pour l'aide.", color=COLOR_RED))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=discord.Embed(description="❌ Membre introuvable.", color=COLOR_RED))
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=discord.Embed(description=f"❌ Argument invalide. Tape `%help` pour l'aide.", color=COLOR_RED))
    else:
        await ctx.send(embed=discord.Embed(description=f"⚠️ Erreur inattendue : {error}", color=COLOR_ORANGE))

# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("❌ La variable d'environnement DISCORD_TOKEN est manquante !")
    bot.run(TOKEN)
