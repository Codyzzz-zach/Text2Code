"""Tests for LLMConfig — provider/model/base_url/api_key configuration."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from t2c.llm_config import LLMConfig, _PROVIDER_PRESETS


class TestProviderPresets:
    def test_minimax_preset(self):
        cfg = LLMConfig.minimax(api_key="sk-test-123")
        assert cfg.provider == "minimax"
        assert cfg.model == "MiniMax-M3"
        assert cfg.base_url == "https://api.minimaxi.com/anthropic"
        assert cfg.api_key == "sk-test-123"

    def test_anthropic_preset(self):
        cfg = LLMConfig.anthropic(api_key="sk-ant-test")
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-3-5-sonnet-20241022"
        assert cfg.base_url == "https://api.anthropic.com"
        assert cfg.api_key == "sk-ant-test"

    def test_openai_preset(self):
        cfg = LLMConfig.openai(api_key="sk-openai", model="gpt-4o-mini")
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.api_key == "sk-openai"

    def test_custom_preset(self):
        cfg = LLMConfig.custom(
            provider="local-llama",
            model="llama-3-70b",
            base_url="http://localhost:8000/v1",
            api_key="not-needed",
        )
        assert cfg.provider == "local-llama"
        assert cfg.model == "llama-3-70b"
        assert cfg.base_url == "http://localhost:8000/v1"

    def test_minimax_env_var_fallback(self):
        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "sk-from-env"}, clear=True):
            cfg = LLMConfig.minimax()
        assert cfg.api_key == "sk-from-env"

    def test_preset_overrides(self):
        cfg = LLMConfig.minimax(api_key="sk-x", model="custom-model",
                                base_url="http://override")
        assert cfg.model == "custom-model"
        assert cfg.base_url == "http://override"


class TestFromEnv:
    def setup_method(self):
        # Clear all T2C_LLM_* env vars so tests are isolated
        for k in list(os.environ):
            if k.startswith("T2C_LLM_") or k in ("T2C_MAX_TOKENS", "T2C_THINKING_BUDGET",
                                                "T2C_CACHE_MODE", "T2C_CACHE_DIR"):
                os.environ.pop(k, None)

    def test_from_env_default_minimax(self):
        cfg = LLMConfig.from_env()
        assert cfg.provider == "minimax"
        assert cfg.model == "MiniMax-M3"
        assert cfg.base_url == "https://api.minimaxi.com/anthropic"

    def test_from_env_explicit_provider(self):
        cfg = LLMConfig.from_env(provider="anthropic")
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-3-5-sonnet-20241022"

    def test_from_env_with_all_overrides(self):
        env = {
            "T2C_LLM_PROVIDER": "openai",
            "T2C_LLM_MODEL": "gpt-4-turbo",
            "T2C_LLM_BASE_URL": "https://api.example.com/v1",
            "T2C_LLM_API_KEY": "sk-test",
            "T2C_LLM_MAX_TOKENS": "4096",
            "T2C_LLM_THINKING_BUDGET": "512",
            "T2C_LLM_CACHE_MODE": "read_only",
            "T2C_LLM_CACHE_DIR": "/tmp/test-cache",
            "T2C_LLM_PROTOCOL": "verbose-v1",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = LLMConfig.from_env()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4-turbo"
        assert cfg.base_url == "https://api.example.com/v1"
        assert cfg.api_key == "sk-test"
        assert cfg.max_tokens == 4096
        assert cfg.thinking_budget == 512
        assert cfg.cache_mode == "read_only"
        assert cfg.cache_dir == "/tmp/test-cache"
        assert cfg.extractor_protocol == "verbose-v1"

    def test_from_env_explicit_kwargs_override(self):
        with patch.dict(os.environ, {"T2C_LLM_PROVIDER": "minimax"}, clear=True), \
             patch("t2c.llm_config._load_dotenv", lambda *a, **kw: None), \
             patch("t2c.llm_config._find_env_file", lambda *a, **kw: None):
            cfg = LLMConfig.from_env(provider="anthropic")
        assert cfg.provider == "anthropic"

    def test_from_env_dotenv_loading(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\n"
            "T2C_LLM_PROVIDER=anthropic\n"
            'T2C_LLM_API_KEY="sk-from-dotenv"\n'
            "T2C_LLM_MODEL=claude-3-haiku-20240307\n"
            "OTHER_VAR=ignored\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            cfg = LLMConfig.from_env(env_file=env_file)
        assert cfg.provider == "anthropic"
        assert cfg.api_key == "sk-from-dotenv"
        assert cfg.model == "claude-3-haiku-20240307"

    def test_from_env_dotenv_doesnt_override_existing(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("T2C_LLM_API_KEY=from-file\n", encoding="utf-8")
        with patch.dict(os.environ, {"T2C_LLM_API_KEY": "from-env"}, clear=True):
            cfg = LLMConfig.from_env(env_file=env_file)
        # Existing env var wins (setdefault behavior)
        assert cfg.api_key == "from-env"

    def test_from_env_custom_provider_requires_url_and_model(self):
        # Custom provider with no model/base_url should raise. We patch
        # _load_dotenv so the project's .env file doesn't leak defaults
        # into the test.
        with patch.dict(os.environ, {"T2C_LLM_PROVIDER": "custom:weird"}, clear=True), \
             patch("t2c.llm_config._load_dotenv", lambda *a, **kw: None), \
             patch("t2c.llm_config._find_env_file", lambda *a, **kw: None):
            with pytest.raises(ValueError, match="requires"):
                LLMConfig.from_env()


class TestFromDict:
    def test_from_dict_minimax(self):
        cfg = LLMConfig.from_dict({
            "provider": "minimax",
            "api_key": "sk-test",
        })
        assert cfg.provider == "minimax"
        assert cfg.api_key == "sk-test"
        assert cfg.model == "MiniMax-M3"

    def test_from_dict_full(self):
        cfg = LLMConfig.from_dict({
            "provider": "anthropic",
            "model": "claude-3-opus-20240229",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-x",
            "max_tokens": 2048,
        })
        assert cfg.model == "claude-3-opus-20240229"
        assert cfg.max_tokens == 2048


class TestSerialization:
    def test_to_dict_roundtrip(self):
        cfg = LLMConfig.minimax(api_key="sk-test", max_tokens=2048)
        d = cfg.to_dict()
        assert d["provider"] == "minimax"
        assert d["api_key"] == "sk-test"
        assert d["max_tokens"] == 2048
        # Roundtrip via from_dict
        cfg2 = LLMConfig.from_dict(d)
        assert cfg2.provider == cfg.provider
        assert cfg2.api_key == cfg.api_key
        assert cfg2.max_tokens == cfg.max_tokens

    def test_to_json_masks_key(self):
        cfg = LLMConfig.minimax(api_key="sk-secret")
        j = cfg.to_json()
        assert "sk-secret" not in j
        assert "***" in j

    def test_masked_hides_key(self):
        cfg = LLMConfig.minimax(api_key="sk-secret")
        m = cfg.masked()
        assert m.api_key == "***"
        assert cfg.api_key == "sk-secret"  # original unchanged


class TestLLMExtractorIntegration:
    """LLMExtractor accepts a config directly."""

    def test_extractor_with_config(self):
        # Use the optional anthropic client path: pass _client
        from t2c.extractor import LLMExtractor
        cfg = LLMConfig.minimax(api_key="sk-minimax-test",
                                 model="MiniMax-M3",
                                 cache_mode="off")
        mock_client = object()  # bypasses anthropic import
        ext = LLMExtractor(config=cfg, _client=mock_client)
        assert ext._client is mock_client
        # The config didn't set max_tokens → default applies
        assert ext._max_tokens > 0
        # No cache (we set cache_mode="off")
        assert ext._cache is None

    def test_extractor_config_overrides_kwarg(self):
        """config wins over individual kwargs when kwargs are default."""
        from t2c.extractor import LLMExtractor
        cfg = LLMConfig.minimax(api_key="sk-config",
                                 model="config-model",
                                 max_tokens=9999)
        mock_client = object()
        ext = LLMExtractor(config=cfg, _client=mock_client)
        # config.max_tokens is 9999
        assert ext._max_tokens == 9999
        # config.model is config-model
        assert ext._model == "config-model"

    def test_extractor_kwarg_overrides_config(self):
        """Explicit kwargs win over config (per v4.0 precedence)."""
        from t2c.extractor import LLMExtractor
        cfg = LLMConfig.minimax(api_key="sk-config", model="config-model")
        mock_client = object()
        ext = LLMExtractor(model="kwarg-model", config=cfg, _client=mock_client)
        # Note: current code uses `model = model if model != "MiniMax-M3" else config.model`
        # so a non-default model passes through. Use the default sentinel to
        # verify config fallback: pass default + config.
        ext2 = LLMExtractor(config=cfg, _client=mock_client)
        assert ext2._model == "config-model"
        assert ext._model == "kwarg-model"
