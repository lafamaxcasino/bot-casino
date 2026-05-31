"""
╔══════════════════════════════════════════════════════╗
║         🎰  CASINO BOT  •  Version 2.0  🎰           ║
╠══════════════════════════════════════════════════════╣
║  XP & Niveaux   │  Shop & Inventaire                 ║
║  Rôles auto     │  Boosts XP                         ║
║  Casino complet │  SQLite                            ║
╠══════════════════════════════════════════════════════╣
║  COMMANDES                                           ║
║  /profil  /classement  /daily  /donner               ║
║  /shop  /acheter  /inventaire  /utiliser             ║
║  /slots  /coinflip  /blackjack  /dés  /roulette      ║
╚══════════════════════════════════════════════════════╝
"""

import discord
from discord.ext import commands
from discord import app_commands
import random, asyncio, aiosqlite
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════
#  CONFIG  —  modifie ici
# ══════════════════════════════════════════════════════
import os
TOKEN = os.environ.get("TOKEN")
DB_FILE      = "casino.db"

XP_MIN       = 15      # XP min par message
XP_MAX       = 25      # XP max par message
COOLDOWN_MSG = 60      # secondes entre deux gains d'XP
BASE_XP      = 100     # XP de base pour niveau 1
COINS_DEPART = 1000    # pièces au démarrage
DAILY_XP     = 250
DAILY_COINS  = 500

# Rôles attribués automatiquement à certains niveaux
# Crée ces rôles sur ton serveur avec exactement ces noms
ROLES_NIVEAUX = {
    5:  "🌱 Débutant du casino",
    10: "⚔️ Aventurier du casino",
    20: "🔥 Vétéran du casino",
    35: "💫 Expert du casino",
    50: "👑 Légende du casino",
}

# Catalogue du shop
SHOP_ITEMS = {
    "boost_xp_1h": {
        "nom":         "⚡ Boost XP 1h",
        "description": "Double ton XP pendant 1 heure",
        "prix":        500,
        "emoji":       "⚡",
        "duree":       3600,
        "type":        "boost",
    },
    "boost_xp_24h": {
        "nom":         "🚀 Boost XP 24h",
        "description": "Double ton XP pendant 24 heures",
        "prix":        2000,
        "emoji":       "🚀",
        "duree":       86400,
        "type":        "boost",
    },
    "shield": {
        "nom":         "🛡️ Bouclier",
        "description": "Protège de ta prochaine perte au casino",
        "prix":        750,
        "emoji":       "🛡️",
        "type":        "protection",
    },
    "lootbox": {
        "nom":         "📦 Loot Box",
        "description": "Ouvre pour gagner entre 100 et 5000 pièces aléatoirement",
        "prix":        300,
        "emoji":       "📦",
        "type":        "lootbox",
    },
    "multiplicateur": {
        "nom":         "✨ Multiplicateur ×2",
        "description": "Double ta prochaine mise gagnante au casino",
        "prix":        1000,
        "emoji":       "✨",
        "type":        "multiplicateur",
    },
}

# ══════════════════════════════════════════════════════
#  CASINO — SYMBOLES & CARTES
# ══════════════════════════════════════════════════════
SLOTS_SYMBOLES = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎"]
SLOTS_MULTI    = {
    ("💎","💎","💎"): 50,
    ("⭐","⭐","⭐"): 20,
    ("🍇","🍇","🍇"): 10,
    ("🍊","🍊","🍊"): 7,
    ("🍋","🍋","🍋"): 5,
    ("🍒","🍒","🍒"): 3,
}
CARTES_VALEUR   = {v: min(int(v) if v.isdigit() else 10, 10) for v in
                   ["2","3","4","5","6","7","8","9","10","J","Q","K"]}
CARTES_VALEUR["A"] = 11
CARTES_COULEURS = ["♠","♥","♦","♣"]
ROULETTE_ROUGE  = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ══════════════════════════════════════════════════════
#  BOT SETUP
# ══════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ══════════════════════════════════════════════════════
#  BASE DE DONNÉES (SQLite async)
# ══════════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid             INTEGER PRIMARY KEY,
                xp              INTEGER DEFAULT 0,
                niveau          INTEGER DEFAULT 0,
                coins           INTEGER DEFAULT ?,
                last_message    TEXT,
                last_daily      TEXT,
                messages_count  INTEGER DEFAULT 0,
                gains_casino    INTEGER DEFAULT 0,
                pertes_casino   INTEGER DEFAULT 0,
                boost_xp_until  TEXT,
                shield          INTEGER DEFAULT 0,
                multiplicateur  INTEGER DEFAULT 0,
                streak_daily    INTEGER DEFAULT 0
            )
        """, (COINS_DEPART,))
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventaire (
                uid     INTEGER,
                item_id TEXT,
                qte     INTEGER DEFAULT 1,
                PRIMARY KEY (uid, item_id)
            )
        """)
        await db.commit()

async def get_user(uid: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (uid) VALUES (?)", (uid,)
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE uid=?", (uid,)) as cur:
                row = await cur.fetchone()
        return dict(row)

async def update_user(uid: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [uid]
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"UPDATE users SET {cols} WHERE uid=?", vals)
        await db.commit()

async def get_inventaire(uid: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT item_id, qte FROM inventaire WHERE uid=?", (uid,)
        ) as cur:
            rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}

async def add_item(uid: int, item_id: str, qte: int = 1):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO inventaire (uid, item_id, qte) VALUES (?,?,?)
            ON CONFLICT(uid, item_id) DO UPDATE SET qte=qte+?
        """, (uid, item_id, qte, qte))
        await db.commit()

async def remove_item(uid: int, item_id: str) -> bool:
    inv = await get_inventaire(uid)
    if inv.get(item_id, 0) <= 0:
        return False
    async with aiosqlite.connect(DB_FILE) as db:
        if inv[item_id] == 1:
            await db.execute("DELETE FROM inventaire WHERE uid=? AND item_id=?", (uid, item_id))
        else:
            await db.execute(
                "UPDATE inventaire SET qte=qte-1 WHERE uid=? AND item_id=?", (uid, item_id)
            )
        await db.commit()
    return True

# ══════════════════════════════════════════════════════
#  XP HELPERS
# ══════════════════════════════════════════════════════
def xp_pour_niveau(n: int) -> int:
    return int(BASE_XP * (n ** 1.6))

def niveau_depuis_xp(xp: int) -> int:
    n = 0
    while xp >= xp_pour_niveau(n + 1):
        n += 1
    return n

def xp_barre(xp: int, niv: int) -> str:
    debut  = xp_pour_niveau(niv)
    fin    = xp_pour_niveau(niv + 1)
    prog   = xp - debut
    total  = fin - debut
    pct    = prog / total if total else 1
    filled = int(pct * 18)
    bar    = "█" * filled + "░" * (18 - filled)
    return f"`{bar}` **{prog:,}/{total:,}**"

def couleur_niveau(n: int) -> discord.Color:
    palettes = [
        0x95a5a6, 0x2ecc71, 0x3498db,
        0x9b59b6, 0xf1c40f, 0xe74c3c,
    ]
    return discord.Color(palettes[min(n // 5, len(palettes) - 1)])

def badge_niveau(n: int) -> str:
    if n < 5:   return "🪨 Novice"
    if n < 10:  return "🌱 Débutant du casino"
    if n < 20:  return "⚔️ Aventurier du casino"
    if n < 35:  return "🔥 Vétéran du casino"
    if n < 50:  return "💫 Expert du casino"
    return "👑 Légende du casino"

async def boost_actif(user: dict) -> bool:
    if not user["boost_xp_until"]:
        return False
    until = datetime.fromisoformat(user["boost_xp_until"])
    return datetime.utcnow() < until

# ══════════════════════════════════════════════════════
#  GESTION DES RÔLES
# ══════════════════════════════════════════════════════
async def attribuer_roles(member: discord.Member, nouveau_niveau: int):
    for niveau_requis, nom_role in ROLES_NIVEAUX.items():
        role = discord.utils.get(member.guild.roles, name=nom_role)
        if role is None:
            continue
        if nouveau_niveau >= niveau_requis:
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Niveau {nouveau_niveau} atteint")
                except discord.Forbidden:
                    pass
        else:
            if role in member.roles:
                try:
                    await member.remove_roles(role, reason="Niveau insuffisant")
                except discord.Forbidden:
                    pass

# ══════════════════════════════════════════════════════
#  ÉVÉNEMENTS
# ══════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await init_db()
    await tree.sync()
    print(f"✅  {bot.user} connecté | {len(bot.guilds)} serveur(s)")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.playing, name="🎰 Casino & XP • /help"
    ))

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    await bot.process_commands(message)

    uid  = message.author.id
    user = await get_user(uid)
    now  = datetime.utcnow()

    # Cooldown XP
    if user["last_message"]:
        last_dt = datetime.fromisoformat(user["last_message"])
        if (now - last_dt).total_seconds() < COOLDOWN_MSG:
            return

    # Gain XP (boosté ou non)
    gain = random.randint(XP_MIN, XP_MAX)
    if await boost_actif(user):
        gain *= 2

    new_xp     = user["xp"] + gain
    ancien_niv = user["niveau"]
    nouveau_niv = niveau_depuis_xp(new_xp)

    await update_user(
        uid,
        xp=new_xp,
        niveau=nouveau_niv,
        last_message=now.isoformat(),
        messages_count=user["messages_count"] + 1,
    )

    # Level UP
    if nouveau_niv > ancien_niv:
        bonus = nouveau_niv * 150
        await update_user(uid, coins=user["coins"] + bonus)
        await attribuer_roles(message.author, nouveau_niv)

        embed = discord.Embed(
            title="🎉  Level UP !",
            description=(
                f"**{message.author.display_name}** passe au **niveau {nouveau_niv}** !\n"
                f"{badge_niveau(nouveau_niv)}\n\n"
                f"💰 Bonus : **+{bonus:,} pièces**"
            ),
            color=couleur_niveau(nouveau_niv),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)

        # Rôle débloqué ?
        if nouveau_niv in ROLES_NIVEAUX:
            embed.add_field(
                name="🏅 Rôle débloqué !",
                value=f"**{ROLES_NIVEAUX[nouveau_niv]}**",
                inline=False
            )
        await message.channel.send(embed=embed)

# ══════════════════════════════════════════════════════
#  /profil
# ══════════════════════════════════════════════════════
@tree.command(name="profil", description="📊 Voir ton profil XP & casino")
@app_commands.describe(membre="Membre à inspecter (optionnel)")
async def profil(interaction: discord.Interaction, membre: discord.Member = None):
    cible = membre or interaction.user
    user  = await get_user(cible.id)
    inv   = await get_inventaire(cible.id)
    niv   = user["niveau"]
    xp    = user["xp"]

    embed = discord.Embed(
        title=f"📊  Profil — {cible.display_name}",
        color=couleur_niveau(niv)
    )
    embed.set_thumbnail(url=cible.display_avatar.url)

    # Statut boost
    boost_str = "❌ Inactif"
    if user["boost_xp_until"]:
        until = datetime.fromisoformat(user["boost_xp_until"])
        if datetime.utcnow() < until:
            reste = until - datetime.utcnow()
            h, m  = divmod(int(reste.total_seconds()) // 60, 60)
            boost_str = f"⚡ Actif encore {h}h{m:02d}m"

    embed.add_field(name="⭐ Niveau",      value=f"**{niv}** — {badge_niveau(niv)}",  inline=True)
    embed.add_field(name="✨ XP total",    value=f"**{xp:,}**",                        inline=True)
    embed.add_field(name="💰 Pièces",      value=f"**{user['coins']:,}**",              inline=True)
    embed.add_field(name="📈 Progression", value=xp_barre(xp, niv),                   inline=False)
    embed.add_field(name="⚡ Boost XP",    value=boost_str,                            inline=True)
    embed.add_field(name="🔥 Streak",      value=f"**{user['streak_daily']}** jours",  inline=True)
    embed.add_field(name="💬 Messages",    value=f"{user['messages_count']:,}",         inline=True)
    embed.add_field(name="🎰 Gains",       value=f"+{user['gains_casino']:,} 💰",      inline=True)
    embed.add_field(name="💸 Pertes",      value=f"-{user['pertes_casino']:,} 💰",     inline=True)

    # Inventaire résumé
    if inv:
        inv_txt = "  ".join(
            f"{SHOP_ITEMS[k]['emoji']} ×{v}"
            for k, v in inv.items() if k in SHOP_ITEMS
        )
        embed.add_field(name="🎒 Inventaire", value=inv_txt or "Vide", inline=False)

    embed.set_footer(text=f"Prochaine récompense daily : /daily")
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /classement
# ══════════════════════════════════════════════════════
@tree.command(name="classement", description="🏆 Top 10 du serveur")
@app_commands.choices(tri=[
    app_commands.Choice(name="XP",     value="xp"),
    app_commands.Choice(name="Pièces", value="coins"),
    app_commands.Choice(name="Gains casino", value="gains_casino"),
])
async def classement(interaction: discord.Interaction, tri: str = "xp"):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            f"SELECT uid, xp, niveau, coins, gains_casino FROM users ORDER BY {tri} DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()

    medals = ["🥇","🥈","🥉"] + ["🏅"] * 7
    titres = {"xp": "XP", "coins": "Pièces 💰", "gains_casino": "Gains Casino 🎰"}
    desc = ""
    for i, (uid, xp, niv, coins, gains) in enumerate(rows):
        member = interaction.guild.get_member(uid)
        name   = member.display_name if member else f"Joueur #{uid}"
        val    = {"xp": f"{xp:,} XP", "coins": f"{coins:,} 💰", "gains_casino": f"+{gains:,} 💰"}[tri]
        desc  += f"{medals[i]} **{name}** — Niv.{niv} | {val}\n"

    embed = discord.Embed(
        title=f"🏆 Classement — {titres[tri]}",
        description=desc or "Aucun joueur.",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /daily
# ══════════════════════════════════════════════════════
@tree.command(name="daily", description="🎁 Récompense quotidienne (XP + pièces + streak)")
async def daily(interaction: discord.Interaction):
    uid  = interaction.user.id
    user = await get_user(uid)
    now  = datetime.utcnow()

    if user["last_daily"]:
        last_dt  = datetime.fromisoformat(user["last_daily"])
        cooldown = timedelta(hours=24)
        reste    = cooldown - (now - last_dt)
        if reste.total_seconds() > 0:
            h, m = divmod(int(reste.total_seconds()) // 60, 60)
            embed = discord.Embed(
                title="⏳ Patience !",
                description=f"Ta prochaine récompense est dans **{h}h {m}min**.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    # Streak (si moins de 48h depuis le dernier daily)
    streak = user["streak_daily"]
    if user["last_daily"]:
        last_dt = datetime.fromisoformat(user["last_daily"])
        if (now - last_dt).total_seconds() < 172800:
            streak += 1
        else:
            streak = 1
    else:
        streak = 1

    # Bonus streak
    bonus_streak = min(streak * 50, 1000)
    xp_gain      = DAILY_XP + bonus_streak // 5
    coins_gain   = DAILY_COINS + bonus_streak

    ancien_niv  = user["niveau"]
    new_xp      = user["xp"] + xp_gain
    nouveau_niv = niveau_depuis_xp(new_xp)

    await update_user(
        uid,
        xp=new_xp,
        niveau=nouveau_niv,
        coins=user["coins"] + coins_gain,
        last_daily=now.isoformat(),
        streak_daily=streak,
    )

    embed = discord.Embed(
        title="🎁  Daily Reward !",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="✨ XP gagné",    value=f"+{xp_gain:,}",    inline=True)
    embed.add_field(name="💰 Pièces",      value=f"+{coins_gain:,}", inline=True)
    embed.add_field(name="🔥 Streak",      value=f"**{streak}** jours 🔥", inline=True)
    if bonus_streak:
        embed.add_field(name="🎁 Bonus streak", value=f"+{bonus_streak:,} pièces !", inline=False)
    if nouveau_niv > ancien_niv:
        embed.add_field(name="🎉 Level UP !", value=f"Tu passes au **niveau {nouveau_niv}** !", inline=False)

    await interaction.response.send_message(embed=embed)
    if nouveau_niv > ancien_niv:
        await attribuer_roles(interaction.user, nouveau_niv)

# ══════════════════════════════════════════════════════
#  /donner
# ══════════════════════════════════════════════════════
@tree.command(name="donner", description="💸 Donner des pièces à un joueur")
@app_commands.describe(membre="Destinataire", montant="Nombre de pièces")
async def donner(interaction: discord.Interaction, membre: discord.Member, montant: int):
    if membre.bot or membre == interaction.user:
        await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
        return
    if montant <= 0:
        await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
        return
    uid   = interaction.user.id
    donor = await get_user(uid)
    if donor["coins"] < montant:
        await interaction.response.send_message(
            f"❌ Tu n'as que **{donor['coins']:,}** pièces.", ephemeral=True
        )
        return
    recvr = await get_user(membre.id)
    await update_user(uid,       coins=donor["coins"] - montant)
    await update_user(membre.id, coins=recvr["coins"] + montant)

    embed = discord.Embed(
        title="💸 Transfert effectué",
        description=(
            f"**{interaction.user.display_name}** a envoyé **{montant:,} 💰** "
            f"à **{membre.display_name}** !"
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /shop
# ══════════════════════════════════════════════════════
@tree.command(name="shop", description="🛍️ Voir le catalogue de la boutique")
async def shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛍️  Boutique",
        description="Utilise `/acheter <id>` pour acheter un article.",
        color=discord.Color.blurple()
    )
    for item_id, item in SHOP_ITEMS.items():
        embed.add_field(
            name=f"{item['emoji']} {item['nom']} — **{item['prix']:,} 💰**",
            value=f"*{item['description']}*\n`ID : {item_id}`",
            inline=False
        )
    embed.set_footer(text="Les objets s'utilisent avec /utiliser")
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /acheter
# ══════════════════════════════════════════════════════
@tree.command(name="acheter", description="🛒 Acheter un objet du shop")
@app_commands.describe(item_id="ID de l'objet (visible dans /shop)")
async def acheter(interaction: discord.Interaction, item_id: str):
    if item_id not in SHOP_ITEMS:
        await interaction.response.send_message("❌ Objet introuvable. Consulte `/shop`.", ephemeral=True)
        return
    item = SHOP_ITEMS[item_id]
    uid  = interaction.user.id
    user = await get_user(uid)

    if user["coins"] < item["prix"]:
        await interaction.response.send_message(
            f"❌ Il te manque **{item['prix'] - user['coins']:,}** pièces !", ephemeral=True
        )
        return

    await update_user(uid, coins=user["coins"] - item["prix"])
    await add_item(uid, item_id)

    embed = discord.Embed(
        title="✅  Achat réussi !",
        description=f"Tu as acheté **{item['nom']}** pour **{item['prix']:,} 💰**.",
        color=discord.Color.green()
    )
    embed.add_field(name="💡 Utilisation", value="Utilise `/utiliser` pour activer cet objet.", inline=False)
    embed.set_footer(text=f"Solde restant : {user['coins'] - item['prix']:,} 💰")
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /inventaire
# ══════════════════════════════════════════════════════
@tree.command(name="inventaire", description="🎒 Voir ton inventaire")
async def inventaire(interaction: discord.Interaction):
    uid = interaction.user.id
    inv = await get_inventaire(uid)

    embed = discord.Embed(title="🎒  Inventaire", color=discord.Color.blurple())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    if not inv:
        embed.description = "Ton inventaire est vide ! Visite le `/shop`."
    else:
        for item_id, qte in inv.items():
            item = SHOP_ITEMS.get(item_id)
            if item:
                embed.add_field(
                    name=f"{item['emoji']} {item['nom']} ×{qte}",
                    value=f"*{item['description']}*\n`/utiliser {item_id}`",
                    inline=True
                )
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /utiliser
# ══════════════════════════════════════════════════════
@tree.command(name="utiliser", description="🔮 Utiliser un objet de ton inventaire")
@app_commands.describe(item_id="ID de l'objet à utiliser")
async def utiliser(interaction: discord.Interaction, item_id: str):
    if item_id not in SHOP_ITEMS:
        await interaction.response.send_message("❌ Objet inconnu.", ephemeral=True)
        return

    uid  = interaction.user.id
    item = SHOP_ITEMS[item_id]
    ok   = await remove_item(uid, item_id)

    if not ok:
        await interaction.response.send_message(
            f"❌ Tu ne possèdes pas **{item['nom']}**. Achète-le dans `/shop` !", ephemeral=True
        )
        return

    user = await get_user(uid)
    msg  = ""

    if item["type"] == "boost":
        until = datetime.utcnow() + timedelta(seconds=item["duree"])
        await update_user(uid, boost_xp_until=until.isoformat())
        h = item["duree"] // 3600
        msg = f"⚡ Boost XP ×2 activé pour **{h} heure(s)** !"

    elif item["type"] == "protection":
        await update_user(uid, shield=1)
        msg = "🛡️ Bouclier activé ! Ta prochaine perte au casino sera annulée."

    elif item["type"] == "multiplicateur":
        await update_user(uid, multiplicateur=1)
        msg = "✨ Multiplicateur activé ! Ta prochaine victoire au casino sera doublée !"

    elif item["type"] == "lootbox":
        gain = random.choices(
            [random.randint(100,500), random.randint(500,2000), random.randint(2000,5000)],
            weights=[60, 30, 10]
        )[0]
        await update_user(uid, coins=user["coins"] + gain)
        msg = f"📦 Tu as ouvert la Loot Box et gagné **{gain:,} 💰** !"

    embed = discord.Embed(title=f"{item['emoji']} Objet utilisé !", description=msg, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  HELPER CASINO  (shield / multiplicateur)
# ══════════════════════════════════════════════════════
async def appliquer_resultat_casino(uid: int, gain_brut: int, mise: int) -> tuple[int, str]:
    """Retourne (gain_net, note_speciale)."""
    user = await get_user(uid)
    note = ""

    if gain_brut > 0 and user["multiplicateur"]:
        gain_brut *= 2
        await update_user(uid, multiplicateur=0)
        note = "✨ **Multiplicateur ×2 appliqué !**\n"

    if gain_brut < 0 and user["shield"]:
        gain_brut = 0
        await update_user(uid, shield=0)
        note = "🛡️ **Bouclier activé — perte annulée !**\n"

    return gain_brut, note

# ══════════════════════════════════════════════════════
#  /slots
# ══════════════════════════════════════════════════════
@tree.command(name="slots", description="🎰 Machine à sous")
@app_commands.describe(mise="Montant à miser")
async def slots(interaction: discord.Interaction, mise: int):
    uid  = interaction.user.id
    user = await get_user(uid)
    if mise <= 0 or user["coins"] < mise:
        await interaction.response.send_message("❌ Mise invalide ou solde insuffisant.", ephemeral=True)
        return

    rouleaux = [random.choice(SLOTS_SYMBOLES) for _ in range(3)]
    r1, r2, r3 = rouleaux
    combo = tuple(rouleaux)

    multi = SLOTS_MULTI.get(combo, 0)
    if multi == 0 and len(set(rouleaux)) == 2:
        multi = 0.5   # paire

    xp_gain = random.randint(5, 20)

    if multi > 0:
        gain_brut = int(mise * multi)
        gain_brut, note = await appliquer_resultat_casino(uid, gain_brut, mise)
        user = await get_user(uid)
        await update_user(uid,
            coins=user["coins"] + gain_brut,
            gains_casino=user["gains_casino"] + gain_brut,
            xp=user["xp"] + xp_gain,
            niveau=niveau_depuis_xp(user["xp"] + xp_gain),
        )
        resultat = f"{note}🎉 **+{gain_brut:,} pièces** (×{multi}) !"
        couleur  = discord.Color.green()
    else:
        gain_brut, note = await appliquer_resultat_casino(uid, -mise, mise)
        user = await get_user(uid)
        perte = abs(gain_brut)
        await update_user(uid,
            coins=user["coins"] - perte,
            pertes_casino=user["pertes_casino"] + perte,
            xp=user["xp"] + xp_gain,
            niveau=niveau_depuis_xp(user["xp"] + xp_gain),
        )
        resultat = f"{note}💸 **-{perte:,} pièces**. Pas de chance !"
        couleur  = discord.Color.red() if perte else discord.Color.orange()

    user = await get_user(uid)
    embed = discord.Embed(title="🎰  Machine à Sous", color=couleur)
    embed.add_field(name="Rouleaux", value=f"╔ {r1} ║ {r2} ║ {r3} ╗", inline=False)
    embed.add_field(name="Résultat", value=resultat, inline=False)
    embed.add_field(name="💰 Solde", value=f"{user['coins']:,} pièces", inline=True)
    embed.add_field(name="✨ XP +",  value=str(xp_gain),               inline=True)
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /coinflip
# ══════════════════════════════════════════════════════
@tree.command(name="coinflip", description="🪙 Pile ou face")
@app_commands.describe(mise="Montant à miser", choix="pile ou face")
@app_commands.choices(choix=[
    app_commands.Choice(name="Pile", value="pile"),
    app_commands.Choice(name="Face", value="face"),
])
async def coinflip(interaction: discord.Interaction, mise: int, choix: str):
    uid  = interaction.user.id
    user = await get_user(uid)
    if mise <= 0 or user["coins"] < mise:
        await interaction.response.send_message("❌ Mise invalide ou solde insuffisant.", ephemeral=True)
        return

    resultat = random.choice(["pile", "face"])
    symbole  = "🪙" if resultat == "pile" else "🌕"
    xp_gain  = random.randint(3, 10)

    if choix == resultat:
        gain_brut, note = await appliquer_resultat_casino(uid, mise, mise)
        user = await get_user(uid)
        await update_user(uid,
            coins=user["coins"] + gain_brut,
            gains_casino=user["gains_casino"] + gain_brut,
            xp=user["xp"] + xp_gain,
            niveau=niveau_depuis_xp(user["xp"] + xp_gain),
        )
        msg, c = f"{note}**{symbole} {resultat.capitalize()}** — **+{gain_brut:,} pièces** !", discord.Color.green()
    else:
        gain_brut, note = await appliquer_resultat_casino(uid, -mise, mise)
        user = await get_user(uid)
        perte = abs(gain_brut)
        await update_user(uid,
            coins=user["coins"] - perte,
            pertes_casino=user["pertes_casino"] + perte,
            xp=user["xp"] + xp_gain,
            niveau=niveau_depuis_xp(user["xp"] + xp_gain),
        )
        msg, c = f"{note}**{symbole} {resultat.capitalize()}** — **-{perte:,} pièces**.", discord.Color.red()

    user = await get_user(uid)
    embed = discord.Embed(title="🪙  Coin Flip", description=msg, color=c)
    embed.add_field(name="Ton choix",  value=choix.capitalize(),       inline=True)
    embed.add_field(name="💰 Solde",   value=f"{user['coins']:,} 💰",  inline=True)
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /roulette
# ══════════════════════════════════════════════════════
@tree.command(name="roulette", description="🎡 Joue à la roulette")
@app_commands.describe(
    mise="Montant à miser",
    pari="rouge, noir, pair, impair, ou un nombre 0-36"
)
async def roulette(interaction: discord.Interaction, mise: int, pari: str):
    uid  = interaction.user.id
    user = await get_user(uid)
    if mise <= 0 or user["coins"] < mise:
        await interaction.response.send_message("❌ Mise invalide ou solde insuffisant.", ephemeral=True)
        return

    numero  = random.randint(0, 36)
    is_rouge = numero in ROULETTE_ROUGE
    couleur_num = "🔴" if is_rouge else ("⚫" if numero > 0 else "🟢")
    pari = pari.lower().strip()

    gain = 0
    valide = True
    if pari == "rouge":
        if is_rouge: gain = mise
        else: gain = -mise
    elif pari == "noir":
        if not is_rouge and numero != 0: gain = mise
        else: gain = -mise
    elif pari == "pair":
        if numero > 0 and numero % 2 == 0: gain = mise
        else: gain = -mise
    elif pari == "impair":
        if numero % 2 == 1: gain = mise
        else: gain = -mise
    elif pari.isdigit() and 0 <= int(pari) <= 36:
        if int(pari) == numero: gain = mise * 35
        else: gain = -mise
    else:
        valide = False

    if not valide:
        await interaction.response.send_message(
            "❌ Pari invalide. Exemples : `rouge`, `noir`, `pair`, `impair`, `17`", ephemeral=True
        )
        return

    xp_gain   = random.randint(5, 20)
    gain_brut, note = await appliquer_resultat_casino(uid, gain, mise)
    user = await get_user(uid)

    if gain_brut > 0:
        await update_user(uid, coins=user["coins"]+gain_brut, gains_casino=user["gains_casino"]+gain_brut,
                          xp=user["xp"]+xp_gain, niveau=niveau_depuis_xp(user["xp"]+xp_gain))
        resultat = f"{note}🎉 **+{gain_brut:,} pièces** !"
        c = discord.Color.green()
    elif gain_brut < 0:
        perte = abs(gain_brut)
        await update_user(uid, coins=user["coins"]-perte, pertes_casino=user["pertes_casino"]+perte,
                          xp=user["xp"]+xp_gain, niveau=niveau_depuis_xp(user["xp"]+xp_gain))
        resultat = f"{note}💸 **-{perte:,} pièces**."
        c = discord.Color.red()
    else:
        await update_user(uid, xp=user["xp"]+xp_gain, niveau=niveau_depuis_xp(user["xp"]+xp_gain))
        resultat = f"{note}🛡️ Perte annulée !"
        c = discord.Color.orange()

    user = await get_user(uid)
    embed = discord.Embed(title="🎡  Roulette", color=c)
    embed.add_field(name="Numéro",   value=f"{couleur_num} **{numero}**",   inline=True)
    embed.add_field(name="Ton pari", value=pari,                            inline=True)
    embed.add_field(name="Résultat", value=resultat,                        inline=False)
    embed.add_field(name="💰 Solde", value=f"{user['coins']:,} pièces",     inline=True)
    embed.add_field(name="✨ XP +",  value=str(xp_gain),                    inline=True)
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  /blackjack
# ══════════════════════════════════════════════════════
def pioche():
    val = random.choice(list(CARTES_VALEUR.keys()))
    sym = random.choice(CARTES_COULEURS)
    return (val, sym, CARTES_VALEUR[val])

def total_main(main):
    total = sum(c[2] for c in main)
    aces  = sum(1 for c in main if c[0] == "A")
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total

def affiche_main(main, masque=False):
    if masque:
        return f"`{main[0][0]}{main[0][1]}` `??`"
    return " ".join(f"`{c[0]}{c[1]}`" for c in main)

@tree.command(name="blackjack", description="🃏 Blackjack contre le croupier")
@app_commands.describe(mise="Montant à miser")
async def blackjack(interaction: discord.Interaction, mise: int):
    uid  = interaction.user.id
    user = await get_user(uid)
    if mise <= 0 or user["coins"] < mise:
        await interaction.response.send_message("❌ Mise invalide ou solde insuffisant.", ephemeral=True)
        return

    mj  = [pioche(), pioche()]
    mb  = [pioche(), pioche()]

    def make_embed(fin=False, msg_fin="", couleur=discord.Color.blurple()):
        e = discord.Embed(title="🃏  Blackjack", color=couleur)
        e.add_field(name=f"🧑 {interaction.user.display_name} ({total_main(mj)})",
                    value=affiche_main(mj), inline=False)
        e.add_field(name=f"🤖 Croupier ({total_main(mb) if fin else '?'})",
                    value=affiche_main(mb, masque=not fin), inline=False)
        if msg_fin:
            e.add_field(name="Résultat", value=msg_fin, inline=False)
        e.set_footer(text=f"Mise : {mise:,} 💰 | Solde : {user['coins']:,} 💰")
        return e

    # Blackjack naturel
    if total_main(mj) == 21:
        gain_brut = int(mise * 1.5)
        gain_brut, note = await appliquer_resultat_casino(uid, gain_brut, mise)
        user = await get_user(uid)
        await update_user(uid, coins=user["coins"]+gain_brut, gains_casino=user["gains_casino"]+gain_brut,
                          xp=user["xp"]+30, niveau=niveau_depuis_xp(user["xp"]+30))
        await interaction.response.send_message(
            embed=make_embed(True, f"{note}🃏 **BLACKJACK ! +{gain_brut:,} pièces** !", discord.Color.gold())
        )
        return

    view = BlackjackView(interaction, mj, mb, mise, make_embed)
    await interaction.response.send_message(embed=make_embed(), view=view)


class BlackjackView(discord.ui.View):
    def __init__(self, interaction, mj, mb, mise, make_embed):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.mj          = mj
        self.mb          = mb
        self.mise        = mise
        self.make_embed  = make_embed

    async def _fin(self, inter: discord.Interaction, msg: str, gain_net: int, c: discord.Color):
        uid  = inter.user.id
        user = await get_user(uid)
        xp_g = random.randint(5, 25)

        if gain_net > 0:
            gain_net, note = await appliquer_resultat_casino(uid, gain_net, self.mise)
            user = await get_user(uid)
            msg  = note + msg
            await update_user(uid, coins=user["coins"]+gain_net, gains_casino=user["gains_casino"]+gain_net,
                               xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))
        elif gain_net < 0:
            gain_net, note = await appliquer_resultat_casino(uid, gain_net, self.mise)
            user = await get_user(uid)
            msg  = note + msg
            perte = abs(gain_net)
            await update_user(uid, coins=user["coins"]-perte, pertes_casino=user["pertes_casino"]+perte,
                               xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))
            if gain_net == 0:
                c = discord.Color.orange()
        else:
            await update_user(uid, xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))

        self.stop()
        for child in self.children: child.disabled = True
        embed = self.make_embed(fin=True, msg_fin=msg, couleur=c)
        await inter.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Tirer 🃏", style=discord.ButtonStyle.green)
    async def tirer(self, inter: discord.Interaction, btn):
        if inter.user != self.interaction.user: return
        self.mj.append(pioche())
        score = total_main(self.mj)
        if score > 21:
            await self._fin(inter, f"💥 Bust ! ({score}) — **-{self.mise:,} pièces**", -self.mise, discord.Color.red())
        elif score == 21:
            await self.rester.callback(inter)
        else:
            await inter.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="Rester 🛑", style=discord.ButtonStyle.red)
    async def rester(self, inter: discord.Interaction, btn=None):
        if inter.user != self.interaction.user: return
        while total_main(self.mb) < 17:
            self.mb.append(pioche())
        pj, pb = total_main(self.mj), total_main(self.mb)
        if pb > 21 or pj > pb:
            await self._fin(inter, f"🏆 Victoire ! ({pj} vs {pb}) — **+{self.mise:,}**", self.mise, discord.Color.green())
        elif pj == pb:
            await self._fin(inter, f"🤝 Égalité ! ({pj}) — Mise remboursée.", 0, discord.Color.greyple())
        else:
            await self._fin(inter, f"😔 Défaite ({pj} vs {pb}) — **-{self.mise:,}**", -self.mise, discord.Color.red())

    @discord.ui.button(label="Doubler ×2", style=discord.ButtonStyle.blurple)
    async def doubler(self, inter: discord.Interaction, btn):
        if inter.user != self.interaction.user: return
        uid  = inter.user.id
        user = await get_user(uid)
        if user["coins"] < self.mise:
            await inter.response.send_message("❌ Plus assez de pièces pour doubler.", ephemeral=True)
            return
        self.mise *= 2
        self.mj.append(pioche())
        score = total_main(self.mj)
        btn.disabled = True
        if score > 21:
            await self._fin(inter, f"💥 Bust ! ({score}) — **-{self.mise:,} pièces**", -self.mise, discord.Color.red())
        else:
            await self.rester.callback(inter)

# ══════════════════════════════════════════════════════
#  /dés
# ══════════════════════════════════════════════════════
@tree.command(name="dés", description="🎲 Lancer de dés contre le bot")
@app_commands.describe(mise="Montant à miser")
async def des(interaction: discord.Interaction, mise: int):
    uid  = interaction.user.id
    user = await get_user(uid)
    if mise <= 0 or user["coins"] < mise:
        await interaction.response.send_message("❌ Mise invalide ou solde insuffisant.", ephemeral=True)
        return

    dj = (random.randint(1,6), random.randint(1,6))
    db = (random.randint(1,6), random.randint(1,6))
    sj, sb = sum(dj), sum(db)
    faces = ["","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
    xp_g  = random.randint(3, 12)

    if sj > sb:
        gain_brut, note = await appliquer_resultat_casino(uid, mise, mise)
        user = await get_user(uid)
        await update_user(uid, coins=user["coins"]+gain_brut, gains_casino=user["gains_casino"]+gain_brut,
                          xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))
        msg, c = f"{note}🏆 Tu gagnes **+{gain_brut:,} pièces** !", discord.Color.green()
    elif sj < sb:
        gain_brut, note = await appliquer_resultat_casino(uid, -mise, mise)
        user = await get_user(uid)
        perte = abs(gain_brut)
        await update_user(uid, coins=user["coins"]-perte, pertes_casino=user["pertes_casino"]+perte,
                          xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))
        msg, c = f"{note}😔 Tu perds **-{perte:,} pièces**.", discord.Color.red()
    else:
        await update_user(uid, xp=user["xp"]+xp_g, niveau=niveau_depuis_xp(user["xp"]+xp_g))
        msg, c = "🤝 Égalité ! Mise remboursée.", discord.Color.greyple()

    user = await get_user(uid)
    embed = discord.Embed(title="🎲  Lancer de Dés", color=c)
    embed.add_field(name=f"🧑 {interaction.user.display_name}",
                    value=f"{faces[dj[0]]} {faces[dj[1]]} = **{sj}**", inline=True)
    embed.add_field(name="🤖 Croupier",
                    value=f"{faces[db[0]]} {faces[db[1]]} = **{sb}**", inline=True)
    embed.add_field(name="Résultat", value=msg, inline=False)
    embed.set_footer(text=f"Solde : {user['coins']:,} 💰  •  XP +{xp_g}")
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════
#  MINI-JEU : /devinombre  — Devine un nombre
# ══════════════════════════════════════════════════════
# Cooldown global : un seul /devinombre par utilisateur à la fois
_devine_actif: set[int] = set()

@tree.command(name="devinombre", description="🔢 Devine le nombre entre 1 et 100 en 5 essais — sans mise !")
async def devinombre(interaction: discord.Interaction):
    uid = interaction.user.id
    if uid in _devine_actif:
        await interaction.response.send_message("⏳ Tu as déjà une partie en cours !", ephemeral=True)
        return
    _devine_actif.add(uid)

    secret   = random.randint(1, 100)
    essais   = 5
    reward   = random.randint(200, 600)
    xp_gain  = 40
    tentatives_restantes = essais

    embed = discord.Embed(
        title="🔢  Devine le nombre !",
        description=(
            f"J'ai choisi un nombre entre **1 et 100**.\n"
            f"Tu as **{essais} essais** pour le trouver.\n"
            f"💰 Récompense : **{reward:,} pièces** + **{xp_gain} XP**\n\n"
            f"Tape un nombre dans le chat !"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Essais restants : {tentatives_restantes}/5")
    await interaction.response.send_message(embed=embed)

    def check(m: discord.Message):
        return m.author.id == uid and m.channel == interaction.channel and m.content.isdigit()

    while tentatives_restantes > 0:
        try:
            msg = await bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            _devine_actif.discard(uid)
            await interaction.followup.send("⌛ Temps écoulé ! Partie annulée.")
            return

        guess = int(msg.content)
        tentatives_restantes -= 1

        if guess == secret:
            user = await get_user(uid)
            await update_user(uid,
                coins=user["coins"] + reward,
                xp=user["xp"] + xp_gain,
                niveau=niveau_depuis_xp(user["xp"] + xp_gain),
                gains_casino=user["gains_casino"] + reward,
            )
            _devine_actif.discard(uid)
            win = discord.Embed(
                title="🎉 Bravo !",
                description=(
                    f"**{interaction.user.display_name}** a trouvé **{secret}** en "
                    f"{essais - tentatives_restantes} essai(s) !\n"
                    f"💰 +**{reward:,} pièces** | ✨ +{xp_gain} XP"
                ),
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=win)
            return
        else:
            hint = "📈 Plus grand !" if guess < secret else "📉 Plus petit !"
            if tentatives_restantes == 0:
                break
            hint_embed = discord.Embed(
                description=f"{hint} ({tentatives_restantes} essai(s) restant(s))",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=hint_embed)

    _devine_actif.discard(uid)
    lose = discord.Embed(
        title="😔 Perdu !",
        description=f"Le nombre était **{secret}**. Retente ta chance !",
        color=discord.Color.red()
    )
    await interaction.followup.send(embed=lose)


# ══════════════════════════════════════════════════════
#  MINI-JEU : /rapidfire  — QCM chrono (boutons)
# ══════════════════════════════════════════════════════
QUESTIONS_RAPIDFIRE = [
    {"q": "Combien font 7 × 8 ?",           "rep": "56",       "choix": ["42","56","63","72"]},
    {"q": "Quelle est la capitale de l'Espagne ?", "rep": "Madrid", "choix": ["Barcelone","Madrid","Lisbonne","Séville"]},
    {"q": "Combien de côtés a un hexagone ?","rep": "6",        "choix": ["5","6","7","8"]},
    {"q": "Quel est le plus grand océan ?",  "rep": "Pacifique","choix": ["Atlantique","Indien","Arctique","Pacifique"]},
    {"q": "Combien font 15² ?",              "rep": "225",      "choix": ["180","200","225","250"]},
    {"q": "En quelle année a été fondée Rome (approx.) ?", "rep": "753 av. J.-C.", "choix": ["500 av. J.-C.","753 av. J.-C.","1000 av. J.-C.","200 av. J.-C."]},
    {"q": "Combien de planètes dans le système solaire ?", "rep": "8", "choix": ["7","8","9","10"]},
    {"q": "Quel élément chimique a le symbole O ?", "rep": "Oxygène", "choix": ["Or","Osmium","Oxygène","Ozone"]},
    {"q": "Combien font 12 × 12 ?",          "rep": "144",      "choix": ["124","132","144","156"]},
    {"q": "Quel animal est le plus rapide sur Terre ?", "rep": "Guépard", "choix": ["Lion","Faucon","Guépard","Antilope"]},
    {"q": "Combien de secondes dans une heure ?", "rep": "3600", "choix": ["600","1800","3600","7200"]},
    {"q": "Quel pays a la plus grande superficie ?", "rep": "Russie", "choix": ["Canada","Chine","USA","Russie"]},
    {"q": "Combien font √144 ?",             "rep": "12",       "choix": ["10","11","12","13"]},
    {"q": "Combien de cordes a une guitare classique ?", "rep": "6", "choix": ["4","5","6","7"]},
    {"q": "Quel est le symbole chimique de l'or ?", "rep": "Au", "choix": ["Go","Or","Ag","Au"]},
]

class RapidFireView(discord.ui.View):
    def __init__(self, question: dict, reward: int, uid: int):
        super().__init__(timeout=15)
        self.question = question
        self.reward   = reward
        self.uid      = uid
        self.answered = False

        choix = question["choix"][:]
        random.shuffle(choix)
        for c in choix:
            btn = discord.ui.Button(label=c, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(c)
            self.add_item(btn)

    def _make_callback(self, choix: str):
        async def callback(inter: discord.Interaction):
            if inter.user.id != self.uid:
                await inter.response.send_message("❌ Ce n'est pas ta partie !", ephemeral=True)
                return
            if self.answered:
                return
            self.answered = True
            self.stop()
            for child in self.children:
                child.disabled = True
                if isinstance(child, discord.ui.Button):
                    if child.label == self.question["rep"]:
                        child.style = discord.ButtonStyle.green
                    elif child.label == choix:
                        child.style = discord.ButtonStyle.red

            user = await get_user(self.uid)
            if choix == self.question["rep"]:
                xp_g = 30
                await update_user(self.uid,
                    coins=user["coins"] + self.reward,
                    xp=user["xp"] + xp_g,
                    niveau=niveau_depuis_xp(user["xp"] + xp_g),
                    gains_casino=user["gains_casino"] + self.reward,
                )
                result_txt = f"✅ **Bonne réponse !** +**{self.reward:,} pièces** | +{xp_g} XP"
                color = discord.Color.green()
            else:
                result_txt = f"❌ Mauvaise réponse... C'était **{self.question['rep']}**."
                color = discord.Color.red()

            embed = discord.Embed(
                title="⚡  Rapid Fire",
                description=f"**{self.question['q']}**\n\n{result_txt}",
                color=color
            )
            await inter.response.edit_message(embed=embed, view=self)
        return callback

@tree.command(name="rapidfire", description="⚡ Question chrono — réponds vite pour gagner des pièces !")
async def rapidfire(interaction: discord.Interaction):
    uid     = interaction.user.id
    reward  = random.randint(100, 400)
    q       = random.choice(QUESTIONS_RAPIDFIRE)
    view    = RapidFireView(q, reward, uid)

    embed = discord.Embed(
        title="⚡  Rapid Fire !",
        description=(
            f"**{q['q']}**\n\n"
            f"⏱️ Tu as **15 secondes** !\n"
            f"💰 Récompense : **{reward:,} pièces**"
        ),
        color=discord.Color.yellow()
    )
    await interaction.response.send_message(embed=embed, view=view)

    await view.wait()
    if not view.answered:
        for child in view.children:
            child.disabled = True
        timeout_embed = discord.Embed(
            title="⚡  Rapid Fire",
            description=f"**{q['q']}**\n\n⌛ Temps écoulé ! La réponse était **{q['rep']}**.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=timeout_embed, view=view)


# ══════════════════════════════════════════════════════
#  MINI-JEU : /motcache  — Trouve le mot masqué
# ══════════════════════════════════════════════════════
MOTS_CACHES = [
    ("PYTHON",   "🐍 Langage de programmation populaire"),
    ("DRAGON",   "🐉 Créature mythologique crachant du feu"),
    ("SOLEIL",   "☀️ Notre étoile"),
    ("GUITARE",  "🎸 Instrument à cordes"),
    ("CHATEAU",  "🏰 Résidence royale fortifiée"),
    ("FUSEE",    "🚀 Véhicule spatial"),
    ("REQUIN",   "🦈 Prédateur des océans"),
    ("VOLCANE",  "🌋 Montagne qui crache de la lave"),  # intentionnel, le joueur cherche VOLCAN
    ("VOLCAN",   "🌋 Montagne qui crache de la lave"),
    ("TRESOR",   "💎 Ce qu'on cherche sur une carte au X"),
    ("FANTOME",  "👻 Esprit d'un défunt"),
    ("PYRAMIDE", "🏛️ Monument égyptien"),
    ("TORNADO",  "🌪️ Tempête tourbillonnante"),
    ("DAUPHIN",  "🐬 Mammifère marin très intelligent"),
    ("LABYRINTHE","🧩 Dédale de couloirs"),
    ("CRISTAL",  "💠 Minéral transparent"),
]

_motcache_actif: set[int] = set()

@tree.command(name="motcache", description="🔤 Trouve le mot masqué lettre par lettre — sans mise !")
async def motcache(interaction: discord.Interaction):
    uid = interaction.user.id
    if uid in _motcache_actif:
        await interaction.response.send_message("⏳ Tu as déjà une partie en cours !", ephemeral=True)
        return
    _motcache_actif.add(uid)

    mot, indice = random.choice(MOTS_CACHES)
    # dédoublonner pour que chaque lettre compte une fois
    lettres_restantes = set(mot)
    decouvert         = ["_"] * len(mot)
    max_erreurs       = 6
    erreurs           = 0
    reward            = random.randint(300, 800)
    xp_gain           = 50

    def affiche():
        return " ".join(decouvert)

    embed = discord.Embed(
        title="🔤  Mot Caché",
        description=(
            f"**Indice :** {indice}\n\n"
            f"`{affiche()}`\n\n"
            f"Tape une **lettre** dans le chat !\n"
            f"💀 Erreurs : **0/{max_erreurs}**\n"
            f"💰 Récompense : **{reward:,} pièces**"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Mot de {len(mot)} lettres")
    await interaction.response.send_message(embed=embed)

    lettres_jouees: set[str] = set()

    def check(m: discord.Message):
        return (
            m.author.id == uid
            and m.channel == interaction.channel
            and len(m.content) == 1
            and m.content.upper().isalpha()
        )

    while erreurs < max_erreurs and "_" in decouvert:
        try:
            msg = await bot.wait_for("message", check=check, timeout=45.0)
        except asyncio.TimeoutError:
            _motcache_actif.discard(uid)
            await interaction.followup.send(f"⌛ Temps écoulé ! Le mot était **{mot}**.")
            return

        lettre = msg.content.upper()
        if lettre in lettres_jouees:
            await interaction.followup.send(f"↩️ Tu as déjà essayé **{lettre}** !", delete_after=4)
            continue
        lettres_jouees.add(lettre)

        if lettre in lettres_restantes:
            for i, l in enumerate(mot):
                if l == lettre:
                    decouvert[i] = lettre
            lettres_restantes.discard(lettre)
            statut = "✅ Bien joué !"
            color  = discord.Color.green()
        else:
            erreurs += 1
            statut  = f"❌ **{lettre}** n'est pas dans le mot."
            color   = discord.Color.orange()

        # Fin ?
        if "_" not in decouvert:
            break

        pendus = ["😀","😐","😟","😰","😨","😱","💀"]
        embed_upd = discord.Embed(
            title="🔤  Mot Caché",
            description=(
                f"**Indice :** {indice}\n\n"
                f"`{affiche()}`\n\n"
                f"{statut}\n"
                f"{pendus[erreurs]} Erreurs : **{erreurs}/{max_erreurs}**\n"
                f"Lettres jouées : {' '.join(sorted(lettres_jouees))}"
            ),
            color=color
        )
        await interaction.followup.send(embed=embed_upd)

    _motcache_actif.discard(uid)

    if "_" not in decouvert:
        user = await get_user(uid)
        await update_user(uid,
            coins=user["coins"] + reward,
            xp=user["xp"] + xp_gain,
            niveau=niveau_depuis_xp(user["xp"] + xp_gain),
            gains_casino=user["gains_casino"] + reward,
        )
        win = discord.Embed(
            title="🎉 Bravo !",
            description=f"Le mot était bien **{mot}** !\n💰 +**{reward:,} pièces** | ✨ +{xp_gain} XP",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=win)
    else:
        lose = discord.Embed(
            title="💀 Perdu !",
            description=f"Le mot était **{mot}**. Plus de chance la prochaine fois !",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=lose)


# ══════════════════════════════════════════════════════
#  MINI-JEU : /memory  — Mémorise la séquence
# ══════════════════════════════════════════════════════
MEMORY_EMOJIS = ["🔴","🔵","🟢","🟡","🟣","🟠"]

class MemoryView(discord.ui.View):
    def __init__(self, sequence: list[str], uid: int, reward: int):
        super().__init__(timeout=30)
        self.sequence  = sequence
        self.saisie    = []
        self.uid       = uid
        self.reward    = reward
        self.done      = asyncio.Event()
        self.success   = False

        for emoji in MEMORY_EMOJIS:
            btn = discord.ui.Button(label=emoji, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(emoji)
            self.add_item(btn)

    def _make_cb(self, emoji: str):
        async def callback(inter: discord.Interaction):
            if inter.user.id != self.uid:
                await inter.response.send_message("❌ Ce n'est pas ta partie !", ephemeral=True)
                return
            self.saisie.append(emoji)
            idx = len(self.saisie) - 1

            # Mauvaise touche
            if self.saisie[idx] != self.sequence[idx]:
                self.stop()
                self.done.set()
                for c in self.children: c.disabled = True
                embed = discord.Embed(
                    title="🧠  Memory",
                    description=f"❌ Mauvaise touche ! La séquence était : {' '.join(self.sequence)}",
                    color=discord.Color.red()
                )
                await inter.response.edit_message(embed=embed, view=self)
                return

            # Séquence complète
            if len(self.saisie) == len(self.sequence):
                self.success = True
                self.stop()
                self.done.set()
                for c in self.children: c.disabled = True
                user = await get_user(self.uid)
                xp_g = 35
                await update_user(self.uid,
                    coins=user["coins"] + self.reward,
                    xp=user["xp"] + xp_g,
                    niveau=niveau_depuis_xp(user["xp"] + xp_g),
                    gains_casino=user["gains_casino"] + self.reward,
                )
                embed = discord.Embed(
                    title="🧠  Memory",
                    description=(
                        f"✅ **Parfait !** Séquence complète !\n"
                        f"💰 +**{self.reward:,} pièces** | ✨ +{xp_g} XP"
                    ),
                    color=discord.Color.green()
                )
                await inter.response.edit_message(embed=embed, view=self)
                return

            # Bonne touche, continue
            embed = discord.Embed(
                title="🧠  Memory",
                description=(
                    f"✅ Bonne touche ! ({len(self.saisie)}/{len(self.sequence)})\n"
                    f"Continue la séquence…"
                ),
                color=discord.Color.blurple()
            )
            await inter.response.edit_message(embed=embed, view=self)
        return callback

@tree.command(name="memory", description="🧠 Mémorise et reproduis la séquence de couleurs — sans mise !")
async def memory(interaction: discord.Interaction):
    uid      = interaction.user.id
    longueur = random.randint(4, 7)
    sequence = [random.choice(MEMORY_EMOJIS) for _ in range(longueur)]
    reward   = longueur * random.randint(60, 120)

    # Affiche la séquence pendant 4 secondes
    show_embed = discord.Embed(
        title="🧠  Memory — Mémorise !",
        description=(
            f"**Retiens cette séquence ({longueur} couleurs) :**\n\n"
            f"## {' '.join(sequence)}\n\n"
            f"⏳ Tu auras **30 secondes** pour la reproduire.\n"
            f"💰 Récompense : **{reward:,} pièces**"
        ),
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=show_embed)
    await asyncio.sleep(4)

    # Masque la séquence, affiche les boutons
    play_embed = discord.Embed(
        title="🧠  Memory — À toi !",
        description=(
            f"La séquence est masquée.\n"
            f"Reproduis les **{longueur} couleurs** dans l'ordre !\n\n"
            f"Progression : **0/{longueur}**"
        ),
        color=discord.Color.yellow()
    )
    view = MemoryView(sequence, uid, reward)
    await interaction.edit_original_response(embed=play_embed, view=view)

    await view.wait()
    if not view.success and not view.done.is_set():
        for c in view.children: c.disabled = True
        timeout_embed = discord.Embed(
            title="🧠  Memory",
            description=f"⌛ Temps écoulé ! La séquence était : {' '.join(sequence)}",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=timeout_embed, view=view)


# ══════════════════════════════════════════════════════
#  MINI-JEU : /bombe  — Désamorce la bombe (boutons)
# ══════════════════════════════════════════════════════
class BombeView(discord.ui.View):
    def __init__(self, bon_fil: str, uid: int, reward: int):
        super().__init__(timeout=12)
        self.bon_fil = bon_fil
        self.uid     = uid
        self.reward  = reward
        self.answered = False

        fils = ["🔴 Rouge", "🔵 Bleu", "🟢 Vert", "🟡 Jaune"]
        random.shuffle(fils)
        for fil in fils:
            btn = discord.ui.Button(label=fil, style=discord.ButtonStyle.danger)
            btn.callback = self._make_cb(fil)
            self.add_item(btn)

    def _make_cb(self, fil: str):
        async def callback(inter: discord.Interaction):
            if inter.user.id != self.uid:
                await inter.response.send_message("❌ Ce n'est pas ta partie !", ephemeral=True)
                return
            if self.answered:
                return
            self.answered = True
            self.stop()
            for c in self.children:
                c.disabled = True
                if isinstance(c, discord.ui.Button) and c.label == self.bon_fil:
                    c.style = discord.ButtonStyle.green

            if fil == self.bon_fil:
                user = await get_user(self.uid)
                xp_g = 25
                await update_user(self.uid,
                    coins=user["coins"] + self.reward,
                    xp=user["xp"] + xp_g,
                    niveau=niveau_depuis_xp(user["xp"] + xp_g),
                    gains_casino=user["gains_casino"] + self.reward,
                )
                embed = discord.Embed(
                    title="💣  Bombe désamorcée !",
                    description=f"✅ Bon fil ! **+{self.reward:,} pièces** | ✨ +{xp_g} XP",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="💥  BOOM !",
                    description=f"❌ Mauvais fil ! C'était le **{self.bon_fil}**.",
                    color=discord.Color.red()
                )
            await inter.response.edit_message(embed=embed, view=self)
        return callback

@tree.command(name="bombe", description="💣 Coupe le bon fil pour désamorcer la bombe — 1 chance sur 4 !")
async def bombe(interaction: discord.Interaction):
    uid     = interaction.user.id
    fils    = ["🔴 Rouge", "🔵 Bleu", "🟢 Vert", "🟡 Jaune"]
    bon_fil = random.choice(fils)
    reward  = random.randint(250, 700)

    embed = discord.Embed(
        title="💣  Désamorce la bombe !",
        description=(
            f"⏱️ **12 secondes** pour couper le bon fil !\n\n"
            f"Un seul fil est le bon parmi 4.\n"
            f"💰 Récompense : **{reward:,} pièces**"
        ),
        color=discord.Color.red()
    )
    view = BombeView(bon_fil, uid, reward)
    await interaction.response.send_message(embed=embed, view=view)

    await view.wait()
    if not view.answered:
        for c in view.children: c.disabled = True
        boom_embed = discord.Embed(
            title="💥  BOOM ! Temps écoulé !",
            description=f"Le bon fil était le **{bon_fil}**.",
            color=discord.Color.dark_red()
        )
        await interaction.edit_original_response(embed=boom_embed, view=view)


# ══════════════════════════════════════════════════════
#  MINI-JEU : /chimie  — Trouve la formule
# ══════════════════════════════════════════════════════
FORMULES = [
    {"q": "Eau",                "rep": "H₂O",   "choix": ["H₂O","CO₂","NaCl","O₂"]},
    {"q": "Dioxyde de carbone", "rep": "CO₂",   "choix": ["CO","CO₂","CH₄","NO₂"]},
    {"q": "Sel de table",       "rep": "NaCl",  "choix": ["KCl","NaCl","MgCl","CaCl"]},
    {"q": "Dihydrogène",        "rep": "H₂",    "choix": ["H","H₂","HO","H₃"]},
    {"q": "Ammoniaque",         "rep": "NH₃",   "choix": ["NH₂","N₂H","NH₃","NH₄"]},
    {"q": "Méthane",            "rep": "CH₄",   "choix": ["CH₂","CH₃","CH₄","C₂H₄"]},
    {"q": "Sulfate de calcium", "rep": "CaSO₄", "choix": ["CaSO₃","CaSO₄","Ca₂SO","CaS"]},
    {"q": "Glucose",            "rep": "C₆H₁₂O₆","choix": ["C₆H₁₂O₆","C₅H₁₀O₅","C₁₂H₂₂O","C₆H₁₀O₅"]},
    {"q": "Dioxygène",          "rep": "O₂",    "choix": ["O","O₂","O₃","O₄"]},
    {"q": "Ozone",              "rep": "O₃",    "choix": ["O₂","O₃","OH","O₄"]},
]

class FormuleView(discord.ui.View):
    def __init__(self, q: dict, uid: int, reward: int):
        super().__init__(timeout=15)
        self.q        = q
        self.uid      = uid
        self.reward   = reward
        self.answered = False
        choix = q["choix"][:]
        random.shuffle(choix)
        for c in choix:
            btn = discord.ui.Button(label=c, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(c)
            self.add_item(btn)

    def _make_cb(self, choix: str):
        async def callback(inter: discord.Interaction):
            if inter.user.id != self.uid:
                await inter.response.send_message("❌ Ce n'est pas ta partie !", ephemeral=True)
                return
            if self.answered: return
            self.answered = True
            self.stop()
            for c in self.children:
                c.disabled = True
                if isinstance(c, discord.ui.Button):
                    if c.label == self.q["rep"]: c.style = discord.ButtonStyle.green
                    elif c.label == choix:       c.style = discord.ButtonStyle.red

            user = await get_user(self.uid)
            if choix == self.q["rep"]:
                xp_g = 25
                await update_user(self.uid,
                    coins=user["coins"] + self.reward,
                    xp=user["xp"] + xp_g,
                    niveau=niveau_depuis_xp(user["xp"] + xp_g),
                    gains_casino=user["gains_casino"] + self.reward,
                )
                result = f"✅ **Bonne formule !** +**{self.reward:,} pièces** | +{xp_g} XP"
                color  = discord.Color.green()
            else:
                result = f"❌ Faux ! La bonne réponse était **{self.q['rep']}**."
                color  = discord.Color.red()

            embed = discord.Embed(
                title="⚗️  Formule Chimique",
                description=f"**{self.q['q']}** → {result}",
                color=color
            )
            await inter.response.edit_message(embed=embed, view=self)
        return callback

@tree.command(name="chimie", description="⚗️ Trouve la bonne formule chimique en 15s — sans mise !")
async def chimie(interaction: discord.Interaction):
    uid    = interaction.user.id
    q      = random.choice(FORMULES)
    reward = random.randint(150, 350)
    view   = FormuleView(q, uid, reward)

    embed = discord.Embed(
        title="⚗️  Formule Chimique !",
        description=(
            f"Quelle est la formule de **{q['q']}** ?\n\n"
            f"⏱️ **15 secondes** !\n"
            f"💰 Récompense : **{reward:,} pièces**"
        ),
        color=discord.Color.teal()
    )
    await interaction.response.send_message(embed=embed, view=view)
    await view.wait()
    if not view.answered:
        for c in view.children: c.disabled = True
        embed = discord.Embed(
            title="⚗️  Formule Chimique",
            description=f"⌛ Temps écoulé ! La réponse était **{q['rep']}**.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed, view=view)


# ══════════════════════════════════════════════════════
#  /minijeux  — Aide
# ══════════════════════════════════════════════════════
@tree.command(name="minijeux", description="🎮 Liste tous les mini-jeux disponibles")
async def minijeux(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮  Mini-Jeux",
        description="Des jeux **sans mise** pour gagner des pièces et de l'XP !",
        color=discord.Color.purple()
    )
    jeux = [
        ("🔢 /devinombre", "Devine un nombre entre 1 et 100 en 5 essais\n💰 200–600 pièces | ✨ 40 XP"),
        ("⚡ /rapidfire",  "Réponds à une question en 15 secondes\n💰 100–400 pièces | ✨ 30 XP"),
        ("🔤 /motcache",   "Trouve le mot masqué lettre par lettre\n💰 300–800 pièces | ✨ 50 XP"),
        ("🧠 /memory",     "Mémorise et reproduis une séquence de couleurs\n💰 240–840 pièces | ✨ 35 XP"),
        ("💣 /bombe",      "Coupe le bon fil parmi 4 en 12 secondes\n💰 250–700 pièces | ✨ 25 XP"),
        ("⚗️ /chimie",     "Trouve la bonne formule chimique en 15s\n💰 150–350 pièces | ✨ 25 XP"),
    ]
    for nom, desc in jeux:
        embed.add_field(name=nom, value=desc, inline=False)
    embed.set_footer(text="Aucune mise requise — juste du skill !")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    bot.run(TOKEN)
