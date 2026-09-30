# 会話モデルの選択

Local Studioの会話・画像理解モデルを、登録済みのプロファイルから選びます。カタログへの登録は、各PCでの取得・実機検証が完了したことを意味しません。以下のコマンドはモデルをダウンロードしません。

| ID | モデル | 用途 |
| --- | --- | --- |
| `qwen-standard` | Qwen3.8-27B UD-Q4_K_M | 通常版の会話・画像理解 |
| `huihui-qwen` | Huihui-Qwen3.8-27B abliteration済み UD-DW-Q4_K_M | 創作相談などの会話・画像理解の候補 |

Huihuiの拒否低減は配布者の説明であり、拒否しなくなることや創作品質の向上を保証しません。成人向けゲーム開発への適合・応答品質は、この選択機能の検証とは別に評価が必要です。

Qwen Image 2.1はComfyUIで使う画像生成モデルです。この会話モデルの切替で画像生成モデルは変更されません。画像をQwen3.8へ添付して読ませることと、Qwen Image 2.1へ生成用の参照画像を渡すことも別の操作です。

## 配置状態と切替

既定の配置では、PowerShellから次を実行できます。

```powershell
& 'C:/AI/LocalLLM/Studio-CLI.cmd' model-profiles
& 'C:/AI/LocalLLM/Studio-CLI.cmd' model-select huihui-qwen
& 'C:/AI/LocalLLM/Studio-CLI.cmd' model-select qwen-standard
```

ソースから直接実行する場合は、サポーターのルートで設定に指定されたPythonを使います。

```powershell
$studioPython = (Get-Content -Raw -Encoding utf8 config/support-config.json | ConvertFrom-Json).chatApp.python
& $studioPython -B -X utf8 scripts/Local-Studio.py model-profiles
& $studioPython -B -X utf8 scripts/Local-Studio.py model-select huihui-qwen
& $studioPython -B -X utf8 scripts/Local-Studio.py model-select qwen-standard
```

`model-profiles` は読み取りだけです。`active` は設定のモデルパスとの一致、`installed` はモデルと画像入力用mmprojの存在・期待サイズとの一致を示します。どちらも、実際に動作中であることやSHA256・応答品質の検証済みを示す値ではありません。配布元URL、固定revision、期待サイズ・SHA256も返します。

`model-select` は両ファイルのSHA256を照合し、処理が空いていることを確認してQwenを停止・再起動します。会話、推論、待機タスク、ComfyUI処理が残っている場合や状態を確認できない場合は切替を拒否します。処理を完了してから再実行してください。切替中の新しい会話要求は一時的に拒否されます。

切替はモデルとmmprojのパスを変更します。現在の **8,192トークン**、単一スロット、APIのポート・モデルIDは維持します。8,192はこの環境の起動設定で、モデルの公称上限やRTX 4090での最大値を示すものではありません。

失敗時は元の構成への復旧を試みます。復旧にも失敗した場合はエラーと `runtime/maintenance-backups` の元設定を確認してください。モデルファイルを削除したり、手作業で切替を重ねたりせず、実際のプロセスと設定を確認してから復旧します。

## ダブルクリックの入口

モデル切替用の入口が配置された環境では、次を使えます。

- `C:/AI/LocalLLM/HuihuiでLocal Studio.cmd`: `huihui-qwen` に切り替えて専用アプリを開く。
- `C:/AI/LocalLLM/通常QwenでLocal Studio.cmd`: `qwen-standard` に戻して専用アプリを開く。

切替に失敗した場合はそこで止まり、エラーを表示します。通常の `Start-ChatApp.cmd` は現在選択された構成を使います。この版の対応先は `C:/AI/LocalLLM` 固定です。

## 固定した配布物

Huihuiの選択肢は、[配布者のGGUFモデルカード](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF) にあるUD-DW系です。固定revisionは `3f101cd22b7999228bbd5d79a33975414eb9758b`、ファイルは `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf`、期待サイズは16,551,316,384バイトです。正確なSHA256は `config/model-profiles.json` に記録しています。

配布者はUD-DW系をUnsloth由来、変更対象を0始まりの層22〜52と説明しています。[紹介されたBF16モデル](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated) はQwen公式由来の別系統で、層18〜51という説明です。同じ名称でも、この2つの重みを同一のものとは扱いません。

プロファイルは通常版の `mmproj-F16.gguf` を共有する構成です。配布者は視覚部分を変更していないと説明していますが、この組合せの実機での画像入力確認は別途必要です。モデルと量子化物のライセンス表示はApache-2.0です。再配布時は [元モデルのLICENSE](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated/blob/739e3c5b89849f6c238ce1e5b70008612ae42cdd/LICENSE) と必要な通知・変更表示を確認してください。
