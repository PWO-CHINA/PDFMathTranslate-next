import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pdf2zh_next import high_level
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import ConfigManager
from pdf2zh_next.config.main import MagicDefault
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.config.model import TranslationSettings


def test_default_and_cli_env_toml_mapping(tmp_path, monkeypatch):
    assert TranslationSettings().experimental_cross_page_context is False
    parser, types = build_args_parser()
    parsed = {key.replace('-', '_'): value for key, value in vars(parser.parse_args(['--experimental-cross-page-context'])).items() if value is not MagicDefault}
    manager = ConfigManager()
    cli = manager.parse_dict_vars(set(), 0, CLIEnvSettingsModel, parsed)
    assert CLIEnvSettingsModel(**cli).to_settings_model().translation.experimental_cross_page_context
    monkeypatch.setenv('PDF2ZH_EXPERIMENTAL_CROSS_PAGE_CONTEXT', 'true')
    env = manager.parse_env_vars(set(), 0, CLIEnvSettingsModel)
    assert CLIEnvSettingsModel(**env).to_settings_model().translation.experimental_cross_page_context
    config = tmp_path / 'settings.toml'
    config.write_text('[translation]\nexperimental_cross_page_context = true\n', encoding='utf-8')
    toml = manager._read_toml_file(config)
    assert CLIEnvSettingsModel(**toml).to_settings_model().translation.experimental_cross_page_context


@pytest.mark.parametrize('enabled', [False, True])
def test_constructor_receives_only_enabled_setting(monkeypatch, enabled):
    calls = []
    omitted = object()

    def constructor(*, experimental_cross_page_context=omitted, **_kwargs):
        calls.append(experimental_cross_page_context)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', constructor)
    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': enabled}, pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert calls == [True if enabled else omitted]


def test_old_constructor_works_when_disabled_and_fails_clearly_when_enabled(monkeypatch):
    calls = []

    def old_constructor(**kwargs):
        assert 'experimental_cross_page_context' not in kwargs
        calls.append(True)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', old_constructor)
    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    settings = CLIEnvSettingsModel(pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    settings.translation.experimental_cross_page_context = True
    with pytest.raises(RuntimeError, match='installed BabelDOC does not support experimental cross-page context'):
        high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert len(calls) == 1


def test_debug_stream_forwards_enabled_setting_to_babeldoc(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')
    calls = []

    async def engine(*, translation_config):
        calls.append(translation_config)
        yield {'type': 'finish'}

    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    monkeypatch.setattr(high_level, 'babeldoc_translate', engine)
    settings = CLIEnvSettingsModel(
        basic={'debug': True},
        translation={'experimental_cross_page_context': True},
        pdf={'translate_table_text': False},
    ).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume():
        return [event async for event in high_level.do_translate_async_stream(settings, source)]

    assert asyncio.run(consume()) == [{'type': 'finish'}]
    assert len(calls) == 1
    assert calls[0].experimental_cross_page_context is True
    assert calls[0].input_file == source


def test_non_debug_stream_passes_enabled_settings_to_subprocess(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')
    calls = []

    async def subprocess_stream(settings, file):
        calls.append((settings.translation.experimental_cross_page_context, file))
        yield {'type': 'finish'}

    monkeypatch.setattr(high_level, '_translate_in_subprocess', subprocess_stream)
    settings = CLIEnvSettingsModel(
        basic={'debug': False},
        translation={'experimental_cross_page_context': True},
    ).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume():
        return [event async for event in high_level.do_translate_async_stream(settings, source)]

    assert asyncio.run(consume()) == [{'type': 'finish'}]
    assert calls == [(True, source)]
