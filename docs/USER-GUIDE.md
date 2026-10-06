# Local Studio ユーザーガイド

## 作業するプロジェクトを選ぶ

画面上部の **フォルダを選択**、または **プロジェクト → フォルダを選択…**（Ctrl+Alt+O）から既存のフォルダを指定します。現在のパスは常時表示され、再起動後も保持します。「開く」でエクスプローラーに表示、「標準へ戻す」で `C:\AI\LocalLLM\workspace` へ戻せます。

選択は **全チャット・CLI・MCP共通** です。プロジェクトを切り替えると、次のファイル参照・編集、生成物の保存、学習準備の作成先が変わります。会話の途中では完了を待ってから切り替えてください。受付済みのMCP/CLIジョブと承認待ちコマンドは受付時の作業先を保持します。フォルダを選ぶだけでは既存の会話・添付・ファイルを移動したり、学習を開始したりしません。

ファイルツールは選択先からの相対パスを使います。`../` やフォルダ外へ向くリンクは拒否し、上書き前バックアップは従来のデータ領域へ保存します。選択先が削除・切断された場合はエラーになり、別の場所へ勝手に書き出しません。ドライブ直下やネットワーク共有は選択できません。

```powershell
& 'C:\AI\LocalLLM\Studio-CLI.cmd' project
& 'C:\AI\LocalLLM\Studio-CLI.cmd' project-select 'D:\Projects\MyProject'
& 'C:\AI\LocalLLM\Studio-CLI.cmd' project-reset
```

Codex／ClaudeのMCPでは `current_project` と `select_project` を使います。新しいツールが出ない場合はMCPを再接続してください。

## チャット

`C:\AI\LocalLLM\Local Studio.lnk` または `Start-ChatApp.cmd` を開きます。通常ブラウザは不要です。左上ボタンで横サイドバーを開閉し、「新しいチャット」や既存の会話を選びます。メニューの「チャット → 新しいセッション」はCtrl+Nです。

画面の＋から画像・テキスト資料を添付できます。Qwenへの質問とファイル作業は日本語で利用できます。大きな資料は必要な範囲に分けてください。履歴は保持しますが、表示設定・未送信入力など画面内だけの状態は終了時にリセットされます。

## 会話モデルの選択

初期設定は通常のQwen3.8-27Bです。準備済みのHuihui版、またはStrataのQwen3.8 Flash Next IQ3_SへCLIで切り替えられます。Flash Nextの追加導入は [READMEのStrata手順](../README.md#strata--qwen38-flash-next任意) を先に実行してください。ダウンロードや準備を済ませていないモデルは選択できません。

```powershell
& 'C:\AI\LocalLLM\Studio-CLI.cmd' model-profiles
& 'C:\AI\LocalLLM\Studio-CLI.cmd' model-select qwen-flash-next
& 'C:\AI\LocalLLM\Studio-CLI.cmd' model-select swift-flash-next
```

切替は、チャット・待機中の依頼・画像動画生成が完了してから行います。履歴と会話プリセットは引き継ぎます。Strataの入力枠は131,072トークンで、履歴圧縮は画像、日本語、ツール結果と出力に余裕を残して開始します。長い資料は必要な範囲を指定してください。日本語JSON、図形画像2枚、ツール往復、通常のストリーム応答、15,673トークンの長文検索、接続切断後の復帰をAPIで検証しました。128K全体の入力は未検証です。

Open WebUIの合成プロンプト作成とMCPの合成質問も成功しました。専用アプリの起動、GPU解放・再起動・Anima生成後の復帰も確認済みです。元の導入環境では、確認後に旧27B重みだけを削除しました。会話画面のクリック操作は今回のAPI検証には含みません。詳細とAPIのJSON schema制限は [検証範囲](VALIDATION.md#strata--qwen38-flash-next-2026-10-06) を参照してください。

`model-select qwen-standard` で通常版、`model-select huihui-qwen` でHuihui版に戻せます。削除済みの重みや未準備の実行環境へは戻せません。これは会話・画像理解のバックエンド選択です。ComfyUIで使うQwen Image 2.1の選択は別の操作です。拒否の低減や創作品質は保証されません。

Swift 1.5 IQ3_XXSの追加は [Swift導入手順](../README.md#swift-15-flash-next任意) と [Swift固有の検証結果](VALIDATION.md#optional-swift-15-flash-next-2026-10-06) を参照してください。準備後は `SwiftでLocal Studio.cmd` でも選べます。現在のFlash Nextの重みを保持するため、`model-select qwen-flash-next` で戻せます。会話履歴は同じDBを使用します。モデルを切り替えた後に挙動を比較する場合は、新しいチャットで試すと以前の応答の影響を分けやすくなります。

このアプリが付加する制作アシスタント指示には、性的内容を一律に拒否する指定はありません。モデル自身の学習挙動や渡された会話履歴によって応答は変わります。生成された自己紹介や「自分のポリシー」の説明だけでは、実際のサーバー設定やモデルの判定根拠は分かりません。

## 作業状況と追加指示

作業フォルダの下に、準備中・モデルの応答待ち・応答中・ツール実行中・承認待ち・停止処理中・完了・エラーを表示します。実行中は経過時間と最後の状態更新からの時間も確認できます。「接続を確認できません」は停止の確定ではありません。

作業中に追加の指示を入力して送信すると待機欄に入ります。待機欄の「今すぐ送信」を1回押すと、現在の応答を止めて、その指示を含む応答へ再開します。上部に受付・送信の状態が出ます。通常の待機欄の指示は今の応答が終わってから処理します。

画像・動画生成や実行済みコマンドは、チャットの停止だけで安全に強制終了できません。その場合は「停止処理中」と表示して、その操作が終わってから追加指示を送ります。待機欄や未送信の入力は画面終了で消えるため、送信状態を確認してから終了してください。

## ファイルの調査

「このフォルダから設定ファイルを探して」「本文に○○を含むファイルを調べて」「そのファイルの100行目から読んで」と依頼できます。UTF-8、BOM付きUTF-16、CP932のテキストを扱えます。大きなファイルは必要な行を分けて読み、長い1行も続きを読めます。PDF・Office文書や画像はテキストファイル用ツールでは読めません。

一覧はページ単位、本文は1回最大2400文字です。本文検索では2MB超のファイル、バイナリ、アクセス不能なファイル、キャッシュフォルダやリンクを省き、省略件数と続きの位置を返します。テキスト読取上限は16MBです。大きな添付や長い会話にはモデルの入力上限が残るため、必要な範囲へ絞ってください。

## 画像・動画生成とファイル

ComfyUIを起動してから「青いティーポットを512×512で生成して」と依頼します。生成時はQwenを止めてGPUメモリを空け、完了後に復帰します。その間の別送信・手動GPUジョブ投入は待ってください。既にComfyUIが忙しい場合は処理を拒否します。既存画像の編集機能ではありません。

「企画をdrafts/idea.mdに保存して」で選択したプロジェクト内へ保存できます。既存テキストの上書き前にはバックアップします。PowerShellは正確なコマンド内容を画面で確認してから実行します。PowerShellの作業フォルダはOSサンドボックスではなく、Windowsユーザー権限で動作します。

## キャッシュ・データ・終了

- `cache/desktop-session`: 画面の一時領域。メモリ内sessionとHTTP cache無効を併用し、画面終了後と次回起動前に削除。
- `data/open-webui`: 会話・添付・認証用秘密値。削除対象外。
- `data/agent-jobs`: MCP/CLIの入力と結果。削除対象外。
- 選択したプロジェクト（初期値 `workspace`）: 利用者のファイル、生成画像・動画、学習準備フォルダ。削除対象外。
- `data/project-workspace.json`: 選択したフォルダ。画面キャッシュとは別に保持。
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

## Qwen Image 2.1のプロンプト設計

「Qwen Image 2.1用に、日本語タイトル付きの表紙プロンプトを作って」のように指定すると、エージェントは `qwen_image21_prompt_guide` で基本ガイドと用途に合う項目を参照します。参照キャラの新規場面、部分編集、透過、日本語サムネ、長文図解、複数参照、画像なしT2Iの設計資料を同梱しています。例文は未生成の設計例です。

1ページ最大1,800文字で、続きは `next_offset` を指定します。Codex／Claudeも同じMCPツールを使えます。プロンプトの作成だけなら画像生成は始めません。標準画像ツールは参照入力のない新規生成のみで、編集用の指示を作ることと編集workflowを実行できることは別です。

```powershell
& 'C:\AI\LocalLLM\Studio-CLI.cmd' prompt-guide --topic overview
& 'C:\AI\LocalLLM\Studio-CLI.cmd' prompt-guide --topic japanese_cover
```

公開版には汎用ガイドのスナップショットを同梱しています。独自の正本へリンクする場合は `scripts/Link-PromptSkill.ps1 -SourcePath <skill-folder>` を使用します。既存フォルダは保存され、上書きはしません。既存環境への差分配備は、バックエンドが空いているときに `python scripts/Deploy-PromptSkill.py`。設定を保存してツールと参照指示だけを更新します。MCPに新しいツールが表示されなければ再接続してください。

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
