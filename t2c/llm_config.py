"""LLMConfig — provider/model/base_url/api_key configuration with presets.

Public API:
    LLMConfig.from_env()                  # read from env + project config
    LLMConfig.from_dict(d)                # read from a dict (e.g. YAML)
    LLMConfig.minimax(api_key=...)        # preset for MiniMax public endpoint
    LLMConfig.anthropic(api_key=...)      # preset for Anthropic API
    LLMConfig.openai(api_key=..., ...)    # preset for OpenAI-compatible
    LLMConfig.deepseek(api_key=..., ...)  # preset for DeepSeek (Anthropic format)
    LLMConfig.custom(provider=..., ...)   # any other OpenAI-compatible endpoint

Usage:
    cfg = LLMConfig.from_env()            # DeepSeek v4 flash by default
    extractor = LLMExtractor(config=cfg)

Resolution order for `from_env`:
    1. explicit kwargs
    2. function arg (e.g. from_dict data)
    3. environment variables
    4. .env file (project root) — best effort, no hard dep on python-dotenv
    5. preset default (provider-specific base_url)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# Provider presets — known base URLs and default model names.
# Add new providers here; the LLMConfig dataclass is provider-agnostic.
DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_CACHE_MODE = "read_write"
DEFAULT_CACHE_DIR = ".t2c_cache"
DEFAULT_EXTRACTOR_PROTOCOL = "compact-v1"

_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "minimax": {
        "base_url": "https://api.minimaxi.com/anthropic",
        "default_model": "MiniMax-M3",
        "api_key_env": "ANTHROPIC_AUTH_TOKEN",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/anthropic",
        "default_model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
}

DEFAULT_LLM_MODEL = _PROVIDER_PRESETS[DEFAULT_LLM_PROVIDER]["default_model"]


def _load_dotenv(path: Path) -> None:
    """Best-effort .env loader. No external dependency.

    Lines like `KEY=value` are added to os.environ if not already set.
    """
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except OSError:
        pass


def _find_env_file(start: Path | None = None) -> Path | None:
    """Look for .env walking up from the given path (default: cwd)."""
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


@dataclass
class LLMConfig:
    """Provider-agnostic LLM endpoint configuration.

    All fields can be set explicitly. `from_env` / `from_dict` / presets
    fill in the gaps from the environment and provider defaults.
    """

    provider: str = DEFAULT_LLM_PROVIDER
    model: str = ""
    base_url: str = ""
    api_key: str = ""

    # v3.4.2: optional overrides
    max_tokens: int | None = None
    thinking_budget: int | None = None
    timeout: float | None = None

    # v3.4.2: cache settings (consumed by LLMExtractor)
    cache_mode: str | None = None  # off / read_write / read_only / refresh
    cache_dir: str | None = None

    # v3.4.2: extractor protocol (verbose-v1 / compact-v1)
    extractor_protocol: str | None = None
    prompt_version: str | None = None

    # Extra headers / metadata for OpenAI-compatible endpoints
    extra: dict[str, Any] = field(default_factory=dict)

    # -- Preset factories ----------------------------------------------

    @classmethod
    def minimax(cls, *, api_key: str | None = None, model: str | None = None,
                base_url: str | None = None, **kwargs: Any) -> "LLMConfig":
        """Preset for the MiniMax public endpoint.

        Defaults match the v3.4.2 environment the test fixtures use.
        """
        preset = _PROVIDER_PRESETS["minimax"]
        return cls(
            provider="minimax",
            model=model or preset["default_model"],
            base_url=base_url or preset["base_url"],
            api_key=api_key or os.environ.get(preset["api_key_env"]) or os.environ.get("ANTHROPIC_API_KEY", ""),
            **kwargs,
        )

    @classmethod
    def anthropic(cls, *, api_key: str | None = None, model: str | None = None,
                  base_url: str | None = None, **kwargs: Any) -> "LLMConfig":
        """Preset for the Anthropic API."""
        preset = _PROVIDER_PRESETS["anthropic"]
        return cls(
            provider="anthropic",
            model=model or preset["default_model"],
            base_url=base_url or preset["base_url"],
            api_key=api_key or os.environ.get(preset["api_key_env"], ""),
            **kwargs,
        )

    @classmethod
    def openai(cls, *, api_key: str | None = None, model: str | None = None,
               base_url: str | None = None, **kwargs: Any) -> "LLMConfig":
        """Preset for OpenAI-compatible endpoints."""
        preset = _PROVIDER_PRESETS["openai"]
        return cls(
            provider="openai",
            model=model or preset["default_model"],
            base_url=base_url or preset["base_url"],
            api_key=api_key or os.environ.get(preset["api_key_env"], ""),
            **kwargs,
        )

    @classmethod
    def deepseek(cls, *, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None, **kwargs: Any) -> "LLMConfig":
        """Preset for DeepSeek via Anthropic-compatible API.

        DeepSeek supports the Anthropic Messages API format at
        https://api.deepseek.com/anthropic, enabling context-hard-disk
        cache hits on shared prompt prefixes.
        """
        preset = _PROVIDER_PRESETS["deepseek"]
        kwargs.setdefault("thinking_budget", 0)
        kwargs.setdefault("cache_mode", DEFAULT_CACHE_MODE)
        kwargs.setdefault("cache_dir", DEFAULT_CACHE_DIR)
        kwargs.setdefault("extractor_protocol", DEFAULT_EXTRACTOR_PROTOCOL)
        return cls(
            provider="deepseek",
            model=model or preset["default_model"],
            base_url=base_url or preset["base_url"],
            api_key=api_key or os.environ.get(preset["api_key_env"], ""),
            **kwargs,
        )

    @classmethod
    def custom(cls, *, provider: str, model: str, base_url: str,
               api_key: str | None = None, **kwargs: Any) -> "LLMConfig":
        """Any other OpenAI-compatible endpoint."""
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key or "",
            **kwargs,
        )

    # -- Load from env / dict / file ------------------------------------

    @classmethod
    def from_env(cls, *, provider: str | None = None,
                 env_file: str | Path | None = None,
                 **overrides: Any) -> "LLMConfig":
        """Build a config from environment variables.

        Reads the project .env (if found) into os.environ, then layers
        T2C_LLM_* overrides, then any explicit `overrides` kwargs.

        Recognized env vars:
            T2C_LLM_PROVIDER       (minimax / anthropic / openai / deepseek / custom:<name>)
            T2C_LLM_MODEL          (model name)
            T2C_LLM_BASE_URL       (endpoint URL)
            T2C_LLM_API_KEY        (key)
            T2C_LLM_MAX_TOKENS
            T2C_LLM_THINKING_BUDGET
            T2C_LLM_TIMEOUT
            T2C_LLM_CACHE_MODE
            T2C_LLM_CACHE_DIR
            T2C_LLM_PROTOCOL
            T2C_LLM_PROMPT_VERSION

        If `provider` is not set anywhere, the factory falls back to
        `deepseek` / `deepseek-v4-flash`, the product default LLM entry.
        """
        # Load .env first so os.environ is populated
        env_path = Path(env_file) if env_file else _find_env_file()
        if env_path is not None:
            _load_dotenv(env_path)

        # Resolution order: explicit kwarg > env var > product default.
        if provider is not None:
            env_provider = provider
        else:
            env_provider = os.environ.get("T2C_LLM_PROVIDER") or DEFAULT_LLM_PROVIDER
        env_model = os.environ.get("T2C_LLM_MODEL")
        env_base_url = os.environ.get("T2C_LLM_BASE_URL")
        env_api_key = os.environ.get("T2C_LLM_API_KEY")

        # Provider preset pulls in base_url + default model.
        if env_provider in _PROVIDER_PRESETS:
            preset = _PROVIDER_PRESETS[env_provider]
            cfg = cls(
                provider=env_provider,
                model=env_model or preset["default_model"],
                base_url=env_base_url or preset["base_url"],
                api_key=env_api_key or os.environ.get(preset["api_key_env"], ""),
            )
        else:
            # Custom provider — all 3 fields required from env
            if not (env_model and env_base_url):
                raise ValueError(
                    f"Custom provider {env_provider!r} requires "
                    "T2C_LLM_MODEL and T2C_LLM_BASE_URL"
                )
            cfg = cls(
                provider=env_provider,
                model=env_model,
                base_url=env_base_url,
                api_key=env_api_key or "",
            )

        # Apply optional overrides
        if (mt := os.environ.get("T2C_LLM_MAX_TOKENS")):
            cfg.max_tokens = int(mt)
        if (tb := os.environ.get("T2C_LLM_THINKING_BUDGET")):
            cfg.thinking_budget = int(tb)
        if (to := os.environ.get("T2C_LLM_TIMEOUT")):
            cfg.timeout = float(to)
        # Cache: accept T2C_LLM_CACHE_MODE first, then T2C_CACHE_MODE
        # (the legacy key that LLMExtractor reads directly).
        if (cm := os.environ.get("T2C_LLM_CACHE_MODE") or os.environ.get("T2C_CACHE_MODE")):
            cfg.cache_mode = cm
        if (cd := os.environ.get("T2C_LLM_CACHE_DIR") or os.environ.get("T2C_CACHE_DIR")):
            cfg.cache_dir = cd
        if (pr := os.environ.get("T2C_LLM_PROTOCOL")):
            cfg.extractor_protocol = pr
        if (pv := os.environ.get("T2C_LLM_PROMPT_VERSION")):
            cfg.prompt_version = pv

        # Product defaults: real extraction should be compact and cacheable
        # unless the caller explicitly opts out. DeepSeek flash does not use
        # a thinking budget in the default path.
        if cfg.cache_mode is None:
            cfg.cache_mode = DEFAULT_CACHE_MODE
        if cfg.cache_dir is None:
            cfg.cache_dir = DEFAULT_CACHE_DIR
        if cfg.extractor_protocol is None:
            cfg.extractor_protocol = DEFAULT_EXTRACTOR_PROTOCOL
        if cfg.provider == "deepseek" and cfg.thinking_budget is None:
            cfg.thinking_budget = 0

        # Finally: explicit overrides win. Include `provider` in overrides
        # so the Special-case block below can detect an explicit provider
        # switch (since `provider=...` is a named parameter that doesn't
        # flow through **overrides).
        if provider is not None:
            overrides["provider"] = provider
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)

        # Special case: if `provider` was explicitly overridden, the
        # provider preset (base_url + default model) needs to be re-applied.
        if "provider" in overrides and overrides["provider"] is not None:
            new_provider = overrides["provider"]
            if new_provider in _PROVIDER_PRESETS:
                preset = _PROVIDER_PRESETS[new_provider]
                # Only fill in fields that the user did NOT explicitly set
                if "model" not in overrides:
                    cfg.model = preset["default_model"]
                if "base_url" not in overrides:
                    cfg.base_url = preset["base_url"]
                cfg.provider = new_provider
        return cfg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMConfig":
        """Build a config from a plain dict (e.g. loaded from YAML/TOML)."""
        data = dict(data)  # copy
        # Resolve provider preset
        provider = data.pop("provider", DEFAULT_LLM_PROVIDER)
        model = data.pop("model", None)
        base_url = data.pop("base_url", None)
        api_key = data.pop("api_key", None)
        if provider in _PROVIDER_PRESETS:
            preset = _PROVIDER_PRESETS[provider]
            if provider == "deepseek":
                data.setdefault("thinking_budget", 0)
                data.setdefault("cache_mode", DEFAULT_CACHE_MODE)
                data.setdefault("cache_dir", DEFAULT_CACHE_DIR)
                data.setdefault("extractor_protocol", DEFAULT_EXTRACTOR_PROTOCOL)
            return cls(
                provider=provider,
                model=model or preset["default_model"],
                base_url=base_url or preset["base_url"],
                api_key=api_key or os.environ.get(preset["api_key_env"], ""),
                **data,
            )
        return cls(
            provider=provider,
            model=model or "",
            base_url=base_url or "",
            api_key=api_key or "",
            **data,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        # Don't serialize api_key by default
        d = self.to_dict()
        d["api_key"] = "***" if self.api_key else ""
        return json.dumps(d, ensure_ascii=False, indent=2)

    def masked(self) -> "LLMConfig":
        """Return a copy with the API key replaced by '***'. Safe to log."""
        return LLMConfig(
            provider=self.provider, model=self.model,
            base_url=self.base_url, api_key="***" if self.api_key else "",
            max_tokens=self.max_tokens, thinking_budget=self.thinking_budget,
            timeout=self.timeout, cache_mode=self.cache_mode,
            cache_dir=self.cache_dir, extractor_protocol=self.extractor_protocol,
            prompt_version=self.prompt_version, extra=dict(self.extra),
        )


__all__ = [
    "LLMConfig",
    "_PROVIDER_PRESETS",
    "DEFAULT_LLM_PROVIDER",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_CACHE_MODE",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_EXTRACTOR_PROTOCOL",
]
