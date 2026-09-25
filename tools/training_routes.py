"""LoRA preparation routes only. Never downloads models or starts training."""
import json
from pathlib import Path
import re

PROFILES = {
    'anima': {
        'label': 'Anima', 'type': '画像・キャラクター・画風', 'engine': 'Anima Standalone Trainer',
        'url': 'https://github.com/gazingstars123/Anima-Standalone-Trainer',
        'dataset': 'dataset/images/ に画像と同名の .txt キャプションを置きます。',
        'steps': ['画像・キャプションと利用目的を揃える', 'Anima DiT / Qwen3 text encoder / VAE と学習設定を確認', 'トレーナーで短い試験学習を行う', '同じseedでLoRA有無を比較してから本学習へ進む'],
        'note': 'Anima用LoRAは他のモデルへ流用できません。'},
    'qwen-image-2.1': {
        'label': 'Qwen Image 2.1', 'type': '画像・キャラクター・画風', 'engine': 'DiffSynth-Studio',
        'url': 'https://github.com/modelscope/DiffSynth-Studio/tree/main/examples/qwen_image_21/model_training',
        'dataset': 'dataset/images/ に画像と同名の .txt、dataset/metadata.example.csv に対応例を置きます。',
        'steps': ['画像・キャプションの組を準備', '2.1専用の学習用重みとprocessorを取得・確認', 'DiffSynthのqwen_image_21レシピでメモリ条件を確認', '短い試験学習とLoRA適用後の比較を実施'],
        'note': '旧Qwen-Image用の学習設定や生成用GGUFを、そのまま2.1の学習に使わないでください。'},
    'minimax-h3': {
        'label': 'MiniMax H3', 'type': '動画・動き・音声', 'engine': 'Musubi Tuner',
        'url': 'https://github.com/kohya-ss/musubi-tuner/blob/main/docs/minimax_h3.md',
        'dataset': 'dataset/videos/ に動画と同名の .txt。音声がある場合は動画内音声または同名 .wav を使います。',
        'steps': ['動画・字幕ではない内容説明・音声の対応を整理', 'FL2VA/Ref2VAと、対応するloss方式を選ぶ', 'latentとtextのキャッシュを別々に作成', '小さい解像度と短い尺で試験学習・生成比較'],
        'note': '実験的な対応です。学習/検証のキャッシュを分け、guidance loss等のH3専用レシピを確認します。'},
    'qwen3.8': {
        'label': 'Qwen3.8', 'type': '会話・文章・応答形式', 'engine': 'Unsloth',
        'url': 'https://unsloth.ai/docs/get-started/fine-tuning-llms-guide',
        'dataset': 'dataset/train.example.jsonl を参考に、messages形式のtrain.jsonlを準備します。',
        'steps': ['用途別の会話例と独立した評価用データを準備', 'GGUFではなく学習対応のbase/4bit重みを選ぶ', 'LoRA/QLoRAのrank・文脈長とGPUメモリを確認', '短い試験学習と未学習の質問で評価してから書き出す'],
        'note': '推論できることと学習できることは別です。現在のRTX 4090で27Bの学習メモリは未検証です。'},
}

def profiles(studio):
    path = studio.SUPPORT / 'config/support-config.json'
    cfg = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    configured = cfg.get('trainingRoutes', {})
    result = []
    for key, profile in PROFILES.items():
        local = configured.get(key, {})
        python = local.get('python', '')
        root = local.get('root', '')
        result.append(dict(id=key, **profile, python=python, root=root,
                           environmentPresent=bool(python and Path(python).is_file()),
                           verifiedTraining=False,
                           status='導線のみ・学習未実行',
                           workspace=str(studio.WORK / 'training')))
    return result

def prepare(studio, model, name):
    if model not in PROFILES or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise ValueError('Choose a listed model and a 1–64 character ASCII project name (letters, digits, - or _).')
    folder = studio.workspace_path('training/' + name)
    folder.mkdir(parents=True, exist_ok=False)
    profile = next(p for p in profiles(studio) if p['id'] == model)
    for child in ['dataset/images','dataset/videos','dataset/validation','configs','output','logs']:
        (folder / child).mkdir(parents=True)
    config = {'model': model, 'project': name, 'status': 'preparation_only',
              'dataset': 'dataset', 'output': 'output', 'rank': 16, 'seed': 42,
              'training_started': False, 'notes': 'Planning template, not a runnable trainer config.'}
    (folder / 'configs/project.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'dataset/metadata.example.csv').write_text('image,prompt\nimages/sample.png,Describe the subject and scene here\n', encoding='utf-8')
    sample = {'messages': [{'role': 'user', 'content': '回答形式の例を教えて。'}, {'role': 'assistant', 'content': '結論と理由を短く答えます。'}]}
    (folder / 'dataset/train.example.jsonl').write_text(json.dumps(sample, ensure_ascii=False) + '\n', encoding='utf-8')
    text = '# ' + name + ' — ' + profile['label'] + ' LoRA準備\n\n'
    text += 'このフォルダの作成では、学習・モデル取得・外部送信は行いません。\n\n'
    text += profile['dataset'] + '\n\n' + '\n'.join(f'{i+1}. {s}' for i,s in enumerate(profile['steps']))
    text += '\n\n' + profile['note'] + '\n\n公式手順: ' + profile['url'] + '\n'
    text += '\nCodex / Claudeへの依頼例: この準備フォルダのデータセットと環境を点検し、実行する学習設定を具体化してください。\n'
    (folder / 'README.md').write_text(text, encoding='utf-8')
    return {'prepared': str(folder), 'model': model, 'training_started': False, 'download_started': False}
