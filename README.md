# Local Studio

Windows用のローカル制作チャット。Open WebUIを専用Electronウィンドウで開き、Qwenの文章・画像理解、ComfyUI Animaの画像生成、ファイル操作を利用できます。Codex／Claude Code向けのstdio MCPとCLIも付属します。

## 機能

- 日本語のチャットと横サイドバーによるセッション切替
- 会話履歴・画像・資料添付の保存
- メモリ内ブラウザセッションと、終了時の専用キャッシュ削除
- ローカルQwenへの文章／画像入力
- ComfyUIとのGPUメモリ交代によるAnima画像生成
- workspace内のテキスト編集と上書き前バックアップ
- 画面で承認したPowerShellコマンドの実行
- MCPから長い処理を受け付け、再接続後に結果を取得

このリポジトリにはソースと設定例のみを含みます。モデル、アプリ依存バイナリ、会話DB、利用者の認証情報・機械固有の設定・元の保守履歴は含めません。

## 対応環境

Windows 10/11 x64、PowerShell 7.2以降、Python 3.11、Node.js 22.12以降、npm、uv。QwenのCUDA版には対応するNVIDIA GPUとドライバーが必要です。

現在は `C:\AI\LocalLLM`、Qwen `127.0.0.1:18080`、Open WebUI `127.0.0.1:18081` の固定構成です。別の保存先・ポートへの変更はまだサポートしていません。モデル取得だけで約18 GBあり、依存関係と利用データの追加領域も必要です。基になった環境は24 GB VRAMのRTX 4090で検証しました。他GPUでの性能・適合性は未確認です。

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

## ComfyUI（任意）

別途ComfyUIを `127.0.0.1:8188` で起動します。付属ワークフローは `anima-base-v1.0.safetensors`、`qwen_3_06b_base.safetensors`、`qwen_image_vae.safetensors` と、それらのローダーに対応する環境が必要です。本リポジトリはComfyUI／モデル／カスタムノードを自動導入しません。`config/anima-chat-workflow.json` を確認し、実際の環境に合わせてください。

## Codex／Claude Code

Setupで生成される `.codex/config.toml` と `.mcp.json` をこのプロジェクトで読み込ませます。生成された設定はGit対象外です。別プロジェクトでも使う場合は、同じ起動コマンドを各クライアントのユーザー設定へ登録してください。ツールが見えない場合はMCP接続を再起動します。

| ツール | 用途 |
| --- | --- |
| `studio_status` | 接続・ワーカー状態 |
| `ask_qwen` | 文章／workspace画像をQwenへ渡す |
| `generate_anima` | Animaで新規画像を生成 |
| `task_result` | job_idで結果を取得 |
| `list_workspace` | ファイル一覧 |
| `read_workspace_file` | UTF-8ファイルを読む |
| `write_workspace_file` | 保存・バックアップ付き編集 |

`ask_qwen` と `generate_anima` はjob_idを返します。実処理は独立ワーカーで進むため、MCP接続を閉じても継続します。MCPの単発処理はデスクトップのチャット一覧へ自動追加しません。

## 検証

```powershell
python scripts/Verify-Source.py
python scripts/Test-ChatTools.py
node --check desktop/main.cjs
```

基になったローカル環境で、専用ウィンドウ・終了時キャッシュ削除・履歴／画像保持・MCP 7ツール・再接続中のAnima生成完了を確認しました。テスト結果と制限は [docs/VALIDATION.md](docs/VALIDATION.md) に区別して記載しています。

詳しい運用は [ユーザーガイド](docs/USER-GUIDE.md)、公開範囲と依存ライセンスは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## ライセンス

このリポジトリの独自コードはMIT。Open WebUI、Electron、llama.cpp、ComfyUI、各モデルはそれぞれの利用条件に従います。Open WebUIの画面上の名称・ロゴは維持しています。
