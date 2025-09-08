"""
VirtualCrypto Standalone Bot
============================

完全に独立して動作するVirtualCrypto風通貨システム Bot
通貨管理、送金、残高確認、二重仕訳台帳システム

このファイルには以下の機能が含まれます：
- 通貨作成・管理 (/create, /give, /treasury, /delete)
- 送金システム (/pay) 
- 残高確認 (/bal)
- 二重仕訳による台帳管理
- データベース操作関数
- Embed作成関数

必要パッケージ:
  pip install -U discord.py aiosqlite python-dotenv

環境変数設定:
  DISCORD_TOKEN=your_bot_token_here
  GUILD_ID=your_guild_id_here  # 任意：特定サーバーのみで有効化
  VC_DB=virtualcrypto.sqlite3  # 任意：DBファイルパス
"""

import os
import asyncio
import aiosqlite
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

import discord
from discord import app_commands
from discord.ext import commands

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Environment variables must be set manually.")

# 設定
TZ = timezone(timedelta(hours=9))  # 日本標準時（JST）
# このスクリプトと同じフォルダにDBを作成
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("VC_DB", os.path.join(SCRIPT_DIR, "vc_ledger.sqlite3"))
DEFAULT_DECIMALS = 2

# ========================== データベース設定 ==========================

async def ensure_db():
    """データベースの初期化"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 既存のテーブルのスキーマを確認し、必要に応じて修正
        try:
            # assetsテーブルの情報を取得してcreated_atカラムの存在を確認
            cursor = await db.execute("PRAGMA table_info(assets)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # created_atカラムが存在する場合は削除（新しいスキーマに合わせる）
            if 'created_at' in column_names:
                print("[DB] Updating assets table schema...")
                # 新しいテーブルを作成
                await db.execute('''
                    CREATE TABLE assets_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        name TEXT NOT NULL,
                        decimals INTEGER NOT NULL DEFAULT 2,
                        UNIQUE(guild_id, symbol)
                    )
                ''')
                
                # データを移行
                await db.execute('''
                    INSERT INTO assets_new (id, guild_id, symbol, name, decimals)
                    SELECT id, guild_id, symbol, name, decimals FROM assets
                ''')
                
                # 古いテーブルを削除し、新しいテーブルをリネーム
                await db.execute('DROP TABLE assets')
                await db.execute('ALTER TABLE assets_new RENAME TO assets')
                print("[DB] Assets table schema updated successfully")
        except:
            # テーブルが存在しない場合は通常の作成処理
            pass
        
        # accountsテーブルの情報を確認してtypeカラムの存在を確認
        try:
            cursor = await db.execute("PRAGMA table_info(accounts)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # typeカラムが存在しない場合は新しいスキーマで再作成
            if 'type' not in column_names:
                print("[DB] Updating accounts table schema...")
                # 新しいテーブルを作成
                await db.execute('''
                    CREATE TABLE accounts_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        guild_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL CHECK (type IN ('user','treasury','burn')),
                        is_active INTEGER NOT NULL DEFAULT 1,
                        UNIQUE(guild_id, name),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                ''')
                
                # データを移行（typeを推定して設定）
                await db.execute('''
                    INSERT INTO accounts_new (id, user_id, guild_id, name, type, is_active)
                    SELECT id, user_id, guild_id, name,
                           CASE 
                               WHEN name LIKE '%Treasury' THEN 'treasury'
                               WHEN name LIKE '%Burn' THEN 'burn'
                               ELSE 'user'
                           END as type,
                           1 as is_active
                    FROM accounts
                ''')
                
                # 古いテーブルを削除し、新しいテーブルをリネーム
                await db.execute('DROP TABLE accounts')
                await db.execute('ALTER TABLE accounts_new RENAME TO accounts')
                print("[DB] Accounts table schema updated successfully")
        except:
            # テーブルが存在しない場合は通常の作成処理
            pass
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT NOT NULL UNIQUE
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                decimals INTEGER NOT NULL DEFAULT 2,
                UNIQUE(guild_id, symbol)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('user','treasury','burn')),
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(guild_id, name),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                amount TEXT NOT NULL,
                FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (asset_id) REFERENCES assets(id)
            )
        ''')
        
        await db.commit()

async def fetch_one(db, query: str, params=()) -> Optional[Tuple]:
    """単一レコードを取得"""
    cursor = await db.execute(query, params)
    return await cursor.fetchone()

async def fetch_all(db, query: str, params=()) -> List[Tuple]:
    """全レコードを取得"""
    cursor = await db.execute(query, params)
    return await cursor.fetchall()

# ========================== ユーザー・アカウント管理 ==========================

async def upsert_user(db, discord_user_id: int) -> int:
    """ユーザーをDBに登録し、IDを返す"""
    existing = await fetch_one(db, "SELECT id FROM users WHERE discord_user_id = ?", (str(discord_user_id),))
    if existing:
        return existing[0]
    
    cursor = await db.execute("INSERT INTO users (discord_user_id) VALUES (?)", (str(discord_user_id),))
    return cursor.lastrowid

async def ensure_user_account(db, discord_user_id: int, guild_id: int) -> int:
    """ユーザーアカウント（口座）を確保し、IDを返す"""
    user_id = await upsert_user(db, discord_user_id)
    account_name = f"user:{discord_user_id}"
    
    existing = await fetch_one(db, "SELECT id FROM accounts WHERE name = ? AND guild_id = ?", (account_name, str(guild_id)))
    if existing:
        return existing[0]
    
    cursor = await db.execute("INSERT INTO accounts (user_id, guild_id, name, type) VALUES (?, ?, ?, ?)", (user_id, str(guild_id), account_name, 'user'))
    return cursor.lastrowid

async def account_id_by_name(db, name: str, guild_id: int) -> int:
    """アカウント名からIDを取得"""
    result = await fetch_one(db, "SELECT id FROM accounts WHERE name = ? AND guild_id = ?", (name, str(guild_id)))
    return result[0] if result else None

async def balance_of(db, account_id: int, asset_id: int) -> Decimal:
    """残高を取得"""
    result = await fetch_one(db, """
        SELECT SUM(CAST(amount AS DECIMAL)) FROM ledger_entries 
        WHERE account_id = ? AND asset_id = ?
    """, (account_id, asset_id))
    return Decimal(result[0] or '0')

# ========================== 通貨管理 ==========================

async def create_asset(db, guild_id: int, symbol: str, name: str, decimals: int = DEFAULT_DECIMALS, initial_supply: Decimal = Decimal('0')) -> Tuple[bool, str, Optional[int]]:
    """
    新しい通貨を作成
    返り値: (成功フラグ, メッセージ, asset_id)
    """
    try:
        # 重複チェック
        existing = await fetch_one(db, "SELECT id FROM assets WHERE guild_id = ? AND symbol = ?", (str(guild_id), symbol))
        if existing:
            return False, f"シンボル '{symbol}' は既に存在します。", None
        
        # 通貨作成
        cursor = await db.execute("""
            INSERT INTO assets (guild_id, symbol, name, decimals) 
            VALUES (?, ?, ?, ?)
        """, (str(guild_id), symbol, name, decimals))
        
        asset_id = cursor.lastrowid
        
        # Treasuryアカウントを確保
        treasury_account = await ensure_treasury_account(db, guild_id)
        
        # 初期供給量があれば直接Treasuryに追加（発行）
        if initial_supply > 0:
            # トランザクション作成
            cursor = await db.execute("""
                INSERT INTO transactions (guild_id, description, created_at) 
                VALUES (?, ?, ?)
            """, (str(guild_id), f"初期供給: {symbol}", datetime.now(TZ).isoformat()))
            
            transaction_id = cursor.lastrowid
            
            # Treasuryに初期供給量を追加（正の値で記録）
            await db.execute("""
                INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
                VALUES (?, ?, ?, ?)
            """, (transaction_id, treasury_account, asset_id, str(initial_supply)))
        
        await db.commit()
        return True, f"通貨 '{symbol}' ({name}) を作成しました。", asset_id
        
    except Exception as e:
        await db.rollback()
        return False, f"通貨作成エラー: {str(e)}", None

async def ensure_treasury_account(db, guild_id: int) -> int:
    """Treasuryアカウントを確保"""
    treasury_name = "treasury"
    existing = await fetch_one(db, "SELECT id FROM accounts WHERE name = ? AND guild_id = ?", (treasury_name, str(guild_id)))
    if existing:
        return existing[0]
    
    cursor = await db.execute("INSERT INTO accounts (user_id, guild_id, name, type) VALUES (?, ?, ?, ?)", (None, str(guild_id), treasury_name, 'treasury'))
    return cursor.lastrowid

async def ensure_burn_account(db, guild_id: int) -> int:
    """Burnアカウントを確保"""
    burn_name = "burn"
    existing = await fetch_one(db, "SELECT id FROM accounts WHERE name = ? AND guild_id = ?", (burn_name, str(guild_id)))
    if existing:
        return existing[0]
    
    cursor = await db.execute("INSERT INTO accounts (user_id, guild_id, name, type) VALUES (?, ?, ?, ?)", (None, str(guild_id), burn_name, 'burn'))
    return cursor.lastrowid

async def issue_currency(db, guild_id: int, from_account: int, to_account: int, asset_id: int, amount: Decimal, description: str) -> bool:
    """通貨発行（二重仕訳）"""
    try:
        # トランザクション作成
        cursor = await db.execute("""
            INSERT INTO transactions (guild_id, description, created_at) 
            VALUES (?, ?, ?)
        """, (str(guild_id), description, datetime.now(TZ).isoformat()))
        
        transaction_id = cursor.lastrowid
        
        # 発行元（Treasury）から減額（負の値で記録）
        await db.execute("""
            INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
            VALUES (?, ?, ?, ?)
        """, (transaction_id, from_account, asset_id, str(-amount)))
        
        # 受取先（ユーザー）に増額（正の値で記録）
        await db.execute("""
            INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
            VALUES (?, ?, ?, ?)
        """, (transaction_id, to_account, asset_id, str(amount)))
        
        return True
        
    except Exception as e:
        await db.rollback()
        print(f"通貨発行エラー: {e}")
        return False

async def transfer_currency(db, guild_id: int, from_account: int, to_account: int, asset_id: int, amount: Decimal, description: str) -> bool:
    """通貨送金（二重仕訳）"""
    try:
        # トランザクション作成
        cursor = await db.execute("""
            INSERT INTO transactions (guild_id, description, created_at) 
            VALUES (?, ?, ?)
        """, (str(guild_id), description, datetime.now(TZ).isoformat()))
        
        transaction_id = cursor.lastrowid
        
        # 送金者から減額
        await db.execute("""
            INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
            VALUES (?, ?, ?, ?)
        """, (transaction_id, from_account, asset_id, str(-amount)))
        
        # 受取者に加算
        await db.execute("""
            INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
            VALUES (?, ?, ?, ?)
        """, (transaction_id, to_account, asset_id, str(amount)))
        
        return True
        
    except Exception as e:
        await db.rollback()
        return False

# ========================== 通貨情報取得 ==========================

async def get_asset_by_symbol(db, guild_id: int, symbol: str) -> Optional[Tuple]:
    """シンボルから通貨情報を取得"""
    return await fetch_one(db, """
        SELECT id, symbol, name, decimals 
        FROM assets 
        WHERE guild_id = ? AND symbol = ?
    """, (str(guild_id), symbol))

async def get_user_balances(db, user_account_id: int, guild_id: int) -> List[Tuple]:
    """ユーザーの全残高を取得"""
    return await fetch_all(db, """
        SELECT 
            a.symbol, 
            a.name, 
            SUM(CAST(le.amount AS DECIMAL)) as balance, 
            a.decimals
        FROM ledger_entries le
        JOIN assets a ON le.asset_id = a.id
        WHERE le.account_id = ? AND a.guild_id = ?
        GROUP BY a.id, a.symbol, a.name, a.decimals
        HAVING SUM(CAST(le.amount AS DECIMAL)) > 0
        ORDER BY a.symbol
    """, (user_account_id, str(guild_id)))

async def get_treasury_balances(db, guild_id: int) -> List[Tuple]:
    """Treasury残高を取得"""
    treasury_account = await account_id_by_name(db, "treasury", guild_id)
    if not treasury_account:
        return []
    
    return await fetch_all(db, """
        SELECT 
            a.symbol, 
            a.name, 
            SUM(CAST(le.amount AS DECIMAL)) as balance, 
            a.decimals
        FROM ledger_entries le
        JOIN assets a ON le.asset_id = a.id
        WHERE le.account_id = ? AND a.guild_id = ?
        GROUP BY a.id, a.symbol, a.name, a.decimals
        ORDER BY a.symbol
    """, (treasury_account, str(guild_id)))

async def get_guild_assets(db, guild_id: int) -> List[Tuple]:
    """ギルドの全通貨を取得"""
    return await fetch_all(db, """
        SELECT id, symbol, name, decimals 
        FROM assets 
        WHERE guild_id = ? 
        ORDER BY symbol
    """, (str(guild_id),))

# ========================== Embed作成関数 ==========================

def create_success_embed(title: str, description: str, user: discord.User = None) -> discord.Embed:
    """成功Embedを作成"""
    embed = discord.Embed(title=title, description=description, color=0x00ff00)
    if user:
        embed.set_footer(text=f"実行者: {user.display_name}", icon_url=user.display_avatar.url)
    return embed

def create_error_embed(title: str, description: str, user: discord.User = None) -> discord.Embed:
    """エラーEmbedを作成"""
    embed = discord.Embed(title=title, description=description, color=0xff0000)
    if user:
        embed.set_footer(text=f"実行者: {user.display_name}", icon_url=user.display_avatar.url)
    return embed

def create_info_embed(title: str, description: str, user: discord.User = None) -> discord.Embed:
    """情報Embedを作成"""
    embed = discord.Embed(title=title, description=description, color=0x0099ff)
    if user:
        embed.set_footer(text=f"実行者: {user.display_name}", icon_url=user.display_avatar.url)
    return embed

def create_transaction_embed(transaction_type: str, from_user: str, to_user: str, amount: str, symbol: str, memo: str = None, executor: discord.User = None) -> discord.Embed:
    """取引Embedを作成"""
    title = f"💸 {transaction_type}"
    
    embed = discord.Embed(title=title, color=0x00ff88)
    embed.add_field(name="送金者", value=from_user, inline=True)
    embed.add_field(name="受取者", value=to_user, inline=True)
    embed.add_field(name="金額", value=f"**{amount} {symbol}**", inline=True)
    
    if memo:
        embed.add_field(name="メモ", value=f"```{memo}```", inline=False)
    
    
    if executor:
        embed.set_footer(text=f"実行者: {executor.display_name}", icon_url=executor.display_avatar.url)
    
    return embed

# ========================== ユーティリティ関数 ==========================

def format_currency_amount(amount: Decimal, decimals: int) -> str:
    """通貨金額をフォーマット"""
    if decimals == 0:
        return str(int(amount))
    else:
        # 指定桁数で四捨五入
        quantized = amount.quantize(Decimal('0.1') ** decimals, rounding=ROUND_DOWN)
        return f"{quantized:.{decimals}f}".rstrip('0').rstrip('.')

def is_valid_currency_symbol(symbol: str) -> bool:
    """通貨シンボルの有効性をチェック"""
    return symbol.isalnum() and 1 <= len(symbol) <= 16

def is_guild_manager(interaction: discord.Interaction) -> bool:
    """管理者権限のチェック"""
    if not interaction.guild:
        return False
    
    perms = interaction.user.guild_permissions
    return bool(perms.manage_guild or perms.administrator)

# ========================== VirtualCrypto Commands ==========================

class VirtualCryptoCommands:
    """VirtualCrypto機能のコマンドクラス（参考用）"""
    
    @staticmethod
    async def create_currency_command(interaction: discord.Interaction, symbol: str, name: str, decimals: int = 2, initial_supply: int = 0):
        """通貨作成コマンドの処理"""
        if not is_guild_manager(interaction):
            embed = create_error_embed("権限エラー", "このコマンドは管理者のみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if not is_valid_currency_symbol(symbol):
            embed = create_error_embed("入力エラー", "シンボルは英数字1-16文字で入力してください。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        try:
            initial_supply_decimal = Decimal(str(initial_supply))
            if initial_supply_decimal < 0:
                raise ValueError()
        except (ValueError, InvalidOperation):
            embed = create_error_embed("入力エラー", "初期供給量が不正です。正の数値を入力してください。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            success, message, asset_id = await create_asset(
                db, interaction.guild.id, symbol, name, decimals, initial_supply_decimal
            )
            
            if success:
                embed = create_success_embed(
                    "通貨作成完了",
                    f"🪙 **{symbol}** ({name}) を作成しました！\n\n"
                    f"• 小数桁数: {decimals}桁\n"
                    f"• 初期供給量: {format_currency_amount(initial_supply_decimal, decimals)} {symbol}",
                    interaction.user
                )
            else:
                embed = create_error_embed("作成エラー", message, interaction.user)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @staticmethod 
    async def pay_currency_command(interaction: discord.Interaction, to_user: discord.Member, symbol: str, amount: float, memo: str = None):
        """送金コマンドの処理"""
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if to_user.id == interaction.user.id:
            embed = create_error_embed("送金エラー", "自分自身には送金できません。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        try:
            amount_decimal = Decimal(str(amount))
            if amount_decimal <= 0:
                raise ValueError()
        except (ValueError, InvalidOperation):
            embed = create_error_embed("入力エラー", "金額は正の数値を入力してください。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            # 通貨情報取得
            asset = await get_asset_by_symbol(db, interaction.guild.id, symbol)
            if not asset:
                embed = create_error_embed("通貨エラー", f"通貨 '{symbol}' が見つかりません。", interaction.user)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            asset_id, symbol, asset_name, decimals = asset
            
            # 小数桁数調整
            amount_decimal = amount_decimal.quantize(Decimal('0.1') ** decimals, rounding=ROUND_DOWN)
            
            # アカウント取得
            from_account = await ensure_user_account(db, interaction.user.id, interaction.guild.id)
            to_account = await ensure_user_account(db, to_user.id, interaction.guild.id)
            
            # 残高チェック
            balance = await balance_of(db, from_account, asset_id)
            if balance < amount_decimal:
                embed = create_error_embed(
                    "残高不足",
                    f"送金に必要な残高が不足しています。\n\n"
                    f"• 必要金額: {format_currency_amount(amount_decimal, decimals)} {symbol}\n"
                    f"• 現在残高: {format_currency_amount(balance, decimals)} {symbol}",
                    interaction.user
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # 送金実行
            description = f"送金: {interaction.user.display_name} → {to_user.display_name}"
            if memo:
                description += f" ({memo})"
            
            success = await transfer_currency(db, interaction.guild.id, from_account, to_account, asset_id, amount_decimal, description)
            
            if success:
                await db.commit()
                
                # 成功Embed
                embed = create_transaction_embed(
                    "送金完了",
                    interaction.user.mention,
                    to_user.mention,
                    format_currency_amount(amount_decimal, decimals),
                    symbol,
                    memo,
                    interaction.user
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=False)
            else:
                embed = create_error_embed("送金エラー", "送金処理中にエラーが発生しました。", interaction.user)
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @staticmethod
    async def balance_command(interaction: discord.Interaction, symbol: str = None):
        """残高確認コマンドの処理（自分の残高のみ）"""
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            if symbol:
                # 特定通貨の残高
                asset = await get_asset_by_symbol(db, interaction.guild.id, symbol)
                if not asset:
                    embed = create_error_embed("通貨エラー", f"通貨 '{symbol}' が見つかりません。", interaction.user)
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                asset_id, symbol, asset_name, decimals = asset
                user_account = await ensure_user_account(db, interaction.user.id, interaction.guild.id)
                balance = await balance_of(db, user_account, asset_id)
                
                embed = create_info_embed(
                    "残高照会",
                    f"💰 あなたの {symbol} 残高\n\n"
                    f"**{format_currency_amount(balance, decimals)} {symbol}**",
                    interaction.user
                )
            else:
                # 全通貨残高
                user_account = await ensure_user_account(db, interaction.user.id, interaction.guild.id)
                balances = await get_user_balances(db, user_account, interaction.guild.id)
                
                if not balances:
                    embed = create_info_embed(
                        "残高照会", 
                        f"💰 あなたの残高\n\n現在保有している通貨はありません。", 
                        interaction.user
                    )
                else:
                    balance_text = ""
                    for symbol, name, balance, decimals in balances:
                        formatted_balance = format_currency_amount(balance, decimals)
                        balance_text += f"• **{formatted_balance} {symbol}** ({name})\n"
                    
                    embed = create_info_embed(
                        "残高照会",
                        f"💰 あなたの残高\n\n{balance_text}",
                        interaction.user
                    )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @staticmethod
    async def give_currency_command(interaction: discord.Interaction, user: discord.Member, symbol: str, amount: float, memo: str = None):
        """通貨発行コマンドの処理"""
        if not is_guild_manager(interaction):
            embed = create_error_embed("権限エラー", "このコマンドは管理者のみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        try:
            amount_decimal = Decimal(str(amount))
            if amount_decimal <= 0:
                raise ValueError()
        except (ValueError, InvalidOperation):
            embed = create_error_embed("入力エラー", "金額は正の数値を入力してください。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            # 通貨情報取得
            asset = await get_asset_by_symbol(db, interaction.guild.id, symbol)
            if not asset:
                embed = create_error_embed("通貨エラー", f"通貨 '{symbol}' が見つかりません。", interaction.user)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            asset_id, symbol, asset_name, decimals = asset
            
            # 小数桁数調整
            amount_decimal = amount_decimal.quantize(Decimal('0.1') ** decimals, rounding=ROUND_DOWN)
            
            # アカウント取得
            treasury_account = await ensure_treasury_account(db, interaction.guild.id)
            user_account = await ensure_user_account(db, user.id, interaction.guild.id)
            
            # Treasury残高チェック
            treasury_balance = await balance_of(db, treasury_account, asset_id)
            if treasury_balance < amount_decimal:
                embed = create_error_embed(
                    "残高不足",
                    f"Treasury の残高が不足しています。\n\n"
                    f"• 必要金額: {format_currency_amount(amount_decimal, decimals)} {symbol}\n"
                    f"• Treasury残高: {format_currency_amount(treasury_balance, decimals)} {symbol}",
                    interaction.user
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # 発行実行
            description = f"発行: Treasury → {user.display_name}"
            if memo:
                description += f" ({memo})"
            
            success = await transfer_currency(db, interaction.guild.id, treasury_account, user_account, asset_id, amount_decimal, description)
            
            if success:
                await db.commit()
                
                embed = create_transaction_embed(
                    "通貨発行完了",
                    "🏦 Treasury",
                    user.mention,
                    format_currency_amount(amount_decimal, decimals),
                    symbol,
                    memo,
                    interaction.user
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=False)
            else:
                embed = create_error_embed("発行エラー", "通貨発行処理中にエラーが発生しました。", interaction.user)
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @staticmethod
    async def treasury_command(interaction: discord.Interaction, symbol: str = None, hidden: bool = True):
        """Treasury残高確認コマンドの処理"""
        if not is_guild_manager(interaction):
            embed = create_error_embed("権限エラー", "このコマンドは管理者のみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            if symbol:
                # 特定通貨のTreasury残高
                asset = await get_asset_by_symbol(db, interaction.guild.id, symbol)
                if not asset:
                    embed = create_error_embed("通貨エラー", f"通貨 '{symbol}' が見つかりません。", interaction.user)
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                asset_id, symbol, asset_name, decimals = asset
                treasury_account = await ensure_treasury_account(db, interaction.guild.id)
                balance = await balance_of(db, treasury_account, asset_id)
                
                embed = create_info_embed(
                    "Treasury残高",
                    f"🏦 **Treasury** の {symbol} 残高\n\n"
                    f"**{format_currency_amount(balance, decimals)} {symbol}**",
                    interaction.user
                )
            else:
                # 全通貨のTreasury残高
                balances = await get_treasury_balances(db, interaction.guild.id)
                
                if not balances:
                    embed = create_info_embed(
                        "Treasury残高", 
                        "🏦 **Treasury** の残高\n\n現在保有している通貨はありません。", 
                        interaction.user
                    )
                else:
                    balance_text = ""
                    for symbol, name, balance, decimals in balances:
                        formatted_balance = format_currency_amount(balance, decimals)
                        balance_text += f"• **{formatted_balance} {symbol}** ({name})\n"
                    
                    embed = create_info_embed(
                        "Treasury残高",
                        f"🏦 **Treasury** の残高\n\n{balance_text}",
                        interaction.user
                    )
            
            await interaction.response.send_message(embed=embed, ephemeral=hidden)
    
    # ランキング機能は削除
    
    @staticmethod
    async def delete_currency_command(interaction: discord.Interaction, symbol: str):
        """通貨削除コマンドの処理"""
        if not is_guild_manager(interaction):
            embed = create_error_embed("権限エラー", "このコマンドは管理者のみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if not interaction.guild:
            embed = create_error_embed("実行エラー", "このコマンドはサーバー内でのみ使用できます。", interaction.user)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # デフォルト通貨の削除制限は削除
        
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            # 通貨存在確認
            asset = await get_asset_by_symbol(db, interaction.guild.id, symbol)
            if not asset:
                embed = create_error_embed("通貨エラー", f"通貨 '{symbol}' が見つかりません。", interaction.user)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            asset_id, symbol, asset_name, decimals = asset
            
            # 残高チェック（全アカウント）
            balances = await fetch_all(db, """
                SELECT SUM(CAST(amount AS DECIMAL)) as total_balance
                FROM ledger_entries 
                WHERE asset_id = ?
            """, (asset_id,))
            
            total_balance = balances[0][0] if balances and balances[0][0] else Decimal('0')
            
            if total_balance != 0:
                embed = create_error_embed(
                    "削除エラー",
                    f"通貨 '{symbol}' は削除できません。\n\n"
                    f"削除条件:\n"
                    f"• 全アカウントで残高がゼロである必要があります\n"
                    f"• 現在の総残高: {format_currency_amount(total_balance, decimals)} {symbol}",
                    interaction.user
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            try:
                # 関連データを削除
                await db.execute("DELETE FROM ledger_entries WHERE asset_id = ?", (asset_id,))
                await db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                await db.commit()
                
                embed = create_success_embed(
                    "通貨削除完了",
                    f"💥 通貨 **{symbol}** ({asset_name}) を削除しました。",
                    interaction.user
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except Exception as e:
                await db.rollback()
                embed = create_error_embed("削除エラー", f"削除処理中にエラーが発生しました: {str(e)}", interaction.user)
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @staticmethod
    async def help_command(interaction: discord.Interaction):
        """ヘルプコマンドの処理"""
        embed = create_info_embed(
            "🏦 VirtualCrypto Bot ヘルプ",
            "サーバー内独自通貨システムの使い方",
            interaction.user
        )
        
        # 一般ユーザー向けコマンド
        embed.add_field(
            name="👤 一般ユーザー向けコマンド",
            value="**`/pay to:@ユーザー symbol:通貨 amount:金額 [memo:メモ]`**\n"
                  "他のユーザーに通貨を送金します\n\n"
                  "**`/bal [symbol:通貨]`**\n"
                  "自分の残高を確認します（プライベート表示）\n"
                  "• symbol省略時：全通貨の残高\n"
                  "• symbol指定時：特定通貨のみ",
            inline=False
        )
        
        # 管理者専用コマンド
        embed.add_field(
            name="🛡️ 管理者専用コマンド",
            value="**`/create symbol:通貨 name:通貨名 [decimals:小数桁] [initial_supply:初期供給量]`**\n"
                  "新しい通貨を作成します\n\n"
                  "**`/give user:@ユーザー symbol:通貨 amount:金額 [memo:理由]`**\n"
                  "Treasuryから通貨を発行します\n\n"
                  "**`/treasury [symbol:通貨] [hidden:非公開]`**\n"
                  "Treasury残高を確認します\n\n"
                  "**`/delete symbol:通貨`**\n"
                  "通貨を削除します（全残高がゼロの場合のみ）",
            inline=False
        )
        
        # システムの特徴
        embed.add_field(
            name="💡 システムの特徴",
            value="• **二重仕訳**: 正確な台帳管理で残高を保証\n"
                  "• **サーバー独立**: 各サーバーで完全に独立した通貨システム\n"
                  "• **オートコンプリート**: コマンド入力時に利用可能な通貨を表示\n"
                  "• **権限管理**: 管理者コマンドは「サーバー管理」権限が必要\n"
                  "• **透明性**: 送金は公開、残高確認は個人のみ表示",
            inline=False
        )
        
        # 使い方の例
        embed.add_field(
            name="📚 使い方の例",
            value="1. 管理者が `/create symbol:GOLD name:ゴールドコイン decimals:2 initial_supply:10000` で通貨作成\n"
                  "2. 管理者が `/give user:@ユーザー symbol:GOLD amount:100` でユーザーに配布\n"
                  "3. ユーザーが `/pay to:@友達 symbol:GOLD amount:50 memo:ありがとう` で送金\n"
                  "4. ユーザーが `/bal` で自分の残高確認\n"
                  "5. 管理者が `/treasury symbol:GOLD` でTreasury残高確認",
            inline=False
        )
        
        embed.set_footer(
            text="💰 VirtualCrypto Bot | 各コマンドの詳細はコマンド入力時に確認できます",
            icon_url=interaction.client.user.display_avatar.url if interaction.client.user else None
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ========================== Bot初期化 ==========================

# Bot intents設定
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# Bot初期化
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ========================== Botイベント ==========================

@bot.event
async def on_ready():
    print(f"VirtualCrypto Bot がログインしました: {bot.user}")
    await ensure_db()
    
    # Guild IDが指定されている場合は特定サーバーのみで同期
    guild_id = os.getenv("GUILD_ID")
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        await tree.sync(guild=guild)
        print(f"コマンドを Guild {guild_id} に同期しました")
    else:
        await tree.sync()
        print("コマンドをグローバルに同期しました")
    
    print("VirtualCrypto Bot の準備が完了しました！")

@bot.event
async def on_guild_join(guild):
    """新しいサーバーに参加した時の初期化"""
    await ensure_db()
    print(f"[JOIN] Joined guild {guild.name} ({guild.id}), ready to use")

# ========================== スラッシュコマンド実装 ==========================

@tree.command(name="create", description="新しい通貨を作成（管理者のみ）")
@app_commands.describe(
    symbol="通貨シンボル（英数字1-16文字）",
    name="通貨名",
    decimals="小数桁数（0-8、既定2）",
    initial_supply="初期供給量（既定0）"
)
@app_commands.default_permissions(manage_guild=True)
async def create(inter: discord.Interaction, symbol: str, name: str, decimals: int = 2, initial_supply: int = 0):
    await VirtualCryptoCommands.create_currency_command(inter, symbol, name, decimals, initial_supply)

@tree.command(name="pay", description="指定ユーザーに送金")
@app_commands.describe(
    to="送金先ユーザー",
    symbol="通貨シンボル",
    amount="送金額",
    memo="メモ（任意）"
)
async def pay(inter: discord.Interaction, to: discord.Member, symbol: str, amount: float, memo: str = None):
    await VirtualCryptoCommands.pay_currency_command(inter, to, symbol, amount, memo)

@tree.command(name="bal", description="自分の残高を表示")
@app_commands.describe(
    symbol="通貨シンボル（省略時は全通貨）"
)
async def balance(inter: discord.Interaction, symbol: str = None):
    await VirtualCryptoCommands.balance_command(inter, symbol)

@tree.command(name="give", description="Treasuryから発行（管理者のみ）")
@app_commands.describe(
    user="発行対象ユーザー",
    symbol="通貨シンボル",
    amount="発行額",
    memo="発行理由（任意）"
)
@app_commands.default_permissions(manage_guild=True)
async def give(inter: discord.Interaction, user: discord.Member, symbol: str, amount: float, memo: str = None):
    await VirtualCryptoCommands.give_currency_command(inter, user, symbol, amount, memo)

@tree.command(name="treasury", description="Treasury残高を確認（管理者のみ）")
@app_commands.describe(
    symbol="通貨シンボル（省略時は全通貨）",
    hidden="非公開で表示するか（既定true）"
)
@app_commands.default_permissions(manage_guild=True)
async def treasury(inter: discord.Interaction, symbol: str = None, hidden: bool = True):
    await VirtualCryptoCommands.treasury_command(inter, symbol, hidden)

# ランキング機能は削除

@tree.command(name="delete", description="通貨を削除（管理者のみ）")
@app_commands.describe(symbol="削除する通貨シンボル")
@app_commands.default_permissions(manage_guild=True)
async def delete_currency(inter: discord.Interaction, symbol: str):
    await VirtualCryptoCommands.delete_currency_command(inter, symbol)

@tree.command(name="help", description="コマンドの使い方を表示")
async def help_command(inter: discord.Interaction):
    await VirtualCryptoCommands.help_command(inter)

@tree.command(name="list", description="サーバーの全通貨一覧を表示")
async def list_currencies(inter: discord.Interaction):
    """デバッグ用: サーバーの全通貨を表示"""
    if not inter.guild:
        return await inter.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            assets = await get_guild_assets(db, inter.guild.id)
            
            if not assets:
                embed = create_info_embed("通貨一覧", "このサーバーには通貨が作成されていません。", inter.user)
            else:
                description = []
                for asset_id, symbol, name, decimals in assets:
                    description.append(f"**{symbol}** - {name} (小数桁: {decimals})")
                
                embed = create_info_embed(
                    "通貨一覧",
                    f"このサーバーの全通貨 ({len(assets)}個):\n\n" + "\n".join(description),
                    inter.user
                )
            
            await inter.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await inter.response.send_message(f"エラーが発生しました: {str(e)}", ephemeral=True)

@tree.command(name="fix_db", description="データベース整合性を修復（管理者のみ・危険）")
@app_commands.describe(
    confirm="修復を実行する場合は 'YES' と入力",
    symbol="修復対象の通貨シンボル（省略時は全通貨）"
)
@app_commands.default_permissions(manage_guild=True)
async def fix_database(inter: discord.Interaction, confirm: str, symbol: str = None):
    """データベース修復コマンド"""
    if not is_guild_manager(inter):
        return await inter.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
    
    if not inter.guild:
        return await inter.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
    
    if confirm != "YES":
        embed = create_error_embed(
            "確認が必要", 
            "⚠️ **危険なコマンドです**\n\n"
            "このコマンドはデータベースの整合性を修復します。\n"
            "実行前にデータのバックアップを推奨します。\n\n"
            "実行する場合は `confirm` に `YES` と入力してください。",
            inter.user
        )
        return await inter.response.send_message(embed=embed, ephemeral=True)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_db()
            
            # Treasury残高の修復
            treasury_account = await ensure_treasury_account(db, inter.guild.id)
            
            if symbol:
                # 特定通貨の修復
                asset = await get_asset_by_symbol(db, inter.guild.id, symbol)
                if not asset:
                    return await inter.response.send_message(f"通貨 '{symbol}' が見つかりません。", ephemeral=True)
                
                asset_id, symbol, asset_name, decimals = asset
                assets_to_fix = [(asset_id, symbol, asset_name, decimals)]
            else:
                # 全通貨の修復
                assets_to_fix = await get_guild_assets(db, inter.guild.id)
            
            fixed_currencies = []
            
            for asset_id, curr_symbol, asset_name, decimals in assets_to_fix:
                # 現在のTreasury残高を計算
                treasury_balance = await balance_of(db, treasury_account, asset_id)
                
                # 全ユーザーの残高合計を計算
                users_total = await fetch_one(db, """
                    SELECT COALESCE(SUM(CAST(le.amount AS DECIMAL)), 0) as total
                    FROM ledger_entries le
                    JOIN accounts a ON le.account_id = a.id
                    WHERE le.asset_id = ? AND a.type = 'user' AND a.guild_id = ?
                """, (asset_id, str(inter.guild.id)))
                
                users_balance = Decimal(users_total[0] if users_total and users_total[0] else '0')
                
                # Treasury残高を正の値に調整（ユーザー残高をカバーできる分 + 1000000）
                target_treasury_balance = users_balance + Decimal('1000000')
                adjustment = target_treasury_balance - treasury_balance
                
                if adjustment != 0:
                    # 調整エントリを追加
                    cursor = await db.execute("""
                        INSERT INTO transactions (guild_id, description, created_at) 
                        VALUES (?, ?, ?)
                    """, (str(inter.guild.id), f"DB修復: {curr_symbol} Treasury残高調整", datetime.now(TZ).isoformat()))
                    
                    transaction_id = cursor.lastrowid
                    
                    await db.execute("""
                        INSERT INTO ledger_entries (transaction_id, account_id, asset_id, amount) 
                        VALUES (?, ?, ?, ?)
                    """, (transaction_id, treasury_account, asset_id, str(adjustment)))
                    
                    fixed_currencies.append(f"• **{curr_symbol}**: {format_currency_amount(adjustment, decimals)} 調整")
            
            await db.commit()
            
            if fixed_currencies:
                embed = create_success_embed(
                    "データベース修復完了",
                    f"以下の通貨が修復されました:\n\n" + "\n".join(fixed_currencies),
                    inter.user
                )
            else:
                embed = create_info_embed(
                    "データベース修復完了",
                    "修復が必要な通貨はありませんでした。",
                    inter.user
                )
            
            await inter.response.send_message(embed=embed, ephemeral=True)
            
    except Exception as e:
        embed = create_error_embed("修復エラー", f"データベース修復中にエラーが発生しました: {str(e)}", inter.user)
        await inter.response.send_message(embed=embed, ephemeral=True)

# ========================== オートコンプリート ==========================

@pay.autocomplete('symbol')
async def pay_symbol_autocomplete(interaction: discord.Interaction, current: str):
    """payコマンドの通貨シンボルオートコンプリート（全通貨表示、残高付き）"""
    if not interaction.guild:
        return []
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # サーバーの全通貨を取得
            assets = await get_guild_assets(db, interaction.guild.id)
            user_account = await ensure_user_account(db, interaction.user.id, interaction.guild.id)
            
            choices = []
            for asset_id, symbol, name, decimals in assets:
                if current.lower() in symbol.lower() or current.lower() in name.lower():
                    # ユーザーの残高を取得
                    balance = await balance_of(db, user_account, asset_id)
                    balance_str = format_currency_amount(balance, decimals)
                    
                    if balance > 0:
                        choices.append(app_commands.Choice(
                            name=f"{symbol} - {balance_str} 所有",
                            value=symbol
                        ))
                    else:
                        choices.append(app_commands.Choice(
                            name=f"{symbol} - {name} (残高なし)",
                            value=symbol
                        ))
            
            return choices[:25]  # Discord limit
    except Exception as e:
        return []

# ========================== Main関数 ==========================

def main():
    """VirtualCrypto Bot のメイン関数"""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ エラー: DISCORD_TOKEN 環境変数が設定されていません。")
        print("\n📋 設定方法:")
        print("1. .envファイルを作成して以下を記載:")
        print("   DISCORD_TOKEN=your_bot_token_here")
        print("   GUILD_ID=your_guild_id_here  # 任意")
        print("   VC_DB=virtualcrypto.sqlite3  # 任意")
        print("\n2. または、環境変数として直接設定")
        print("   export DISCORD_TOKEN=your_bot_token_here")
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")
    
    print("🚀 VirtualCrypto Bot を起動します...")
    print(f"📁 データベース: {DB_PATH}")
    
    guild_id = os.getenv("GUILD_ID")
    if guild_id:
        print(f"🎯 Guild 限定モード: {guild_id}")
    else:
        print("🌍 グローバルモード（全サーバー対応）")
    
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ ログインに失敗しました。Bot Tokenを確認してください。")
    except discord.HTTPException as e:
        print(f"❌ HTTP エラー: {e}")
    except KeyboardInterrupt:
        print("\n⏹️ Bot を停止します...")
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")

if __name__ == "__main__":
    main()

"""
==============================================
VirtualCrypto Standalone Bot
==============================================

このファイルを単独で実行することで、完全に動作する
VirtualCrypto風通貨システムBotとして利用できます。

📋 利用可能なコマンド:
━━━━━━━━━━━━━━━━━━━━━━━━

👤 一般ユーザー向け:
• /pay    - 他のユーザーに送金
• /bal    - 自分の残高を表示（プライベート表示）
• /help   - コマンドの使い方を表示

🛡️ 管理者専用:
• /create   - 新しい通貨を作成
• /give     - Treasuryから通貨を発行
• /treasury - Treasury残高を確認
• /delete   - 通貨を削除（条件あり）

💡 特徴:
• 二重仕訳による正確な台帳管理
• サーバーごとの独立した通貨システム
• オートコンプリート対応
• 美しいEmbed表示

🔧 セットアップ:
1. pip install -U discord.py aiosqlite python-dotenv
2. .envファイルに DISCORD_TOKEN を設定
3. python virtualcrypto_core.py

📖 詳細な使い方:
Botが起動したら、/help コマンドまたは上記コマンドを試してください。
==============================================
"""

@balance.autocomplete('symbol')
@give.autocomplete('symbol') 
@treasury.autocomplete('symbol')
@delete_currency.autocomplete('symbol')
@fix_database.autocomplete('symbol')
async def general_symbol_autocomplete(interaction: discord.Interaction, current: str):
    """一般的な通貨シンボルオートコンプリート（全通貨）"""
    if not interaction.guild:
        return []
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            assets = await get_guild_assets(db, interaction.guild.id)
            
            choices = []
            for asset_id, symbol, name, decimals in assets:
                if current.lower() in symbol.lower() or current.lower() in name.lower():
                    choices.append(app_commands.Choice(
                        name=f"{symbol} - {name}",
                        value=symbol
                    ))
            
            return choices[:25]  # Discord limit
    except Exception as e:
        return []

# ========================== Main関数 ==========================

def main():
    """VirtualCrypto Bot のメイン関数"""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ エラー: DISCORD_TOKEN 環境変数が設定されていません。")
        print("\n📋 設定方法:")
        print("1. .envファイルを作成して以下を記載:")
        print("   DISCORD_TOKEN=your_bot_token_here")
        print("   GUILD_ID=your_guild_id_here  # 任意")
        print("   VC_DB=virtualcrypto.sqlite3  # 任意")
        print("\n2. または、環境変数として直接設定")
        print("   export DISCORD_TOKEN=your_bot_token_here")
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")
    
    print("🚀 VirtualCrypto Bot を起動します...")
    print(f"📁 データベース: {DB_PATH}")
    
    guild_id = os.getenv("GUILD_ID")
    if guild_id:
        print(f"🎯 Guild 限定モード: {guild_id}")
    else:
        print("🌍 グローバルモード（全サーバー対応）")
    
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ ログインに失敗しました。Bot Tokenを確認してください。")
    except discord.HTTPException as e:
        print(f"❌ HTTP エラー: {e}")
    except KeyboardInterrupt:
        print("\n⏹️ Bot を停止します...")
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")

if __name__ == "__main__":
    main()