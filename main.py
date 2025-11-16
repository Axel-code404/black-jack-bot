import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import aiohttp
import asyncio
import random
from PIL import Image, ImageDraw
import io
import json

TOKEN = ""

CARD_DIR = "cards"
if not os.path.exists(CARD_DIR):
    os.makedirs(CARD_DIR)

SUITS = {"C": "clubs", "D": "diamonds", "H": "hearts", "S": "spades"}
RANKS = ["A","2","3","4","5","6","7","8","9","0","J","Q","K"]  # 0は10

CHANNELS_FILE = "bj_channels.json"
HISTORY_FILE = "bj_history.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

def load_channels():
    if os.path.isfile(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return []

def save_channels(channels):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

def load_history():
    if os.path.isfile(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def card_code(rank, suit):
    return f"{rank}{suit}"

async def download_card_image(session, code):
    url = f"https://deckofcardsapi.com/static/img/{code}.png"
    save_path = os.path.join(CARD_DIR, f"{code}.png")
    if not os.path.isfile(save_path):
        async with session.get(url) as resp:
            if resp.status == 200:
                img_data = await resp.read()
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print(f"Downloaded {code}.png")
            else:
                print(f"Failed to download {code}.png")

async def download_back_image(session):
    url = "https://deckofcardsapi.com/static/img/back.png"
    save_path = os.path.join(CARD_DIR, "back.png")
    if not os.path.isfile(save_path):
        async with session.get(url) as resp:
            if resp.status == 200:
                img_data = await resp.read()
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print("Downloaded back.png")
            else:
                print("Failed to download back.png")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    async with aiohttp.ClientSession() as session:
        tasks_dl = []
        for suit in SUITS.keys():
            for rank in RANKS:
                code = card_code(rank, suit)
                tasks_dl.append(download_card_image(session, code))
        tasks_dl.append(download_back_image(session))
        await asyncio.gather(*tasks_dl)
    print("All card images downloaded or already exist.")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

def card_value(card_rank):
    if card_rank in ["J","Q","K","0"]:
        return 10
    elif card_rank == "A":
        return 11
    else:
        return int(card_rank)

def hand_value(cards):
    value = 0
    aces = 0
    for c in cards:
        rank = c[0]
        v = card_value(rank)
        value += v
        if rank == "A":
            aces += 1
    while value > 21 and aces > 0:
        value -= 10
        aces -= 1
    return value

def combine_cards_image(player_cards, dealer_cards, hide_dealer_second=True):
    CARD_W, CARD_H = 226, 314
    GAP = 20
    PADDING = 30

    max_cards = max(len(player_cards), len(dealer_cards))
    width = max_cards * (CARD_W + GAP) - GAP + PADDING * 2
    height = CARD_H * 2 + GAP + PADDING * 2

    table_green = (0, 100, 0)
    img = Image.new("RGBA", (width, height), table_green)
    draw = ImageDraw.Draw(img)

    def load_card_image(code):
        path = os.path.join(CARD_DIR, f"{code}.png")
        return Image.open(path).convert("RGBA")

    back_path = os.path.join(CARD_DIR, "back.png")
    back_img = Image.open(back_path).convert("RGBA")

    for i, c in enumerate(player_cards):
        card_img = load_card_image(c)
        x = PADDING + i * (CARD_W + GAP)
        y = PADDING
        img.paste(card_img, (x, y), card_img)

    for i, c in enumerate(dealer_cards):
        x = PADDING + i * (CARD_W + GAP)
        y = PADDING + CARD_H + GAP
        if i == 1 and hide_dealer_second:
            img.paste(back_img, (x, y), back_img)
        else:
            card_img = load_card_image(c)
            img.paste(card_img, (x, y), card_img)

    with io.BytesIO() as image_binary:
        img.save(image_binary, "PNG")
        image_binary.seek(0)
        return image_binary.read()

class BlackjackGame:
    def __init__(self, player_id):
        self.player_id = player_id
        self.deck = self.create_deck()
        random.shuffle(self.deck)
        self.player_cards = []
        self.dealer_cards = []
        self.is_over = False
        self.result = None

        self.player_cards.append(self.deck.pop())
        self.player_cards.append(self.deck.pop())
        self.dealer_cards.append(self.deck.pop())
        self.dealer_cards.append(self.deck.pop())

    def create_deck(self):
        deck = []
        for suit in SUITS.keys():
            for rank in RANKS:
                deck.append(f"{rank}{suit}")
        return deck

    def player_hit(self):
        if not self.is_over:
            self.player_cards.append(self.deck.pop())
            if hand_value(self.player_cards) > 21:
                self.is_over = True
                self.result = "lose"
        return self.is_over

    def player_stand(self):
        while hand_value(self.dealer_cards) < 17:
            self.dealer_cards.append(self.deck.pop())

        p_val = hand_value(self.player_cards)
        d_val = hand_value(self.dealer_cards)

        if d_val > 21 or p_val > d_val:
            self.result = "win"
        elif p_val == d_val:
            self.result = "draw"
        else:
            self.result = "lose"
        self.is_over = True
        return self.result

active_games = {}

history = load_history()

def update_history(user_id, result):
    user_id_str = str(user_id)
    if user_id_str not in history:
        history[user_id_str] = {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "max_streak": 0,
            "current_streak": 0,
            "last_result": None,
        }
    data = history[user_id_str]
    if result == "win":
        data["wins"] += 1
        if data["last_result"] == "win":
            data["current_streak"] += 1
        else:
            data["current_streak"] = 1
        data["max_streak"] = max(data["max_streak"], data["current_streak"])
    elif result == "lose":
        data["losses"] += 1
        data["current_streak"] = 0
    else:
        data["draws"] += 1
        data["current_streak"] = 0
    data["last_result"] = result
    save_history(history)

allowed_channels = load_channels()

def can_play(channel_id):
    return channel_id in allowed_channels or len(allowed_channels) == 0

class BlackjackView(discord.ui.View):
    def __init__(self, game, interaction):
        super().__init__(timeout=120)
        self.game = game
        self.interaction = interaction
        self.message = None

    async def update_message(self):
        p_cards = self.game.player_cards
        d_cards = self.game.dealer_cards
        hide_dealer_second = not self.game.is_over
        img_bytes = combine_cards_image(p_cards, d_cards, hide_dealer_second)
        file = discord.File(io.BytesIO(img_bytes), filename="table.png")

        p_val = hand_value(p_cards)
        d_val = hand_value(d_cards) if self.game.is_over else "?"

        embed = discord.Embed(title="Blackjack Game", description=f"Your hand: {p_val}\nDealer's hand: {d_val}", color=0x2ecc71)
        embed.set_image(url="attachment://table.png")

        if self.game.is_over:
            if self.game.result == "win":
                embed.add_field(name="Result", value="You Win! 🎉", inline=False)
            elif self.game.result == "lose":
                embed.add_field(name="Result", value="You Lose 😢", inline=False)
            else:
                embed.add_field(name="Result", value="Draw", inline=False)
            self.clear_items()

        if self.message is None:
            self.message = await self.interaction.channel.send(embed=embed, file=file, view=None if self.game.is_over else self)
        else:
            await self.message.edit(embed=embed, attachments=[file], view=None if self.game.is_over else self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.player_id:
            await interaction.response.send_message("You are not the player.", ephemeral=True)
            return
        if self.game.is_over:
            await interaction.response.defer()
            return
        self.game.player_hit()
        if self.game.is_over:
            update_history(self.game.player_id, self.game.result)
        await interaction.response.defer()
        await self.update_message()

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.player_id:
            await interaction.response.send_message("You are not the player.", ephemeral=True)
            return
        if self.game.is_over:
            await interaction.response.defer()
            return
        self.game.player_stand()
        update_history(self.game.player_id, self.game.result)
        await interaction.response.defer()
        await self.update_message()

@tree.command(name="ブラックジャック", description="Start a blackjack game")
async def blackjack(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if not can_play(channel_id):
        await interaction.response.send_message("This channel is not allowed for Blackjack. Please ask admin to set allowed channel.", ephemeral=True)
        return

    if interaction.user.id in active_games:
        await interaction.response.send_message("You already have an active game. Finish it first.", ephemeral=True)
        return

    game = BlackjackGame(interaction.user.id)
    active_games[interaction.user.id] = game

    # ここがポイント！
    # defer()は使わず最初にメッセージを送信（必ず最初のレスポンスを送る）
    view = BlackjackView(game, interaction)
    img_bytes = combine_cards_image(game.player_cards, game.dealer_cards, hide_dealer_second=True)
    file = discord.File(io.BytesIO(img_bytes), filename="table.png")

    p_val = hand_value(game.player_cards)
    d_val = "?"

    embed = discord.Embed(title="Blackjack Game", description=f"Your hand: {p_val}\nDealer's hand: {d_val}", color=0x2ecc71)
    embed.set_image(url="attachment://table.png")

    await interaction.response.send_message(embed=embed, file=file, view=view)

    async def wait_game_end():
        while not game.is_over:
            await asyncio.sleep(1)
        active_games.pop(interaction.user.id, None)

    bot.loop.create_task(wait_game_end())

@tree.command(name="ブラックジャックチャンネル", description="Set the allowed channel for blackjack")
@app_commands.checks.has_permissions(administrator=True)
async def blackjack_channel(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id in allowed_channels:
        await interaction.response.send_message("This channel is already allowed.", ephemeral=True)
        return
    allowed_channels.append(channel_id)
    save_channels(allowed_channels)
    await interaction.response.send_message(f"This channel is now allowed for Blackjack commands.")

@tree.command(name="ブラックジャックチャンネル解除", description="Remove allowed blackjack channel")
@app_commands.checks.has_permissions(administrator=True)
async def blackjack_channel_remove(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in allowed_channels:
        await interaction.response.send_message("This channel was not allowed.", ephemeral=True)
        return
    allowed_channels.remove(channel_id)
    save_channels(allowed_channels)
    await interaction.response.send_message(f"Blackjack command is no longer allowed in this channel.")

@tree.command(name="ブラックジャック履歴", description="Show your blackjack game history")
async def blackjack_history(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    data = history.get(user_id_str, None)
    if not data:
        await interaction.response.send_message("No history found.", ephemeral=True)
        return
    embed = discord.Embed(title=f"{interaction.user.display_name}'s Blackjack History", color=0x2ecc71)
    embed.add_field(name="Wins", value=str(data["wins"]), inline=True)
    embed.add_field(name="Losses", value=str(data["losses"]), inline=True)
    embed.add_field(name="Draws", value=str(data["draws"]), inline=True)
    embed.add_field(name="Max Winning Streak", value=str(data["max_streak"]), inline=False)
    await interaction.response.send_message(embed=embed)

@blackjack_channel.error
@blackjack_channel_remove.error
async def admin_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You need administrator permission to run this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)

bot.run(TOKEN)
