import os
import random
import sqlite3
import time
from typing import Optional, Tuple

import discord
from discord.ext import commands

# ==================== SETTINGS ====================

DB_FILE = "flower_bot.sqlite3"
DEFAULT_PREFIX = "!"
HUNT_COOLDOWN = 60
TRADE_LIFETIME = 15 * 60

GARDENS = {
    1: {"name": "Sprout Patch", "capacity": 10, "cost": 0},
    2: {"name": "Blooming Grove", "capacity": 50, "cost": 1000},
    3: {"name": "Enchanted Conservatory", "capacity": 100, "cost": 5000},
    4: {"name": "Eternal Garden", "capacity": 200, "cost": 20000},
}

RARITIES = {
    "Common": {
        "weight": 60, "base_value": 10, "power": 10,
        "emoji": "🌼",
        "flowers": ["Daisy", "Tulip", "Marigold", "Pansy", "Buttercup"],
    },
    "Rare": {
        "weight": 25, "base_value": 30, "power": 20,
        "emoji": "🌷",
        "flowers": ["Bluebell", "Lavender", "Iris", "Jasmine", "Forget-me-not"],
    },
    "Epic": {
        "weight": 10, "base_value": 90, "power": 35,
        "emoji": "🪻",
        "flowers": ["Moonflower", "Fire Lily", "Star Orchid", "Night Bloom"],
    },
    "Mythic": {
        "weight": 4, "base_value": 250, "power": 55,
        "emoji": "🌺",
        "flowers": ["Crystal Rose", "Phoenix Bloom", "Ghost Orchid"],
    },
    "Legendary": {
        "weight": 0.99, "base_value": 1000, "power": 80,
        "emoji": "🌟",
        "flowers": ["Celestial Lotus", "Dragonflower", "Sunfire Blossom"],
    },
    "Electro": {
        "weight": 0.01, "base_value": 10000, "power": 130,
        "emoji": "⚡",
        "flowers": ["Voltaic Orchid", "Thunder Rose", "Neon Starbloom"],
    },
}

RARITY_ORDER = ["Common", "Rare", "Epic", "Mythic", "Legendary", "Electro"]

EVOLUTION_THRESHOLDS = [2 * 3600, 10 * 3600, 36 * 3600]
EVOLUTION_NAMES = ["Seedling", "Blooming", "Radiant", "Ascended"]

SHOP = {
    "luck_booster": {
        "name": "Luck Booster", "price": 500,
        "description": "Adds 5 lucky hunts with better rarity odds.",
    },
    "coin_booster": {
        "name": "Coin Booster", "price": 650,
        "description": "Earn 50% more Flower Coins for 30 minutes.",
    },
    "xp_nectar": {
        "name": "XP Nectar", "price": 700,
        "description": "Doubles flower battle XP for 3 battles.",
    },
    "growth_fertilizer": {
        "name": "Growth Fertilizer", "price": 400,
        "description": "Adds 6 hours of growth to one planted flower.",
    },
    "battle_pollen": {
        "name": "Battle Pollen", "price": 600,
        "description": "Boosts team power by 20% for 3 battles.",
    },
    "mystery_seed": {
        "name": "Mystery Seed", "price": 350,
        "description": "Gives you one random flower.",
    },
    "cooldown_charm": {
        "name": "Cooldown Charm", "price": 250,
        "description": "Skips your next hunting cooldown.",
    },
    "garden_voucher": {
        "name": "Garden Voucher", "price": 900,
        "description": "Gives 25% off your next garden upgrade.",
    },
    "golden_can": {
        "name": "Golden Watering Can", "price": 800,
        "description": "Adds 24 hours of growth to one planted flower.",
    },
    "rare_bloom_capsule": {
        "name": "Rare Bloom Capsule", "price": 1000,
        "description": "Greatly improves your next hunt's rarity odds.",
    },
}

# ==================== DATABASE ====================

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")


def init_db():
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        prefix TEXT NOT NULL DEFAULT '!'
    );

    CREATE TABLE IF NOT EXISTS players (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        coins INTEGER NOT NULL DEFAULT 100,
        garden_tier INTEGER NOT NULL DEFAULT 1,
        accepted INTEGER NOT NULL DEFAULT 0,
        last_hunt REAL NOT NULL DEFAULT 0,
        luck_hunts INTEGER NOT NULL DEFAULT 0,
        coin_boost_until REAL NOT NULL DEFAULT 0,
        xp_boost_battles INTEGER NOT NULL DEFAULT 0,
        battle_boost INTEGER NOT NULL DEFAULT 0,
        rare_hunt INTEGER NOT NULL DEFAULT 0,
        skip_hunt_cooldown INTEGER NOT NULL DEFAULT 0,
        garden_discount INTEGER NOT NULL DEFAULT 0,
        last_daily TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (guild_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS flowers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        rarity TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 1,
        xp INTEGER NOT NULL DEFAULT 0,
        planted INTEGER NOT NULL DEFAULT 0,
        growth_seconds REAL NOT NULL DEFAULT 0,
        last_growth_at REAL NOT NULL DEFAULT 0,
        evolution INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS team_slots (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        slot INTEGER NOT NULL,
        flower_id INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id, slot),
        UNIQUE (guild_id, user_id, flower_id)
    );

    CREATE TABLE IF NOT EXISTS player_items (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        item_key TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, item_key)
    );

    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        buyer_id INTEGER NOT NULL,
        flower_id INTEGER NOT NULL,
        price INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL
    );
    """)
    conn.commit()


init_db()


def ensure_player(guild_id, user_id):
    conn.execute(
        "INSERT OR IGNORE INTO players (guild_id,user_id) VALUES (?,?)",
        (guild_id, user_id),
    )
    conn.commit()


def get_player(guild_id, user_id):
    ensure_player(guild_id, user_id)
    return conn.execute(
        "SELECT * FROM players WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchone()


def get_prefix_for_guild(guild_id):
    row = conn.execute(
        "SELECT prefix FROM guild_settings WHERE guild_id=?",
        (guild_id,),
    ).fetchone()
    return row["prefix"] if row else DEFAULT_PREFIX


def update_flower_growth(guild_id, owner_id, flower_id=None):
    now = time.time()

    if flower_id is None:
        rows = conn.execute(
            "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? AND planted=1",
            (guild_id, owner_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? AND id=? AND planted=1",
            (guild_id, owner_id, flower_id),
        ).fetchall()

    for flower in rows:
        last = flower["last_growth_at"] or now
        total = flower["growth_seconds"] + max(0, now - last)
        evolution = sum(1 for threshold in EVOLUTION_THRESHOLDS if total >= threshold)

        conn.execute(
            "UPDATE flowers SET growth_seconds=?,last_growth_at=?,evolution=? WHERE id=?",
            (total, now, evolution, flower["id"]),
        )

    conn.commit()


def add_flower(guild_id, owner_id, rarity=None):
    if rarity is None:
        rarity = random.choices(
            RARITY_ORDER,
            weights=[RARITIES[r]["weight"] for r in RARITY_ORDER],
            k=1,
        )[0]

    name = random.choice(RARITIES[rarity]["flowers"])

    cur = conn.execute(
        "INSERT INTO flowers (guild_id,owner_id,name,rarity) VALUES (?,?,?,?)",
        (guild_id, owner_id, name, rarity),
    )
    conn.commit()
    return cur.lastrowid


def get_flower(guild_id, owner_id, flower_id):
    return conn.execute(
        "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? AND id=?",
        (guild_id, owner_id, flower_id),
    ).fetchone()


def flower_value(flower):
    base = RARITIES[flower["rarity"]]["base_value"]
    level_multiplier = 1 + (max(1, flower["level"]) - 1) * 0.15
    evolution_multiplier = 1 + flower["evolution"] * 0.25
    return int(base * level_multiplier * evolution_multiplier)


def add_coins(guild_id, user_id, amount):
    player = get_player(guild_id, user_id)
    multiplier = 1.5 if player["coin_boost_until"] > time.time() else 1
    final_amount = int(amount * multiplier)

    conn.execute(
        "UPDATE players SET coins=coins+? WHERE guild_id=? AND user_id=?",
        (final_amount, guild_id, user_id),
    )
    conn.commit()
    return final_amount


def remove_flower_from_team(guild_id, flower_id):
    conn.execute(
        "DELETE FROM team_slots WHERE guild_id=? AND flower_id=?",
        (guild_id, flower_id),
    )


def get_team(guild_id, user_id):
    return conn.execute(
        "SELECT t.slot,f.* FROM team_slots t JOIN flowers f ON f.id=t.flower_id "
        "WHERE t.guild_id=? AND t.user_id=? ORDER BY t.slot",
        (guild_id, user_id),
    ).fetchall()


def get_item_count(guild_id, user_id, item_key):
    row = conn.execute(
        "SELECT quantity FROM player_items WHERE guild_id=? AND user_id=? AND item_key=?",
        (guild_id, user_id, item_key),
    ).fetchone()
    return row["quantity"] if row else 0


def add_item(guild_id, user_id, item_key, amount=1):
    conn.execute(
        "INSERT INTO player_items (guild_id,user_id,item_key,quantity) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id,user_id,item_key) DO UPDATE SET quantity=quantity+excluded.quantity",
        (guild_id, user_id, item_key, amount),
    )
    conn.commit()


def take_item(guild_id, user_id, item_key, amount=1):
    count = get_item_count(guild_id, user_id, item_key)
    if count < amount:
        return False

    conn.execute(
        "UPDATE player_items SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_key=?",
        (amount, guild_id, user_id, item_key),
    )
    conn.execute(
        "DELETE FROM player_items WHERE guild_id=? AND user_id=? AND item_key=? AND quantity<=0",
        (guild_id, user_id, item_key),
    )
    conn.commit()
    return True


# ==================== BOT SETUP ====================

async def dynamic_prefix(bot, message):
    if message.guild is None:
        return ["!"]

    prefix = get_prefix_for_guild(message.guild.id)
    return commands.when_mentioned_or(prefix)(bot, message)


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(
    command_prefix=dynamic_prefix,
    intents=intents,
    help_command=None,
    case_insensitive=True,
    strip_after_prefix=True,
)

COLOR = discord.Color.from_rgb(80, 190, 135)


def make_embed(title, description="", color=COLOR):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Flower Bot • Grow your own little world")
    return embed


async def send_embed(ctx, title, description="", color=COLOR):
    await ctx.send(embed=make_embed(title, description, color))


def garden_info(tier):
    return GARDENS[max(1, min(4, tier))]


def format_flower(flower):
    rarity = flower["rarity"]
    evo = EVOLUTION_NAMES[flower["evolution"]]
    status = "🌱 Planted" if flower["planted"] else "📦 Stored"

    return (
        f"`#{flower['id']}` {RARITIES[rarity]['emoji']} **{flower['name']}** — {rarity}\n"
        f"Level **{flower['level']}** • {evo} • {status} • "
        f"Sell value: **{flower_value(flower):,} FC**"
    )


def roll_hunt(lucky=False, rare_capsule=False):
    if rare_capsule:
        weights = [30, 30, 20, 12, 7.5, 0.5]
    elif lucky:
        weights = [50, 27, 14, 6, 2.95, 0.05]
    else:
        weights = [RARITIES[r]["weight"] for r in RARITY_ORDER]

    return random.choices(RARITY_ORDER, weights=weights, k=1)[0]


def is_admin_or_owner(ctx):
    return bool(
        ctx.guild and (
            ctx.author.id == ctx.guild.owner_id
            or ctx.author.guild_permissions.administrator
        )
    )


# ==================== PRIVACY POLICY ====================

class PrivacyView(discord.ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.user_id = user_id

    @discord.ui.button(
        label="Accept Privacy Policy",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def accept(self, interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=make_embed(
                    "This button isn't for you",
                    "Run a command yourself to receive your own privacy agreement.",
                ),
                ephemeral=True,
            )
            return

        conn.execute(
            "UPDATE players SET accepted=1 WHERE guild_id=? AND user_id=?",
            (self.guild_id, self.user_id),
        )
        conn.commit()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=make_embed(
                "Privacy policy accepted! 🌸",
                "You're ready to play. Run your command again to start collecting flowers.",
                discord.Color.green(),
            ),
            view=self,
        )


async def send_privacy_policy(ctx):
    embed = make_embed(
        "🌸 Flower Bot — Privacy & Game Rules",
        "**1. Data saved:** Your Discord user ID, server ID, coins, flowers, "
        "garden, team, inventory, trades and prefix settings are saved in SQLite.\n\n"
        "**2. Purpose:** This data is needed to save game progress and run game features.\n\n"
        "**3. Sharing:** The bot does not intentionally sell or share your game data. "
        "People with access to the bot host or database may be able to view it.\n\n"
        "**4. Security:** Keep your bot token private.\n\n"
        "**5. Game rules:** Do not exploit bugs, spam commands, impersonate players "
        "or use trades to harass others.\n\n"
        "**6. Your choice:** You can decline. Game commands will remain unavailable "
        "until you accept. Ask the bot host to delete your saved data if needed.\n\n"
        "Press **Accept Privacy Policy** to continue.",
        discord.Color.blurple(),
    )
    embed.set_footer(text="Displayed once per player per server.")
    await ctx.send(embed=embed, view=PrivacyView(ctx.guild.id, ctx.author.id))


@bot.check
async def privacy_gate(ctx):
    if ctx.guild is None:
        return False

    player = get_player(ctx.guild.id, ctx.author.id)

    if player["accepted"]:
        return True

    if ctx.command and ctx.command.name == "privacy":
        return True

    await send_privacy_policy(ctx)
    return False


# ==================== SHOP SELECT MENU ====================

async def purchase_item(guild_id, user_id, item_key):
    if item_key not in SHOP:
        return False, "That shop item does not exist."

    player = get_player(guild_id, user_id)
    item = SHOP[item_key]

    if player["coins"] < item["price"]:
        return False, (
            f"You need **{item['price']:,} FC**, "
            f"but you have **{player['coins']:,} FC**."
        )

    conn.execute(
        "UPDATE players SET coins=coins-? WHERE guild_id=? AND user_id=?",
        (item["price"], guild_id, user_id),
    )
    conn.commit()

    add_item(guild_id, user_id, item_key)
    return True, f"Purchased **{item['name']}** for **{item['price']:,} Flower Coins**."


class ShopSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{item['name']} — {item['price']} FC",
                value=key,
                description=item["description"][:100],
            )
            for key, item in SHOP.items()
        ]

        super().__init__(
            placeholder="Choose an item to purchase...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="flower_shop_select",
        )

    async def callback(self, interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=make_embed("Server only", "Use the shop inside a server."),
                ephemeral=True,
            )
            return

        ok, message = await purchase_item(
            interaction.guild.id,
            interaction.user.id,
            self.values[0],
        )

        color = discord.Color.green() if ok else discord.Color.red()

        await interaction.response.send_message(
            embed=make_embed(
                "🌸 Shop purchase" if ok else "Purchase failed",
                message,
                color,
            ),
            ephemeral=True,
        )


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ShopSelect())


# ==================== BATTLE SYSTEM ====================

def flower_power(flower):
    power = RARITIES[flower["rarity"]]["power"]
    power += flower["level"] * 4
    power += flower["evolution"] * 18

    if flower["planted"]:
        power *= 1.25

    return power


def award_flower_xp(guild_id, user_id, flower, xp_amount):
    if not flower["planted"]:
        return None

    player = get_player(guild_id, user_id)

    if player["xp_boost_battles"] > 0:
        xp_amount *= 2

    new_xp = flower["xp"] + xp_amount
    level = flower["level"]
    levels_gained = 0

    while new_xp >= 100 + (level * 35):
        new_xp -= 100 + (level * 35)
        level += 1
        levels_gained += 1

    conn.execute(
        "UPDATE flowers SET xp=?,level=? WHERE id=?",
        (new_xp, level, flower["id"]),
    )
    conn.commit()

    return levels_gained


async def run_battle(guild, challenger_id, defender_id):
    update_flower_growth(guild.id, challenger_id)
    update_flower_growth(guild.id, defender_id)

    team_a = get_team(guild.id, challenger_id)
    team_b = get_team(guild.id, defender_id)

    if len(team_a) != 3 or len(team_b) != 3:
        return None, "Both players must have exactly 3 flowers in their battle teams."

    player_a = get_player(guild.id, challenger_id)
    player_b = get_player(guild.id, defender_id)

    boost_a = 1.2 if player_a["battle_boost"] > 0 else 1.0
    boost_b = 1.2 if player_b["battle_boost"] > 0 else 1.0

    lines = []
    wins_a = 0
    wins_b = 0

    for index in range(3):
        flower_a = team_a[index]
        flower_b = team_b[index]

        score_a = flower_power(flower_a) * boost_a * random.uniform(0.85, 1.15)
        score_b = flower_power(flower_b) * boost_b * random.uniform(0.85, 1.15)

        if score_a >= score_b:
            wins_a += 1
            lines.append(
                f"**Round {index + 1}:** {flower_a['name']} defeated "
                f"{flower_b['name']} ({score_a:.0f} vs {score_b:.0f})"
            )
        else:
            wins_b += 1
            lines.append(
                f"**Round {index + 1}:** {flower_b['name']} defeated "
                f"{flower_a['name']} ({score_b:.0f} vs {score_a:.0f})"
            )

    a_won = wins_a > wins_b
    winner_id = challenger_id if a_won else defender_id
    loser_id = defender_id if a_won else challenger_id

    reward_winner = add_coins(guild.id, winner_id, 100)
    reward_loser = add_coins(guild.id, loser_id, 30)

    level_messages = []

    for flower in team_a:
        gained = award_flower_xp(
            guild.id, challenger_id, flower, 45 if a_won else 25
        )
        if gained:
            level_messages.append(
                f"<@{challenger_id}>: **{flower['name']}** gained {gained} level(s)"
            )

    for flower in team_b:
        gained = award_flower_xp(
            guild.id, defender_id, flower, 45 if not a_won else 25
        )
        if gained:
            level_messages.append(
                f"<@{defender_id}>: **{flower['name']}** gained {gained} level(s)"
            )

    for user_id, player in (
        (challenger_id, player_a),
        (defender_id, player_b),
    ):
        if player["xp_boost_battles"] > 0:
            conn.execute(
                "UPDATE players SET xp_boost_battles=xp_boost_battles-1 "
                "WHERE guild_id=? AND user_id=?",
                (guild.id, user_id),
            )

        if player["battle_boost"] > 0:
            conn.execute(
                "UPDATE players SET battle_boost=battle_boost-1 "
                "WHERE guild_id=? AND user_id=?",
                (guild.id, user_id),
            )

    conn.commit()

    description = "\n".join(lines)
    description += (
        f"\n\n🏆 **Winner:** <@{winner_id}> ({wins_a}-{wins_b})"
        f"\n🪙 Winner reward: **{reward_winner} FC**"
        f"\n🪙 Other player reward: **{reward_loser} FC**"
    )

    if level_messages:
        description += "\n\n✨ **Level-ups**\n" + "\n".join(level_messages[:6])

    description += "\n\n🌱 Planted flowers gain battle XP. Plant your flowers to train them!"

    return make_embed(
        "⚔️ Flower Battle Results",
        description,
        discord.Color.gold(),
    ), None


class BattleChallengeView(discord.ui.View):
    def __init__(self, guild_id, challenger_id, defender_id):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.defender_id:
            await interaction.response.send_message(
                embed=make_embed(
                    "Not your challenge",
                    "Only the challenged player can respond.",
                    discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Accept Battle",
        style=discord.ButtonStyle.success,
        emoji="⚔️",
    )
    async def accept(self, interaction, button):
        if self.finished:
            await interaction.response.send_message(
                embed=make_embed("Challenge closed", "This challenge has ended."),
                ephemeral=True,
            )
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                embed=make_embed("Server only", "Battles take place in a server."),
                ephemeral=True,
            )
            return

        embed, error = await run_battle(
            guild,
            self.challenger_id,
            self.defender_id,
        )

        self.finished = True

        for child in self.children:
            child.disabled = True

        if error:
            await interaction.response.edit_message(
                embed=make_embed("Battle unavailable", error, discord.Color.red()),
                view=self,
            )
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Decline",
        style=discord.ButtonStyle.danger,
        emoji="✖️",
    )
    async def decline(self, interaction, button):
        self.finished = True

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=make_embed(
                "Battle declined",
                f"<@{self.defender_id}> declined the battle challenge.",
            ),
            view=self,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ==================== PREFIX COMMANDS ====================

@bot.command(name="help")
async def help_command(ctx):
    p = ctx.prefix

    description = (
        f"**Server prefix:** `{p}`\n\n"
        f"**START & PROFILE**\n"
        f"`{p}hunt` — Find a flower\n"
        f"`{p}profile [@user]` — View profile\n"
        f"`{p}coins` — Check coins\n"
        f"`{p}daily` — Daily coins\n"
        f"`{p}inventory` — View flowers\n"
        f"`{p}flower <id>` — Inspect flower\n\n"
        f"**GARDEN**\n"
        f"`{p}garden` — View garden\n"
        f"`{p}plant <id>` — Plant flower\n"
        f"`{p}unplant <id>` — Store flower\n"
        f"`{p}gardenupgrade` — Upgrade garden\n"
        f"`{p}sell <id|all>` — Sell flowers\n\n"
        f"**BATTLE TEAM**\n"
        f"`{p}team` — View battle team\n"
        f"`{p}teamadd <id>` — Add flower\n"
        f"`{p}teamremove <slot>` — Remove flower\n"
        f"`{p}battle @user` — Challenge player\n\n"
        f"**SHOP & TRADE**\n"
        f"`{p}shop` — Open shop menu\n"
        f"`{p}buy <item_key>` — Buy item\n"
        f"`{p}items` — View items\n"
        f"`{p}use <item_key> [flower_id]` — Use item\n"
        f"`{p}trade @user <flower_id> <coins>` — Offer flower\n"
        f"`{p}tradeaccept <offer_id>` — Accept offer\n"
        f"`{p}tradecancel <offer_id>` — Cancel offer\n\n"
        f"**OTHER**\n"
        f"`{p}leaderboard` — Top players\n"
        f"`{p}setprefix <prefix>` — Change prefix (admin)\n"
        f"`{p}prefix` — Show prefix\n"
        f"`{p}privacy` — View privacy policy\n"
        f"`{p}release <flower_id>` — Release flower"
    )

    await ctx.send(embed=make_embed("🌸 Flower Bot Command Guide", description, discord.Color.blurple()))


@bot.command(name="privacy")
async def privacy_command(ctx):
    await send_privacy_policy(ctx)


@bot.command(name="setprefix")
async def setprefix(ctx, new_prefix: str):
    if not is_admin_or_owner(ctx):
        await send_embed(
            ctx,
            "Permission denied",
            "Only this server's owner or an administrator can change the prefix.",
            discord.Color.red(),
        )
        return

    if (
        not 1 <= len(new_prefix) <= 5
        or any(ch.isspace() for ch in new_prefix)
        or "@" in new_prefix
    ):
        await send_embed(
            ctx,
            "Invalid prefix",
            "Choose a prefix of 1–5 characters with no spaces or @ symbol.",
            discord.Color.red(),
        )
        return

    conn.execute(
        "INSERT INTO guild_settings (guild_id,prefix) VALUES (?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix",
        (ctx.guild.id, new_prefix),
    )
    conn.commit()

    await send_embed(
        ctx,
        "Prefix updated ✅",
        f"New prefix: `{new_prefix}`. Example: `{new_prefix}help`.",
        discord.Color.green(),
    )


@bot.command(name="prefix")
async def prefix_command(ctx):
    await send_embed(
        ctx,
        "Server prefix",
        f"This server's prefix is `{get_prefix_for_guild(ctx.guild.id)}`.",
    )


@bot.command(name="profile")
async def profile(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    player = get_player(ctx.guild.id, member.id)
    garden = garden_info(player["garden_tier"])

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM flowers WHERE guild_id=? AND owner_id=?",
        (ctx.guild.id, member.id),
    ).fetchone()["n"]

    planted = conn.execute(
        "SELECT COUNT(*) AS n FROM flowers WHERE guild_id=? AND owner_id=? AND planted=1",
        (ctx.guild.id, member.id),
    ).fetchone()["n"]

    embed = make_embed(
        f"🌸 {member.display_name}'s Flower Profile",
        f"🪙 Flower Coins: **{player['coins']:,}**\n"
        f"🌷 Flowers owned: **{total}**\n"
        f"🌱 Planted: **{planted}/{garden['capacity']}**\n"
        f"🏡 Garden: **{garden['name']}** (Tier {player['garden_tier']})",
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="coins", aliases=["balance"])
async def coins(ctx):
    player = get_player(ctx.guild.id, ctx.author.id)
    booster = "Active ✨" if player["coin_boost_until"] > time.time() else "Inactive"

    await send_embed(
        ctx,
        "🪙 Flower Coin Wallet",
        f"You have **{player['coins']:,} Flower Coins**.\n"
        f"Coin Booster: **{booster}**",
    )


@bot.command(name="daily")
async def daily(ctx):
    player = get_player(ctx.guild.id, ctx.author.id)
    today = time.strftime("%Y-%m-%d", time.gmtime())

    if player["last_daily"] == today:
        await send_embed(
            ctx,
            "Daily reward already claimed",
            "Come back after the daily reset for another reward.",
            discord.Color.orange(),
        )
        return

    conn.execute(
        "UPDATE players SET coins=coins+150,last_daily=? WHERE guild_id=? AND user_id=?",
        (today, ctx.guild.id, ctx.author.id),
    )
    conn.commit()

    await send_embed(
        ctx,
        "🎁 Daily Flower Coins",
        "You received **150 Flower Coins**!",
        discord.Color.green(),
    )


@bot.command(name="hunt")
async def hunt(ctx):
    player = get_player(ctx.guild.id, ctx.author.id)
    now = time.time()

    if (
        player["last_hunt"] + HUNT_COOLDOWN > now
        and not player["skip_hunt_cooldown"]
    ):
        remaining = int(player["last_hunt"] + HUNT_COOLDOWN - now)

        await send_embed(
            ctx,
            "🌿 The meadow needs time",
            f"You can hunt again in **{remaining} seconds**.",
            discord.Color.orange(),
        )
        return

    lucky = player["luck_hunts"] > 0
    rare_capsule = player["rare_hunt"] > 0

    rarity = roll_hunt(lucky=lucky, rare_capsule=rare_capsule)
    flower_id = add_flower(ctx.guild.id, ctx.author.id, rarity)
    coin_reward = add_coins(ctx.guild.id, ctx.author.id, 5)

    conn.execute(
        "UPDATE players SET last_hunt=?,luck_hunts=MAX(0,luck_hunts-1),"
        "rare_hunt=0,skip_hunt_cooldown=0 WHERE guild_id=? AND user_id=?",
        (now, ctx.guild.id, ctx.author.id),
    )
    conn.commit()

    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    embed = make_embed(
        "🌸 A flower was discovered!",
        f"You found {RARITIES[rarity]['emoji']} **{flower['name']}**!\n"
        f"Rarity: **{rarity}**\n"
        f"Flower ID: `#{flower_id}`\n"
        f"Estimated sell value: **{flower_value(flower):,} FC**\n"
        f"Hunt bonus: **{coin_reward} FC**",
        discord.Color.gold()
        if rarity in ("Legendary", "Electro")
        else COLOR,
    )

    if rarity == "Electro":
        embed.add_field(
            name="⚡ Ultra-rare discovery!",
            value="Electro flowers have only a **0.01%** base hunt chance!",
            inline=False,
        )

    await ctx.send(embed=embed)


@bot.command(name="inventory", aliases=["inv"])
async def inventory(ctx):
    update_flower_growth(ctx.guild.id, ctx.author.id)

    flowers = conn.execute(
        "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? ORDER BY id DESC LIMIT 20",
        (ctx.guild.id, ctx.author.id),
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM flowers WHERE guild_id=? AND owner_id=?",
        (ctx.guild.id, ctx.author.id),
    ).fetchone()["n"]

    if not flowers:
        await send_embed(ctx, "🎒 Empty flower bag", "Use `hunt` to find your first flower.")
        return

    description = "\n\n".join(format_flower(f) for f in flowers)

    if total > len(flowers):
        description += f"\n\nShowing newest **20** of **{total}** flowers."

    await send_embed(
        ctx,
        f"🎒 {ctx.author.display_name}'s Flower Collection",
        description,
    )


@bot.command(name="flower")
async def flower_info(ctx, flower_id: int):
    update_flower_growth(ctx.guild.id, ctx.author.id, flower_id)

    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(
            ctx,
            "Flower not found",
            "That flower ID is not in your collection.",
            discord.Color.red(),
        )
        return

    threshold = 100 + flower["level"] * 35

    next_evo = (
        "Fully evolved"
        if flower["evolution"] >= 3
        else f"Next evolution at {EVOLUTION_THRESHOLDS[flower['evolution']] // 3600}h planted time"
    )

    await send_embed(
        ctx,
        f"{RARITIES[flower['rarity']]['emoji']} {flower['name']} — #{flower_id}",
        f"Rarity: **{flower['rarity']}**\n"
        f"Level: **{flower['level']}**\n"
        f"XP: **{flower['xp']}/{threshold}**\n"
        f"Evolution: **{EVOLUTION_NAMES[flower['evolution']]}**\n"
        f"Garden growth: **{int(flower['growth_seconds'] // 3600)} hours**\n"
        f"Status: **{'Planted' if flower['planted'] else 'Stored'}**\n"
        f"Sell value: **{flower_value(flower):,} FC**\n"
        f"{next_evo}",
    )


@bot.command(name="garden")
async def garden(ctx):
    update_flower_growth(ctx.guild.id, ctx.author.id)

    player = get_player(ctx.guild.id, ctx.author.id)
    info = garden_info(player["garden_tier"])

    flowers = conn.execute(
        "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? AND planted=1 ORDER BY id",
        (ctx.guild.id, ctx.author.id),
    ).fetchall()

    lines = [format_flower(f) for f in flowers[:15]]

    description = (
        f"🏡 **{info['name']}** — Tier {player['garden_tier']}\n"
        f"Capacity: **{len(flowers)}/{info['capacity']} plants**\n\n"
    )

    description += (
        "\n\n".join(lines)
        if lines
        else "Your garden is empty. Use `plant <flower_id>` to plant a flower."
    )

    if len(flowers) > 15:
        description += f"\n\nShowing 15 of {len(flowers)} planted flowers."

    description += "\n\n🌱 Flowers evolve only while planted."

    await send_embed(ctx, "🌻 Your Garden", description)


@bot.command(name="plant")
async def plant(ctx, flower_id: int):
    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(ctx, "Flower not found", "That flower does not belong to you.", discord.Color.red())
        return

    if flower["planted"]:
        await send_embed(ctx, "Already planted", f"**{flower['name']}** is already in your garden.")
        return

    player = get_player(ctx.guild.id, ctx.author.id)
    info = garden_info(player["garden_tier"])

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM flowers WHERE guild_id=? AND owner_id=? AND planted=1",
        (ctx.guild.id, ctx.author.id),
    ).fetchone()["n"]

    if count >= info["capacity"]:
        await send_embed(
            ctx,
            "Garden is full",
            f"Your **{info['name']}** holds {info['capacity']} plants. Upgrade your garden to plant more.",
            discord.Color.orange(),
        )
        return

    conn.execute(
        "UPDATE flowers SET planted=1,last_growth_at=? WHERE id=?",
        (time.time(), flower_id),
    )
    conn.commit()

    await send_embed(
        ctx,
        "🌱 Flower planted!",
        f"**{flower['name']}** is now growing in your garden. It will evolve while planted.",
        discord.Color.green(),
    )


@bot.command(name="unplant")
async def unplant(ctx, flower_id: int):
    update_flower_growth(ctx.guild.id, ctx.author.id, flower_id)
    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(ctx, "Flower not found", "That flower does not belong to you.", discord.Color.red())
        return

    if not flower["planted"]:
        await send_embed(ctx, "Not planted", "That flower is already stored in your collection.")
        return

    conn.execute(
        "UPDATE flowers SET planted=0,last_growth_at=0 WHERE id=?",
        (flower_id,),
    )
    conn.commit()

    await send_embed(
        ctx,
        "📦 Flower stored",
        f"**{flower['name']}** has been unplanted. Its current evolution is saved, but it will not grow while stored.",
    )


@bot.command(name="gardenupgrade", aliases=["upgradegarden"])
async def gardenupgrade(ctx):
    player = get_player(ctx.guild.id, ctx.author.id)
    current = player["garden_tier"]

    if current >= 4:
        await send_embed(
            ctx,
            "Garden fully upgraded",
            "Your garden has reached the highest tier: **Eternal Garden**.",
        )
        return

    next_tier = current + 1
    target = garden_info(next_tier)
    cost = target["cost"]
    discount_used = bool(player["garden_discount"])

    if discount_used:
        cost = int(cost * 0.75)

    if player["coins"] < cost:
        await send_embed(
            ctx,
            "Not enough Flower Coins",
            f"Upgrade to **{target['name']}** requires **{cost:,} FC**. "
            f"Your balance: **{player['coins']:,} FC**.",
            discord.Color.red(),
        )
        return

    conn.execute(
        "UPDATE players SET coins=coins-?,garden_tier=?,garden_discount=0 "
        "WHERE guild_id=? AND user_id=?",
        (cost, next_tier, ctx.guild.id, ctx.author.id),
    )
    conn.commit()

    extra = " Your Garden Voucher discount was used." if discount_used else ""

    await send_embed(
        ctx,
        "🏡 Garden upgraded!",
        f"Your garden is now **{target['name']}** (Tier {next_tier}) "
        f"and can hold **{target['capacity']} plants**.\n"
        f"Spent: **{cost:,} FC**.{extra}",
        discord.Color.green(),
    )


@bot.command(name="sell")
async def sell(ctx, target: str):
    if target.lower() == "all":
        flowers = conn.execute(
            "SELECT * FROM flowers WHERE guild_id=? AND owner_id=? AND planted=0",
            (ctx.guild.id, ctx.author.id),
        ).fetchall()
    else:
        try:
            flower_id = int(target)
        except ValueError:
            await send_embed(
                ctx,
                "Invalid flower ID",
                "Use `sell <flower_id>` or `sell all` (only stored flowers are sold in bulk).",
                discord.Color.red(),
            )
            return

        flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

        if not flower:
            await send_embed(ctx, "Flower not found", "That flower does not belong to you.", discord.Color.red())
            return

        if flower["planted"]:
            await send_embed(
                ctx,
                "Flower is planted",
                "Unplant it first with `unplant <flower_id>` before selling it.",
                discord.Color.orange(),
            )
            return

        flowers = [flower]

    if not flowers:
        await send_embed(ctx, "Nothing to sell", "You have no eligible stored flowers to sell.")
        return

    ids = [f["id"] for f in flowers]
    placeholders = ",".join("?" for _ in ids)

    pending = conn.execute(
        f"SELECT COUNT(*) AS n FROM trades WHERE guild_id=? "
        f"AND flower_id IN ({placeholders}) AND status='pending'",
        [ctx.guild.id] + ids,
    ).fetchone()["n"]

    if pending:
        await send_embed(
            ctx,
            "Flower has a pending trade",
            "Cancel or complete its trade before selling it.",
            discord.Color.orange(),
        )
        return

    total = sum(flower_value(f) for f in flowers)

    for flower in flowers:
        remove_flower_from_team(ctx.guild.id, flower["id"])

    conn.execute(
        f"DELETE FROM flowers WHERE guild_id=? AND owner_id=? AND id IN ({placeholders})",
        [ctx.guild.id, ctx.author.id] + ids,
    )
    conn.commit()

    earned = add_coins(ctx.guild.id, ctx.author.id, total)

    await send_embed(
        ctx,
        "💰 Flowers sold",
        f"Sold **{len(flowers)}** flower(s) for **{earned:,} Flower Coins**.",
        discord.Color.green(),
    )


@bot.command(name="team")
async def team(ctx):
    team_flowers = get_team(ctx.guild.id, ctx.author.id)
    slots = {f["slot"]: f for f in team_flowers}
    lines = []

    for slot in range(1, 4):
        flower = slots.get(slot)

        if flower:
            lines.append(
                f"**Slot {slot}:** {RARITIES[flower['rarity']]['emoji']} "
                f"{flower['name']} — {flower['rarity']} • Lv. {flower['level']} "
                f"• {'Planted' if flower['planted'] else 'Stored'} • ID `#{flower['id']}`"
            )
        else:
            lines.append(f"**Slot {slot}:** Empty")

    await send_embed(
        ctx,
        "⚔️ Your Battle Team",
        "\n".join(lines) + "\n\nAdd flowers with `teamadd <flower_id>`. You need 3 flowers to challenge someone.",
    )


@bot.command(name="teamadd")
async def teamadd(ctx, flower_id: int):
    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(ctx, "Flower not found", "That flower does not belong to you.", discord.Color.red())
        return

    existing = get_team(ctx.guild.id, ctx.author.id)

    if any(f["id"] == flower_id for f in existing):
        await send_embed(ctx, "Already in team", "That flower is already in your battle team.")
        return

    if len(existing) >= 3:
        await send_embed(
            ctx,
            "Team is full",
            "Your team can contain only 3 flowers. Use `teamremove <slot>` first.",
            discord.Color.orange(),
        )
        return

    used_slots = [f["slot"] for f in existing]
    slot = next(s for s in (1, 2, 3) if s not in used_slots)

    conn.execute(
        "INSERT INTO team_slots (guild_id,user_id,slot,flower_id) VALUES (?,?,?,?)",
        (ctx.guild.id, ctx.author.id, slot, flower_id),
    )
    conn.commit()

    await send_embed(
        ctx,
        "⚔️ Flower added",
        f"**{flower['name']}** has been added to battle slot **{slot}**.",
        discord.Color.green(),
    )


@bot.command(name="teamremove")
async def teamremove(ctx, slot: int):
    if slot not in (1, 2, 3):
        await send_embed(ctx, "Invalid slot", "Choose slot 1, 2 or 3.", discord.Color.red())
        return

    row = conn.execute(
        "SELECT flower_id FROM team_slots WHERE guild_id=? AND user_id=? AND slot=?",
        (ctx.guild.id, ctx.author.id, slot),
    ).fetchone()

    if not row:
        await send_embed(ctx, "Empty slot", f"Team slot {slot} is already empty.")
        return

    conn.execute(
        "DELETE FROM team_slots WHERE guild_id=? AND user_id=? AND slot=?",
        (ctx.guild.id, ctx.author.id, slot),
    )
    conn.commit()

    await send_embed(
        ctx,
        "Flower removed",
        f"Removed flower `#{row['flower_id']}` from slot {slot}.",
    )


@bot.command(name="battle", aliases=["duel"])
async def battle(ctx, opponent: discord.Member):
    if opponent.bot or opponent.id == ctx.author.id:
        await send_embed(
            ctx,
            "Invalid opponent",
            "Choose another human player from this server.",
            discord.Color.red(),
        )
        return

    if len(get_team(ctx.guild.id, ctx.author.id)) != 3:
        await send_embed(
            ctx,
            "Your team is incomplete",
            "Add 3 flowers with `teamadd <flower_id>` before battling.",
            discord.Color.orange(),
        )
        return

    if len(get_team(ctx.guild.id, opponent.id)) != 3:
        await send_embed(
            ctx,
            "Opponent team is incomplete",
            f"{opponent.mention} needs to add 3 flowers to their battle team first.",
            discord.Color.orange(),
        )
        return

    view = BattleChallengeView(ctx.guild.id, ctx.author.id, opponent.id)

    await ctx.send(
        embed=make_embed(
            "⚔️ Flower Battle Challenge",
            f"{ctx.author.mention} challenged {opponent.mention}!\n\n"
            "The challenged player has 120 seconds to accept or decline.",
        ),
        view=view,
    )


@bot.command(name="shop")
async def shop(ctx):
    player = get_player(ctx.guild.id, ctx.author.id)

    lines = []

    for key, item in SHOP.items():
        lines.append(
            f"**{item['name']}** — {item['price']:,} FC\n"
            f"{item['description']}\nKey: `{key}`"
        )

    embed = make_embed(
        "🛍️ Flower Shop",
        f"Your balance: **{player['coins']:,} FC**\n\n"
        + "\n\n".join(lines)
        + "\n\nChoose an item from the select menu below to buy it.",
    )

    await ctx.send(embed=embed, view=ShopView())


@bot.command(name="buy")
async def buy(ctx, item_key: str):
    item_key = item_key.lower()

    ok, message = await purchase_item(
        ctx.guild.id,
        ctx.author.id,
        item_key,
    )

    await send_embed(
        ctx,
        "Purchase complete" if ok else "Purchase failed",
        message,
        discord.Color.green() if ok else discord.Color.red(),
    )


@bot.command(name="items", aliases=["bag"])
async def items(ctx):
    rows = conn.execute(
        "SELECT item_key,quantity FROM player_items "
        "WHERE guild_id=? AND user_id=? AND quantity>0 ORDER BY item_key",
        (ctx.guild.id, ctx.author.id),
    ).fetchall()

    if not rows:
        await send_embed(
            ctx,
            "🎒 Item bag",
            "You do not own any shop items yet. Visit the shop to buy some.",
        )
        return

    lines = []

    for row in rows:
        item = SHOP[row["item_key"]]
        lines.append(
            f"**{item['name']}** × {row['quantity']} — `{row['item_key']}`"
        )

    await send_embed(
        ctx,
        "🎒 Your Shop Items",
        "\n".join(lines) + "\n\nUse `use <item_key> [flower_id]` to activate an item.",
    )


@bot.command(name="use")
async def use_item(ctx, item_key: str, flower_id: Optional[int] = None):
    item_key = item_key.lower()

    if item_key not in SHOP:
        await send_embed(ctx, "Unknown item", "Use `items` to see your item keys.", discord.Color.red())
        return

    if get_item_count(ctx.guild.id, ctx.author.id, item_key) < 1:
        await send_embed(ctx, "Item not owned", f"You do not have `{item_key}` in your bag.", discord.Color.red())
        return

    player = get_player(ctx.guild.id, ctx.author.id)
    success_text = ""

    if item_key == "luck_booster":
        take_item(ctx.guild.id, ctx.author.id, item_key)
        conn.execute(
            "UPDATE players SET luck_hunts=luck_hunts+5 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )
        success_text = "Your next **5 hunts** have improved rarity odds."

    elif item_key == "coin_booster":
        take_item(ctx.guild.id, ctx.author.id, item_key)
        until = max(time.time(), player["coin_boost_until"]) + 1800

        conn.execute(
            "UPDATE players SET coin_boost_until=? WHERE guild_id=? AND user_id=?",
            (until, ctx.guild.id, ctx.author.id),
        )
        success_text = "You will earn **50% more Flower Coins** for 30 minutes."

    elif item_key == "xp_nectar":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        conn.execute(
            "UPDATE players SET xp_boost_battles=xp_boost_battles+3 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )
        success_text = "Your planted flowers get **double battle XP** for the next 3 battles."

    elif item_key in ("growth_fertilizer", "golden_can"):
        if flower_id is None:
            await send_embed(
                ctx,
                "Flower ID needed",
                f"Use `use {item_key} <flower_id>` for a planted flower.",
                discord.Color.orange(),
            )
            return

        flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

        if not flower or not flower["planted"]:
            await send_embed(
                ctx,
                "Flower must be planted",
                "Choose one of your currently planted flowers.",
                discord.Color.orange(),
            )
            return

        update_flower_growth(ctx.guild.id, ctx.author.id, flower_id)

        seconds = 6 * 3600 if item_key == "growth_fertilizer" else 24 * 3600

        take_item(ctx.guild.id, ctx.author.id, item_key)

        current = get_flower(ctx.guild.id, ctx.author.id, flower_id)
        new_growth = current["growth_seconds"] + seconds
        new_evo = sum(
            1 for threshold in EVOLUTION_THRESHOLDS
            if new_growth >= threshold
        )

        conn.execute(
            "UPDATE flowers SET growth_seconds=?,evolution=? WHERE id=?",
            (new_growth, new_evo, flower_id),
        )

        success_text = (
            f"Added **{seconds // 3600} hours** of growth to **{flower['name']}**."
        )

    elif item_key == "battle_pollen":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        conn.execute(
            "UPDATE players SET battle_boost=battle_boost+3 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )

        success_text = "Your battle team receives **20% extra power** for the next 3 battles."

    elif item_key == "mystery_seed":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        rarity = roll_hunt(lucky=True)
        new_id = add_flower(ctx.guild.id, ctx.author.id, rarity)
        new_flower = get_flower(ctx.guild.id, ctx.author.id, new_id)

        success_text = (
            f"Your Mystery Seed grew into "
            f"{RARITIES[rarity]['emoji']} **{new_flower['name']}** "
            f"({rarity}) — ID `#{new_id}`."
        )

    elif item_key == "cooldown_charm":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        conn.execute(
            "UPDATE players SET skip_hunt_cooldown=1 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )

        success_text = "Your next hunt will skip its cooldown."

    elif item_key == "garden_voucher":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        conn.execute(
            "UPDATE players SET garden_discount=1 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )

        success_text = "Your next garden upgrade will cost **25% less**."

    elif item_key == "rare_bloom_capsule":
        take_item(ctx.guild.id, ctx.author.id, item_key)

        conn.execute(
            "UPDATE players SET rare_hunt=1 WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )

        success_text = "Your next hunt will use boosted rarity odds."

    conn.commit()

    await send_embed(
        ctx,
        "✨ Item activated",
        success_text,
        discord.Color.green(),
    )


@bot.command(name="trade")
async def trade(ctx, buyer: discord.Member, flower_id: int, price: int):
    if buyer.bot or buyer.id == ctx.author.id:
        await send_embed(
            ctx,
            "Invalid trade partner",
            "Choose another human player in this server.",
            discord.Color.red(),
        )
        return

    if price < 0 or price > 100000000:
        await send_embed(
            ctx,
            "Invalid price",
            "Choose a price from 0 to 100,000,000 Flower Coins.",
            discord.Color.red(),
        )
        return

    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(ctx, "Flower not found", "That flower does not belong to you.", discord.Color.red())
        return

    if flower["planted"]:
        await send_embed(
            ctx,
            "Unplant the flower first",
            "Use `unplant <flower_id>` before offering it in a trade.",
            discord.Color.orange(),
        )
        return

    pending = conn.execute(
        "SELECT id FROM trades WHERE guild_id=? AND flower_id=? AND status='pending'",
        (ctx.guild.id, flower_id),
    ).fetchone()

    if pending:
        await send_embed(
            ctx,
            "Already listed",
            "That flower already has a pending trade offer.",
            discord.Color.orange(),
        )
        return

    cur = conn.execute(
        "INSERT INTO trades (guild_id,seller_id,buyer_id,flower_id,price,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (ctx.guild.id, ctx.author.id, buyer.id, flower_id, price, time.time()),
    )

    conn.commit()
    trade_id = cur.lastrowid

    await send_embed(
        ctx,
        "🤝 Flower trade offer created",
        f"Offer ID: **#{trade_id}**\n"
        f"Seller: {ctx.author.mention}\n"
        f"Buyer: {buyer.mention}\n"
        f"Flower: {RARITIES[flower['rarity']]['emoji']} **{flower['name']}** "
        f"({flower['rarity']}, Lv. {flower['level']})\n"
        f"Price: **{price:,} Flower Coins**\n\n"
        f"The buyer can accept with `tradeaccept {trade_id}`. Offer expires in 15 minutes.",
    )


@bot.command(name="tradeaccept")
async def tradeaccept(ctx, offer_id: int):
    offer = conn.execute(
        "SELECT * FROM trades WHERE id=? AND guild_id=? AND status='pending'",
        (offer_id, ctx.guild.id),
    ).fetchone()

    if not offer:
        await send_embed(
            ctx,
            "Offer not found",
            "That trade offer is no longer available.",
            discord.Color.red(),
        )
        return

    if offer["buyer_id"] != ctx.author.id:
        await send_embed(
            ctx,
            "Not your offer",
            "Only the selected buyer can accept this trade.",
            discord.Color.red(),
        )
        return

    if time.time() - offer["created_at"] > TRADE_LIFETIME:
        conn.execute(
            "UPDATE trades SET status='expired' WHERE id=?",
            (offer_id,),
        )
        conn.commit()

        await send_embed(
            ctx,
            "Offer expired",
            "This trade offer has expired.",
            discord.Color.orange(),
        )
        return

    buyer = get_player(ctx.guild.id, ctx.author.id)
    flower = get_flower(ctx.guild.id, offer["seller_id"], offer["flower_id"])

    if not flower or flower["planted"]:
        conn.execute(
            "UPDATE trades SET status='cancelled' WHERE id=?",
            (offer_id,),
        )
        conn.commit()

        await send_embed(
            ctx,
            "Trade cancelled",
            "The flower is no longer available.",
            discord.Color.red(),
        )
        return

    if buyer["coins"] < offer["price"]:
        await send_embed(
            ctx,
            "Not enough Flower Coins",
            f"You need **{offer['price']:,} FC** but have **{buyer['coins']:,} FC**.",
            discord.Color.red(),
        )
        return

    conn.execute(
        "UPDATE players SET coins=coins-? WHERE guild_id=? AND user_id=?",
        (offer["price"], ctx.guild.id, ctx.author.id),
    )

    conn.execute(
        "UPDATE players SET coins=coins+? WHERE guild_id=? AND user_id=?",
        (offer["price"], ctx.guild.id, offer["seller_id"]),
    )

    conn.execute(
        "UPDATE flowers SET owner_id=? WHERE id=?",
        (ctx.author.id, offer["flower_id"]),
    )

    conn.execute(
        "UPDATE trades SET status='completed' WHERE id=?",
        (offer_id,),
    )

    remove_flower_from_team(ctx.guild.id, offer["flower_id"])
    conn.commit()

    await send_embed(
        ctx,
        "✅ Trade completed",
        f"You purchased **{flower['name']}** from <@{offer['seller_id']}> "
        f"for **{offer['price']:,} Flower Coins**.",
        discord.Color.green(),
    )


@bot.command(name="tradecancel")
async def tradecancel(ctx, offer_id: int):
    offer = conn.execute(
        "SELECT * FROM trades WHERE id=? AND guild_id=? AND status='pending'",
        (offer_id, ctx.guild.id),
    ).fetchone()

    if not offer or offer["seller_id"] != ctx.author.id:
        await send_embed(
            ctx,
            "Offer not found",
            "You do not own that pending trade offer.",
            discord.Color.red(),
        )
        return

    conn.execute(
        "UPDATE trades SET status='cancelled' WHERE id=?",
        (offer_id,),
    )
    conn.commit()

    await send_embed(
        ctx,
        "Trade cancelled",
        f"Offer **#{offer_id}** has been cancelled.",
    )


@bot.command(name="leaderboard", aliases=["top"])
async def leaderboard(ctx):
    rows = conn.execute(
        "SELECT user_id,coins FROM players WHERE guild_id=? ORDER BY coins DESC LIMIT 10",
        (ctx.guild.id,),
    ).fetchall()

    if not rows:
        await send_embed(ctx, "Flower Coin Leaderboard", "No players yet.")
        return

    lines = []
    medals = ["🥇", "🥈", "🥉"]

    for index, row in enumerate(rows):
        member = ctx.guild.get_member(row["user_id"])
        name = member.display_name if member else f"User {row['user_id']}"
        medal = medals[index] if index < 3 else f"**{index + 1}.**"
        lines.append(f"{medal} **{name}** — {row['coins']:,} FC")

    await send_embed(
        ctx,
        "🏆 Flower Coin Leaderboard",
        "\n".join(lines),
    )


@bot.command(name="release")
async def release(ctx, flower_id: int):
    flower = get_flower(ctx.guild.id, ctx.author.id, flower_id)

    if not flower:
        await send_embed(
            ctx,
            "Flower not found",
            "That flower does not belong to you.",
            discord.Color.red(),
        )
        return

    pending = conn.execute(
        "SELECT id FROM trades WHERE guild_id=? AND flower_id=? AND status='pending'",
        (ctx.guild.id, flower_id),
    ).fetchone()

    if pending:
        await send_embed(
            ctx,
            "Pending trade",
            "Cancel the flower's trade offer before releasing it.",
            discord.Color.orange(),
        )
        return

    remove_flower_from_team(ctx.guild.id, flower_id)

    conn.execute(
        "DELETE FROM flowers WHERE id=?",
        (flower_id,),
    )
    conn.commit()

    await send_embed(
        ctx,
        "🍃 Flower released",
        f"**{flower['name']}** has been released from your collection. No coins were earned.",
    )


# ==================== ERRORS & STARTUP ====================

@bot.event
async def on_ready():
    print(f"Flower Bot is online as {bot.user} (ID: {bot.user.id})")
    print("Prefix-only mode is active. No slash commands are registered or synced.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await send_embed(
            ctx,
            "Missing information",
            f"Please provide: **{error.param.name}**. Use `{ctx.prefix}help` for examples.",
            discord.Color.orange(),
        )

    elif isinstance(error, commands.BadArgument):
        await send_embed(
            ctx,
            "Invalid input",
            f"One of the values was invalid. Use `{ctx.prefix}help` for examples.",
            discord.Color.red(),
        )

    elif isinstance(error, commands.NoPrivateMessage):
        await send_embed(
            ctx,
            "Server only",
            "Flower Bot game commands are available inside servers.",
            discord.Color.orange(),
        )

    elif isinstance(error, commands.CheckFailure):
        return

    else:
        print(f"Command error in {ctx.command}: {repr(error)}")

        await send_embed(
            ctx,
            "Something went wrong",
            "The command could not be completed. Check the bot console for details.",
            discord.Color.red(),
        )


@bot.check
async def server_only_check(ctx):
    return ctx.guild is not None


# ==================== BOT TOKEN ====================

TOKEN = os.getenv(
    "DISCORD_TOKEN",
    " 
    ",
)

if __name__ == "__main__":
    if not TOKEN or TOKEN == "PASTE_YOUR_DISCORD_BOT_TOKEN_HERE":
        raise SystemExit(
            "Missing bot token. Set the DISCORD_TOKEN environment variable "
            "or replace the TOKEN placeholder at the bottom of flower_bot.py."
        )

    bot.run(TOKEN)
