# 🎰 CasinoBot Discord

Un bot Discord complet combinant **système d'XP**, **casino** et **mini-jeux** avec économie, shop et rôles automatiques.

---

## 📋 Prérequis

- Python **3.10+**
- Un token bot Discord ([discord.com/developers](https://discord.com/developers/applications))

---

## ⚙️ Installation

```bash
# 1. Cloner / télécharger les fichiers
# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Définir la variable d'environnement avec votre token
# Windows
set DISCORD_TOKEN=ton_token_ici

# Linux / macOS
export DISCORD_TOKEN=ton_token_ici

# 4. Lancer le bot
python bot.py
```

---

## 🌐 Déploiement en ligne (Heroku / Railway)

Le `Procfile` est déjà configuré. Il suffit de :

1. Créer une application sur [Heroku](https://heroku.com) ou [Railway](https://railway.app)
2. Pousser les fichiers (`bot.py`, `requirements.txt`, `Procfile`)
3. Ajouter la variable d'environnement `DISCORD_TOKEN` dans les settings
4. Activer le **worker** (pas web) dans les dynos

---

## 🔧 Configuration du serveur Discord

### Permissions requises pour le bot
Dans le portail développeur → OAuth2 → Bot, active :
- ✅ **Read Messages / View Channels**
- ✅ **Send Messages**
- ✅ **Read Message History**
- ✅ **Manage Roles** *(pour créer les rôles personnalisés)*

### Intents à activer (portail développeur → Bot)
- ✅ **Server Members Intent**
- ✅ **Message Content Intent**

### Créer les rôles manuellement sur ton serveur
Le bot attribue automatiquement ces rôles quand un membre atteint le niveau requis.  
**Tu dois les créer au préalable sur ton serveur avec exactement ces noms :**

| Niveau requis | Nom du rôle              |
|:---:|:---|
| 5   | `Débutant du casino`     |
| 15  | `Aventurier du casino`   |
| 30  | `Vétéran du casino`      |
| 50  | `Expert du casino`       |
| 100 | `Légende du casino`      |

> ⚠️ Le rôle du bot doit être **au-dessus** des rôles casino dans la liste des rôles.

---

## 🎮 Commandes disponibles (préfixe `%`)

### 📊 Profil & XP
| Commande | Description |
|---|---|
| `%profil [@user]` | Affiche le profil avec niveau, XP, coins et progression |
| `%classement` | Top 10 des membres par XP |
| `%richesse` | Top 10 des membres les plus riches |
| `%solde` | Voir son solde de coins |

### 💰 Économie
| Commande | Cooldown | Description |
|---|---|---|
| `%daily` | 24h | Récupère entre 100 et 300 coins |
| `%work` | 30min | Travaille pour gagner des coins |
| `%crime` | 1h | Crime risqué — 35% de chance d'amende |
| `%rob @user` | 2h | Vole des coins à un autre membre |

### 🎰 Casino
| Commande | Description |
|---|---|
| `%slot <mise>` | Machine à sous (3 rouleaux, jackpots multiples) |
| `%coinflip <mise> <pile\|face>` | Pile ou face x2 |
| `%blackjack <mise>` | Blackjack interactif complet |
| `%roulette <mise> <rouge\|noir\|pair\|impair\|0-36>` | Roulette (x2 ou x36) |
| `%dice <mise>` | Duel de dés (total > 7 = gagné) |

### 🎮 Mini-jeux
| Commande | Description |
|---|---|
| `%trivia` | Question culture générale — +coins +XP |
| `%rps @user <mise>` | Pierre Feuille Ciseaux PvP |
| `%duel @user <mise>` | Duel au hasard PvP |
| `%mines <mise> <nb_mines>` | Mines (1 à 8 bombes, multiplicateur croissant) |
| `%course` | Course de chevaux multijoueur (30s pour parier) |

### 🛒 Shop
| Commande | Description |
|---|---|
| `%shop` | Voir les items disponibles |
| `%buy <item>` | Acheter un item |
| `%inventaire` | Voir son inventaire |
| `%use <item>` | Activer un item |

**Items disponibles :**
| Clé | Nom | Prix | Effet |
|---|---|---|---|
| `role_perso` | 🎨 Rôle Personnalisé | 5 000 🪙 | Crée un rôle avec couleur et nom au choix |
| `xp_boost_1h` | ⚡ Boost XP 1h | 800 🪙 | Double les gains XP pendant 1h |
| `shield` | 🛡️ Bouclier | 400 🪙 | Protège contre le prochain vol |
| `lucky_charm` | 🍀 Porte-bonheur | 1 200 🪙 | +5% de chance au casino pendant 24h |
| `daily_bonus` | 🎁 Bonus Journalier x2 | 600 🪙 | Double le prochain `%daily` |

---

## ⭐ Système d'XP

| Source | Gain |
|---|---|
| Message envoyé | 5–15 XP (cooldown 60s) |
| Temps en vocal | 3 XP/minute |
| Trivia réussi | 20 XP |
| Boost XP actif | Tous les gains x2 |

**Formule de niveau :** `XP requis = 100 × N^1.7` (difficulté croissante)

| Niveau | XP total approximatif |
|---|---|
| 5 | ~1 600 XP |
| 15 | ~10 000 XP |
| 30 | ~35 000 XP |
| 50 | ~90 000 XP |
| 100 | ~300 000 XP |

---

## 📁 Structure des fichiers

```
├── bot.py           # Code principal du bot
├── requirements.txt # Dépendances Python
├── Procfile         # Configuration déploiement
├── README.md        # Ce fichier
└── data.json        # Données (créé automatiquement au premier lancement)
```

---

## 🔒 Sécurité

- Le token ne doit **jamais** être mis dans le code source
- Utilise toujours une variable d'environnement (`DISCORD_TOKEN`)
- Le fichier `data.json` contient les données des utilisateurs — pense à le sauvegarder régulièrement

---

## 🛠️ Personnalisation

Toutes les valeurs configurables se trouvent en haut de `bot.py` :

```python
XP_PER_MESSAGE = (5, 15)       # Plage d'XP par message
XP_PER_MINUTE_VOCAL = 3        # XP par minute en vocal
XP_MESSAGE_COOLDOWN = 60       # Cooldown anti-spam XP (secondes)
STARTING_COINS = 200           # Coins de départ
LEVEL_ROLES = { ... }          # Paliers de niveaux → noms de rôles
```
