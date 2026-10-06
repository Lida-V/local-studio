# Local Studio

Windows用のローカル制作チャット。Open WebUIを専用Electronウィンドウで開き、Qwenの文章・画像理解、ComfyUIによるAnima／Qwen Image 2.1の画像生成、MiniMax H3の音声付き動画生成、ファイル操作を利用できます。Codex／Claude Code向けのstdio MCPとCLIも付属します。

## 機能

- プロジェクトフォルダ選択・現在の作業先表示・再起動後の保持
- 日本語のチャットと横サイドバーによるセッション切替
- 会話履歴・画像・資料添付の保存
- メモリ内ブラウザセッションと、終了時の専用キャッシュ削除
- ローカルQwenへの文章／画像入力
- 通常Qwen／追加したHuihui Qwen／StrataのFlash Nextの切替と、作業中の切替防止
- ComfyUIとのGPUメモリ交代によるAnima／Qwen Image 2.1画像・MiniMax H3動画生成
- 4モデルのLoRA準備画面と素材フォルダ作成（学習・モデル取得は開始しません）
- 選択したプロジェクト内のテキスト編集と上書き前バックアップ
- ファイル名・本文検索、ページ単位の一覧、UTF-8／UTF-16／CP932テキストの行指定読取
- 実行状況・最後の更新からの時間・承認待ち・停止状態の常時表示
- 待機中の追加指示を「今すぐ送信」で1回だけ割り込み送信
- 画面で承認したPowerShellコマンドの実行
- MCPから長い処理を受け付け、再接続後に結果を取得

このリポジトリにはソースと設定例のみを含みます。モデル、アプリ依存バイナリ、会話DB、利用者の認証情報・機械固有の設定・元の保守履歴は含めません。

## 対応環境

Windows 10/11 x64、PowerShell 7.2以降、Python 3.11、Node.js 22.12以降、npm、uv。任意のStrata導入にはGitも必要です。QwenのCUDA版には対応するNVIDIA GPUとドライバーが必要です。

現在は `C:\AI\LocalLLM`、Qwen `127.0.0.1:18080`、Open WebUI `127.0.0.1:18081` の固定構成です。別の保存先・ポートへの変更はまだサポートしていません。初期Qwenモデル取得だけで約18 GBあり、依存関係と利用データの追加領域も必要です。基になった環境は24 GB VRAMのRTX 4090で検証しました。他GPUでの性能・適合性は未確認です。

## 導入

1. ソースをダウンロードまたはcloneし、そのフォルダをPowerShell 7で開きます。
2. 上記のPython・Node.js・uvを用意します。
3. Python 3.11の実行ファイルを指定して設定を生成します。

```powershell
pwsh -File scripts/Setup.ps1 -Python 'C:/path/to/Python311/python.exe'
```

4. `config/support-config.json` とダウンロード元のモデル／ソフトウェア利用条件を確認します。
5. 新規環境への導入を実行します。Qwen／llama.cppの取得、SHA256検証、Open WebUIとElectronの導入、プロジェクト内MCP設定を行います。

```powershell
pwsh -File scripts/Setup.ps1 -Python 'C:/path/to/Python311/python.exe' -Install
```

6. `C:\AI\LocalLLM\Local Studio.lnk` を開きます。

既存のLocalLLM環境がある場合、Setupは上書きを拒否します。元の設定・DBをバックアップし、個別スクリプトと変更内容を確認して移行してください。初期公開版のソース検査・境界テストは実施済みですが、公開用Setupを未使用PCで一括実行する検証は未実施です。

## Huihui会話モデル（任意）

既存の通常Qwenを保持して、配布者のUD-DW-Q4_K_M版を追加できます。約16.6GBの追加領域と取得時の5GiB余裕が必要です。設定済みのソースフォルダで実行します。

```powershell
$studioPython = (Get-Content -Raw -Encoding utf8 config/support-config.json | ConvertFrom-Json).chatApp.python
& $studioPython -B -X utf8 scripts/Install-Huihui.py
pwsh -File scripts/Deploy-ModelEntrypoints.ps1
pwsh -File scripts/Start-ChatApp.ps1
& $studioPython -B -X utf8 scripts/Deploy-PromptSkill.py
& $studioPython -B -X utf8 scripts/Local-Studio.py model-select huihui-qwen
```

通常版へ戻すには `model-select qwen-standard` を使います。拒否の低減や創作品質は保証されません。これは会話・画像理解モデルの切替で、ComfyUIのQwen Image 2.1とは別です。プロファイルの意味、ダブルクリックの入口、固定配布元と復旧手順は [モデル選択ガイド](docs/model-profiles.md) を参照してください。

## Strata + Qwen3.8 Flash Next（任意）

既存の `C:\AI\LocalLLM` のアプリとデータを使い、会話・画像理解のバックエンドをStrataへ切り替える追加導入です。初期設定例と新規Setupは通常Qwenのままです。対象はWindows x64、RTX 4090 24GB、約158GiB RAM、NVIDIAドライバー580以降の構成です。この構成でStrata APIの8項目とOpen WebUI・MCPの合成入力検証が成功しました。StrataのGPU解放・再起動・既存Anima生成後の復帰も成功し、元の導入環境の旧27Bを条件付きで削除しました。他GPU・RAM容量での適合性は未確認です。

配布元を固定したGSQ-RCO IQ3_Sの2分割GGUF（合計約83.6GB）、画像用projector（約0.91GB）、MTP（約5.2GB）とエンジン・専用Python依存を取得します。準備用の余裕を含め100GB以上の追加領域を用意してください。ダウンローダーはサイズとSHA256を確認します。モデルの利用条件は[Qwen公式ライセンス](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/de4b8e4d43b917e7706784d8bb445c9af86a3540/LICENSE)です。

既存アプリを構築したLocal Studioのソースフォルダを更新し、同じフォルダの設定を使って、既存の処理が完了してから実行します。別フォルダから実行すると既存のショートカットやCLIが古いソースを参照するため、元のソースフォルダを使ってください。Strataの初回cloneは次のとおりです。既に同じ保存先にソースがある場合は、削除や上書きをせず、固定commitと未変更のソースであることを確認してください。

```powershell
git clone --branch v0.1.39 --single-branch https://github.com/Niko1221/Strata.git C:/AI/LocalLLM/apps/Strata/source
git -C C:/AI/LocalLLM/apps/Strata/source checkout --detach 6f32ec070f23ced9f50e704d854d775da52591ab

$studioPython = (Get-Content -Raw -Encoding utf8 config/support-config.json | ConvertFrom-Json).chatApp.python
pwsh -File scripts/Start-ChatApp.ps1
& $studioPython -B -X utf8 scripts/Deploy-PromptSkill.py
& $studioPython -B -X utf8 scripts/Install-StrataFiles.py
pwsh -File scripts/Prepare-Strata.ps1 -Phase Dependencies
pwsh -File scripts/Prepare-Strata.ps1 -Phase Model -ContextSize 131072
& $studioPython -B -X utf8 scripts/Local-Studio.py model-select qwen-flash-next
pwsh -File scripts/Start-ChatApp.ps1
& $studioPython -B -X utf8 scripts/Deploy-StrataChat.py --apply
& $studioPython -B -X utf8 scripts/Verify-StrataLive.py --phase all
```

`Prepare-Strata.ps1` は[Strata v0.1.39](https://github.com/Niko1221/Strata/releases/tag/v0.1.39)のWindows CUDA 13エンジンと専用venvを準備し、Model段階で固定revision・tensor範囲・SHA256を使う `Fetch-StrataMTP.py` を呼びます。グローバルPythonやドライバーを入れ替える処理ではありません。

最初の `Start-ChatApp.ps1` と `Deploy-PromptSkill.py` は既存バックエンドで更新済みツールと切替保護APIを配備する段階です。このAPIが未配備の場合、モデル切替は拒否されます。

このプロファイルの入力枠は131,072トークンです。専用アプリ併用の実測に合わせ、VRAM予約は1536MiBにしています。長文検索は15,673トークンの合成入力で検証しました。入力枠全体を埋める128Kの検証は未実施です。`Deploy-StrataChat.py` は既存の会話プリセットを保持し、表示名と履歴圧縮の設定を更新します。`--apply` を省くと変更予定だけを表示します。画像、日本語、ツール結果と出力に余裕を残すため、履歴圧縮は入力枠より早く開始します。

`Verify-StrataLive.py --phase all` は合成した日本語・図形画像・ダミーツール・長文検索・切断後の復帰をStrata APIで検査し、結果を `C:\AI\LocalLLM\tests` へ保存します。Open WebUIの画面、MCP、画像生成とのGPU交代は別に確認してください。旧モデルの削除は必要な動作を確認した後に判断します。通常版へ戻す `model-select qwen-standard` には、旧モデルとllama.cppが残っている必要があります。拒否の低減や創作品質は保証されません。

StrataのJSON schemaは生成後の検証方式です。文法で生成を制約する方式ではなく、`response_format` とtools/MCPの併用にも制限があります。詳しくは [検証範囲とAPI制限](docs/VALIDATION.md#strata--qwen38-flash-next-2026-10-06) を参照してください。成人向け内容の適合性・拒否率・創作品質は未評価です。

## Swift 1.5 Flash Next（任意）

Strataの準備済み環境へ[SC117のSwift 1.5 abliterated IQ3_XXS](https://huggingface.co/SC117/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)を追加できます。2分割GGUFと独立projectorは合計約76.7GB。通常のFlash Nextを保持し、専用native packを作ります。SwiftではPLEがshard 1にあるため、通常版のpackやshard 2指定を流用できません。SHA256が一致する既存MTP runtimeだけを共有し、`--spec 4` を維持します。

```powershell
$studioPython = (Get-Content -Raw -Encoding utf8 config/support-config.json | ConvertFrom-Json).chatApp.python
& $studioPython -B -X utf8 scripts/Install-SwiftFiles.py
& $studioPython -B -X utf8 scripts/Prepare-SwiftStrata.py --apply
& $studioPython -B -X utf8 scripts/Local-Studio.py model-select swift-flash-next
& $studioPython -B -X utf8 scripts/Verify-StrataLive.py --phase all --canonical swift1.5-qwen3.8-flash-next-iq3_xxs
pwsh -File scripts/Deploy-ModelEntrypoints.ps1 -ProfileId swift-flash-next
```

準備スクリプトはStrataの固定commit、取得物のサイズ・SHA256、共有MTPを検査し、既存packと設定を上書きしません。`--apply` を省くと確認と計画表示だけです。実行するソースフォルダは既存のLocal Studioと同じものを使います。切り戻しは `model-select qwen-flash-next`。新規PCの一括Setupや、配布者が説明する拒否低減の効果は別途検証が必要です。

重みには[Swift Open License 1.0](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF/blob/b22d729eae29b5796f76fb70f91aef549b9fc52c/LICENSE)とQwen Community License 1.0が適用されます。Swiftの商用条項は関連法人を含む直近会計年度の総売上を基準にUS$1,000,000のThresholdを定義します。対象企業には別途商用ライセンスの条項があるため、ゲーム単体の売上だけで判断せず保存した原文を確認してください。

## ComfyUI（任意）

別途ComfyUIを `127.0.0.1:8188` で起動します。付属ワークフローは `anima-base-v1.0.safetensors`、`qwen_3_06b_base.safetensors`、`qwen_image_vae.safetensors` と、それらのローダーに対応する環境が必要です。本リポジトリはComfyUI／モデル／カスタムノードを自動導入しません。`config/anima-chat-workflow.json` を確認し、実際の環境に合わせてください。

画像・動画の追加モデルは [モデル設定ガイド](docs/MEDIA-AND-TRAINING.md) を参照してください。追加の重み・カスタムノードは別途必要です。

## Codex／Claude Code

Setupで生成される `.codex/config.toml` と `.mcp.json` をこのプロジェクトで読み込ませます。生成された設定はGit対象外です。別プロジェクトでも使う場合は、同じ起動コマンドを各クライアントのユーザー設定へ登録してください。ツールが見えない場合はMCP接続を再起動します。

| ツール | 用途 |
| --- | --- |
| `current_project` | 現在の作業フォルダを確認 |
| `select_project` | ユーザー指定の既存フォルダを選択 |
| `studio_status` | 接続・ワーカー状態 |
| `ask_qwen` | 文章／workspace画像をQwenへ渡す |
| `generate_anima` | Animaで新規画像を生成 |
| `generate_qwen_image` | Qwen Image 2.1で新規画像を生成 |
| `qwen_image21_prompt_guide` | Qwen Image 2.1のプロンプト設計を用途別・小分けで参照 |
| `generate_minimax_video` | MiniMax H3で短い音声付き動画を生成 |
| `training_guide` | 4モデルの学習準備案内 |
| `prepare_training` | 素材・設定例のフォルダのみ作成 |
| `task_result` | job_idで結果を取得 |
| `list_workspace` | ページ単位のファイル一覧 |
| `search_workspace` | ファイル名／本文を検索 |
| `read_workspace_file` | 行指定でテキストを読む（UTF-8／UTF-16／CP932） |
| `write_workspace_file` | 保存・バックアップ付き編集 |

`ask_qwen` と3つの生成ツール はjob_idを返します。実処理は独立ワーカーで進むため、MCP接続を閉じても継続します。MCPの単発処理はデスクトップのチャット一覧へ自動追加しません。

## 検証

```powershell
python scripts/Verify-Source.py
python scripts/Test-ChatTools.py
python scripts/Test-MediaRoutes.py
python scripts/Test-ProjectWorkspace.py
python scripts/Test-AgentReliability.py
python scripts/Test-ModelProfiles.py
python scripts/Test-ModelSwitch.py
python scripts/Test-ModelMaintenance.py
python scripts/Test-RangeDownload.py
python scripts/Test-StrataLifecycle.py
python scripts/Test-StrataChat.py
python scripts/Test-StrataMTP.py
python scripts/Test-SwiftStrata.py
python scripts/Test-SwiftDownload.py
node scripts/Test-QueueInsertion.cjs
node --check desktop/main.cjs
```

基になったローカル環境で、専用ウィンドウ・終了時キャッシュ削除・履歴／画像保持・MCP 11ツール・再接続中のAnima生成完了を確認しました。テスト結果と制限は [docs/VALIDATION.md](docs/VALIDATION.md) に区別して記載しています。

Strata追加後はMCP 15ツール、合成質問のjob結果取得、Open WebUIのガイド参照とプロンプトのみの応答をAPIで確認しました。`Test-StrataMTP.py` は11件のオフライン検査で、Strataの固定ソースが未準備の場合は上流コードを使う8件をskipします。テストからソースや重みは取得しません。

詳しい運用は [ユーザーガイド](docs/USER-GUIDE.md)、公開範囲と依存ライセンスは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## ライセンス

このリポジトリの独自コードとStrataのエンジンコードはMIT。Qwen3.8 Flash Nextの重みはQwen Community License 1.0、Swift派生モデルにはSwift Open License 1.0の追加条件があります。エンジンのMITは重みの利用条件を置き換えません。Open WebUI、Electron、llama.cpp、ComfyUI、他のモデルはそれぞれの利用条件に従います。Open WebUIの画面上の名称・ロゴは維持しています。
