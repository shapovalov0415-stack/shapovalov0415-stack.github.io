# Claude × Instagram 連携 — 動画の検証と、実際に動かすための道具

動画（54秒, 2026-10-24 受領）の内容を文字起こしして事実確認し、**動画のやり方の危険な部分を直した手順**と、
トークンが用意できたらすぐ使える **CLI（`ig.py`）** をまとめたもの。

---

## 1. 動画が言っていること（画面テロップの文字起こし）

| 時刻 | テロップ |
|---|---|
| 0:00 | Claude×Instagram 神連携 / 直接連携できるようになりました |
| 0:06 | 投稿・コメント・DM（アイコン3種） |
| 0:10 | 任せられるようになったので |
| 0:12 | 伸びている投稿の分析も |
| 0:14 | お願いできるようになっちゃいます |
| 0:16 | **① Meta for Developers でアプリを作る** |
| 0:18–0:20 | 「Meta for Developers」で検索 → 一番上に出てくる公式サイトを開いて |
| 0:22 | Facebookでログインして |
| 0:24 | **② Instagram と連携する** |
| 0:26–0:28 | Instagram のユースケース（「Instagramでメッセージとコンテンツを管理」）を選んで / 自分の Instagram のアカウントを連携 |
| 0:30 | **③ アクセストークンを Claude に渡す** |
| 0:32 | グラフAPIエクスプローラーにアクセスして |
| 0:36 | 自分が利用したいアクセス許可を追加 |
| 0:38 | キーを生成できます |
| 0:40 | それを Claude と連携させれば OK |
| 0:42–0:44 | ただ連携できるのは 個人アカウントじゃなくて…（※この後の結論テロップは無し。音声で「プロアカウントだけ」と続いていると推測） |
| 0:46– | 宣伝パート |

0:34 の画面には実際のグラフAPIエクスプローラーが映っており、付与スコープは
`pages_show_list` / `business_management` / `instagram_basic` / `instagram_manage_insights` /
`pages_read_engagement` / `instagram_creator_marketplace_discovery` が読み取れる。
→ これは **Facebook ログイン方式**（Facebook ページ連携が必要な方）のスコープ。

---

## 2. 事実確認

| # | 動画の主張 | 判定 | 補足 |
|---|---|---|---|
| 1 | 投稿・コメント・DM・インサイトを API で操作できる | ✅ 正しい | Meta の Instagram Platform は content publishing / comment moderation / messaging / insights を公式に提供 |
| 2 | 使えるのは個人アカウントではない | ✅ 正しい | プロアカウント（ビジネス or クリエイター）が必須 |
| 3 | Meta for Developers でアプリを作る | ✅ 正しい | 手順そのものは現行 |
| 4 | 「直接連携できるようになりました」 | ⚠️ 誇張 | **Anthropic 公式の Instagram コネクタは確認できない**。実体は「アクセストークンを渡して Claude に Graph API を叩かせる」方式。サードパーティ製 MCP コネクタは多数ある（Metricool / Planoly / Composio など、いずれも非公式） |
| 5 | グラフAPIエクスプローラーで出したキーをそのまま使う | ⚠️ 不十分 | Explorer のユーザートークンは **約1時間で失効**。`/access_token`（`ig_exchange_token`）で **60日の長期トークン**に交換し、以後 `refresh_access_token` で更新する必要がある |
| 6 | 動画のスコープ構成 | ⚠️ 条件付き | `instagram_basic` 系＝Facebook ログイン方式。**Instagram プロアカウントを Facebook ページに連携**する必要がある。ページ無しで済ませたいなら Instagram ログイン方式（`instagram_business_*` 系, ホストは `graph.instagram.com`） |
| 7 | （動画は触れていない）他人のアカウントも扱える | ❌ 要App Review | 自分＝アプリに役割があるユーザーのアカウントなら開発モード/Standard Access のままで可。第三者のアカウントを扱うには App Review が必要 |
| 8 | （動画は触れていない）DM 自動化の制約 | ⚠️ 重要 | 相手から来たメッセージへの返信が基本。**24時間ウィンドウ**などの制約があり、Meta のプラットフォーム規約の対象 |
| 9 | （動画は触れていない）投稿数の上限 | ⚠️ 重要 | API 経由の投稿は 24時間あたり 50件（Meta ドキュメント内に 50 と 100 の記述ゆれあり）。`ig.py limit` で実測を確認するのが確実 |
| 10 | （動画は触れていない）指標名の変更 | ⚠️ 重要 | `impressions` / `plays` は 2025年4月以降 `views` に置換済み。古い記事のコードはそのままでは動かない |

> 出典は本ファイル末尾。`developers.facebook.com` はこのサンドボックスから直接取得できなかったため、
> 公式ドキュメントの内容は検索経由の要約で確認した（一次情報での再確認を推奨）。

---

## 3. ⚠️ 動画の ③ は、そのままやってはいけない

アクセストークンは「**あなたのアカウントで投稿・DM送信・コメント削除ができる鍵**」そのもの。
チャット欄に貼ると会話履歴（＝複数の場所に残るログ）に平文で残る。

**正しい置き場所：**

- Claude Code クラウドの **環境設定 → Network secrets（旧：API credentials）／環境変数** に `IG_ACCESS_TOKEN` として登録する。新しいセッションから読み込まれる。
- アプリシークレット（`IG_APP_SECRET`）はトークン交換時だけ使い、同じく環境変数に置く。クライアント側に出さない。
- スコープは必要最小限だけ付ける（分析だけなら publish / messages は付けない）。
- 漏れたと思ったら Meta 側でトークンを失効させて再発行する。

このリポジトリは **公開リポジトリ** なので、トークンやシークレットは絶対にコミットしない（`.gitignore` 済み）。

---

## 4. 修正版の手順

### 方式A：Instagram ログイン（推奨 / Facebook ページ不要）

1. Instagram アプリで アカウント → プロアカウントに切替（ビジネス or クリエイター）
2. [Meta for Developers](https://developers.facebook.com/) でアプリ作成 → ユースケース「Instagram でメッセージとコンテンツを管理」
3. 「Instagram アカウントを連携」→ 自分のプロアカウントを認可
4. スコープを付与：
   - `instagram_business_basic`（必須）
   - `instagram_business_content_publish`（投稿する場合）
   - `instagram_business_manage_comments`（コメント取得・返信する場合）
   - `instagram_business_manage_messages`（DM を扱う場合）
5. 短命トークン（1時間）を取得 → 長期トークン（60日）に交換
   ```bash
   IG_ACCESS_TOKEN=<短命トークン> IG_APP_SECRET=<app secret> \
     python3 ig.py token-exchange --out ./ig.token      # 600 で保存、標準出力にはマスク表示のみ
   ```
6. `./ig.token` の中身を環境変数 `IG_ACCESS_TOKEN` に登録（チャットに貼らない）
7. 60日ごと（24時間以上経過してから）に更新
   ```bash
   python3 ig.py token-refresh --out ./ig.token
   ```

### 方式B：Facebook ログイン（動画と同じ）

方式A との違いだけ：

- Instagram プロアカウントを **Facebook ページに連携** しておく
- `IG_AUTH_MODE=facebook`（ホストが `graph.facebook.com` になる）
- スコープは `instagram_basic` / `instagram_content_publish` / `instagram_manage_comments` / `instagram_manage_insights` / `pages_show_list` / `pages_read_engagement`
- アカウント ID は `/me/accounts` → `instagram_business_account` から解決（`ig.py whoami` が自動でやる）

---

## 5. `ig.py` の使い方

依存ライブラリなし（Python 3 標準ライブラリのみ）。トークンは環境変数からのみ読む。
**書き込み系は `--yes` を付けない限り送信しない**（付けなければ送る予定のリクエストを表示して終了）。

```bash
export IG_ACCESS_TOKEN=...          # 環境のシークレットから
export IG_AUTH_MODE=instagram       # 方式B なら facebook

python3 ig.py whoami                                   # トークンの持ち主を確認
python3 ig.py media --limit 10                         # 直近の投稿
python3 ig.py top --limit 12                           # 伸びている投稿の分析（エンゲージメント率で並べ替え）
python3 ig.py insights --metrics views,reach,accounts_engaged
python3 ig.py comments <media_id>                      # コメント一覧
python3 ig.py reply <comment_id> "ありがとうございます！" --yes
python3 ig.py hide <comment_id> --yes                  # 非表示（--unhide で戻す）
python3 ig.py private-reply <comment_id> "DMしますね" --yes
python3 ig.py conversations                            # DM スレッド一覧
python3 ig.py messages <conversation_id>
python3 ig.py dm-send <igsid> "お問い合わせありがとうございます" --yes
python3 ig.py publish-image --image-url https://… --caption "本文" --yes
python3 ig.py publish-reel  --video-url https://… --caption "本文" --yes
python3 ig.py publish-carousel --image-url https://a.jpg --image-url https://b.jpg --caption "本文" --yes
python3 ig.py limit                                    # 24時間の投稿枠の残り
python3 ig.py get <path> --param fields=id,username    # 任意のパスを叩く
python3 ig.py --dry-run <任意のコマンド>                 # 送らずにリクエストだけ表示
```

投稿する画像・動画は **公開 URL が必要**（Instagram 側が取りに来る）。ローカルファイルは直接投稿できない。
`publish-*` は「コンテナ作成 → `status_code=FINISHED` までポーリング → 公開」の 3 段階を自動で行う。

---

## 6. 既知の制限

- **このクラウドサンドボックスからは `graph.facebook.com` / `graph.instagram.com` に到達できない**（プロキシが 403 を返す）。
  Claude のクラウド環境設定 → Network access で両ホストを許可ドメインに追加すれば、このセッションからも実行できる。
  手順: https://code.claude.com/docs/en/cloud-environments#network-access
  許可しない場合は、手元の Mac などで `ig.py` を実行する。
- コメント非表示のパラメータは `hide=true` を使用（一部の非公式記事は `hidden=true` と記載しており、ここは一次情報で要確認）。
- インサイトの指標はメディア種別（画像 / リール / ストーリーズ）で使えるものが違う。`top` は取得できなかった指標をエラー文付きで返す。
- Graph API のバージョンは既定 `v26.0`（2026-07-29 リリース）。`IG_API_VERSION` で変更可能。

## 出典

- Instagram Platform 概要 / Instagram API with Instagram Login — https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
- Business Login for Instagram（スコープ一覧） — https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
- Content Publishing（コンテナ→公開、投稿上限） — https://developers.facebook.com/docs/instagram-platform/content-publishing
- Comment Moderation — https://developers.facebook.com/docs/instagram-platform/comment-moderation
- 長期トークンへの交換 / 更新 — https://developers.facebook.com/docs/instagram-platform/reference/access_token , https://developers.facebook.com/docs/instagram-platform/reference/refresh_access_token
- Graph API v26.0 リリース（2026-07-29） — https://developers.facebook.com/blog/post/2026/07/29/introducing-graph-api-v26-and-marketing-api-v26/
- `impressions` → `views` 置換 — https://www.socialmediatoday.com/news/meta-deprecates-impressions-in-favor-of-views-api/757958/
- Claude 側に公式 Instagram コネクタが無いことの傍証（第三者ガイド） — https://metricool.com/connect-claude-to-instagram/ , https://composio.dev/toolkits/instagram/framework/claude-code.md
