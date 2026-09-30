"""Read the installed Qwen Image 2.1 drafting skill in bounded, selected excerpts."""
from pathlib import Path
import hashlib
import re

_helper_file = Path(__file__)
LOADED_SIGNATURE = (_helper_file.stat().st_mtime_ns, _helper_file.stat().st_size)
PAGE_CHARS = 1800
REVIEWED_CORE_SHA256 = '5b8fe3dbc1a82d1006f3a119b37246212e7de77ba2a77a266fe4b9fda3e438d4'
SKILL_ROOT = Path(__file__).resolve().parents[1] / 'skills/qwen-image21-prompting'
RECIPE_HEADINGS = {
    'scene_style': '参照キャラの新規シーン／画風',
    'local_edit': '局所編集',
    'transparent': '透過PNG',
    'japanese_cover': '日本語ポスター／サムネ',
    'text_dense_infographic': '説明文付きインフォグラフィックス',
    'multi_reference': '複数参照',
    't2i': '画像なしのT2I',
}
TOPICS = ['overview', 'core', *RECIPE_HEADINGS, 'local_runtime', 'sources']
INSTRUCTION_START = '\n[local-studio:qwen-image21-prompting]\n'
INSTRUCTION_END = '\n[/local-studio:qwen-image21-prompting]\n'
MODEL_INSTRUCTION = INSTRUCTION_START + (
    ' Qwen Image 2.1向けのプロンプト作成・修正・生成では、まず'
    'qwen_image21_prompt_guide(topic="overview")を読み、依頼に合うtopicだけ追加で読みます。'
    'Qwenの会話やAnima/MiniMax用には適用しません。必要な続きはnext_offsetで読みます。'
    'overview_current=falseなら更新されたcoreの全ページを読みます。参照なしならt2iを選びます。'
    '簡潔な日本語の設計説明とコピーできるプロンプトを返します。'
    'プロンプト作成だけの依頼から生成・PE実行・モデル取得・既存テンプレート変更を開始しません。'
    '参照画像をLLMで見ることとComfyUIの画像入力に渡すことは別です。'
) + INSTRUCTION_END


def install_instruction(system: str) -> str:
    """Replace this integration's block while preserving all other preset text."""
    system = re.sub(re.escape(INSTRUCTION_START) + '.*?' + re.escape(INSTRUCTION_END), '', system, flags=re.DOTALL)
    # Upgrade the two pre-marker instructions used by the initial local deployment.
    legacy_start = ' Qwen Image 2.1向けのプロンプト作成・修正・生成では、まず'
    legacy_end = '参照画像をLLMで見ることとComfyUIの画像入力に渡すことは別です。'
    system = re.sub(re.escape(legacy_start) + '.*?' + re.escape(legacy_end), '', system, flags=re.DOTALL)
    return system + MODEL_INSTRUCTION
OVERVIEW = '''Qwen Image 2.1専用のプロンプト設計ガイド（ComfyUIサポーターのqwen-image21-prompting）。Qwen会話・他の画像/動画モデルには適用しない。PEモデルの導入/実行は不要。

1. 依頼を分類: 画像なしT2Iは完成画面を描写。局所編集は変更操作から始め、対象外を保持。参照キャラの新規場面は同一性を保ち、行動・場所・構図を新しく設計。複数参照は入力ごとの役割を明示。
2. 参照は実画像を確認し、未確認の外見を創作しない。単一参照は自然に指し、複数参照は実入力順に<image1>、<image2>を割り当てる。顔・衣装等を細かく言い直しすぎない。服替えでは衣装、画風変更では画材、デフォルメでは頭身を保持条件から外す。
3. 通常は英文の自然文。ユーザー指定言語を優先。行動・視線・位置・奥行き・背景密度・光の方向・素材を具体化。局所編集に依頼外の物や構図変更を足さない。
4. 画像内の文字は原稿を一字も省かず半角ダブルクォートで囲み、位置・階層・行を指定。依頼外の署名/英訳/数字を足さず、事実・数値は根拠資料から確定。編集時の文字言語は明示指定→元画像の主要言語→文字なしなら依頼言語。
5. 比率・幅・高さは本文と分離。局所編集は元画像、新規場面は新しい構図に合わせる。negativeは実workflowに従う（ローカル基準は空欄、モデル全体の保証ではない）。
6. 簡潔な日本語説明＋コピーできるpositiveを返す。必要なら参照役割/順序、保持・変更点、negative、比率/サイズ、検品点を添える。
7. PE互換JSONは要求時のみ。Comfyのprompt欄にはrewritten_promptの文字列だけを渡す。wh_ratioとratio_followは片方だけ値を持ち、ratio_followは実在入力を指す。単一編集はwh_ratio="", ratio_follow="<image1>"。編集promptは改行のない一段落。比率フィールドだけではノードの寸法は変わらない。
8. プロンプトだけの依頼では生成・環境更新を開始しない。create_qwen_imageは参照入力のない新規生成のみ。標準ツールの寸法は512～1536・64の倍数・総画素1.5MP以下（3:2例は1152×768）。別workflowの対応寸法とは区別する。参照/編集の実行は案件の対応workflowと実画像入力を確認する。生成後は顔・アクセサリー・手・文字を実画像で検品し、透過はAlpha確認。プロンプト指定だけで透過成功とは言わない。
9. 用途別レシピは未生成の設計例。成功作例と呼ばない。構図/サイズも異なる画風セットは条件固定比較ではない。

必要なtopicだけ読む: scene_style、local_edit、transparent、japanese_cover、text_dense_infographic、multi_reference、t2i。core=原本の全文、local_runtime=実行時だけ、sources=根拠。truncated=trueならnext_offsetが続き。'''


def _text(root: Path, topic: str):
    if topic == 'overview':
        return OVERVIEW, 'Local Studio compact routing guide'
    if topic in RECIPE_HEADINGS:
        name = 'references/prompt-recipes.md'
        text = (root / name).read_text(encoding='utf-8-sig')
        heading = RECIPE_HEADINGS[topic]
        matches = list(re.finditer(r'^## (.+)$', text, re.MULTILINE))
        for index, match in enumerate(matches):
            if match.group(1).strip() == heading:
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                return text[match.start():end], name + '#' + heading
        raise ValueError('Installed recipe heading is missing.')
    name = {'core': 'SKILL.md', 'local_runtime': 'references/local-comfyui.md',
            'sources': 'references/sources.md'}[topic]
    return (root / name).read_text(encoding='utf-8-sig'), name


def guide(topic: str = 'overview', offset: int = 0, source_root=None) -> dict:
    """Read a fixed topic only; source_root is an internal installation/test hook."""
    if topic not in TOPICS:
        return {'ok': False, 'reason': 'unknown_topic', 'topics': TOPICS,
                'next_step': 'Choose one of the listed topics, starting with overview.'}
    if type(offset) is not int or offset < 0:
        return {'ok': False, 'reason': 'invalid_offset', 'next_step': 'Use offset=0 or the returned next_offset.'}
    root = Path(source_root) if source_root is not None else SKILL_ROOT
    freshness = {}
    if topic == 'overview':
        try:
            core = (root / 'SKILL.md').read_text(encoding='utf-8-sig')
            digest = hashlib.sha256(core.encode()).hexdigest()
        except (OSError, UnicodeError):
            digest = None
        freshness = {'overview_current': digest == REVIEWED_CORE_SHA256,
                     'canonical_core_sha256': digest}
    try:
        text, source = _text(root, topic)
    except (OSError, ValueError) as error:
        return {'ok': False, 'topic': topic, 'reason': 'skill_unavailable',
                'next_step': 'Restore the installed qwen-image21-prompting skill link/files; overview remains available.',
                'error_type': type(error).__name__}
    if topic == 'overview' and not freshness['overview_current']:
        text = '原本が更新されたか未導入です。この要約よりcoreの実ファイルを優先し、必要な全ページを読んでください。\n\n' + text
    if offset > len(text):
        return {'ok': False, 'reason': 'offset_out_of_range', 'total_chars': len(text),
                'next_step': 'Use offset=0 or the returned next_offset.'}
    end = min(offset + PAGE_CHARS, len(text))
    # Keep paragraph boundaries when possible, without losing a long paragraph.
    if end < len(text):
        boundary = text.rfind('\n\n', offset + PAGE_CHARS // 2, end)
        if boundary != -1:
            end = boundary + 2
    return {'ok': True, 'topic': topic, 'content': text[offset:end],
            'offset': offset, 'total_chars': len(text), 'truncated': end < len(text),
            'next_offset': end if end < len(text) else None, 'page_char_limit': PAGE_CHARS,
            'source': source, 'revision_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'topics': TOPICS if topic == 'overview' else [],
            'scope': 'Prompt drafting only; recipes are ungenerated design examples.', **freshness}
