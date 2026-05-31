# 🎰 Casino Bot v2.0

Bot Discord avec système XP avancé, économie complète et casino.

## 🚀 Installation

```bash
pip install -r requirements.txt
```

Puis dans `bot.py`, remplace `TON_TOKEN_ICI` par ton token Discord.

```bash
python bot.py
```

---

## ⚙️ Configuration des rôles automatiques

Crée ces rôles **exactement** avec ces noms sur ton serveur Discord :

| Niveau | Nom du rôle      |
|--------|------------------|
| 5      | 🌱 Débutant      |
| 10     | ⚔️ Aventurier    |
| 20     | 🔥 Vétéran       |
| 35     | 💫 Expert        |
| 50     | 👑 Légende       |

> Le bot doit avoir un rôle **au-dessus** des rôles qu'il doit attribuer.

---

## 📋 Commandes

### 👤 Profil & Social
| Commande | Description |
|----------|-------------|
| `/profil [@membre]` | Affiche le profil XP, niveau, pièces, inventaire |
| `/classement [xp\|coins\|gains_casino]` | Top 10 du serveur |
| `/daily` | Récompense quotidienne avec système de streak |
| `/donner @membre montant` | Envoyer des pièces à un joueur |

### 🛍️ Shop & Inventaire
| Commande | Description |
|----------|-------------|
| `/shop` | Voir le catalogue |
| `/acheter <item_id>` | Acheter un objet |
| `/inventaire` | Voir ses objets |
| `/utiliser <item_id>` | Activer un objet |

#### Objets disponibles
| ID | Objet | Prix | Effet |
|----|-------|------|-------|
| `boost_xp_1h` | ⚡ Boost XP 1h | 500 💰 | XP ×2 pendant 1h |
| `boost_xp_24h` | 🚀 Boost XP 24h | 2000 💰 | XP ×2 pendant 24h |
| `shield` | 🛡️ Bouclier | 750 💰 | Annule la prochaine perte casino |
| `lootbox` | 📦 Loot Box | 300 💰 | Gagne entre 100 et 5000 pièces |
| `multiplicateur` | ✨ Multiplicateur ×2 | 1000 💰 | Double la prochaine victoire casino |

### 🎰 Casino
| Commande | Description |
|----------|-------------|
| `/slots <mise>` | Machine à sous (×3 à ×50) |
| `/coinflip <mise> <pile\|face>` | Pile ou face (×2) |
| `/blackjack <mise>` | Blackjack avec Tirer / Rester / Doubler |
| `/dés <mise>` | 2d6 contre le croupier |
| `/roulette <mise> <pari>` | Roulette 0-36 (rouge, noir, pair, impair, numéro) |

---

## 📁 Fichiers générés
- `casino.db` — base de données SQLite (créée automatiquement au démarrage)

---

## 🛠️ Personnalisation

Dans `bot.py`, la section **CONFIG** permet de modifier :
- `XP_MIN / XP_MAX` — fourchette d'XP par message
- `COOLDOWN_MSG` — délai anti-spam (secondes)
- `COINS_DEPART` — pièces de départ
- `DAILY_XP / DAILY_COINS` — récompenses quotidiennes
- `ROLES_NIVEAUX` — niveaux et noms des rôles
- `SHOP_ITEMS` — catalogue de la boutique
