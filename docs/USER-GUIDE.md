# Local Studio ユーザーガイド

## チャット

`C:\AI\LocalLLM\Local Studio.lnk` または `Start-ChatApp.cmd` を開きます。通常ブラウザは不要です。左上ボタンで横サイドバーを開閉し、「新しいチャット」や既存の会話を選びます。メニューの「チャット → 新しいセッション」はCtrl+Nです。

画面の＋から画像・テキスト資料を添付できます。Qwenへの質問とファイル作業は日本語で利用できます。大きな資料は必要な範囲に分けてください。履歴は保持しますが、表示設定・未送信入力など画面内だけの状態は終了時にリセットされます。

## 画像・動画生成とファイル

ComfyUIを起動してから「青いティーポットを512×512で生成して」と依頼します。生成時はQwenを止めてGPUメモリを空け、完了後に復帰します。その間の別送信・手動GPUジョブ投入は待ってください。既にComfyUIが忙しい場合は処理を拒否します。既存画像の編集機能ではありません。

「企画をdrafts/idea.mdに保存して」でworkspace内へ保存できます。既存テキストの上書き前にはバックアップします。PowerShellは正確なコマンド内容を画面で確認してから実行します。PowerShellの作業フォルダはOSサンドボックスではなく、Windowsユーザー権限で動作します。

## キャッシュ・データ・終了

- `cache/desktop-session`: 画面の一時領域。メモリ内sessionとHTTP cache無効を併用し、画面終了後と次回起動前に削除。
- `data/open-webui`: 会話・添付・認証用秘密値。削除対象外。
- `data/agent-jobs`: MCP/CLIの入力と結果。削除対象外。
- `workspace`: 利用者のファイル、生成画像・動画、学習準備フォルダ。削除対象外。
- `data/file-backups`: 編集前のテキスト。削除対象外。
- `cache/npm-desktop` 等: インストール時の取得キャッシュ。画面キャッシュとは別。

ウィンドウの×は画面だけを終了し、裏側のワーカー・Qwen・Open WebUIを維持します。全停止する場合は処理完了後に画面を閉じ、`Stop-ChatApp.cmd` を実行します。待機／実行中のエージェント処理があれば停止を拒否します。ComfyUI本体は停止しません。

異常終了でキャッシュ削除ができなくても次回起動時に再処理します。通常ブラウザに以前保存されたキャッシュは触りません。

## CLI

画面なしの起動は `Start-AgentBackend.cmd`。Windowsへの自動起動登録は行いません。

```powershell
& 'C:\AI\LocalLLM\Studio-CLI.cmd' status
& 'C:\AI\LocalLLM\Studio-CLI.cmd' ask 'アイデアを3つ提案して' --wait
& 'C:\AI\LocalLLM\Studio-CLI.cmd' ask '画像を説明して' --image 'images/example/image.png' --wait
& 'C:\AI\LocalLLM\Studio-CLI.cmd' generate 'A blue ceramic teapot on a white table' --width 512 --height 512
& 'C:\AI\LocalLLM\Studio-CLI.cmd' task '返されたjob_id'
```

## 通信範囲

Qwenと各画像・動画モデルの推論はローカルです。Codex／Claudeから呼び出す場合、その依頼とツール結果は呼び出し元にも渡ります。PC内だけで扱う内容は専用アプリで入力してください。

単一ユーザー・loopback限定で、ネットワーク公開用ではありません。起動したPC上の他プロセスからはAPIへアクセス可能です。ポートを外部へ公開しないでください。MiniMax H3の動画内音声以外の音声処理、外部Web検索、任意動画編集、既存画像編集は未対応です。

## モデル指定とLoRA準備

「Qwen Image 2.1で白いカップを生成」「MiniMax H3で赤い帆船が進む2秒の動画を生成」のように指定します。生成動画はチャット内で再生できます。Qwen3.8は会話モデル、Qwen Image 2.1は画像モデルです。

メニューの **制作 → LoRA学習の準備** でAnima／Qwen Image 2.1／MiniMax H3／Qwen3.8を選べます。データ形式・手順・公式手順のURLを確認し、英数字・ハイフン・アンダースコアの名前で準備フォルダを作成します。この操作はモデル取得、環境インストール、学習を実行しません。学習環境が存在しても実動作検証済みとは表示しません。

```powershell
& 'C:\AI\LocalLLM\Studio-CLI.cmd' generate 'A red sailboat moving on a pond, soft water sounds' --model minimax-h3 --seconds 2 --wait
& 'C:\AI\LocalLLM\Studio-CLI.cmd' generate 'A white ceramic cup' --model qwen-image-2.1 --width 512 --height 512 --wait
& 'C:\AI\LocalLLM\Studio-CLI.cmd' training-guide
& 'C:\AI\LocalLLM\Studio-CLI.cmd' prepare-training anima character-study
```

詳しい前提は [モデル設定と学習準備](MEDIA-AND-TRAINING.md) を参照してください。
