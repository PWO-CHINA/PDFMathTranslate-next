from pathlib import Path
from types import SimpleNamespace

import pytest

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import ConfigManager, MagicDefault, build_args_parser
from pdf2zh_next.config.model import TranslationSettings
from pdf2zh_next import high_level


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

    def constructor(*, experimental_cross_page_context=False, **kwargs):
        calls.append(experimental_cross_page_context)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', constructor)
    monkeypatch.setattr(high_level, 'get_translator', lambda settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda settings: [])
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': enabled}, pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert calls == [enabled]


def test_old_constructor_works_when_disabled_and_fails_clearly_when_enabled(monkeypatch):
    calls = []

    def old_constructor(**kwargs):
        assert 'experimental_cross_page_context' not in kwargs
        calls.append(True)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', old_constructor)
    monkeypatch.setattr(high_level, 'get_translator', lambda settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda settings: [])
    settings = CLIEnvSettingsModel(pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    settings.translation.experimental_cross_page_context = True
    with pytest.raises(RuntimeError, match='installed BabelDOC does not support experimental cross-page context'):
        high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert len(calls) == 1
