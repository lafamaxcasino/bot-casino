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
XP_PER_MESSAGE = (3, 10)        # min, max XP par message (réduit)
XP_PER_MINUTE_VOCAL = 2         # XP par minute en vocal (réduit)
XP_MESSAGE_COOLDOWN = 90        # secondes entre deux gains de XP (augmenté)

# Couleurs embed
COLOR_GOLD    = 0xF1C40F
COLOR_GREEN   = 0x2ECC71
COLOR_RED     = 0xE74C3C
COLOR_BLUE    = 0x3498DB
COLOR_PURPLE  = 0x9B59B6
COLOR_ORANGE  = 0xE67E22
COLOR_DARK    = 0x2C2F33
COLOR_CASINO  = 0xFF6B35

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

STARTING_COINS = 100  # réduit de 200 à 100

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
        }
    # Migrations pour anciens profils
    defaults = {
        "vip_until": 0, "insurance": False,
        "streak_daily": 0, "last_daily_streak": 0,
        "total_games_played": 0, "total_earned": STARTING_COINS
    }
    for k, v in defaults.items():
        if k not in data[uid]:
            data[uid][k] = v
    return data[uid]

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
    """Retourne le multiplicateur de cooldown (0.5 si VIP actif)"""
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

# ─── Bot setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

vocal_sessions: dict[int, float] = {}

# ─── Events ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté !")
    vocal_xp_loop.start()

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
        "`%stats` • Statistiques détaillées"
    ), inline=True)
    embed.add_field(name="💰  Économie", value=(
        "`%daily` • Bonus journalier (24h)\n"
        "`%work` • Travailler (45min)\n"
        "`%crime` • Crime risqué (90min)\n"
        "`%rob @user` • Voler (3h)\n"
        "`%transfer @user <montant>` • Transférer\n"
        "`%solde` • Voir tes coins"
    ), inline=True)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    embed.add_field(name="🎰  Casino", value=(
        "`%slot <mise>` • Machine à sous\n"
        "`%coinflip <mise> <pile|face>` • Pile ou face\n"
        "`%blackjack <mise>` • Blackjack\n"
        "`%roulette <mise> <choix>` • Roulette\n"
        "`%dice <mise>` • Duel de dés\n"
        "`%crash <mise>` • Crash (enchères)"
    ), inline=True)
    embed.add_field(name="🎮  Mini-jeux", value=(
        "`%trivia` • Culture générale\n"
        "`%rps @user <mise>` • Pierre-Feuille-Ciseaux\n"
        "`%duel @user <mise>` • Duel\n"
        "`%mines <mise> <nb_mines>` • Démineur\n"
        "`%course` • Course de chevaux\n"
        "`%wordgame` • Jeu de mots (solo)"
    ), inline=True)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    embed.add_field(name="🛒  Shop", value=(
        "`%shop` • Voir le magasin\n"
        "`%buy <item>` • Acheter\n"
        "`%inventaire` • Mon inventaire\n"
        "`%use <item>` • Utiliser un item"
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

    # Badges actifs
    badges = []
    now = time.time()
    if user.get("xp_boost_until", 0) > now: badges.append("⚡ Boost XP")
    if user.get("lucky_charm_until", 0) > now: badges.append("🍀 Chance+")
    if user.get("shield"): badges.append("🛡️ Bouclier")
    if user.get("vip_until", 0) > now: badges.append("💎 VIP")
    if user.get("insurance"): badges.append("🔒 Assurance")

    embed = discord.Embed(
        title=f"🎰  Profil de {member.display_name}",
        color=COLOR_GOLD
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📊 Niveau", value=f"**{level}**", inline=True)
    embed.add_field(name="⭐ XP Total", value=f"**{user['xp']:,}**", inline=True)
    embed.add_field(name="💰 Coins", value=f"**{user['coins']:,}** 🪙", inline=True)
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

    embed = discord.Embed(
        title=f"📈  Statistiques — {member.display_name}",
        color=COLOR_BLUE
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏆 Victoires casino", value=f"**{wins:,}**", inline=True)
    embed.add_field(name="💔 Défaites casino", value=f"**{losses:,}**", inline=True)
    embed.add_field(name="📊 Win Rate", value=f"**{wr}**", inline=True)
    embed.add_field(name="🎮 Parties jouées", value=f"**{user.get('total_games_played',0):,}**", inline=True)
    embed.add_field(name="💵 Total gagné (vie)", value=f"**{user.get('total_earned',0):,}** 🪙", inline=True)
    embed.add_field(name="🔥 Streak daily", value=f"**{user.get('streak_daily',0)}** jours", inline=True)
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
    scores = [(int(uid), d["coins"]) for uid, d in data.items()]
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

    # Streak
    streak = user.get("streak_daily", 0)
    last_streak = user.get("last_daily_streak", 0)
    if now - last_streak < 172800:  # moins de 48h depuis dernier daily → streak continue
        streak += 1
    else:
        streak = 1
    user["streak_daily"] = streak
    user["last_daily_streak"] = now

    # Montant de base réduit, mais streak donne bonus
    base = random.randint(80, 180)
    streak_bonus = min(streak * 5, 100)  # max +100 au bout de 20 jours
    amount = base + streak_bonus

    if user.get("daily_bonus_x2"):
        amount *= 2
        user["daily_bonus_x2"] = False

    user["coins"] += amount
    user["total_earned"] = user.get("total_earned", 0) + amount
    user["last_daily"] = now
    save_data(data)

    embed = discord.Embed(
        title="🎁  Daily récupéré !",
        color=COLOR_GREEN
    )
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
    cooldown = 2700 * get_cooldown_mult(user)  # 45min
    if now - user["last_work"] < cooldown:
        remaining = cooldown - (now - user["last_work"])
        embed = discord.Embed(
            title="⏳  Tu travailles déjà !",
            description=f"Repose-toi encore **{format_time(remaining)}**.",
            color=COLOR_RED
        )
        return await ctx.send(embed=embed)
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
    cooldown = 5400 * get_cooldown_mult(user)  # 90min
    if now - user["last_crime"] < cooldown:
        remaining = cooldown - (now - user["last_crime"])
        embed = discord.Embed(
            title="⏳  Les flics te surveillent !",
            description=f"Attends **{format_time(remaining)}** avant de recommencer.",
            color=COLOR_RED
        )
        return await ctx.send(embed=embed)
    user["last_crime"] = now
    if random.random() < 0.40:  # 40% de risque
        fine = random.randint(80, 300)
        user["coins"] = max(0, user["coins"] - fine)
        save_data(data)
        embed = discord.Embed(
            title="🚔  Arrêté !",
            description=f"La police t'a rattrapé. Amende de **{fine:,}** 🪙.",
            color=COLOR_RED
        )
        embed.set_footer(text="Prends garde la prochaine fois...")
        return await ctx.send(embed=embed)
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
    cooldown = 10800 * get_cooldown_mult(robber)  # 3h
    if now - robber.get("last_rob", 0) < cooldown:
        remaining = cooldown - (now - robber["last_rob"])
        embed = discord.Embed(
            title="⏳  Trop risqué !",
            description=f"Attends **{format_time(remaining)}** avant de voler à nouveau.",
            color=COLOR_RED
        )
        return await ctx.send(embed=embed)
    if victim.get("shield"):
        victim["shield"] = False
        robber["last_rob"] = now
        save_data(data)
        embed = discord.Embed(
            title="🛡️  Bouclier activé !",
            description=f"{target.display_name} était protégé. Ton tentative de vol a échoué !",
            color=COLOR_BLUE
        )
        return await ctx.send(embed=embed)
    if victim["coins"] < 100:
        return await ctx.send(embed=discord.Embed(description=f"💸 {target.display_name} n'a pas assez de coins.", color=COLOR_RED))
    robber["last_rob"] = now
    if random.random() < 0.45:  # 45% de se faire attraper
        fine = random.randint(60, 250)
        robber["coins"] = max(0, robber["coins"] - fine)
        save_data(data)
        embed = discord.Embed(
            title="🚔  Pris la main dans le sac !",
            description=f"{ctx.author.mention} s'est fait attraper. Amende : **{fine:,}** 🪙.",
            color=COLOR_RED
        )
        return await ctx.send(embed=embed)
    stolen = random.randint(80, min(400, victim["coins"] // 3))
    victim["coins"] -= stolen
    robber["coins"] += stolen
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
    # Taxe de transfert : 5%
    tax = max(1, int(amt * 0.05))
    net = amt - tax
    sender["coins"] -= amt
    receiver["coins"] += net
    save_data(data)
    embed = discord.Embed(
        title="💸  Transfert effectué",
        color=COLOR_GREEN
    )
    embed.add_field(name="📤 Envoyé", value=f"**{amt:,}** 🪙", inline=True)
    embed.add_field(name="📥 Reçu", value=f"**{net:,}** 🪙", inline=True)
    embed.add_field(name="🏦 Taxe (5%)", value=f"**{tax:,}** 🪙", inline=True)
    embed.set_footer(text=f"{ctx.author.display_name} → {target.display_name}")
    await ctx.send(embed=embed)

# ─── Casino helpers ────────────────────────────────────────────────────────────

def parse_bet(user: dict, arg: str) -> int | None:
    if arg.lower() in ("all", "tout"):
        return user["coins"]
    try:
        v = int(arg)
        return v if v > 0 else None
    except:
        return None

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
        user["coins"] += win - bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + (win - bet)
        embed = discord.Embed(title="🎰  JACKPOT !", description=f"╔══════════════╗\n║  {result_str}  ║\n╚══════════════╝", color=COLOR_GOLD)
        embed.add_field(name="🎉 Multiplicateur", value=f"x**{mult}**", inline=True)
        embed.add_field(name="💰 Gains", value=f"+**{win - bet:,}** 🪙", inline=True)
        embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        embed = discord.Embed(title="🎰  Deux identiques !", description=f"╔══════════════╗\n║  {result_str}  ║\n╚══════════════╝", color=COLOR_BLUE)
        embed.add_field(name="🤝 Résultat", value="Mise récupérée", inline=True)
        embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
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
        embed = discord.Embed(title="🪙  Pile ou Face", description=f"La pièce tombe sur **{result.upper()}** !", color=COLOR_GREEN)
        embed.add_field(name="✅ Gagné !", value=f"+**{bet:,}** 🪙", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
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
        p_cards = " ".join(player)
        if hide_dealer:
            d_display = f"{dealer[0]}  🂠"
            d_val_str = "?"
        else:
            d_display = " ".join(dealer)
            d_val_str = str(hand_value(dealer))
        embed = discord.Embed(title="🃏  Blackjack", color=COLOR_DARK)
        embed.add_field(name=f"Toi  ({pv})", value=f"`{p_cards}`", inline=True)
        embed.add_field(name=f"Croupier  ({d_val_str})", value=f"`{d_display}`", inline=True)
        embed.add_field(name="💰 Mise", value=f"**{bet:,}** 🪙", inline=False)
        if hide_dealer:
            embed.set_footer(text="hit • stand  (ou h • s)")
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
        e.color = COLOR_GREEN
        e.add_field(name="🎉 Victoire !", value=f"+**{bet:,}** 🪙", inline=True)
    elif pv == dv:
        e.color = COLOR_BLUE
        e.add_field(name="🤝 Égalité", value="Mise remboursée", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
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
        embed.add_field(name="🎉 Gagné !", value=f"+**{gain:,}** 🪙  (x{mult})", inline=False)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
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
        embed.color = COLOR_GREEN
        embed.add_field(name="🎉 Gagné !", value=f"+**{bet:,}** 🪙", inline=True)
    elif total == 7:
        embed.color = COLOR_BLUE
        embed.add_field(name="🤝 Égalité", value="Mise remboursée", inline=True)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        embed.color = COLOR_RED
        embed.add_field(name="❌ Perdu !", value=f"-**{bet:,}** 🪙", inline=True)
    embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=embed)

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

    # Génère le multiplicateur de crash (distribution réaliste)
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
        e.add_field(name="📊 Multiplicateur", value=f"**x{mult:.2f}** {'💥' if crashed else '🚀'}", inline=True)
        e.add_field(name="💰 Valeur actuelle", value=f"**{val:,}** 🪙", inline=True)
        e.add_field(name="💵 Mise", value=f"**{bet:,}** 🪙", inline=True)
        if not crashed:
            e.set_footer(text="Tape 'stop' pour encaisser !")
        return e

    # Envoie UN seul embed dès le départ
    msg = await ctx.send(embed=make_crash_embed(1.0))

    current_mult = 1.0
    step = 0.10
    cashed_out = False
    stop_mult = None

    # Boucle principale : on avance le mult, on édite l'embed, on vérifie les messages
    while True:
        # Attente entre chaque tick — pendant ce temps on écoute les messages
        try:
            resp = await asyncio.wait_for(
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
            # Le joueur a tapé stop
            cashed_out = True
            stop_mult = current_mult
            break
        except asyncio.TimeoutError:
            pass  # Pas de stop, on continue

        # Avance le multiplicateur
        current_mult = round(current_mult + step, 2)
        step = round(step * 1.06, 3)  # accélération progressive

        if current_mult >= crash_at:
            current_mult = crash_at
            # Crash ! On édite l'embed avec l'état final crashé
            await msg.edit(embed=make_crash_embed(current_mult, crashed=True))
            break

        # Mise à jour de l'embed (edit, pas nouveau message)
        await msg.edit(embed=make_crash_embed(current_mult))

    # Résultat
    if cashed_out:
        mult_used = stop_mult
        win = int(bet * mult_used)
        gain = win - bet
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        result_embed = discord.Embed(
            title="💸  Cashout !",
            description=f"Tu as encaissé à **x{mult_used:.2f}** !\n*Le crash était à x{crash_at:.2f}*",
            color=COLOR_GREEN
        )
        result_embed.add_field(name="💰 Gains", value=f"+**{gain:,}** 🪙", inline=True)
        result_embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)
    else:
        # Crash sans cashout
        if user.get("insurance"):
            refund = bet // 2
            user["coins"] = max(0, user["coins"] - bet + refund)
            user["insurance"] = False
            result_embed = discord.Embed(
                title="💥  Crash !",
                description=f"Crash à **x{crash_at:.2f}** !\n🔒 Assurance activée — remboursement partiel.",
                color=COLOR_ORANGE
            )
            result_embed.add_field(name="❌ Perte nette", value=f"-**{bet - refund:,}** 🪙", inline=True)
            result_embed.add_field(name="🔒 Remboursé", value=f"+**{refund:,}** 🪙", inline=True)
        else:
            user["coins"] = max(0, user["coins"] - bet)
            result_embed = discord.Embed(
                title="💥  CRASH !",
                description=f"Le marché s'est effondré à **x{crash_at:.2f}** ! 📉",
                color=COLOR_RED
            )
            result_embed.add_field(name="❌ Perte", value=f"-**{bet:,}** 🪙", inline=True)
        user["casino_losses"] += 1
        result_embed.add_field(name="💳 Solde", value=f"**{user['coins']:,}** 🪙", inline=True)

    save_data(data)
    # On édite le message existant avec le résultat final (toujours 1 seul message)
    await msg.edit(embed=result_embed)

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

@bot.command(name="trivia")
async def trivia(ctx):
    q = random.choice(TRIVIA_QUESTIONS)
    reward_coins = random.randint(40, 150)
    embed = discord.Embed(
        title="🧠  Trivia",
        description=f"**{q['q']}**",
        color=COLOR_BLUE
    )
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
    wins = {"pierre":"ciseaux","feuille":"pierre","ciseaux":"feuille"}

    async def get_choice(player):
        try:
            await player.send(f"🎮 **RPS** — Choisis : `pierre`, `feuille` ou `ciseaux`")
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
    elif wins[c1n] == c2n:
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
                if i in revealed:
                    line += "💣 " if i in mine_positions else "💎 "
                else:
                    line += "⬛ "
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
            # Timeout = cashout automatique
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
            # MINE
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            # Révèle toutes les mines
            for m_idx in mine_positions:
                if m_idx not in revealed:
                    revealed.append(m_idx)
            save_data(data)
            e = make_mines_embed("lose")
            e.add_field(name="💥 MINE !", value=f"Perdu **{bet:,}** 🪙", inline=False)
            return await ctx.send(embed=e)

        safe = total - cases
        mult = round(1 + (len(revealed) / safe) * (cases * 0.85), 2)
        await ctx.send(embed=make_mines_embed())

    # Cashout
    win = int(bet * mult)
    gain = win - bet
    user["coins"] += gain
    if gain >= 0:
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
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
            result_embed.add_field(name=f"🎉 {name}", value=f"+**{gain:,}** 🪙", inline=True)
        else:
            user["coins"] = max(0, user["coins"] - bet_amt)
            user["casino_losses"] += 1
            result_embed.add_field(name=f"❌ {name}", value=f"-**{bet_amt:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=result_embed)

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
    """Jeu du pendu / devinette de mot"""
    word, hint = random.choice(WORDGAME_WORDS)
    reward = len(word) * 20
    xp_reward = len(word) * 5

    hidden = ["_"] * len(word)
    guessed = []
    lives = 6
    life_icons = ["❤️","❤️","❤️","❤️","❤️","❤️"]

    def display():
        return " ".join(hidden)

    def make_embed():
        e = discord.Embed(title="🔤  Jeu de Mots", color=COLOR_PURPLE)
        e.add_field(name="Mot", value=f"```{display()}```", inline=False)
        e.add_field(name="💡 Indice", value=hint, inline=True)
        e.add_field(name="❤️ Vies", value=" ".join(life_icons[:lives]), inline=True)
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
    embed.set_footer(text="Utilise %buy <clé> pour acheter • %inventaire pour voir tes items")
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
            description="Ton inventaire est vide.\nAchète des items avec `%shop` !",
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
