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
XP_PER_MESSAGE = (5, 15)        # min, max XP par message
XP_PER_MINUTE_VOCAL = 3         # XP par minute en vocal
XP_MESSAGE_COOLDOWN = 60        # secondes entre deux gains de XP par message

# Niveaux → rôles (level requis : nom du rôle)
LEVEL_ROLES = {
    5:   "Débutant du casino",
    15:  "Aventurier du casino",
    30:  "Vétéran du casino",
    50:  "Expert du casino",
    100: "Légende du casino",
}

# Formule XP pour passer au niveau N : 100 * N^1.7
def xp_for_level(level: int) -> int:
    return int(100 * (level ** 1.7))

# Argent de départ
STARTING_COINS = 200

# Shop items
SHOP_ITEMS = {
    "role_perso": {
        "name": "🎨 Rôle Personnalisé",
        "description": "Un rôle avec la couleur et le nom de votre choix.",
        "price": 5000,
        "emoji": "🎨",
    },
    "xp_boost_1h": {
        "name": "⚡ Boost XP (1h)",
        "description": "Double votre gain d'XP pendant 1 heure.",
        "price": 800,
        "emoji": "⚡",
    },
    "shield": {
        "name": "🛡️ Bouclier",
        "description": "Protège vos coins lors du prochain vol.",
        "price": 400,
        "emoji": "🛡️",
    },
    "lucky_charm": {
        "name": "🍀 Porte-bonheur",
        "description": "Augmente vos chances au casino pendant 24h (+5%).",
        "price": 1200,
        "emoji": "🍀",
    },
    "daily_bonus": {
        "name": "🎁 Bonus Journalier x2",
        "description": "Double votre prochain %daily.",
        "price": 600,
        "emoji": "🎁",
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
        }
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

# ─── Bot setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

vocal_sessions: dict[int, float] = {}  # user_id → timestamp d'entrée

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

    # Gain XP si cooldown écoulé
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
    # Attribution de rôle si palier atteint
    role_name = LEVEL_ROLES.get(new_level)
    role_msg = ""
    if role_name:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            # Retirer les anciens rôles casino
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

    embed = discord.Embed(
        title="🎉 Niveau supérieur !",
        description=f"Félicitations {member.mention} ! Tu passes au **niveau {new_level}** !{role_msg}",
        color=0xFFD700
    )
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
    embed = discord.Embed(title="📖 Aide — Toutes les commandes", color=0x5865F2)
    embed.add_field(name="📊 Profil & XP", value=(
        "`%profil` — Voir ton profil\n"
        "`%classement` — Top 10 XP\n"
        "`%richesse` — Top 10 coins"
    ), inline=False)
    embed.add_field(name="💰 Argent", value=(
        "`%daily` — Bonus journalier\n"
        "`%work` — Travailler (30min cooldown)\n"
        "`%crime` — Crime risqué (1h cooldown)\n"
        "`%rob @user` — Voler quelqu'un (2h cooldown)\n"
        "`%solde` — Voir tes coins"
    ), inline=False)
    embed.add_field(name="🎰 Casino", value=(
        "`%slot <mise>` — Machine à sous\n"
        "`%coinflip <mise> <pile/face>` — Pile ou Face\n"
        "`%blackjack <mise>` — Blackjack\n"
        "`%roulette <mise> <choix>` — Roulette\n"
        "`%dice <mise>` — Lancer de dé"
    ), inline=False)
    embed.add_field(name="🎮 Mini-jeux", value=(
        "`%trivia` — Question culture générale\n"
        "`%rps @user <mise>` — Pierre Feuille Ciseaux\n"
        "`%duel @user <mise>` — Duel au hasard\n"
        "`%mines <mise> <cases>` — Mines\n"
        "`%course` — Course de chevaux (multijoueur)"
    ), inline=False)
    embed.add_field(name="🛒 Shop", value=(
        "`%shop` — Voir le magasin\n"
        "`%buy <item>` — Acheter un item\n"
        "`%inventaire` — Voir ton inventaire\n"
        "`%use <item>` — Utiliser un item"
    ), inline=False)
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
    bar = "█" * filled + "░" * (bar_len - filled)
    next_role_level = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
    next_role_info = f"Prochain rôle : **{LEVEL_ROLES[next_role_level]}** (niv. {next_role_level})" if next_role_level else "🏆 Rang maximum atteint !"
    embed = discord.Embed(title=f"🎰 Profil de {member.display_name}", color=0xFFD700)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📊 Niveau", value=f"**{level}**", inline=True)
    embed.add_field(name="⭐ XP Total", value=f"**{user['xp']}**", inline=True)
    embed.add_field(name="💰 Coins", value=f"**{user['coins']:,}** 🪙", inline=True)
    embed.add_field(name="Progression", value=f"`{bar}` {current_xp}/{needed_xp} XP", inline=False)
    embed.add_field(name="🎯 Objectif", value=next_role_info, inline=False)
    embed.add_field(name="🎰 Casino", value=f"✅ {user.get('casino_wins',0)} victoires | ❌ {user.get('casino_losses',0)} défaites", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="solde", aliases=["balance", "coins"])
async def solde(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    save_data(data)
    await ctx.send(f"💰 {ctx.author.mention} tu possèdes **{user['coins']:,}** 🪙")

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
        lines.append(f"{medals[i]} **{name}** — Niv. {lvl} ({xp} XP)")
    embed.description = "\n".join(lines) if lines else "Aucune donnée."
    await ctx.send(embed=embed)

@bot.command(name="richesse")
async def richesse(ctx):
    data = load_data()
    scores = [(int(uid), d["coins"]) for uid, d in data.items()]
    scores.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="💰 Top 10 — Richesse", color=0x2ECC71)
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
        h, m = divmod(int(remaining), 3600)
        m //= 60
        return await ctx.send(f"⏳ Prochain daily dans **{h}h{m:02d}m**.")
    amount = random.randint(100, 300)
    if user.get("daily_bonus_x2"):
        amount *= 2
        user["daily_bonus_x2"] = False
        await ctx.send(f"🎁 Bonus x2 activé ! Tu reçois **{amount:,}** 🪙 !")
    else:
        await ctx.send(f"🎁 Daily récupéré ! Tu reçois **{amount:,}** 🪙 !")
    user["coins"] += amount
    user["last_daily"] = now
    save_data(data)

@bot.command(name="work")
async def work(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 1800
    if now - user["last_work"] < cooldown:
        remaining = cooldown - (now - user["last_work"])
        m = int(remaining // 60)
        return await ctx.send(f"⏳ Tu peux retravailler dans **{m} minutes**.")
    jobs = [
        ("🍕 Livraison de pizzas", 50, 120),
        ("💻 Développeur freelance", 80, 200),
        ("🎸 Musicien de rue", 30, 90),
        ("🚕 Chauffeur VTC", 60, 150),
        ("🧹 Agent d'entretien", 40, 100),
        ("📦 Livreur Amazon", 70, 160),
    ]
    job, mn, mx = random.choice(jobs)
    amount = random.randint(mn, mx)
    user["coins"] += amount
    user["last_work"] = now
    save_data(data)
    await ctx.send(f"{job} — Tu gagnes **{amount}** 🪙 !")

@bot.command(name="crime")
async def crime(ctx):
    data = load_data()
    user = get_user(data, ctx.author.id)
    now = time.time()
    cooldown = 3600
    if now - user["last_crime"] < cooldown:
        remaining = cooldown - (now - user["last_crime"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return await ctx.send(f"⏳ Tu dois attendre **{h}h{m:02d}m** avant de recommencer.")
    user["last_crime"] = now
    if random.random() < 0.35:
        fine = random.randint(100, 400)
        user["coins"] = max(0, user["coins"] - fine)
        save_data(data)
        return await ctx.send(f"🚔 Tu t'es fait attraper ! Amende de **{fine}** 🪙.")
    amount = random.randint(200, 600)
    user["coins"] += amount
    save_data(data)
    crimes = ["🏦 Braquage de banque", "💎 Vol de bijoux", "🎭 Arnaque à l'arnaque", "🖥️ Piratage informatique"]
    await ctx.send(f"{random.choice(crimes)} réussi ! Tu gagnes **{amount}** 🪙 !")

@bot.command(name="rob")
async def rob(ctx, target: discord.Member):
    if target.bot or target.id == ctx.author.id:
        return await ctx.send("❌ Cible invalide.")
    data = load_data()
    robber = get_user(data, ctx.author.id)
    victim = get_user(data, target.id)
    now = time.time()
    cooldown = 7200
    if now - robber.get("last_rob", 0) < cooldown:
        remaining = cooldown - (now - robber["last_rob"])
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return await ctx.send(f"⏳ Tu dois attendre **{h}h{m:02d}m** avant de voler à nouveau.")
    if victim.get("shield"):
        victim["shield"] = False
        robber["last_rob"] = now
        save_data(data)
        return await ctx.send(f"🛡️ {target.display_name} était protégé par un bouclier ! Vol annulé.")
    if victim["coins"] < 50:
        return await ctx.send(f"💸 {target.display_name} n'a pas assez de coins à voler.")
    robber["last_rob"] = now
    if random.random() < 0.4:
        fine = random.randint(50, 200)
        robber["coins"] = max(0, robber["coins"] - fine)
        save_data(data)
        return await ctx.send(f"🚔 {ctx.author.mention} s'est fait attraper ! Amende de **{fine}** 🪙.")
    stolen = random.randint(50, min(300, victim["coins"] // 2))
    victim["coins"] -= stolen
    robber["coins"] += stolen
    save_data(data)
    await ctx.send(f"🦹 {ctx.author.mention} vole **{stolen}** 🪙 à {target.mention} !")

# ─── Casino ───────────────────────────────────────────────────────────────────

def parse_bet(user: dict, arg: str) -> int | None:
    if arg.lower() in ("all", "tout"):
        return user["coins"]
    try:
        v = int(arg)
        return v if v > 0 else None
    except:
        return None

@bot.command(name="slot", aliases=["slots"])
async def slot(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Mise minimum : **10** 🪙. Usage : `%slot <mise>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Tu n'as pas assez de coins.")
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
    weights = [20, 18, 15, 12, 10, 8, 5, 3]  # pondération
    reels = random.choices(symbols, weights=weights, k=3)
    result_str = " | ".join(reels)
    if reels[0] == reels[1] == reels[2]:
        if reels[0] == "7️⃣":
            mult = 20
        elif reels[0] == "💎":
            mult = 10
        elif reels[0] == "⭐":
            mult = 7
        elif reels[0] == "🔔":
            mult = 5
        else:
            mult = 3
        win = bet * mult
        user["coins"] += win - bet
        user["casino_wins"] += 1
        msg = f"🎰 {result_str}\n🎉 JACKPOT x{mult} ! Tu gagnes **{win:,}** 🪙 !"
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        win = bet
        user["coins"] += win - bet
        msg = f"🎰 {result_str}\n✅ Deux identiques ! Mise récupérée : **{bet:,}** 🪙."
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        msg = f"🎰 {result_str}\n❌ Perdu ! Tu perds **{bet:,}** 🪙."
    save_data(data)
    await ctx.send(msg)

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
    result = random.choice(["pile", "face"])
    icon = "🪙" if result == "pile" else "🌟"
    if result == choix:
        user["coins"] += bet
        user["casino_wins"] += 1
        msg = f"{icon} **{result.capitalize()}** ! Tu gagnes **{bet:,}** 🪙 !"
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        msg = f"{icon} **{result.capitalize()}** ! Tu perds **{bet:,}** 🪙."
    save_data(data)
    await ctx.send(msg)

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

    suits = "♠♥♦♣"
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    deck = [r+s for r in ranks for s in suits]
    random.shuffle(deck)

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    def show_hands(hide_dealer=True):
        p_val = hand_value(player)
        if hide_dealer:
            d_display = f"{dealer[0]} 🂠"
        else:
            d_display = " ".join(dealer) + f" ({hand_value(dealer)})"
        return (
            f"🃏 **Blackjack** — Mise : {bet:,} 🪙\n"
            f"Toi : {' '.join(player)} **({p_val})**\n"
            f"Croupier : {d_display}"
        )

    msg = await ctx.send(show_hands() + "\n\nTape `hit` pour tirer, `stand` pour rester.")

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
            return await ctx.send(show_hands(False) + "\n💥 **Bust !** Tu perds **{:,}** 🪙.".format(bet))
        await ctx.send(show_hands())

    # Croupier joue
    while hand_value(dealer) < 17:
        dealer.append(deck.pop())

    pv, dv = hand_value(player), hand_value(dealer)
    if dv > 21 or pv > dv:
        user["coins"] += bet
        user["casino_wins"] += 1
        result = f"🎉 Victoire ! Tu gagnes **{bet:,}** 🪙 !"
    elif pv == dv:
        result = "🤝 Égalité ! Mise remboursée."
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        result = f"❌ Défaite ! Tu perds **{bet:,}** 🪙."
    save_data(data)
    await ctx.send(show_hands(False) + f"\n{result}")

@bot.command(name="roulette")
async def roulette(ctx, mise: str = "0", choix: str = "rouge"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Usage : `%roulette <mise> <rouge|noir|pair|impair|0-36>`")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")
    num = random.randint(0, 36)
    rouges = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    color = "🔴 Rouge" if num in rouges else ("⚫ Noir" if num != 0 else "🟢 Zéro")
    win = False; mult = 1
    choix = choix.lower()
    if choix in ("rouge","red") and num in rouges: win=True; mult=2
    elif choix in ("noir","black") and num not in rouges and num!=0: win=True; mult=2
    elif choix in ("pair","even") and num%2==0 and num!=0: win=True; mult=2
    elif choix in ("impair","odd") and num%2!=0: win=True; mult=2
    else:
        try:
            n = int(choix)
            if n == num: win=True; mult=36
        except: pass

    if win:
        user["coins"] += bet * (mult - 1)
        user["casino_wins"] += 1
        msg = f"🎡 La bille tombe sur **{num}** ({color}) !\n🎉 Gagné ! +**{bet*(mult-1):,}** 🪙"
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        msg = f"🎡 La bille tombe sur **{num}** ({color}) !\n❌ Perdu ! -**{bet:,}** 🪙"
    save_data(data)
    await ctx.send(msg)

@bot.command(name="dice", aliases=["de"])
async def dice(ctx, mise: str = "0"):
    data = load_data()
    user = get_user(data, ctx.author.id)
    bet = parse_bet(user, mise)
    if not bet or bet < 10:
        return await ctx.send("❌ Usage : `%dice <mise>` — Tu dois faire plus de 3 avec deux dés.")
    if bet > user["coins"]:
        return await ctx.send("❌ Pas assez de coins.")
    d1, d2 = random.randint(1,6), random.randint(1,6)
    total = d1 + d2
    if total > 7:
        user["coins"] += bet
        user["casino_wins"] += 1
        msg = f"🎲 {d1} + {d2} = **{total}** ! 🎉 Tu gagnes **{bet:,}** 🪙 !"
    elif total == 7:
        msg = f"🎲 {d1} + {d2} = **{total}** ! 🤝 Égalité, mise remboursée."
    else:
        user["coins"] = max(0, user["coins"] - bet)
        user["casino_losses"] += 1
        msg = f"🎲 {d1} + {d2} = **{total}** ! ❌ Tu perds **{bet:,}** 🪙."
    save_data(data)
    await ctx.send(msg)

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
]

@bot.command(name="trivia")
async def trivia(ctx):
    q = random.choice(TRIVIA_QUESTIONS)
    reward = random.randint(50, 200)
    embed = discord.Embed(title="🧠 Trivia", description=q["q"], color=0x3498DB)
    choices_str = "\n".join(f"**{i+1}.** {c}" for i,c in enumerate(q["choices"]))
    embed.add_field(name="Choix", value=choices_str)
    embed.set_footer(text=f"Réponds avec le numéro ou le texte — Récompense : {reward} 🪙 — 20 secondes")
    await ctx.send(embed=embed)

    def check(m):
        if m.author != ctx.author or m.channel != ctx.channel:
            return False
        ans = m.content.strip().lower()
        try:
            idx = int(ans) - 1
            return 0 <= idx < len(q["choices"])
        except:
            return any(ans in c.lower() for c in q["choices"])

    try:
        resp = await bot.wait_for("message", check=check, timeout=20)
    except asyncio.TimeoutError:
        return await ctx.send(f"⏳ Temps écoulé ! La réponse était **{q['a'].title()}**.")

    ans = resp.content.strip().lower()
    try:
        idx = int(ans) - 1
        given = q["choices"][idx].lower()
    except:
        given = ans

    if q["a"].lower() in given or given in q["a"].lower():
        data = load_data()
        user = get_user(data, ctx.author.id)
        user["coins"] += reward
        xp_gain = 20
        user["xp"] += xp_gain
        save_data(data)
        await ctx.send(f"✅ Bonne réponse ! +**{reward}** 🪙 et +**{xp_gain}** XP !")
    else:
        await ctx.send(f"❌ Mauvaise réponse ! C'était **{q['a'].title()}**.")

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

    await ctx.send(f"⚔️ {target.mention}, {ctx.author.mention} te défie en Pierre-Feuille-Ciseaux pour **{bet:,}** 🪙 ! Acceptes-tu ? (oui/non)")

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
        await player.send(f"🎮 **RPS** — Choisis : `pierre`, `feuille` ou `ciseaux`")
        def dm_check(m): return m.author == player and isinstance(m.channel, discord.DMChannel) and m.content.lower() in choices_map
        try:
            r = await bot.wait_for("message", check=dm_check, timeout=30)
            return r.content.lower()
        except:
            return None

    await ctx.send("📩 Vérifiez vos DMs pour choisir !")
    c1 = await get_choice(ctx.author)
    c2 = await get_choice(target)
    if not c1 or not c2:
        return await ctx.send("⏳ L'un des joueurs n'a pas répondu à temps.")

    c1n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c1,c1)
    c2n = {"p":"pierre","f":"feuille","c":"ciseaux"}.get(c2,c2)
    e1, e2 = choices_map[c1], choices_map[c2]

    if c1n == c2n:
        result = "🤝 Égalité !"
    elif wins[c1n] == c2n:
        challenger["coins"] += bet; opponent["coins"] = max(0, opponent["coins"] - bet)
        challenger["casino_wins"] += 1
        result = f"🏆 {ctx.author.mention} gagne **{bet:,}** 🪙 !"
    else:
        opponent["coins"] += bet; challenger["coins"] = max(0, challenger["coins"] - bet)
        opponent["casino_wins"] += 1
        result = f"🏆 {target.mention} gagne **{bet:,}** 🪙 !"
    save_data(data)
    await ctx.send(f"{ctx.author.display_name} : {e1} vs {target.display_name} : {e2}\n{result}")

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

    await ctx.send(f"⚔️ {target.mention}, tu es défié par {ctx.author.mention} pour **{bet:,}** 🪙 ! (oui/non)")
    def check_a(m): return m.author == target and m.channel == ctx.channel and m.content.lower() in ("oui","non")
    try:
        r = await bot.wait_for("message", check=check_a, timeout=30)
    except asyncio.TimeoutError: return await ctx.send("⏳ Défi expiré.")
    if r.content.lower() == "non": return await ctx.send("❌ Défi refusé.")

    await ctx.send("🎲 Le duel commence ! Chacun lance un dé...")
    await asyncio.sleep(2)
    r1, r2 = random.randint(1,100), random.randint(1,100)
    while r1 == r2:
        r1, r2 = random.randint(1,100), random.randint(1,100)

    if r1 > r2:
        challenger["coins"] += bet; opponent["coins"] = max(0, opponent["coins"] - bet)
        result = f"🏆 {ctx.author.mention} (**{r1}**) bat {target.mention} (**{r2}**) ! +**{bet:,}** 🪙"
    else:
        opponent["coins"] += bet; challenger["coins"] = max(0, challenger["coins"] - bet)
        result = f"🏆 {target.mention} (**{r2}**) bat {ctx.author.mention} (**{r1}**) ! +**{bet:,}** 🪙"
    save_data(data)
    await ctx.send(result)

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
        out = ""
        for i in range(total):
            if i in revealed:
                out += "💣 " if i in mine_positions else "💎 "
            else:
                out += "⬛ "
            if (i+1) % 3 == 0: out += "\n"
        return out

    msg = await ctx.send(
        f"💣 **Mines** ({cases} mines) — Mise : {bet:,} 🪙\n{grid_display()}\n"
        f"Tape un numéro (1-9) pour révéler une case, ou `stop` pour encaisser.\nMultiplicateur actuel : x**{mult:.2f}**"
    )

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
            return await ctx.send(f"💥 MINE ! {grid_display()}\n❌ Tu perds **{bet:,}** 🪙.")
        safe = total - cases
        mult = round(1 + (len(revealed) / safe) * (cases * 0.8), 2)
        await ctx.send(f"{grid_display()}\n✅ Case sûre ! Multiplicateur : x**{mult:.2f}** — Continue ou `stop`")

    win = int(bet * mult)
    gain = win - bet
    user["coins"] += gain
    if gain >= 0: user["casino_wins"] += 1
    save_data(data)
    await ctx.send(f"🏁 {grid_display()}\n💰 Encaissé ! x{mult:.2f} → **{win:,}** 🪙 (+**{gain:,}**)")

@bot.command(name="course")
async def course(ctx):
    horses = ["🐴 Éclair", "🦄 Pégase", "🐎 Tornado", "🏇 Foudre"]
    embed = discord.Embed(title="🏇 Course de Chevaux", description="Pariez sur un cheval ! (1-4)", color=0xE67E22)
    for i, h in enumerate(horses):
        embed.add_field(name=f"{i+1}. {h}", value="Cotes : x3", inline=True)
    embed.set_footer(text="Réponds avec : <numéro> <mise> — ex: 2 500 — 30 secondes pour parier")
    await ctx.send(embed=embed)

    bets: dict[int, tuple] = {}

    def check(m):
        if m.channel != ctx.channel or m.author.bot: return False
        parts = m.content.strip().split()
        if len(parts) == 2:
            try: return 1 <= int(parts[0]) <= 4 and int(parts[1]) >= 10
            except: pass
        return False

    deadline = time.time() + 30
    await ctx.send("⏳ 30 secondes pour parier !")

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
            await ctx.send(f"❌ {resp.author.mention} n'a pas assez de coins."); continue
        bets[resp.author.id] = (horse_idx, bet_amt)
        await ctx.send(f"✅ {resp.author.mention} mise **{bet_amt}** 🪙 sur **{horses[horse_idx]}** !")
        save_data(data)

    if not bets:
        return await ctx.send("🏇 Aucun pari — course annulée.")

    await ctx.send("🏁 La course commence !")
    await asyncio.sleep(2)
    positions = list(range(4))
    random.shuffle(positions)
    winner_idx = positions[0]

    result_lines = [f"🏆 Gagnant : **{horses[winner_idx]}** !"]
    data = load_data()
    for uid, (hidx, bet_amt) in bets.items():
        user = get_user(data, uid)
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else str(uid)
        if hidx == winner_idx:
            win = bet_amt * 3
            user["coins"] += win - bet_amt
            user["casino_wins"] += 1
            result_lines.append(f"🎉 {name} : +**{win - bet_amt:,}** 🪙")
        else:
            user["coins"] = max(0, user["coins"] - bet_amt)
            user["casino_losses"] += 1
            result_lines.append(f"❌ {name} : -**{bet_amt:,}** 🪙")
    save_data(data)
    await ctx.send("\n".join(result_lines))

# ─── Shop ─────────────────────────────────────────────────────────────────────

@bot.command(name="shop", aliases=["magasin"])
async def shop(ctx):
    embed = discord.Embed(title="🛒 Shop", color=0x9B59B6)
    for key, item in SHOP_ITEMS.items():
        embed.add_field(
            name=f"{item['emoji']} {item['name']} — {item['price']:,} 🪙",
            value=f"{item['description']}\n`%buy {key}`",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="buy", aliases=["acheter"])
async def buy(ctx, item_key: str = ""):
    if item_key not in SHOP_ITEMS:
        return await ctx.send(f"❌ Item invalide. Utilise `%shop` pour voir les items disponibles.")
    item = SHOP_ITEMS[item_key]
    data = load_data()
    user = get_user(data, ctx.author.id)
    if user["coins"] < item["price"]:
        return await ctx.send(f"❌ Tu n'as pas assez de coins. (Besoin : {item['price']:,} 🪙, Tu as : {user['coins']:,} 🪙)")

    if item_key == "role_perso":
        await ctx.send(f"🎨 Quel nom veux-tu pour ton rôle ? (ex: `MegaGamer`)")
        def check_name(m): return m.author == ctx.author and m.channel == ctx.channel
        try:
            rn = await bot.wait_for("message", check=check_name, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("⏳ Temps écoulé.")
        await ctx.send(f"🎨 Quelle couleur ? (ex: `#FF5733` ou `rouge`, `bleu`, `vert`, `violet`, `orange`)")
        color_names = {"rouge":0xFF0000,"bleu":0x0000FF,"vert":0x00FF00,"violet":0x800080,"orange":0xFF8C00}
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
        await ctx.send(f"✅ Tu as acheté **{item['name']}** ! Utilise `%use {item_key}` pour l'activer.")

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
    item = SHOP_ITEMS.get(item_key)
    if item_key == "xp_boost_1h":
        user["xp_boost_until"] = now + 3600
        msg = "⚡ Boost XP x2 activé pour 1 heure !"
    elif item_key == "shield":
        user["shield"] = True
        msg = "🛡️ Bouclier activé ! Tu es protégé contre le prochain vol."
    elif item_key == "lucky_charm":
        user["lucky_charm_until"] = now + 86400
        msg = "🍀 Porte-bonheur activé pour 24h !"
    elif item_key == "daily_bonus":
        user["daily_bonus_x2"] = True
        msg = "🎁 Ton prochain %daily sera doublé !"
    else:
        msg = "❌ Cet item ne peut pas être utilisé manuellement."
    user["inventory"].remove(item_key)
    save_data(data)
    await ctx.send(msg)

# ─── Error handler ────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant. Tape `%help` pour l'aide.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Membre introuvable.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        await ctx.send(f"⚠️ Erreur : {error}")

# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("❌ La variable d'environnement DISCORD_TOKEN est manquante !")
    bot.run(TOKEN)
