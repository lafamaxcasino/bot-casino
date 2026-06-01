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

XP_PER_MESSAGE = (5, 15)
XP_PER_MINUTE_VOCAL = 3
XP_MESSAGE_COOLDOWN = 60

LEVEL_ROLES = {
    5:   "Débutant du casino",
    15:  "Aventurier du casino",
    30:  "Vétéran du casino",
    50:  "Expert du casino",
    100: "Légende du casino",
}

def xp_for_level(level: int) -> int:
    return int(100 * (level ** 1.7))

STARTING_COINS = 500

SHOP_ITEMS = {
    "role_perso": {
        "name": "🎨 Rôle Personnalisé",
        "description": "Un rôle avec la couleur et le nom de votre choix.",
        "price": 15000,
        "emoji": "🎨",
    },
    "xp_boost_1h": {
        "name": "⚡ Boost XP (1h)",
        "description": "Double votre gain d'XP pendant 1 heure.",
        "price": 3000,
        "emoji": "⚡",
    },
    "xp_boost_24h": {
        "name": "🌩️ Boost XP (24h)",
        "description": "Double votre gain d'XP pendant 24 heures.",
        "price": 10000,
        "emoji": "🌩️",
    },
    "shield": {
        "name": "🛡️ Bouclier",
        "description": "Protège vos coins lors du prochain vol.",
        "price": 2000,
        "emoji": "🛡️",
    },
    "mega_shield": {
        "name": "🔰 Mega Bouclier",
        "description": "Protège contre 3 vols consécutifs.",
        "price": 5000,
        "emoji": "🔰",
    },
    "lucky_charm": {
        "name": "🍀 Porte-bonheur",
        "description": "Augmente vos chances au casino pendant 24h (+8%).",
        "price": 5000,
        "emoji": "🍀",
    },
    "mega_luck": {
        "name": "🌈 Méga Chance",
        "description": "Bonus casino +15% pendant 48h.",
        "price": 12000,
        "emoji": "🌈",
    },
    "daily_bonus": {
        "name": "🎁 Bonus Journalier x2",
        "description": "Double votre prochain %daily.",
        "price": 2500,
        "emoji": "🎁",
    },
    "daily_bonus_x3": {
        "name": "💝 Bonus Journalier x3",
        "description": "Triple votre prochain %daily.",
        "price": 6000,
        "emoji": "💝",
    },
    "work_boost": {
        "name": "💼 Boost Travail",
        "description": "Double vos gains de %work pendant 2h.",
        "price": 3500,
        "emoji": "💼",
    },
    "vip_pass": {
        "name": "👑 VIP Pass",
        "description": "Réduit tous les cooldowns de 50% pendant 12h.",
        "price": 20000,
        "emoji": "👑",
    },
    "casino_insurance": {
        "name": "🔒 Assurance Casino",
        "description": "Rembourse votre prochaine perte au casino (max 5000).",
        "price": 8000,
        "emoji": "🔒",
    },
    "trivia_hint": {
        "name": "💡 Indice Trivia",
        "description": "Élimine 2 mauvaises réponses au prochain trivia.",
        "price": 1500,
        "emoji": "💡",
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
            "last_trivia": 0,
            "inventory": [],
            "xp_boost_until": 0,
            "lucky_charm_until": 0,
            "mega_luck_until": 0,
            "vip_pass_until": 0,
            "work_boost_until": 0,
            "shield": False,
            "mega_shield_charges": 0,
            "daily_bonus_x2": False,
            "daily_bonus_x3": False,
            "casino_insurance": False,
            "trivia_hint": False,
            "vocal_start": 0,
            "casino_wins": 0,
            "casino_losses": 0,
            "trivia_wins": 0,
            "trivia_losses": 0,
            "total_earned": STARTING_COINS,
            "streak_daily": 0,
            "last_daily_streak": 0,
        }
    # Ensure new fields exist for old users
    defaults = {
        "last_trivia": 0, "mega_shield_charges": 0, "mega_luck_until": 0,
        "vip_pass_until": 0, "work_boost_until": 0, "daily_bonus_x3": False,
        "casino_insurance": False, "trivia_hint": False, "trivia_wins": 0,
        "trivia_losses": 0, "streak_daily": 0, "last_daily_streak": 0,
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

def get_cooldown_reduction(user: dict, now: float) -> float:
    """Returns cooldown multiplier (0.5 = 50% reduction if VIP active)"""
    if user.get("vip_pass_until", 0) > now:
        return 0.5
    return 1.0

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
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
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

async def handle_level_up(member: discord.Member, guild: discord.Guild, new_level: int, channel):
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
                role_msg = f"\n🏅 Nouveau rôle débloqué : **{role_name}** !"
            except:
                role_msg = f"\n⚠️ Rôle **{role_name}** introuvable — crée-le sur le serveur !"

    reward_coins = new_level * 50
    data = load_data()
    user = get_user(data, member.id)
    user["coins"] += reward_coins
    save_data(data)

    embed = discord.Embed(
        title="🎉 NIVEAU SUPÉRIEUR !",
        description=(
            f"╔══════════════════════╗\n"
            f"║  {member.mention} passe au niveau **{new_level}** !  ║\n"
            f"╚══════════════════════╝\n"
            f"{role_msg}\n"
            f"💰 Récompense : **+{reward_coins:,}** 🪙"
        ),
        color=0xFFD700
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Continuez à chatter pour gagner de l'XP !")
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
        title="📖 AIDE — Toutes les commandes",
        description="```\nPréfixe : %\n```",
        color=0x5865F2
    )
    embed.add_field(name="━━━ 📊 Profil & XP ━━━", value=(
        "`%profil [@user]` — Voir ton profil\n"
        "`%classement` — Top 10 XP\n"
        "`%richesse` — Top 10 coins\n"
        "`%stats` — Tes statistiques détaillées"
    ), inline=False)
    embed.add_field(name="━━━ 💰 Argent ━━━", value=(
        "`%daily` — Bonus journalier (streak bonus!)\n"
        "`%work` — Travailler (30min cooldown)\n"
        "`%crime` — Crime risqué (1h cooldown)\n"
        "`%rob @user` — Voler quelqu'un (2h cooldown)\n"
        "`%solde` — Voir tes coins\n"
        "`%give @user <montant>` — Donner des coins"
    ), inline=False)
    embed.add_field(name="━━━ 🎰 Casino ━━━", value=(
        "`%slot <mise>` — Machine à sous\n"
        "`%coinflip <mise> <pile/face>` — Pile ou Face\n"
        "`%blackjack <mise>` — Blackjack\n"
        "`%roulette <mise> <choix>` — Roulette\n"
        "`%dice <mise>` — Lancer de dé\n"
        "`%crash <mise>` — 🆕 Crash (risque/récompense)"
    ), inline=False)
    embed.add_field(name="━━━ 🎮 Mini-jeux ━━━", value=(
        "`%trivia` — Question culture générale (10s, cooldown 30s)\n"
        "`%rps @user <mise>` — Pierre Feuille Ciseaux\n"
        "`%duel @user <mise>` — Duel au hasard\n"
        "`%mines <mise> <cases>` — Mines\n"
        "`%course` — Course de chevaux (multijoueur)\n"
        "`%pendu <mise>` — 🆕 Le Pendu"
    ), inline=False)
    embed.add_field(name="━━━ 🛒 Shop ━━━", value=(
        "`%shop` — Voir le magasin\n"
        "`%buy <item>` — Acheter un item\n"
        "`%inventaire` — Voir ton inventaire\n"
        "`%use <item>` — Utiliser un item"
    ), inline=False)
    embed.set_footer(text="💡 Bonne chance au casino !")
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
    bar_len = 20
    filled = int(bar_len * current_xp / needed_xp) if needed_xp else bar_len
    bar = "🟩" * filled + "⬛" * (bar_len - filled)
    next_role_level = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
    next_role_info = f"Prochain rôle : **{LEVEL_ROLES[next_role_level]}** (niv. {next_role_level})" if next_role_level else "🏆 Rang maximum atteint !"

    now = time.time()
    boosts = []
    if user.get("xp_boost_until", 0) > now:
        remaining = int((user["xp_boost_until"] - now) / 60)
        boosts.append(f"⚡ Boost XP ({remaining}min)")
    if user.get("lucky_charm_until", 0) > now:
        boosts.append("🍀 Porte-bonheur")
    if user.get("mega_luck_until", 0) > now:
        boosts.append("🌈 Méga Chance")
    if user.get("vip_pass_until", 0) > now:
        boosts.append("👑 VIP Pass")
    if user.get("shield"):
        boosts.append("🛡️ Bouclier")
    boost_str = " | ".join(boosts) if boosts else "Aucun"

    trivia_total = user.get("trivia_wins", 0) + user.get("trivia_losses", 0)
    trivia_rate = f"{int(user.get('trivia_wins',0)/trivia_total*100)}%" if trivia_total > 0 else "N/A"

    embed = discord.Embed(
        title=f"🎰 Profil de {member.display_name}",
        color=0xFFD700
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📊 Niveau", value=f"**{level}**", inline=True)
    embed.add_field(name="⭐ XP Total", value=f"**{user['xp']:,}**", inline=True)
    embed.add_field(name="💰 Coins", value=f"**{user['coins']:,}** 🪙", inline=True)
    embed.add_field(name="📈 Progression XP", value=f"`{bar}`\n{current_xp:,} / {needed_xp:,} XP", inline=False)
    embed.add_field(name="🎯 Objectif", value=next_role_info, inline=False)
    embed.add_field(
        name="🎰 Casino",
        value=f"✅ **{user.get('casino_wins',0)}** victoires | ❌ **{user.get('casino_losses',0)}** défaites",
        inline=True
    )
    embed.add_field(
        name="🧠 Trivia",
        value=f"✅ **{user.get('trivia_wins',0)}** | ❌ **{user.get('trivia_losses',0)}** | Taux: **{trivia_rate}**",
        inline=True
    )
    embed.add_field(name="🔥 Streak Daily", value=f"**{user.get('streak_daily', 0)}** jours", inline=True)
    embed.add_field(name="✨ Boosts actifs", value=boost_str, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="stats")
async def stats(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = load_data()
    user = get_user(data, member.id)
    save_data(data)
    total_games = user.get("casino_wins", 0) + user.get("casino_losses", 0)
    winrate = f"{int(user.get('casino_wins',0)/total_games*100)}%" if total_games > 0 else "N/A"
    embed = discord.Embed(title=f"📊 Statistiques de {member.display_name}", color=0x2ECC71)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🪙 Coins actuels", value=f"{user['coins']:,}", inline=True)
    embed.add_field(name="💹 Total gagné", value=f"{user.get('total_earned',0):,}", inline=True)
    embed.add_field(name="🎰 Parties jouées", value=f"{total_games}", inline=True)
    embed.add_field(name="✅ Victoires casino", value=f"{user.get('casino_wins',0)}", inline=True)
    embed.add_field(name="❌ Défaites casino", value=f"{user.get('casino_losses',0)}", inline=True)
    embed.add_field(name="📈 Taux de victoire", value=winrate, inline=True)
    embed.add_field(name="🧠 Trivia réussis", value=f"{user.get('trivia_wins',0)}", inline=True)
    embed.add_field(name="❌ Trivia ratés", value=f"{user.get('trivia_losses',0)}", inline=True)
    embed.add_field(name="🔥 Streak daily", value=f"{user.get('streak_daily',0)} jours", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="solde", aliases=["balance", "coins"])
async def solde(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    embed = discord.Embed(
        description=f"💰 {ctx.author.mention} possède **{user['coins']:,}** 🪙",
        color=0x2ECC71
    )
    await ctx.send(embed=embed)

@bot.command(name="give", aliases=["donner"])
async def give(ctx, target: discord.Member, amount: int):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send("❌ Cible invalide.")
    if amount <= 0:
        return await ctx.send("❌ Montant invalide.")
    data = load_data()
    sender = get_user(data, ctx.author.id)
    receiver = get_user(data, target.id)
    if sender["coins"] < amount:
        return await ctx.send(f"❌ Tu n'as pas assez de coins. (Tu as : **{sender['coins']:,}** 🪙)")
    sender["coins"] -= amount
    receiver["coins"] += amount
    save_data(data)
    embed = discord.Embed(
        description=f"💸 {ctx.author.mention} a envoyé **{amount:,}** 🪙 à {target.mention} !",
        color=0x2ECC71
    )
    await ctx.send(embed=embed)

@bot.command(name="classement", aliases=["top", "leaderboard"])
async def classement(ctx):
    data = load_data()
    scores = [(int(uid), d["xp"], compute_level(d["xp"])) for uid, d in data.items()]
    scores.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="🏆 Top 10 — XP", color=0xFFD700)
    medals = ["🥇","🥈","🥉"] + ["🎖️"]*7
    lines = []
    for i, (uid, xp, lvl) in enumerate(scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"User#{uid}"
        lines.append(f"{medals[i]} **{name}** — Niv. {lvl} ({xp:,} XP)")
    embed.description = "\n".join(lines) if lines else "Aucune donnée."
    await ctx.send(embed=embed)

@bot.command(name="richesse")
async def richesse(ctx):
    data = load_data()
    scores = [(int(uid), d["coins"]) for uid, d in data.items()]
    scores.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="💰 Top 10 — Richesse", color=0xF1C40F)
    medals = ["🥇","🥈","🥉"] + ["🎖️"]*7
    lines = []
    for i, (uid, coins) in enumerate(scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"User#{uid}"
        lines.append(f"{medals[i]} **{name}** — {coins:,} 🪙")
    embed.description = "\n".join(lines) if lines else "Aucune donnée."
    await ctx.send(embed=embed)

# ─── Argent ───────────────────────────────────────────────────────────────────

@bot.command(name="daily")
async def daily(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 86400
    if now - user["last_daily"] < cooldown:
        remaining = cooldown - (now - user["last_daily"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return await ctx.send(f"⏳ Prochain daily dans **{h}h{m:02d}m**.")

    # Streak system
    last_streak = user.get("last_daily_streak", 0)
    if now - last_streak < 172800:  # moins de 48h = streak maintenu
        user["streak_daily"] = user.get("streak_daily", 0) + 1
    else:
        user["streak_daily"] = 1
    user["last_daily_streak"] = now

    streak = user["streak_daily"]
    streak_bonus = min(streak * 20, 500)  # max 500 bonus
    amount = random.randint(200, 500)

    multiplier = 1
    bonus_text = ""
    if user.get("daily_bonus_x3"):
        multiplier = 3
        user["daily_bonus_x3"] = False
        bonus_text = "💝 **Bonus x3 activé !**\n"
    elif user.get("daily_bonus_x2"):
        multiplier = 2
        user["daily_bonus_x2"] = False
        bonus_text = "🎁 **Bonus x2 activé !**\n"

    amount = amount * multiplier + streak_bonus
    user["coins"] += amount
    user["last_daily"] = now
    user["total_earned"] = user.get("total_earned", 0) + amount
    save_data(data)

    embed = discord.Embed(title="🎁 Daily récupéré !", color=0xF39C12)
    embed.description = (
        f"{bonus_text}"
        f"💰 Tu reçois **{amount:,}** 🪙 !\n"
        f"🔥 Streak : **{streak}** jour(s) (+{streak_bonus} bonus)\n"
        f"💳 Solde : **{user['coins']:,}** 🪙"
    )
    embed.set_footer(text="Reviens demain pour maintenir ton streak !")
    await ctx.send(embed=embed)

@bot.command(name="work")
async def work(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cd_mult = get_cooldown_reduction(user, now)
    cooldown = int(1800 * cd_mult)
    if now - user["last_work"] < cooldown:
        remaining = cooldown - (now - user["last_work"])
        m = int(remaining // 60)
        return await ctx.send(f"⏳ Tu peux retravailler dans **{m} minutes**.")
    jobs = [
        ("🍕 Livraison de pizzas", 150, 350),
        ("💻 Développeur freelance", 250, 600),
        ("🎸 Musicien de rue", 100, 280),
        ("🚕 Chauffeur VTC", 200, 450),
        ("🧹 Agent d'entretien", 130, 300),
        ("📦 Livreur Amazon", 220, 480),
        ("🎰 Croupier de casino", 300, 700),
        ("🍔 Cuisinier", 160, 380),
        ("🛡️ Agent de sécurité", 180, 420),
        ("💼 Consultant", 280, 650),
        ("🎨 Graphiste", 200, 500),
        ("📱 Influenceur", 100, 900),
    ]
    job, mn, mx = random.choice(jobs)
    amount = random.randint(mn, mx)
    if user.get("work_boost_until", 0) > now:
        amount *= 2
        boost_text = " (⚡ x2 Boost!)"
    else:
        boost_text = ""
    user["coins"] += amount
    user["last_work"] = now
    user["total_earned"] = user.get("total_earned", 0) + amount
    save_data(data)
    embed = discord.Embed(
        description=f"{job}{boost_text}\n💰 Tu gagnes **{amount:,}** 🪙 !",
        color=0x2ECC71
    )
    await ctx.send(embed=embed)

@bot.command(name="crime")
async def crime(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cd_mult = get_cooldown_reduction(user, now)
    cooldown = int(3600 * cd_mult)
    if now - user["last_crime"] < cooldown:
        remaining = cooldown - (now - user["last_crime"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return await ctx.send(f"⏳ Tu dois attendre **{h}h{m:02d}m** avant de recommencer.")
    user["last_crime"] = now
    if random.random() < 0.35:
        fine = random.randint(200, 800)
        user["coins"] = max(0, user["coins"] - fine)
        save_data(data)
        embed = discord.Embed(
            description=f"🚔 Tu t'es fait attraper ! Amende de **{fine:,}** 🪙.",
            color=0xE74C3C
        )
        return await ctx.send(embed=embed)
    amount = random.randint(400, 1200)
    user["coins"] += amount
    user["total_earned"] = user.get("total_earned", 0) + amount
    save_data(data)
    crimes = [
        "🏦 Braquage de banque",
        "💎 Vol de bijoux",
        "🎭 Arnaque à l'arnaque",
        "🖥️ Piratage informatique",
        "🃏 Triche au casino",
        "🚗 Fuite après braquage",
        "💊 Deal dans la ruelle"
    ]
    embed = discord.Embed(
        description=f"{random.choice(crimes)} réussi ! Tu gagnes **{amount:,}** 🪙 !",
        color=0x9B59B6
    )
    await ctx.send(embed=embed)

@bot.command(name="rob")
async def rob(ctx, target: discord.Member):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send("❌ Cible invalide.")
    data = load_data()
    robber = get_user(data, ctx.author.id)
    victim = get_user(data, target.id)
    now = time.time()
    cd_mult = get_cooldown_reduction(robber, now)
    cooldown = int(7200 * cd_mult)
    if now - robber.get("last_rob", 0) < cooldown:
        remaining = cooldown - (now - robber["last_rob"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return await ctx.send(f"⏳ Tu dois attendre **{h}h{m:02d}m** avant de voler à nouveau.")

    if victim.get("mega_shield_charges", 0) > 0:
        victim["mega_shield_charges"] -= 1
        robber["last_rob"] = now
        save_data(data)
        return await ctx.send(f"🔰 {target.display_name} était protégé par un Mega Bouclier ! ({victim['mega_shield_charges']} charges restantes)")
    if victim.get("shield"):
        victim["shield"] = False
        robber["last_rob"] = now
        save_data(data)
        return await ctx.send(f"🛡️ {target.display_name} était protégé par un bouclier ! Vol annulé.")
    if victim["coins"] < 100:
        return await ctx.send(f"💸 {target.display_name} n'a pas assez de coins à voler (minimum 100).")
    robber["last_rob"] = now
    if random.random() < 0.4:
        fine = random.randint(100, 400)
        robber["coins"] = max(0, robber["coins"] - fine)
        save_data(data)
        return await ctx.send(f"🚔 {ctx.author.mention} s'est fait attraper ! Amende de **{fine:,}** 🪙.")
    stolen = random.randint(100, min(600, victim["coins"] // 2))
    victim["coins"] -= stolen
    robber["coins"] += stolen
    save_data(data)
    await ctx.send(f"🦹 {ctx.author.mention} vole **{stolen:,}** 🪙 à {target.mention} !")

# ─── Casino ───────────────────────────────────────────────────────────────────

def parse_bet(user: dict, arg: str) -> int | None:
    if arg.lower() in ("all", "tout"):
        return user["coins"]
    try:
        v = int(arg)
        return v if v > 0 else None
    except:
        return None

def get_lucky_bonus(user: dict, now: float) -> float:
    bonus = 0.0
    if user.get("lucky_charm_until", 0) > now:
        bonus += 0.08
    if user.get("mega_luck_until", 0) > now:
        bonus += 0.15
    return bonus

@bot.command(name="slot", aliases=["slots"])
async def slot(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : **10** 🪙. Usage : `%slot <mise>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Tu n'as pas assez de coins.")

    now = time.time()
    lucky_bonus = get_lucky_bonus(user, now)
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
    weights = [20, 18, 15, 12, 10, 8, 5, 3]
    reels = random.choices(symbols, weights=weights, k=3)

    # Animation-like display
    spin_msg = await ctx.send(
        f"```\n🎰  MACHINE À SOUS  🎰\n"
        f"┌─────────────────┐\n"
        f"│  🎲  🎲  🎲     │\n"
        f"└─────────────────┘\n"
        f"💰 Mise : {bet:,} 🪙\n```"
        f"*Le tambour tourne...*"
    )
    await asyncio.sleep(1.5)

    result_str = " │ ".join(reels)

    if reels[0] == reels[1] == reels[2]:
        if reels[0] == "7️⃣":
            mult = 25
            label = "🎊 JACKPOT LÉGENDAIRE"
        elif reels[0] == "💎":
            mult = 12
            label = "💎 JACKPOT DIAMANT"
        elif reels[0] == "⭐":
            mult = 8
            label = "⭐ SUPER JACKPOT"
        elif reels[0] == "🔔":
            mult = 5
            label = "🔔 JACKPOT"
        else:
            mult = 3
            label = "✅ COMBINAISON"
        if random.random() < lucky_bonus:
            mult = int(mult * 1.2)
        win = bet * mult
        user["coins"] += win - bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + (win - bet)
        msg = (
            f"```\n🎰  MACHINE À SOUS  🎰\n"
            f"┌─────────────────┐\n"
            f"│  {result_str}  │\n"
            f"└─────────────────┘\n```\n"
            f"🎉 **{label}** x{mult} !\n"
            f"💰 Tu gagnes **{win:,}** 🪙 !"
        )
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        user["coins"] += 0  # remboursé
        msg = (
            f"```\n🎰  MACHINE À SOUS  🎰\n"
            f"┌─────────────────┐\n"
            f"│  {result_str}  │\n"
            f"└─────────────────┘\n```\n"
            f"✅ Deux identiques ! Mise récupérée : **{bet:,}** 🪙."
        )
    else:
        # Apply insurance
        if user.get("casino_insurance") and bet <= 5000:
            user["casino_insurance"] = False
            msg = (
                f"```\n🎰  MACHINE À SOUS  🎰\n"
                f"┌─────────────────┐\n"
                f"│  {result_str}  │\n"
                f"└─────────────────┘\n```\n"
                f"❌ Perdu ! Mais 🔒 **Assurance** activée — mise remboursée !"
            )
        else:
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            msg = (
                f"```\n🎰  MACHINE À SOUS  🎰\n"
                f"┌─────────────────┐\n"
                f"│  {result_str}  │\n"
                f"└─────────────────┘\n```\n"
                f"❌ Perdu ! Tu perds **{bet:,}** 🪙."
            )
    save_data(data)
    await spin_msg.edit(content=msg)

@bot.command(name="coinflip", aliases=["cf", "flip"])
async def coinflip(ctx, mise: str = "0", choix: str = "pile"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%coinflip <mise> <pile|face>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")
    choix = choix.lower()
    if choix not in ("pile", "face"):
        return await ctx.send("❌ Choisis `pile` ou `face`.")

    flip_msg = await ctx.send("🪙 *La pièce est lancée...*")
    await asyncio.sleep(1.5)

    result = random.choice(["pile", "face"])
    icon = "🌕" if result == "pile" else "⭐"
    if result == choix:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        embed = discord.Embed(
            title=f"{icon} {result.upper()} !",
            description=f"✅ Bonne prédiction ! Tu gagnes **{bet:,}** 🪙 !\n💳 Solde : **{user['coins']:,}** 🪙",
            color=0x2ECC71
        )
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        embed = discord.Embed(
            title=f"{icon} {result.upper()} !",
            description=f"❌ Mauvaise prédiction ! Tu perds **{bet:,}** 🪙.\n💳 Solde : **{user['coins']:,}** 🪙",
            color=0xE74C3C
        )
    save_data(data)
    await flip_msg.edit(content=None, embed=embed)

@bot.command(name="blackjack", aliases=["bj"])
async def blackjack(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%blackjack <mise>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")

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

    suits = ["♠️","♥️","♦️","♣️"]
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    deck = [r+s for r in ranks for s in suits]
    random.shuffle(deck)

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    def show_hands(hide_dealer=True):
        p_val = hand_value(player)
        p_cards = " ".join(player)
        if hide_dealer:
            d_display = f"{dealer[0]} 🂠"
            d_val = "?"
        else:
            d_display = " ".join(dealer)
            d_val = hand_value(dealer)
        return (
            f"```\n♠ BLACKJACK ♠  —  Mise : {bet:,} 🪙\n"
            f"{'─'*30}\n"
            f"Toi    : {p_cards} [{p_val}]\n"
            f"Dealer : {d_display} [{d_val}]\n"
            f"{'─'*30}\n```"
        )

    msg = await ctx.send(show_hands() + "\n`hit` → Tirer | `stand` → Rester | `double` → Doubler")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ("hit","stand","h","s","double","d")

    doubled = False
    while True:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("⏳ Temps écoulé. Stand automatique.")
            break
        action = resp.content.lower()
        if action in ("stand","s"):
            break
        if action in ("double","d") and not doubled and len(player) == 2:
            if bet * 2 > user["coins"]:
                await ctx.send("❌ Pas assez de coins pour doubler.")
            else:
                bet *= 2
                doubled = True
                player.append(deck.pop())
                await ctx.send(show_hands() + "\n💥 **Double !**")
                if hand_value(player) > 21:
                    user["coins"] = max(0, user["coins"] - bet)
                    user["casino_losses"] += 1
                    save_data(data)
                    return await ctx.send(show_hands(False) + f"\n💥 **Bust !** Tu perds **{bet:,}** 🪙.")
                break
        else:
            player.append(deck.pop())
            if hand_value(player) > 21:
                user["coins"] = max(0, user["coins"] - bet)
                user["casino_losses"] += 1
                save_data(data)
                return await ctx.send(show_hands(False) + f"\n💥 **Bust !** Tu perds **{bet:,}** 🪙.")
            await ctx.send(show_hands())

    while hand_value(dealer) < 17:
        dealer.append(deck.pop())

    pv, dv = hand_value(player), hand_value(dealer)
    if pv == 21 and len(player) == 2:
        win = int(bet * 2.5)
        user["coins"] += win - bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + (win - bet)
        result = f"🃏 **BLACKJACK !** x2.5 — Tu gagnes **{win:,}** 🪙 !"
    elif dv > 21 or pv > dv:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        result = f"🎉 **Victoire !** Tu gagnes **{bet:,}** 🪙 !"
    elif pv == dv:
        result = "🤝 **Égalité !** Mise remboursée."
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        result = f"❌ **Défaite !** Tu perds **{bet:,}** 🪙."
    save_data(data)
    await ctx.send(show_hands(False) + f"\n{result}\n💳 Solde : **{user['coins']:,}** 🪙")

@bot.command(name="roulette")
async def roulette(ctx, mise: str = "0", choix: str = "rouge"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Usage : `%roulette <mise> <rouge|noir|pair|impair|0-36>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")

    spin_msg = await ctx.send(
        f"```\n🎡  ROULETTE  🎡\n"
        f"La bille tourne...\n"
        f"Mise : {bet:,} 🪙 sur '{choix}'\n```"
    )
    await asyncio.sleep(2)

    num = random.randint(0, 36)
    rouges = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    color = "🔴" if num in rouges else ("⬛" if num != 0 else "🟢")
    color_name = "Rouge" if num in rouges else ("Noir" if num != 0 else "Zéro")

    win = False; mult = 1
    choix_l = choix.lower()
    if choix_l in ("rouge","red") and num in rouges: win=True; mult=2
    elif choix_l in ("noir","black") and num not in rouges and num!=0: win=True; mult=2
    elif choix_l in ("pair","even") and num%2==0 and num!=0: win=True; mult=2
    elif choix_l in ("impair","odd") and num%2!=0: win=True; mult=2
    else:
        try:
            n = int(choix_l)
            if n == num: win=True; mult=36
        except: pass

    if win:
        gain = bet * (mult - 1)
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        embed = discord.Embed(
            title=f"🎡 Roulette — {color} **{num}** ({color_name})",
            description=f"🎉 **Gagné !** +**{gain:,}** 🪙\n💳 Solde : **{user['coins']:,}** 🪙",
            color=0x2ECC71
        )
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        embed = discord.Embed(
            title=f"🎡 Roulette — {color} **{num}** ({color_name})",
            description=f"❌ **Perdu !** -**{bet:,}** 🪙\n💳 Solde : **{user['coins']:,}** 🪙",
            color=0xE74C3C
        )
    save_data(data)
    await spin_msg.edit(content=None, embed=embed)

@bot.command(name="dice", aliases=["de"])
async def dice(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Usage : `%dice <mise>` — Fais >7 avec deux dés pour gagner.")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")

    roll_msg = await ctx.send("🎲 *Les dés roulent...*")
    await asyncio.sleep(1.5)

    d1, d2 = random.randint(1,6), random.randint(1,6)
    total = d1 + d2
    dice_faces = ["", "1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
    result_display = f"{dice_faces[d1]} + {dice_faces[d2]} = **{total}**"

    if total > 7:
        user["coins"] += bet
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + bet
        embed = discord.Embed(title="🎲 Lancer de Dés", description=f"{result_display}\n🎉 Tu gagnes **{bet:,}** 🪙 !", color=0x2ECC71)
    elif total == 7:
        embed = discord.Embed(title="🎲 Lancer de Dés", description=f"{result_display}\n🤝 Égalité, mise remboursée.", color=0xF39C12)
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        embed = discord.Embed(title="🎲 Lancer de Dés", description=f"{result_display}\n❌ Tu perds **{bet:,}** 🪙.", color=0xE74C3C)
    save_data(data)
    await roll_msg.edit(content=None, embed=embed)

@bot.command(name="crash")
async def crash(ctx, mise: str = "0"):
    """Jeu Crash : le multiplicateur monte, mais peut crasher à tout moment. Tape 'stop' pour encaisser."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%crash <mise>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")

    crash_point = round(random.uniform(1.0, 10.0), 2)
    mult = 1.0
    step = 0.1

    embed = discord.Embed(
        title="📈 CRASH — Jeu en cours",
        description=(
            f"💰 Mise : **{bet:,}** 🪙\n"
            f"📊 Multiplicateur : **x{mult:.2f}**\n\n"
            f"*Tape* `stop` *pour encaisser avant le crash !*"
        ),
        color=0x3498DB
    )
    msg = await ctx.send(embed=embed)

    stopped = False

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "stop"

    while mult < crash_point:
        await asyncio.sleep(1.5)
        mult = round(mult + step + random.uniform(0, 0.15), 2)
        mult = min(mult, crash_point)

        new_embed = discord.Embed(
            title="📈 CRASH — Jeu en cours",
            description=(
                f"💰 Mise : **{bet:,}** 🪙\n"
                f"📊 Multiplicateur : **x{mult:.2f}**\n"
                f"💵 Gain potentiel : **{int(bet*mult):,}** 🪙\n\n"
                f"*Tape* `stop` *pour encaisser !*"
            ),
            color=0x2ECC71 if mult < 3 else (0xF39C12 if mult < 6 else 0xE74C3C)
        )
        await msg.edit(embed=new_embed)

        # Check if user stopped
        try:
            await bot.wait_for("message", check=check, timeout=0.1)
            stopped = True
            break
        except asyncio.TimeoutError:
            pass

    if stopped:
        win = int(bet * mult)
        gain = win - bet
        user["coins"] += gain
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
        final_embed = discord.Embed(
            title="📈 CRASH — Encaissé !",
            description=f"✅ Tu as encaissé à **x{mult:.2f}** !\n💰 Gain : **+{gain:,}** 🪙",
            color=0x2ECC71
        )
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        final_embed = discord.Embed(
            title="💥 CRASH !",
            description=f"Le jeu a crashé à **x{crash_point:.2f}** !\n❌ Tu perds **{bet:,}** 🪙.",
            color=0xE74C3C
        )
    save_data(data)
    await msg.edit(embed=final_embed)

# ─── Trivia (100 questions) ───────────────────────────────────────────────────

TRIVIA_QUESTIONS = [
    # ═══ FOOTBALL (20 questions) ═══
    {"q":"Quel pays a remporté la Coupe du Monde 2018 ?","a":"france","choices":["Brésil","Allemagne","France","Argentine"],"difficulty":"normal"},
    {"q":"Combien de fois le Brésil a-t-il remporté la Coupe du Monde ?","a":"5","choices":["4","5","6","3"],"difficulty":"normal"},
    {"q":"Quel club détient le record de victoires en Ligue des Champions ?","a":"real madrid","choices":["FC Barcelone","Bayern Munich","Real Madrid","AC Milan"],"difficulty":"hard"},
    {"q":"Dans quel pays se trouve le stade Maracanã ?","a":"brésil","choices":["Argentine","Brésil","Uruguay","Colombie"],"difficulty":"normal"},
    {"q":"Qui a marqué le but de la victoire en finale du Mondial 2014 ?","a":"götze","choices":["Müller","Schweinsteiger","Götze","Klose"],"difficulty":"hard"},
    {"q":"Quelle est la distance réglementaire d'un penalty en football ?","a":"11 mètres","choices":["9 mètres","11 mètres","12 mètres","10 mètres"],"difficulty":"normal"},
    {"q":"Quel joueur a gagné le plus de Ballons d'Or ?","a":"messi","choices":["Ronaldo","Messi","Zidane","Platini"],"difficulty":"normal"},
    {"q":"En quelle année a été créée la Premier League anglaise ?","a":"1992","choices":["1985","1988","1990","1992"],"difficulty":"hard"},
    {"q":"Quel pays a organisé la Coupe du Monde 2022 ?","a":"qatar","choices":["Arabie Saoudite","Qatar","Émirats Arabes Unis","Bahreïn"],"difficulty":"normal"},
    {"q":"Combien de joueurs compte une équipe de football sur le terrain ?","a":"11","choices":["9","10","11","12"],"difficulty":"normal"},
    {"q":"Quel club a remporté la Ligue des Champions en 2023 ?","a":"manchester city","choices":["Real Madrid","Bayern Munich","Manchester City","PSG"],"difficulty":"normal"},
    {"q":"Qui est le meilleur buteur de l'histoire de la Ligue des Champions ?","a":"cristiano ronaldo","choices":["Messi","Benzema","Ronaldo","Lewandowski"],"difficulty":"normal"},
    {"q":"Combien de minutes dure un match de football (temps réglementaire) ?","a":"90","choices":["80","85","90","95"],"difficulty":"normal"},
    {"q":"Quel joueur français porte le numéro 10 en équipe nationale depuis 2018 ?","a":"kylian mbappé","choices":["Griezmann","Giroud","Mbappé","Dembélé"],"difficulty":"normal"},
    {"q":"Quel stade accueille les matchs du FC Barcelone ?","a":"camp nou","choices":["Bernabéu","Wanda Metropolitano","Camp Nou","Nou Mestalla"],"difficulty":"normal"},
    {"q":"Combien de cartons jaunes mènent à une suspension en Ligue des Champions ?","a":"3","choices":["2","3","4","5"],"difficulty":"hard"},
    {"q":"Quel pays a inventé le football moderne (règles de 1863) ?","a":"angleterre","choices":["Écosse","France","Angleterre","Allemagne"],"difficulty":"hard"},
    {"q":"Qui a remporté le Ballon d'Or 2023 ?","a":"erling haaland","choices":["Mbappé","Bellingham","Haaland","De Bruyne"],"difficulty":"hard"},
    {"q":"Quelle couleur de carton signifie l'expulsion directe au football ?","a":"rouge","choices":["Orange","Bleu","Rouge","Violet"],"difficulty":"normal"},
    {"q":"Quel joueur a marqué lors de 5 Coupes du Monde différentes ?","a":"cristiano ronaldo","choices":["Messi","Pelé","Ronaldo","Baggio"],"difficulty":"hard"},

    # ═══ CULTURE GÉNÉRALE (80 questions) — dont ~30 très difficiles ═══

    # --- Géographie ---
    {"q":"Quelle est la capitale de l'Australie ?","a":"canberra","choices":["Sydney","Melbourne","Canberra","Brisbane"],"difficulty":"normal"},
    {"q":"Quel est le plus grand océan du monde ?","a":"pacifique","choices":["Atlantique","Indien","Pacifique","Arctique"],"difficulty":"normal"},
    {"q":"Quel pays a la plus grande superficie du monde ?","a":"russie","choices":["Canada","États-Unis","Russie","Chine"],"difficulty":"normal"},
    {"q":"Quelle est la capitale du Canada ?","a":"ottawa","choices":["Toronto","Montréal","Vancouver","Ottawa"],"difficulty":"normal"},
    {"q":"Quel est le plus long fleuve du monde ?","a":"nil","choices":["Amazone","Nil","Mississippi","Congo"],"difficulty":"normal"},
    {"q":"Dans quel pays se trouve la ville de Tombouctou ?","a":"mali","choices":["Niger","Sénégal","Mali","Mauritanie"],"difficulty":"hard"},
    {"q":"Quelle mer se trouve entre l'Italie et la Grèce ?","a":"mer ionienne","choices":["Mer Adriatique","Mer Tyrrhénienne","Mer Ionienne","Mer Égée"],"difficulty":"hard"},
    {"q":"Quel est le plus petit pays du monde ?","a":"vatican","choices":["Monaco","Liechtenstein","Vatican","Saint-Marin"],"difficulty":"normal"},
    {"q":"Quelle est la capitale du Kazakhstan ?","a":"astana","choices":["Almaty","Astana","Nur-Sultan","Karaganda"],"difficulty":"hard"},
    {"q":"Quel détroit sépare l'Europe de l'Afrique ?","a":"gibraltar","choices":["Magellan","Bosphore","Gibraltar","Ormuz"],"difficulty":"normal"},

    # --- Sciences ---
    {"q":"Combien de côtés a un hexagone ?","a":"6","choices":["5","6","7","8"],"difficulty":"normal"},
    {"q":"Quel élément chimique a le symbole 'Au' ?","a":"or","choices":["Argent","Or","Cuivre","Aluminium"],"difficulty":"normal"},
    {"q":"Combien de planètes compte notre système solaire ?","a":"8","choices":["7","8","9","10"],"difficulty":"normal"},
    {"q":"Quel est le symbole chimique de l'eau ?","a":"h2o","choices":["H2O","CO2","O2","H2"],"difficulty":"normal"},
    {"q":"Quelle est la vitesse de la lumière (approx.) ?","a":"300 000 km/s","choices":["150 000 km/s","300 000 km/s","450 000 km/s","500 000 km/s"],"difficulty":"normal"},
    {"q":"Quel est le numéro atomique de l'hydrogène ?","a":"1","choices":["1","2","3","4"],"difficulty":"normal"},
    {"q":"Qui a formulé la théorie de la relativité générale ?","a":"einstein","choices":["Newton","Curie","Einstein","Bohr"],"difficulty":"normal"},
    {"q":"Quel est l'organe le plus grand du corps humain ?","a":"peau","choices":["Foie","Poumon","Peau","Intestin"],"difficulty":"normal"},
    {"q":"Combien de chromosomes a un être humain normal ?","a":"46","choices":["23","44","46","48"],"difficulty":"normal"},
    {"q":"Quelle particule subatomique porte une charge négative ?","a":"électron","choices":["Proton","Neutron","Électron","Positon"],"difficulty":"normal"},
    {"q":"Quel gaz est principalement responsable de l'effet de serre ?","a":"co2","choices":["O2","N2","CO2","CH4"],"difficulty":"normal"},
    {"q":"Quelle est la table des éléments appelée ?","a":"tableau périodique","choices":["Table de Mendeleïev","Tableau Périodique","Classification atomique","Grille chimique"],"difficulty":"normal"},
    {"q":"En quelle année Darwin a-t-il publié 'De l'origine des espèces' ?","a":"1859","choices":["1849","1859","1869","1879"],"difficulty":"hard"},
    {"q":"Quelle est la formule chimique du sel de table ?","a":"nacl","choices":["KCl","NaCl","CaCl2","MgCl"],"difficulty":"normal"},
    {"q":"Quel est le métal le plus abondant dans la croûte terrestre ?","a":"aluminium","choices":["Fer","Cuivre","Aluminium","Silicium"],"difficulty":"hard"},

    # --- Histoire ---
    {"q":"En quelle année l'homme a-t-il marché sur la Lune ?","a":"1969","choices":["1965","1967","1969","1971"],"difficulty":"normal"},
    {"q":"Quelle est la devise de la France ?","a":"liberté égalité fraternité","choices":["Honneur et Patrie","Liberté Égalité Fraternité","Force et Honneur","Dieu et Mon Droit"],"difficulty":"normal"},
    {"q":"En quelle année la Première Guerre Mondiale a-t-elle commencé ?","a":"1914","choices":["1910","1912","1914","1916"],"difficulty":"normal"},
    {"q":"Qui était le premier président des États-Unis ?","a":"george washington","choices":["Abraham Lincoln","Thomas Jefferson","George Washington","Benjamin Franklin"],"difficulty":"normal"},
    {"q":"En quelle année est tombé le mur de Berlin ?","a":"1989","choices":["1985","1987","1989","1991"],"difficulty":"normal"},
    {"q":"Quel empire était gouverné par Gengis Khan ?","a":"mongol","choices":["Ottoman","Mongol","Romain","Chinois"],"difficulty":"normal"},
    {"q":"En quelle année Napoléon a-t-il été exilé à Sainte-Hélène ?","a":"1815","choices":["1810","1812","1814","1815"],"difficulty":"hard"},
    {"q":"Qui a assassiné Jules César ?","a":"brutus et cassius","choices":["Octave","Brutus et Cassius","Antoine","Pompée"],"difficulty":"hard"},
    {"q":"En quelle année a eu lieu la Révolution française ?","a":"1789","choices":["1776","1783","1789","1799"],"difficulty":"normal"},
    {"q":"Quel pharaon a fait construire la Grande Pyramide de Gizeh ?","a":"khéops","choices":["Ramsès II","Khéops","Toutânkhamon","Cléopâtre"],"difficulty":"normal"},
    {"q":"Quelle bataille a mis fin au règne de Napoléon en 1815 ?","a":"waterloo","choices":["Austerlitz","Iéna","Waterloo","Trafalgar"],"difficulty":"normal"},
    {"q":"En quelle année les États-Unis ont-ils déclaré leur indépendance ?","a":"1776","choices":["1774","1776","1778","1780"],"difficulty":"normal"},
    {"q":"Qui a découvert l'Amérique en 1492 ?","a":"christophe colomb","choices":["Vasco de Gama","Magellan","Christophe Colomb","Amerigo Vespucci"],"difficulty":"normal"},
    {"q":"Quel traité a mis fin à la Première Guerre Mondiale ?","a":"traité de versailles","choices":["Traité de Paris","Traité de Versailles","Traité de Brest-Litovsk","Traité de Trianon"],"difficulty":"hard"},
    {"q":"Quelle civilisation ancienne a inventé l'écriture cunéiforme ?","a":"mésopotamie","choices":["Égypte","Grèce","Mésopotamie","Perse"],"difficulty":"hard"},

    # --- Arts & Culture ---
    {"q":"Qui a peint la Joconde ?","a":"léonard de vinci","choices":["Michel-Ange","Raphaël","Léonard de Vinci","Botticelli"],"difficulty":"normal"},
    {"q":"Quel auteur a écrit 'Les Misérables' ?","a":"victor hugo","choices":["Zola","Balzac","Victor Hugo","Flaubert"],"difficulty":"normal"},
    {"q":"Dans quelle ville se trouve le musée du Louvre ?","a":"paris","choices":["Lyon","Marseille","Paris","Bordeaux"],"difficulty":"normal"},
    {"q":"Qui a composé la 9ème Symphonie 'Ode à la Joie' ?","a":"beethoven","choices":["Mozart","Bach","Beethoven","Schubert"],"difficulty":"normal"},
    {"q":"Quel peintre espagnol a fondé le cubisme avec Braque ?","a":"picasso","choices":["Dalí","Miró","Picasso","Goya"],"difficulty":"normal"},
    {"q":"Quel roman de Jules Verne parle d'un tour du monde en 80 jours ?","a":"le tour du monde en 80 jours","choices":["Vingt Mille Lieues sous les Mers","Le Tour du Monde en 80 Jours","Voyage au Centre de la Terre","Michel Strogoff"],"difficulty":"normal"},
    {"q":"Qui a écrit 'Don Quichotte' ?","a":"cervantes","choices":["Lope de Vega","Cervantes","Calderon","Quevedo"],"difficulty":"normal"},
    {"q":"Quel est le vrai nom de Molière ?","a":"jean-baptiste poquelin","choices":["François Arouet","Jean-Baptiste Poquelin","Pierre Corneille","Philippe Quinault"],"difficulty":"hard"},
    {"q":"Dans quelle ville se trouve la Sagrada Familia ?","a":"barcelone","choices":["Madrid","Séville","Barcelone","Valence"],"difficulty":"normal"},
    {"q":"Quel artiste a peint 'La Nuit étoilée' ?","a":"van gogh","choices":["Monet","Renoir","Van Gogh","Gauguin"],"difficulty":"normal"},
    {"q":"Qui a écrit 'L'Étranger' ?","a":"albert camus","choices":["Sartre","Camus","Malraux","Aragon"],"difficulty":"normal"},
    {"q":"Quel opéra de Verdi raconte l'histoire d'une geisha ?","a":"madama butterfly","choices":["La Traviata","Madama Butterfly","Aida","Tosca"],"difficulty":"hard"},
    {"q":"Quel peintre a coupé son oreille ?","a":"van gogh","choices":["Gauguin","Cézanne","Van Gogh","Manet"],"difficulty":"normal"},

    # --- Technologie & Informatique ---
    {"q":"Qui a fondé Apple avec Steve Jobs ?","a":"steve wozniak","choices":["Bill Gates","Steve Wozniak","Mark Zuckerberg","Elon Musk"],"difficulty":"normal"},
    {"q":"En quelle année a été lancé le premier iPhone ?","a":"2007","choices":["2005","2006","2007","2008"],"difficulty":"normal"},
    {"q":"Quel est le langage de programmation créé par Guido van Rossum ?","a":"python","choices":["Java","Python","Ruby","Perl"],"difficulty":"normal"},
    {"q":"Quel protocole permet de naviguer sur le web ?","a":"http","choices":["FTP","SMTP","HTTP","SSH"],"difficulty":"normal"},
    {"q":"Qui a inventé le World Wide Web ?","a":"tim berners-lee","choices":["Bill Gates","Steve Jobs","Tim Berners-Lee","Vint Cerf"],"difficulty":"normal"},
    {"q":"En quelle année a été créé Google ?","a":"1998","choices":["1996","1997","1998","2000"],"difficulty":"normal"},
    {"q":"Quel est le système d'exploitation open-source le plus utilisé sur les serveurs ?","a":"linux","choices":["Windows","macOS","Linux","Unix"],"difficulty":"normal"},
    {"q":"Que signifie l'acronyme 'CPU' ?","a":"central processing unit","choices":["Computer Power Unit","Central Processing Unit","Core Processing Unit","Central Program Unit"],"difficulty":"normal"},
    {"q":"Qui a créé le réseau social Facebook ?","a":"mark zuckerberg","choices":["Jack Dorsey","Mark Zuckerberg","Kevin Systrom","Evan Spiegel"],"difficulty":"normal"},
    {"q":"Quel algorithme de tri est considéré comme le plus efficace en moyenne ?","a":"quicksort","choices":["Bubble Sort","Quicksort","Merge Sort","Selection Sort"],"difficulty":"hard"},
    {"q":"En quelle année a été lancé Bitcoin ?","a":"2009","choices":["2007","2008","2009","2010"],"difficulty":"normal"},
    {"q":"Qui a inventé la machine à calculer en 1642 ?","a":"pascal","choices":["Leibniz","Newton","Pascal","Babbage"],"difficulty":"hard"},

    # --- Très Difficiles (mix) ---
    {"q":"Quelle est la constante de Planck (en Joule·seconde) ?","a":"6.626 × 10^-34","choices":["3.14 × 10^-20","6.626 × 10^-34","9.81 × 10^-15","1.38 × 10^-23"],"difficulty":"very_hard"},
    {"q":"Quel philosophe grec a écrit 'La République' ?","a":"platon","choices":["Socrate","Aristote","Platon","Épicure"],"difficulty":"normal"},
    {"q":"Quelle est la monnaie officielle de la Suisse ?","a":"franc suisse","choices":["Euro","Franc Suisse","Couronne","Florin"],"difficulty":"normal"},
    {"q":"Qui a peint le 'Radeau de la Méduse' ?","a":"géricault","choices":["Delacroix","Géricault","David","Ingres"],"difficulty":"hard"},
    {"q":"Quel est le plus long os du corps humain ?","a":"fémur","choices":["Tibia","Radius","Fémur","Humérus"],"difficulty":"normal"},
    {"q":"En quelle année a été signée la Magna Carta ?","a":"1215","choices":["1066","1189","1215","1348"],"difficulty":"hard"},
    {"q":"Quelle est la langue la plus parlée dans le monde en nombre de locuteurs natifs ?","a":"mandarin","choices":["Espagnol","Anglais","Mandarin","Hindi"],"difficulty":"normal"},
    {"q":"Quel scientifique a découvert la pénicilline ?","a":"alexander fleming","choices":["Louis Pasteur","Marie Curie","Alexander Fleming","Joseph Lister"],"difficulty":"normal"},
    {"q":"Combien de symphonies Beethoven a-t-il composées ?","a":"9","choices":["7","8","9","10"],"difficulty":"normal"},
    {"q":"Quel est l'élément chimique le plus rare sur Terre ?","a":"astate","choices":["Francium","Astate","Oganesson","Technetium"],"difficulty":"very_hard"},
    {"q":"En quelle année a été fondée l'Organisation des Nations Unies ?","a":"1945","choices":["1919","1939","1945","1950"],"difficulty":"normal"},
    {"q":"Quel mathématicien a prouvé le dernier théorème de Fermat en 1995 ?","a":"andrew wiles","choices":["Grigori Perelman","Andrew Wiles","Terence Tao","John Nash"],"difficulty":"very_hard"},
    {"q":"Quelle constellation contient l'étoile Sirius ?","a":"grand chien","choices":["Orion","Cassiopée","Grand Chien","Ursa Major"],"difficulty":"hard"},
    {"q":"Quelle est la distance moyenne Terre-Lune ?","a":"384 400 km","choices":["150 000 km","384 400 km","500 000 km","1 200 000 km"],"difficulty":"hard"},
    {"q":"Quel empire romain d'Orient a duré jusqu'en 1453 ?","a":"empire byzantin","choices":["Empire Ottoman","Empire Byzantin","Empire Sassanide","Empire Mongol"],"difficulty":"hard"},
]

# Cooldown tracking for trivia (per user)
trivia_cooldowns: dict[int, float] = {}

@bot.command(name="trivia")
async def trivia(ctx):
    now = time.time()
    # 30 second cooldown between trivias
    last_trivia = trivia_cooldowns.get(ctx.author.id, 0)
    if now - last_trivia < 30:
        remaining = int(30 - (now - last_trivia))
        return await ctx.send(f"⏳ Attends encore **{remaining}s** avant le prochain trivia !")

    data = load_data()
    user = get_user(data, ctx.author.id)

    q = random.choice(TRIVIA_QUESTIONS)
    difficulty = q.get("difficulty", "normal")

    if difficulty == "very_hard":
        reward = random.randint(400, 800)
        penalty = random.randint(200, 400)
        diff_label = "🔴 TRÈS DIFFICILE"
        diff_color = 0xE74C3C
    elif difficulty == "hard":
        reward = random.randint(200, 400)
        penalty = random.randint(100, 200)
        diff_label = "🟠 DIFFICILE"
        diff_color = 0xE67E22
    else:
        reward = random.randint(80, 180)
        penalty = random.randint(40, 90)
        diff_label = "🟢 NORMAL"
        diff_color = 0x3498DB

    choices = q["choices"].copy()
    # Apply hint if user has it
    hint_used = False
    if user.get("trivia_hint"):
        wrong = [c for c in choices if c.lower() != q["a"].lower()]
        if len(wrong) >= 2:
            to_remove = random.sample(wrong, 2)
            choices = [c for c in choices if c not in to_remove]
            user["trivia_hint"] = False
            hint_used = True

    choices_str = "\n".join(f"**{i+1}.** {c}" for i, c in enumerate(choices))

    embed = discord.Embed(
        title=f"🧠 TRIVIA  [{diff_label}]",
        description=f"**{q['q']}**",
        color=diff_color
    )
    embed.add_field(name="Choix", value=choices_str, inline=False)
    if hint_used:
        embed.add_field(name="💡 Indice", value="2 mauvaises réponses éliminées !", inline=False)
    embed.set_footer(text=f"✅ +{reward} 🪙 | ❌ -{penalty} 🪙 | ⏱️ 10 secondes")

    await ctx.send(embed=embed)
    trivia_cooldowns[ctx.author.id] = now

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel:
            return False
        ans = m.content.strip().lower()
        try:
            idx = int(ans) - 1
            return 0 <= idx < len(choices)
        except:
            return any(ans in c.lower() for c in choices)

    try:
        resp = await bot.wait_for("message", check=check, timeout=10)
    except asyncio.TimeoutError:
        user["coins"] = max(0, user["coins"] - penalty)
        user["trivia_losses"] = user.get("trivia_losses", 0) + 1
        save_data(data)
        return await ctx.send(
            f"⏳ **Temps écoulé !** La réponse était **{q['a'].title()}**.\n"
            f"❌ Tu perds **{penalty:,}** 🪙 (trop lent !)"
        )

    ans = resp.content.strip().lower()
    try:
        idx = int(ans) - 1
        given = choices[idx].lower()
    except:
        given = ans

    if q["a"].lower() in given or given in q["a"].lower():
        user["coins"] += reward
        xp_gain = 25 if difficulty == "very_hard" else (15 if difficulty == "hard" else 10)
        user["xp"] += xp_gain
        user["trivia_wins"] = user.get("trivia_wins", 0) + 1
        user["total_earned"] = user.get("total_earned", 0) + reward
        save_data(data)
        embed_result = discord.Embed(
            title="✅ BONNE RÉPONSE !",
            description=f"🎉 +**{reward:,}** 🪙 et +**{xp_gain}** XP !",
            color=0x2ECC71
        )
        await ctx.send(embed=embed_result)
    else:
        user["coins"] = max(0, user["coins"] - penalty)
        user["trivia_losses"] = user.get("trivia_losses", 0) + 1
        save_data(data)
        embed_result = discord.Embed(
            title="❌ MAUVAISE RÉPONSE !",
            description=f"La réponse était **{q['a'].title()}**.\n💸 Tu perds **{penalty:,}** 🪙 !",
            color=0xE74C3C
        )
        await ctx.send(embed=embed_result)

# ─── Mini-jeux ────────────────────────────────────────────────────────────────

@bot.command(name="rps")
async def rps(ctx, target: discord.Member, mise: str = "0"):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send("❌ Cible invalide.")
    data = load_data()
    challenger = get_user(data, ctx.author.id)
    opponent = get_user(data, target.id)
    bet = parse_bet(challenger, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%rps @user <mise>`")
    if bet > challenger["coins"]:
        return await ctx.send("❌ Tu n'as pas assez de coins.")
    if bet > opponent["coins"]:
        return await ctx.send(f"❌ {target.display_name} n'a pas assez de coins.")

    embed_challenge = discord.Embed(
        title="⚔️ Pierre Feuille Ciseaux — Défi",
        description=f"{target.mention}, {ctx.author.mention} te défie pour **{bet:,}** 🪙 !\nAcceptes-tu ? (`oui` / `non`)",
        color=0x9B59B6
    )
    await ctx.send(embed=embed_challenge)

    def check_accept(m):
        return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non","yes","no")
    try:
        resp = await bot.wait_for("message", check=check_accept, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Défi expiré.")
    if resp.content.lower() in ("non","no"):
        return await ctx.send("❌ Défi refusé.")

    choices_map = {"pierre":"🪨","feuille":"📄","ciseaux":"✂️","p":"🪨","f":"📄","c":"✂️"}
    wins = {"pierre":"ciseaux","feuille":"pierre","ciseaux":"feuille"}

    async def get_choice(player):
        try:
            await player.send(f"🎮 **Pierre Feuille Ciseaux** — Choisis : `pierre`, `feuille` ou `ciseaux` (30s)")
        except:
            return None
        def dm_check(m): return m.author == player and isinstance(m.channel, discord.DMChannel) and m.content.lower() in choices_map
        try:
            r = await bot.wait_for("message", check=dm_check, timeout=30)
            return r.content.lower()
        except:
            return None

    await ctx.send("📩 Vérifiez vos DMs pour choisir !")
    c1, c2 = await get_choice(ctx.author), await get_choice(target)
    if not c1 or not c2:
        return await ctx.send("⏳ L'un des joueurs n'a pas répondu à temps.")

    c1n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c1, c1)
    c2n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c2, c2)
    e1, e2 = choices_map[c1], choices_map[c2]

    if c1n == c2n:
        result = "🤝 **Égalité !** Mises remboursées."
        color = 0xF39C12
    elif wins[c1n] == c2n:
        challenger["coins"] += bet
        opponent["coins"] = max(0, opponent["coins"] - bet)
        challenger["casino_wins"] += 1
        result = f"🏆 **{ctx.author.display_name}** gagne **{bet:,}** 🪙 !"
        color = 0x2ECC71
    else:
        opponent["coins"] += bet
        challenger["coins"] = max(0, challenger["coins"] - bet)
        opponent["casino_wins"] += 1
        result = f"🏆 **{target.display_name}** gagne **{bet:,}** 🪙 !"
        color = 0x2ECC71
    save_data(data)

    embed_result = discord.Embed(title="⚔️ Pierre Feuille Ciseaux — Résultat", color=color)
    embed_result.add_field(name=ctx.author.display_name, value=e1, inline=True)
    embed_result.add_field(name="VS", value="⚔️", inline=True)
    embed_result.add_field(name=target.display_name, value=e2, inline=True)
    embed_result.add_field(name="Résultat", value=result, inline=False)
    await ctx.send(embed=embed_result)

@bot.command(name="duel")
async def duel(ctx, target: discord.Member, mise: str = "0"):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send("❌ Cible invalide.")
    data = load_data()
    challenger = get_user(data, ctx.author.id)
    opponent = get_user(data, target.id)
    bet = parse_bet(challenger, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%duel @user <mise>`")
    if bet > challenger["coins"]: return await ctx.send("❌ Pas assez de coins.")
    if bet > opponent["coins"]: return await ctx.send(f"❌ {target.display_name} n'a pas assez de coins.")

    embed_challenge = discord.Embed(
        title="⚔️ DUEL",
        description=f"{target.mention}, tu es défié par {ctx.author.mention} pour **{bet:,}** 🪙 !\n(`oui` / `non`)",
        color=0xE74C3C
    )
    await ctx.send(embed=embed_challenge)

    def check_a(m): return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non")
    try:
        r = await bot.wait_for("message", check=check_a, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Défi expiré.")
    if r.content.lower() == "non": return await ctx.send("❌ Défi refusé.")

    duel_msg = await ctx.send("⚔️ *Le duel commence ! Les dés roulent...*")
    await asyncio.sleep(2)
    r1, r2 = random.randint(1,100), random.randint(1,100)
    while r1 == r2:
        r1, r2 = random.randint(1,100), random.randint(1,100)

    if r1 > r2:
        challenger["coins"] += bet
        opponent["coins"] = max(0, opponent["coins"] - bet)
        challenger["casino_wins"] += 1
        embed_result = discord.Embed(
            title="⚔️ DUEL — Résultat",
            description=f"🏆 **{ctx.author.display_name}** (**{r1}**) bat **{target.display_name}** (**{r2}**) !\n+**{bet:,}** 🪙",
            color=0x2ECC71
        )
    else:
        opponent["coins"] += bet
        challenger["coins"] = max(0, challenger["coins"] - bet)
        opponent["casino_wins"] += 1
        embed_result = discord.Embed(
            title="⚔️ DUEL — Résultat",
            description=f"🏆 **{target.display_name}** (**{r2}**) bat **{ctx.author.display_name}** (**{r1}**) !\n+**{bet:,}** 🪙",
            color=0x2ECC71
        )
    save_data(data)
    await duel_msg.edit(content=None, embed=embed_result)

@bot.command(name="mines")
async def mines(ctx, mise: str = "0", cases: int = 3):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Usage : `%mines <mise> <nb_mines 1-8>`")
    if bet > user["coins"]: return await ctx.send("❌ Pas assez de coins.")
    cases = max(1, min(8, cases))
    total = 9
    mine_positions = random.sample(range(total), cases)
    revealed = []
    mult = 1.0

    def grid_display():
        rows = []
        for row in range(3):
            row_str = ""
            for col in range(3):
                i = row * 3 + col
                if i in revealed:
                    row_str += "💣 " if i in mine_positions else "💎 "
                else:
                    row_str += "⬛ "
            rows.append(row_str.strip())
        return "\n".join(rows)

    embed = discord.Embed(
        title=f"💣 MINES — {cases} mine(s)",
        description=f"{grid_display()}\n\n💰 Mise : **{bet:,}** 🪙\n📊 Multiplicateur : **x{mult:.2f}**",
        color=0xE67E22
    )
    embed.set_footer(text="Tape un numéro (1-9) pour révéler | 'stop' pour encaisser")
    msg = await ctx.send(embed=embed)

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel: return False
        if m.content.lower() == "stop": return True
        try: v = int(m.content); return 1 <= v <= 9
        except: return False

    while len(revealed) < total - cases:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            break
        if resp.content.lower() == "stop":
            break
        idx = int(resp.content) - 1
        if idx in revealed:
            await ctx.send("⚠️ Case déjà révélée."); continue
        revealed.append(idx)
        if idx in mine_positions:
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            save_data(data)
            embed_lose = discord.Embed(
                title="💥 MINE TOUCHÉE !",
                description=f"{grid_display()}\n\n❌ Tu perds **{bet:,}** 🪙 !",
                color=0xE74C3C
            )
            return await msg.edit(embed=embed_lose)
        safe = total - cases
        mult = round(1 + (len(revealed) / safe) * (cases * 0.9), 2)
        embed_update = discord.Embed(
            title=f"💣 MINES — {cases} mine(s)",
            description=f"{grid_display()}\n\n💰 Mise : **{bet:,}** 🪙\n📊 Multiplicateur : **x{mult:.2f}**\n💵 Gain potentiel : **{int(bet*mult):,}** 🪙",
            color=0x2ECC71
        )
        embed_update.set_footer(text="Tape un numéro (1-9) | 'stop' pour encaisser")
        await msg.edit(embed=embed_update)

    win = int(bet * mult)
    gain = win - bet
    user["coins"] += gain
    if gain >= 0:
        user["casino_wins"] += 1
        user["total_earned"] = user.get("total_earned", 0) + gain
    save_data(data)
    embed_win = discord.Embed(
        title="🏁 MINES — Encaissé !",
        description=f"{grid_display()}\n\n✅ x{mult:.2f} → **+{gain:,}** 🪙\n💳 Solde : **{user['coins']:,}** 🪙",
        color=0x2ECC71
    )
    await msg.edit(embed=embed_win)

@bot.command(name="course")
async def course(ctx):
    horses = ["🐴 Éclair", "🦄 Pégase", "🐎 Tornado", "🏇 Foudre", "🎠 Tempête", "🐂 Tonnerre"]
    odds = [2, 3, 4, 5, 6, 8]

    embed = discord.Embed(
        title="🏇 COURSE DE CHEVAUX",
        description="**Pariez sur un cheval !**\nFormat : `<numéro> <mise>` — ex: `2 500`",
        color=0xE67E22
    )
    for i, (h, o) in enumerate(zip(horses, odds)):
        embed.add_field(name=f"{i+1}. {h}", value=f"Cote : x{o}", inline=True)
    embed.set_footer(text="⏳ 30 secondes pour parier !")
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
    while time.time() < deadline:
        remaining = max(0, deadline - time.time())
        try:
            resp = await bot.wait_for("message", check=check, timeout=remaining)
        except asyncio.TimeoutError:
            break
        parts = resp.content.strip().split()
        horse_idx, bet_amt = int(parts[0]) - 1, int(parts[1])
        data = load_data()
        u = get_user(data, resp.author.id)
        if bet_amt > u["coins"]:
            await ctx.send(f"❌ {resp.author.mention} n'a pas assez de coins."); continue
        bets[resp.author.id] = (horse_idx, bet_amt)
        await ctx.send(f"✅ {resp.author.mention} mise **{bet_amt:,}** 🪙 sur **{horses[horse_idx]}** !")
        save_data(data)

    if not bets:
        return await ctx.send("🏇 Aucun pari — course annulée.")

    # Race animation
    race_msg = await ctx.send("```\n🏁 La course commence !\n```")
    await asyncio.sleep(1)

    positions = list(range(len(horses)))
    random.shuffle(positions)
    winner_idx = positions[0]

    # Show race progress
    progress = {i: 0 for i in range(len(horses))}
    for _ in range(5):
        for i in range(len(horses)):
            progress[i] += random.randint(1, 5)
        race_display = "```\n🏁 EN COURS...\n"
        for i, h in enumerate(horses):
            bar = "─" * progress[i]
            race_display += f"{h[:8]:8} |{bar}\n"
        race_display += "```"
        await race_msg.edit(content=race_display)
        await asyncio.sleep(0.8)

    result_embed = discord.Embed(
        title=f"🏆 VICTOIRE : {horses[winner_idx]} !",
        color=0xFFD700
    )
    data = load_data()
    for uid, (hidx, bet_amt) in bets.items():
        u = get_user(data, uid)
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else str(uid)
        if hidx == winner_idx:
            win = bet_amt * odds[winner_idx]
            gain = win - bet_amt
            u["coins"] += gain
            u["casino_wins"] += 1
            result_embed.add_field(name=f"🎉 {name}", value=f"+**{gain:,}** 🪙 (x{odds[winner_idx]})", inline=True)
        else:
            u["coins"] = max(0, u["coins"] - bet_amt)
            u["casino_losses"] += 1
            result_embed.add_field(name=f"❌ {name}", value=f"-**{bet_amt:,}** 🪙", inline=True)
    save_data(data)
    await ctx.send(embed=result_embed)

@bot.command(name="pendu")
async def pendu(ctx, mise: str = "0"):
    """Jeu du pendu : devinez le mot lettre par lettre."""
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : 10. Usage : `%pendu <mise>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")

    words = [
        ("PYTHON","Langage de programmation"),("CASINO","Lieu de jeux"),("FOOTBALL","Sport collectif"),
        ("DISCORD","Application de chat"),("DIAMANT","Gemme précieuse"),("VICTOIRE","Résultat d'une bataille"),
        ("GALAXIE","Ensemble d'étoiles"),("PYRAMIDE","Monument égyptien"),("AVENTURE","Quête périlleuse"),
        ("CHAMPION","Le meilleur"),("MYSTERE","Énigme à résoudre"),("PAYSAGE","Vue naturelle"),
        ("TOURNOI","Compétition sportive"),("STRATEGIE","Plan d'action"),("MOLECULE","Ensemble d'atomes"),
    ]
    word, hint = random.choice(words)
    guessed = set()
    max_errors = 6
    errors = 0
    hangman_stages = ["😊","😐","😟","😰","😨","😱","💀"]

    def display_word():
        return " ".join(c if c in guessed else "\_" for c in word)

    def hangman_display():
        return (
            f"```\n"
            f"  ┌──┐\n"
            f"  │  {hangman_stages[errors]}\n"
            f"  │  {'👕' if errors >= 2 else ''}\n"
            f"  │ {'🦵' if errors >= 4 else ''} {'🦵' if errors >= 5 else ''}\n"
            f"──┴──\n"
            f"Erreurs : {errors}/{max_errors}\n"
            f"```"
        )

    embed = discord.Embed(
        title="🎭 LE PENDU",
        description=(
            f"{hangman_display()}\n"
            f"**Indice :** {hint}\n"
            f"**Mot :** {display_word()}\n\n"
            f"💰 Mise : **{bet:,}** 🪙\n"
            f"Lettres : {len(word)} lettres\n\n"
            f"*Propose une lettre en tapant juste la lettre !*"
        ),
        color=0x9B59B6
    )
    embed.set_footer(text="Tu as 6 erreurs maximum.")
    msg = await ctx.send(embed=embed)

    wrong_letters = []

    def check(m):
        return (m.author == ctx.author and m.channel == ctx.channel
                and len(m.content) == 1 and m.content.isalpha())

    while errors < max_errors:
        try:
            resp = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            user["coins"] = max(0, user["coins"] - bet)
            user["casino_losses"] += 1
            save_data(data)
            return await ctx.send(f"⏳ Temps écoulé ! Le mot était **{word}**. Tu perds **{bet:,}** 🪙.")

        letter = resp.content.upper()
        if letter in guessed or letter in wrong_letters:
            await ctx.send(f"⚠️ Tu as déjà proposé **{letter}** !")
            continue

        if letter in word:
            guessed.add(letter)
            if all(c in guessed for c in word):
                user["coins"] += bet * 2
                user["casino_wins"] += 1
                save_data(data)
                embed_win = discord.Embed(
                    title="🎭 PENDU — VICTOIRE !",
                    description=f"✅ Le mot était **{word}** !\n🎉 Tu gagnes **{bet*2:,}** 🪙 !",
                    color=0x2ECC71
                )
                return await msg.edit(embed=embed_win)
        else:
            errors += 1
            wrong_letters.append(letter)

        color = 0x2ECC71 if errors < 3 else (0xE67E22 if errors < 5 else 0xE74C3C)
        embed_update = discord.Embed(
            title="🎭 LE PENDU",
            description=(
                f"{hangman_display()}\n"
                f"**Indice :** {hint}\n"
                f"**Mot :** {display_word()}\n"
                f"**Lettres ratées :** {', '.join(wrong_letters) if wrong_letters else '—'}\n\n"
                f"💰 Mise : **{bet:,}** 🪙"
            ),
            color=color
        )
        await msg.edit(embed=embed_update)

    user["coins"] = max(0, user["coins"] - bet)
    user["casino_losses"] += 1
    save_data(data)
    embed_lose = discord.Embed(
        title="💀 PENDU — PERDU !",
        description=f"Le mot était **{word}** !\n❌ Tu perds **{bet:,}** 🪙.",
        color=0xE74C3C
    )
    await msg.edit(embed=embed_lose)

# ─── Shop ─────────────────────────────────────────────────────────────────────

@bot.command(name="shop", aliases=["magasin"])
async def shop(ctx):
    embed = discord.Embed(
        title="🛒 BOUTIQUE",
        description="Achète des items pour améliorer tes performances !\n`%buy <clé>` pour acheter.",
        color=0x9B59B6
    )
    for key, item in SHOP_ITEMS.items():
        embed.add_field(
            name=f"{item['emoji']} {item['name']} — **{item['price']:,}** 🪙",
            value=f"{item['description']}\n`%buy {key}`",
            inline=False
        )
    embed.set_footer(text="💡 Utilise %use <clé> pour activer un item de ton inventaire")
    await ctx.send(embed=embed)

@bot.command(name="buy", aliases=["acheter"])
async def buy(ctx, item_key: str = ""):
    if item_key not in SHOP_ITEMS:
        return await ctx.send(f"❌ Item invalide. Utilise `%shop` pour voir les items disponibles.")
    item = SHOP_ITEMS[item_key]
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user["coins"] < item["price"]:
        return await ctx.send(f"❌ Pas assez de coins. (Besoin : **{item['price']:,}** 🪙, Tu as : **{user['coins']:,}** 🪙)")

    if item_key == "role_perso":
        await ctx.send("🎨 Quel nom veux-tu pour ton rôle ? (ex: `MegaGamer`)")
        def check_name(m): return m.author == ctx.author and m.channel == ctx.channel
        try:
            rn = await bot.wait_for("message", check=check_name, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("⏳ Temps écoulé.")
        await ctx.send("🎨 Quelle couleur ? (ex: `#FF5733` ou `rouge`, `bleu`, `vert`, `violet`, `orange`, `doré`)")
        color_names = {"rouge":0xFF0000,"bleu":0x0000FF,"vert":0x00FF00,"violet":0x800080,"orange":0xFF8C00,"doré":0xFFD700,"rose":0xFF69B4,"cyan":0x00FFFF}
        try:
            rc = await bot.wait_for("message", check=check_name, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("⏳ Temps écoulé.")
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
            await ctx.send(f"✅ Rôle **{role.name}** créé et attribué !")
        except discord.Forbidden:
            return await ctx.send("❌ Je n'ai pas la permission de créer des rôles.")
    else:
        user["coins"] -= item["price"]
        user["inventory"].append(item_key)
        save_data(data)
        embed = discord.Embed(
            description=f"✅ Tu as acheté **{item['name']}** ! Utilise `%use {item_key}` pour l'activer.",
            color=0x2ECC71
        )
        await ctx.send(embed=embed)

@bot.command(name="inventaire", aliases=["inv", "inventory"])
async def inventaire(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    if not user["inventory"]:
        return await ctx.send("🎒 Ton inventaire est vide.")
    embed = discord.Embed(title=f"🎒 Inventaire de {ctx.author.display_name}", color=0x9B59B6)
    counts: dict[str,int] = {}
    for i in user["inventory"]:
        counts[i] = counts.get(i,0) + 1
    for k, cnt in counts.items():
        item = SHOP_ITEMS.get(k, {"name": k, "emoji": "❓"})
        embed.add_field(name=f"{item['emoji']} {item['name']} x{cnt}", value=f"`%use {k}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="use", aliases=["utiliser"])
async def use(ctx, item_key: str = ""):
    data = load_data()
    user = get_user(data, ctx.author.id)
    if item_key not in user["inventory"]:
        return await ctx.send("❌ Tu ne possèdes pas cet item.")
    now = time.time()

    if item_key == "xp_boost_1h":
        user["xp_boost_until"] = now + 3600
        msg = "⚡ Boost XP x2 activé pour **1 heure** !"
    elif item_key == "xp_boost_24h":
        user["xp_boost_until"] = now + 86400
        msg = "🌩️ Boost XP x2 activé pour **24 heures** !"
    elif item_key == "shield":
        user["shield"] = True
        msg = "🛡️ Bouclier activé ! Tu es protégé contre le prochain vol."
    elif item_key == "mega_shield":
        user["mega_shield_charges"] = 3
        msg = "🔰 Mega Bouclier activé ! Tu es protégé contre les **3 prochains vols**."
    elif item_key == "lucky_charm":
        user["lucky_charm_until"] = now + 86400
        msg = "🍀 Porte-bonheur activé pour **24h** ! (+8% casino)"
    elif item_key == "mega_luck":
        user["mega_luck_until"] = now + 172800
        msg = "🌈 Méga Chance activée pour **48h** ! (+15% casino)"
    elif item_key == "daily_bonus":
        user["daily_bonus_x2"] = True
        msg = "🎁 Ton prochain `%daily` sera **x2** !"
    elif item_key == "daily_bonus_x3":
        user["daily_bonus_x3"] = True
        msg = "💝 Ton prochain `%daily` sera **x3** !"
    elif item_key == "work_boost":
        user["work_boost_until"] = now + 7200
        msg = "💼 Boost Travail activé ! Gains de `%work` x2 pendant **2h** !"
    elif item_key == "vip_pass":
        user["vip_pass_until"] = now + 43200
        msg = "👑 VIP Pass activé ! Tous les cooldowns réduits de **50%** pendant **12h** !"
    elif item_key == "casino_insurance":
        user["casino_insurance"] = True
        msg = "🔒 Assurance Casino activée ! Ta prochaine perte (max 5000 🪙) sera remboursée."
    elif item_key == "trivia_hint":
        user["trivia_hint"] = True
        msg = "💡 Indice Trivia activé ! 2 mauvaises réponses seront éliminées au prochain trivia."
    else:
        msg = "❌ Cet item ne peut pas être utilisé manuellement."

    user["inventory"].remove(item_key)
    save_data(data)
    embed = discord.Embed(description=msg, color=0x2ECC71)
    await ctx.send(embed=embed)

# ─── Error handler ────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant. Tape `%help` pour l'aide.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Membre introuvable.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument invalide. Tape `%help` pour l'aide.")
    else:
        await ctx.send(f"⚠️ Erreur : {error}")

# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("❌ La variable d'environnement DISCORD_TOKEN est manquante !")
    bot.run(TOKEN)
