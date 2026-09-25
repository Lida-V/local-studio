# モデル設定と学習準備

## 生成

`config/media-models.json` で接続先・ワークフロー・ノードIDを指定します。モデルとカスタムノードの取得は自動化していません。各ワークフローのローダー名とモデルの配置を起動済みComfyUIの環境に合わせてください。

| モデル | 既定接続先 | ワークフロー | 主な前提 |
| --- | --- | --- | --- |
| Anima | 127.0.0.1:8188 | anima-chat-workflow.json | Anima base、Qwen3 text encoder、Qwen image VAE |
| Qwen Image 2.1 | 127.0.0.1:8191 | qwen-image21-workflow.json | GGUFローダー、Q4_K_M DiT、Qwen3-VL 8B INT8 ConvRot、2.1 VAE、TextEncodeQwenImage21 |
| MiniMax H3 | 127.0.0.1:8188 | minimax-h3-workflow.json | H3 FL2VA INT8 ConvRot、Qwen3-VL 32B NVFP4 AWQ、映像・音声VAE、MiniMax H3対応ノード |

画像は512〜1536・64の倍数・最大1.5MP。動画は256〜1024・32の倍数・最大0.75MP、指定秒数1〜5。H3のフレーム条件に合わせて尺を切り上げます。既定608×352・2秒指定は56フレーム／24fps＝約2.33秒です。長尺・高解像度の性能は検証していません。

生成中はQwenを停止してGPUメモリを明け渡します。登録済みサーバーと既存8190のキューも確認し、他ジョブがあれば開始・解放を拒否します。タイムアウトを「空き」と判断しません。処理完了時にキューが空いている場合だけQwenを復帰します。手動で同時にGPUジョブを投入しないでください。

## LoRAの準備導線

専用アプリの「制作 → LoRA学習の準備」、CLI、MCPの同じ機能から、モデル別案内と `workspace/training/<名前>/` を作成できます。画像・動画・検証素材のフォルダ、CSV/JSONLの例、計画用JSON、READMEを作成します。計画用JSONはトレーナーに直接渡せる設定ではありません。

| 対象 | 参照する学習ツール |
| --- | --- |
| Anima | [Anima Standalone Trainer](https://github.com/gazingstars123/Anima-Standalone-Trainer) |
| Qwen Image 2.1 | [DiffSynth-Studioの2.1専用レシピ](https://github.com/modelscope/DiffSynth-Studio/tree/main/examples/qwen_image_21/model_training) |
| MiniMax H3 | [Musubi Tuner H3手順](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/minimax_h3.md)（実験的対応） |
| Qwen3.8 | [Unsloth fine-tuning guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide) |

環境導入・重み取得・学習・外部送信は行いません。実学習時には別途、モデル対応・ライセンス・データセット・GPUメモリと実行設定を確認してください。生成用GGUFと学習用重み、推論可能と学習可能を区別します。学習成果物の生成・品質・24GB GPUへの適合は未検証です。
