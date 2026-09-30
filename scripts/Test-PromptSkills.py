"""Offline prompt-guide checks; fixtures never generate images or use the network."""
import asyncio
import hashlib
import importlib
import inspect
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import prompt_skills
import local_studio as studio


RECIPE_HEADINGS = {
    'scene_style': '参照キャラの新規シーン／画風',
    'local_edit': '局所編集',
    'transparent': '透過PNG',
    'japanese_cover': '日本語ポスター／サムネ',
    'text_dense_infographic': '説明文付きインフォグラフィックス',
    'multi_reference': '複数参照',
    't2i': '画像なしのT2I',
}
TOPICS = {'overview', 'core', *RECIPE_HEADINGS, 'local_runtime', 'sources'}
REQUIRED_FIELDS = {
    'ok', 'topic', 'content', 'total_chars', 'offset', 'next_offset',
    'truncated', 'topics', 'source',
}
REAL_SKILL = SOURCE / 'skills/qwen-image21-prompting'


def markdown_section(text, heading):
    """Independent expected section: exact level-two heading, including its heading."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.rstrip() == '## ' + heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
    return ''.join(lines[start:end]).strip()


class GuideChecks(unittest.TestCase):
    def complete_topic(self, root, topic):
        chunks = []
        offset = 0
        total = None
        for _ in range(100):
            result = prompt_skills.guide(topic=topic, offset=offset, source_root=root)
            self.assertTrue(result.get('ok'), result)
            self.assertTrue(REQUIRED_FIELDS <= result.keys())
            self.assertEqual(result['topic'], topic)
            self.assertEqual(result['offset'], offset)
            self.assertIsInstance(result['content'], str)
            self.assertLessEqual(len(result['content']), 1800)
            if topic == 'overview':
                self.assertEqual(TOPICS, set(result['topics']))
            else:
                self.assertTrue(set(result['topics']) <= TOPICS)
            if total is None:
                total = result['total_chars']
            self.assertEqual(result['total_chars'], total)
            chunks.append(result['content'])
            consumed = offset + len(result['content'])
            self.assertLessEqual(consumed, total)
            if result['truncated']:
                self.assertTrue(result['content'], 'A continuation must make progress')
                self.assertEqual(result['next_offset'], consumed)
                self.assertLess(consumed, total)
                offset = result['next_offset']
            else:
                self.assertIsNone(result['next_offset'])
                self.assertEqual(consumed, total)
                joined = ''.join(chunks)
                self.assertEqual(len(joined), total)
                return joined, chunks
        self.fail('Guide pagination did not finish')


class FixtureGuides(GuideChecks):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='prompt-guide-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'support/skills/qwen-image21-prompting'
        refs = self.root / 'references'
        refs.mkdir(parents=True)
        self.core = '# Fixture skill\n\nDrafting only. Keep supplied image text exact.\n'
        (self.root / 'SKILL.md').write_text(self.core, encoding='utf-8')
        self.sections = {}
        for topic, heading in RECIPE_HEADINGS.items():
            content = '## ' + heading + '\n\nFixture for ' + topic + '.\n'
            if topic == 'text_dense_infographic':
                for number in range(1, 7):
                    content += f'Heading reads "{number:02d} Fixture heading". '
                    content += f'Body reads "確認文{number * 2 - 1:02d}です。" and "確認文{number * 2:02d}です。".\n'
                content += ('日本語の長い説明をページごとに欠落なく返す。' * 220) + '\n'
            self.sections[topic] = content.strip()
        self.recipes = '# Fixture recipes\n\n' + '\n\n'.join(self.sections.values()) + '\n'
        (refs / 'prompt-recipes.md').write_text(self.recipes, encoding='utf-8')
        (refs / 'local-comfyui.md').write_text('# Fixture local runtime\n\nNo execution.\n', encoding='utf-8')
        (refs / 'sources.md').write_text('# Fixture sources\n\nDesign examples are ungenerated.\n', encoding='utf-8')

    def test_bounded_topic_index_and_default(self):
        self.assertEqual(prompt_skills.PAGE_CHARS, 1800)
        default = prompt_skills.guide(source_root=self.root)
        explicit = prompt_skills.guide(topic='overview', source_root=self.root)
        self.assertEqual(default, explicit)
        overview, _ = self.complete_topic(self.root, 'overview')
        self.assertTrue(overview)

    def test_overview_freshness_matches_normalized_installed_core(self):
        # BOM and Windows newlines must not make an otherwise identical core stale.
        windows_core = '\ufeff' + self.core.replace('\n', '\r\n')
        (self.root / 'SKILL.md').write_bytes(windows_core.encode('utf-8'))
        expected_hash = hashlib.sha256(self.core.encode('utf-8')).hexdigest()
        with patch.object(prompt_skills, 'REVIEWED_CORE_SHA256', expected_hash):
            result = prompt_skills.guide(source_root=self.root)
            self.assertIs(result.get('overview_current'), True)
            self.assertEqual(result.get('canonical_core_sha256'), expected_hash)
            self.complete_topic(self.root, 'overview')

    def test_changed_core_marks_overview_stale_and_directs_reader_to_core(self):
        reviewed_hash = hashlib.sha256(self.core.encode('utf-8')).hexdigest()
        changed_core = self.core + '\nA new fixture rule changes the canonical guide.\n'
        (self.root / 'SKILL.md').write_text(changed_core, encoding='utf-8')
        observed_hash = hashlib.sha256(changed_core.encode('utf-8')).hexdigest()
        with patch.object(prompt_skills, 'REVIEWED_CORE_SHA256', reviewed_hash):
            result = prompt_skills.guide(source_root=self.root)
            self.assertTrue(result.get('ok'), result)
            self.assertIs(result.get('overview_current'), False)
            self.assertEqual(result.get('canonical_core_sha256'), observed_hash)
            content, _ = self.complete_topic(self.root, 'overview')
        self.assertRegex(content, r'(?is)(?:core.{0,100}(?:読む|読み|read)|(?:読む|読み|read).{0,100}core)')

    def test_missing_core_keeps_overview_available_but_not_current(self):
        result = prompt_skills.guide(source_root=self.root / 'missing')
        self.assertTrue(result.get('ok'), result)
        self.assertIs(result.get('overview_current'), False)
        self.assertIsNone(result.get('canonical_core_sha256'))
        self.complete_topic(self.root / 'missing', 'overview')

    def test_unreadable_core_keeps_overview_available_but_not_current(self):
        (self.root / 'SKILL.md').write_bytes(b'\xff')
        result = prompt_skills.guide(source_root=self.root)
        self.assertTrue(result.get('ok'), result)
        self.assertIs(result.get('overview_current'), False)
        self.assertIsNone(result.get('canonical_core_sha256'))
        self.complete_topic(self.root, 'overview')

    def test_exact_recipe_topics_without_neighbour_sections(self):
        for topic, heading in RECIPE_HEADINGS.items():
            with self.subTest(topic=topic):
                actual, _ = self.complete_topic(self.root, topic)
                self.assertEqual(actual.strip(), self.sections[topic])
                self.assertEqual(actual.strip(), markdown_section(self.recipes, heading))

    def test_long_recipe_continuation_preserves_all_text(self):
        actual, pages = self.complete_topic(self.root, 'text_dense_infographic')
        self.assertGreater(len(pages), 1)
        self.assertEqual(actual.strip(), self.sections['text_dense_infographic'])
        for number in range(1, 7):
            self.assertEqual(actual.count(f'"{number:02d} Fixture heading"'), 1)
        for number in range(1, 13):
            self.assertEqual(actual.count(f'"確認文{number:02d}です。"'), 1)

    def test_non_recipe_documents_are_available(self):
        core, _ = self.complete_topic(self.root, 'core')
        self.assertIn('Drafting only.', core)
        runtime, _ = self.complete_topic(self.root, 'local_runtime')
        self.assertIn('No execution.', runtime)
        sources, _ = self.complete_topic(self.root, 'sources')
        self.assertIn('Design examples are ungenerated.', sources)

    def test_bad_topic_cannot_select_a_file(self):
        for topic in ['unknown', '../SKILL.md', 'references/sources.md', str(self.root / 'SKILL.md'), '', None, 42]:
            with self.subTest(topic=topic):
                result = prompt_skills.guide(topic=topic, source_root=self.root)
                self.assertIs(result.get('ok'), False)

    def test_invalid_offsets_are_rejected(self):
        total = prompt_skills.guide(topic='core', source_root=self.root)['total_chars']
        for offset in [-1, 1.5, '0', None, True, False, total + 1, 10**12]:
            with self.subTest(offset=offset):
                result = prompt_skills.guide(topic='core', offset=offset, source_root=self.root)
                self.assertIs(result.get('ok'), False)

    def test_missing_source_and_near_match_heading_are_errors(self):
        missing = prompt_skills.guide(topic='core', source_root=self.root / 'missing')
        self.assertIs(missing.get('ok'), False)
        recipe_path = self.root / 'references/prompt-recipes.md'
        altered = self.recipes.replace('## 局所編集\n', '## 局所編集 (not the exact topic)\n')
        recipe_path.write_text(altered, encoding='utf-8')
        result = prompt_skills.guide(topic='local_edit', source_root=self.root)
        self.assertIs(result.get('ok'), False)

    def test_async_tool_reads_supporter_skill_independent_of_project(self):
        signature = inspect.signature(studio.Tools.qwen_image21_prompt_guide)
        self.assertTrue(inspect.iscoroutinefunction(studio.Tools.qwen_image21_prompt_guide))
        self.assertEqual(set(signature.parameters), {'self', 'topic', 'offset'})
        support = self.root.parents[1]
        with patch.object(studio, 'SUPPORT', support), \
             patch.object(studio, 'current_project', side_effect=AssertionError('Selected project must not be read')), \
             patch.object(studio, 'workspace_path', side_effect=AssertionError('Project path must not be used')), \
             patch.object(studio, 'media_runtime', side_effect=AssertionError('Media must not be touched')), \
             patch.object(studio, 'generate', side_effect=AssertionError('Generation must not run')), \
             patch.object(studio, 'script', side_effect=AssertionError('No process must be launched')), \
             patch.object(studio, 'api', side_effect=AssertionError('No network calls')), \
             patch.object(prompt_skills, 'guide', wraps=prompt_skills.guide) as delegate:
            actual = asyncio.run(studio.Tools().qwen_image21_prompt_guide(topic='local_edit', offset=0))
        self.assertTrue(actual.get('ok'), actual)
        self.assertEqual(actual['content'].strip(), self.sections['local_edit'])
        delegate.assert_called_once()
        bound = inspect.signature(prompt_skills.guide).bind(*delegate.call_args.args, **delegate.call_args.kwargs)
        self.assertEqual(Path(bound.arguments['source_root']), self.root)
        self.assertEqual(bound.arguments['topic'], 'local_edit')
        self.assertEqual(bound.arguments['offset'], 0)

    def test_tool_reloads_stale_helper_once_and_reuses_current_signature(self):
        support = self.root.parents[1]
        helper_stat = Path(prompt_skills.__file__).stat()
        expected_signature = (helper_stat.st_mtime_ns, helper_stat.st_size)
        with patch.object(studio, 'SUPPORT', support), \
             patch.object(studio, 'current_project', side_effect=AssertionError('Selected project must not be read')), \
             patch.object(prompt_skills, 'LOADED_SIGNATURE', (-1, -1)), \
             patch.object(importlib, 'reload', wraps=importlib.reload) as reload_helper:
            first = asyncio.run(studio.Tools().qwen_image21_prompt_guide(topic='local_edit'))
            reload_helper.assert_called_once_with(prompt_skills)
            self.assertEqual(prompt_skills.LOADED_SIGNATURE, expected_signature)
            reload_helper.reset_mock()
            second = asyncio.run(studio.Tools().qwen_image21_prompt_guide(topic='local_edit'))
            reload_helper.assert_not_called()
        self.assertTrue(first.get('ok'), first)
        self.assertEqual(first['content'].strip(), self.sections['local_edit'])
        self.assertEqual(first, second)


@unittest.skipUnless((REAL_SKILL / 'SKILL.md').exists(), 'Canonical prompt guide is not installed')
class CanonicalGuides(GuideChecks):
    def test_real_overview_freshness_reports_observed_core_hash(self):
        core = (REAL_SKILL / 'SKILL.md').read_text(encoding='utf-8-sig')
        expected_hash = hashlib.sha256(core.encode('utf-8')).hexdigest()
        result = prompt_skills.guide(source_root=REAL_SKILL)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(result.get('canonical_core_sha256'), expected_hash)
        self.assertIs(result.get('overview_current'), expected_hash == prompt_skills.REVIEWED_CORE_SHA256)

    def test_real_source_topics_match_the_canonical_sections(self):
        recipes = (REAL_SKILL / 'references/prompt-recipes.md').read_text(encoding='utf-8-sig')
        for topic, heading in RECIPE_HEADINGS.items():
            with self.subTest(topic=topic):
                actual, _ = self.complete_topic(REAL_SKILL, topic)
                self.assertEqual(actual.strip(), markdown_section(recipes, heading))
        for topic in ['overview', 'core', 'local_runtime', 'sources']:
            with self.subTest(topic=topic):
                actual, _ = self.complete_topic(REAL_SKILL, topic)
                self.assertTrue(actual)

    def test_real_dense_recipe_preserves_six_headings_and_twelve_sentences(self):
        actual, pages = self.complete_topic(REAL_SKILL, 'text_dense_infographic')
        self.assertGreater(len(pages), 1)
        quoted = re.findall(r'"([^"\n]+)"', actual)
        headings = [value for value in quoted if re.match(r'^0[1-6] ', value)]
        sentences = [value for value in quoted if value.endswith('。')]
        self.assertEqual(len(headings), 6)
        self.assertEqual([value[:2] for value in headings], [f'{number:02d}' for number in range(1, 7)])
        self.assertEqual(len(sentences), 12)
        self.assertEqual(len(set(sentences)), 12)


class InstructionUpdates(unittest.TestCase):
    def test_fresh_install_preserves_existing_text(self):
        existing = 'Answer in Japanese.\nKeep the selected workflow preference.\n'
        actual = prompt_skills.install_instruction(existing)
        self.assertEqual(actual, existing + prompt_skills.MODEL_INSTRUCTION)
        self.assertEqual(actual.count(prompt_skills.INSTRUCTION_START), 1)
        self.assertEqual(actual.count(prompt_skills.INSTRUCTION_END), 1)

    def test_repeated_install_is_idempotent(self):
        once = prompt_skills.install_instruction('Existing preference.\n')
        self.assertEqual(prompt_skills.install_instruction(once), once)
        self.assertEqual(prompt_skills.install_instruction(prompt_skills.install_instruction(once)), once)

    def test_old_marked_block_replacement_preserves_user_prefix_and_suffix(self):
        prefix = 'User prefix: keep reference policy.\n\n'
        suffix = '\nUser suffix: keep export settings exactly.\n'
        old = prompt_skills.INSTRUCTION_START + 'Obsolete integration guidance.\nSecond old line.' + prompt_skills.INSTRUCTION_END
        actual = prompt_skills.install_instruction(prefix + old + suffix)
        self.assertEqual(actual, prefix + suffix + prompt_skills.MODEL_INSTRUCTION)
        self.assertNotIn('Obsolete integration guidance.', actual)
        self.assertEqual(actual.count(prompt_skills.INSTRUCTION_START), 1)
        self.assertEqual(actual.count(prompt_skills.INSTRUCTION_END), 1)

    def test_legacy_upgrade_removes_only_integration_text(self):
        prefix = 'Existing prefix.\n'
        suffix = '\nExisting suffix.\n'
        legacy = (
            ' Qwen Image 2.1向けのプロンプト作成・修正・生成では、まず'
            'qwen_image21_prompt_guide(topic="overview")を読みます。'
            '参照画像をLLMで見ることとComfyUIの画像入力に渡すことは別です。'
        )
        actual = prompt_skills.install_instruction(prefix + legacy + suffix)
        self.assertEqual(actual, prefix + suffix + prompt_skills.MODEL_INSTRUCTION)
        self.assertEqual(prompt_skills.install_instruction(actual), actual)


if __name__ == '__main__':
    unittest.main(verbosity=2)
