# VirtualCrypto Bot

Discord サーバー内で独立して動作するVirtualCrypto風通貨システムBot

## 概要

VirtualCrypto Bot は、Discord サーバー内で独自の仮想通貨システムを提供するBotです。二重仕訳台帳システムを採用し、正確な残高管理と取引履歴を維持します。

## 主な機能

### 🏦 通貨管理システム
- **通貨作成**: サーバー管理者が独自通貨を作成可能
- **通貨発行**: Treasury から通貨を発行・配布
- **通貨削除**: 条件を満たす通貨の削除機能

### 💸 取引システム
- **送金機能**: ユーザー間での通貨送金
- **残高確認**: 個人の通貨残高をプライベート表示
- **Treasury管理**: 管理者向け通貨プール管理

### 🛡️ セキュリティ機能
- **二重仕訳台帳**: 正確な残高保証
- **権限管理**: 管理者コマンドは「サーバー管理」権限が必要
- **サーバー独立**: 各サーバーで完全に独立した通貨システム

## インストール・セットアップ

### 必要要件

- Python 3.8以上
- Discord Bot Token

### 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 環境変数の設定

`.env` ファイルを作成し、以下を設定してください：

```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_guild_id_here  # 任意：特定サーバーのみで有効化
VC_DB=virtualcrypto.sqlite3  # 任意：DBファイルパス
```

### Botの起動

```bash
python virtualcrypto_core.py
```

## 利用可能なコマンド

### 👤 一般ユーザー向けコマンド

| コマンド | 説明 | 使用例 |
|----------|------|---------|
| `/pay` | 他のユーザーに通貨を送金 | `/pay to:@ユーザー symbol:GOLD amount:100 memo:ありがとう` |
| `/bal` | 自分の残高を確認（プライベート表示） | `/bal` または `/bal symbol:GOLD` |
| `/help` | コマンドの使い方を表示 | `/help` |

### 🛡️ 管理者専用コマンド

| コマンド | 説明 | 使用例 |
|----------|------|---------|
| `/create` | 新しい通貨を作成 | `/create symbol:GOLD name:ゴールドコイン decimals:2 initial_supply:10000` |
| `/give` | Treasury から通貨を発行 | `/give user:@ユーザー symbol:GOLD amount:100 memo:報酬` |
| `/treasury` | Treasury残高を確認 | `/treasury` または `/treasury symbol:GOLD` |
| `/delete` | 通貨を削除（全残高がゼロの場合のみ） | `/delete symbol:GOLD` |

### 🔧 管理・デバッグ用コマンド

| コマンド | 説明 | 使用例 |
|----------|------|---------|
| `/list` | サーバーの全通貨一覧を表示 | `/list` |
| `/fix_db` | データベース整合性を修復 | `/fix_db confirm:YES` |

## 使用例

### 1. 通貨作成から配布まで

```
1. 管理者: /create symbol:GOLD name:ゴールドコイン decimals:2 initial_supply:10000
   → GOLD通貨を作成、初期供給量10,000をTreasuryに配置

2. 管理者: /give user:@太郎 symbol:GOLD amount:100 memo:初回ボーナス
   → 太郎に100GOLD発行

3. 太郎: /pay to:@花子 symbol:GOLD amount:50 memo:お礼
   → 花子に50GOLD送金

4. 花子: /bal symbol:GOLD
   → GOLD残高を確認
```

### 2. 残高確認

```
/bal                    # 全通貨の残高表示
/bal symbol:GOLD       # GOLD通貨のみ表示
```

## データベース構造

SQLite データベースを使用し、以下のテーブル構成で二重仕訳システムを実現：

- **users**: Discord ユーザー情報
- **assets**: 通貨情報（シンボル、名前、小数桁数）
- **accounts**: 口座情報（ユーザー口座、Treasury、Burn）
- **transactions**: 取引情報
- **ledger_entries**: 仕訳エントリ（借方・貸方記録）

## システムの特徴

### ✅ 二重仕訳システム
全ての取引が借方・貸方で記録され、システム全体の残高が常に一致することを保証します。

### ✅ サーバー独立性
各Discordサーバーで完全に独立した通貨システムが動作し、相互に影響しません。

### ✅ オートコンプリート
コマンド入力時に利用可能な通貨が自動表示され、ユーザビリティを向上させています。

### ✅ 権限管理
通貨作成・発行などの重要な操作は「サーバー管理」権限を持つユーザーのみが実行可能です。

## トラブルシューティング

### よくある問題

**Q: Botが反応しない**
A: DISCORD_TOKEN が正しく設定されているか確認してください。

**Q: コマンドが表示されない**
A: Bot に適切な権限（アプリケーションコマンドの使用）が付与されているか確認してください。

**Q: データベースエラーが発生する**
A: 管理者権限で `/fix_db confirm:YES` コマンドを実行してデータベースを修復してください。

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## サポート

問題や質問がある場合は、GitHub Issues または Discord サーバーでお問い合わせください。