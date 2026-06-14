from __future__ import annotations

import os
import logging
import random
import threading
import time
from dataclasses import dataclass
from collections import defaultdict

import requests
from openai import OpenAI
from colorama import init, Fore, Style

init(autoreset=True)


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Defines a single LLM provider's connection and behavior settings."""
    name: str                    # e.g. "openrouter", "local"
    base_url: str                # API base URL
    api_key: str                 # real API key or "none" for local
    models_file: str             # filename for this provider's model list
    cost_per_call: bool = True   # False → cost_usd=0.0, source="local"


# ---------------------------------------------------------------------------
# Data class to hold the result of one LLM call
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    """Holds billing information for a single API call."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    source: str  # "openrouter", "generation_endpoint", "estimate", or "local"
    latency_s: float | None = None
    temperature: float | None = None
    top_p: float | None = None
    model_version: str | None = None
    provider: str | None = None  # "openrouter" or "local"


# ---------------------------------------------------------------------------
# Sampling validation helpers (STATISTICS_SPEC v1.3 — Etapa E3)
# ---------------------------------------------------------------------------

# Provider-qualified prefixes to reduce false positives (P5).
# A new reasoning model not in this list will not be caught — known limitation.
REASONING_MODEL_PATTERNS: tuple[str, ...] = (
    "openai/o1",
    "openai/o3",
    "openai/gpt-5",
    "deepseek/r1",
    ":thinking",           # catches anthropic/claude-3.7-sonnet:thinking
)


def is_reasoning_model(model: str) -> bool:
    """Return True if *model* matches a known reasoning-model prefix."""
    model_lower = model.lower()
    return any(p in model_lower for p in REASONING_MODEL_PATTERNS)


def validate_sampling_for_model(
    model: str, temperature: float, top_p: float,
    *,
    strict: bool = True,
) -> tuple[float, float]:
    """Validate sampling params for reasoning models.

    Args:
        strict: If True (default, CLI path), raises ValueError on mismatch.
                If False (runtime path), logs warning and returns (1.0, 1.0).

    Returns the (validated/effective) sampling params.
    """
    if is_reasoning_model(model) and (temperature != 1.0 or top_p != 1.0):
        msg = (
            f"Model '{model}' is a reasoning model and only supports "
            f"temperature=1.0 and top_p=1.0. "
            f"Got temperature={temperature}, top_p={top_p}."
        )
        if strict:
            raise ValueError(msg)
        else:
            logging.warning(msg + " Overriding to 1.0/1.0 for this call.")
            return 1.0, 1.0
    return temperature, top_p


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LLMAnalyzer:
    """Wraps LLM API calls with accurate per-call cost tracking.

    Supports multiple providers (openrouter, local). Provider is selected
    at construction time; one OpenAI client is created for the active provider.

    Cost accuracy hierarchy (best to worst, openrouter only):
    1. ``response.usage.model_extra['cost']`` — returned directly in the
       completion response by OpenRouter; zero-latency, fully accurate.
    2. ``GET /api/v1/generation?id=<id>`` — queried after the call; used only
       when (1) is unavailable.
    3. Local pricing-table estimate — last resort when the API is unreachable.

    For the local provider, cost_usd is always 0.0 and source is "local".
    """

    # ------------------------------------------------------------------
    # OpenRouter generation-stats endpoint (secondary source)
    # ------------------------------------------------------------------
    _GENERATION_URL = "https://openrouter.ai/api/v1/generation"
    _GENERATION_RETRIES = 3
    _GENERATION_RETRY_DELAY = 1.5  # seconds

    def __init__(self, api_key: str | None = None,
                 models_file: str = "remote_models.txt",
                 temperature: float = 1.0, top_p: float = 1.0,
                 provider: str = "openrouter",
                 local_base_url: str | None = None):
        self.temperature = temperature
        self.top_p = top_p

        # ----------------------------------------------------------------
        # Provider registry (MULTIPROVIDER_SPEC v1.2 — E2)
        # ----------------------------------------------------------------
        providers: dict[str, ProviderConfig] = {}

        # OpenRouter — always registered if ROUTER_API_KEY exists
        router_key = api_key or os.getenv("ROUTER_API_KEY")
        if router_key:
            providers["openrouter"] = ProviderConfig(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=router_key,
                models_file="remote_models.txt",
                cost_per_call=True,
            )

        # Local LLM — from env or constructor or default
        local_url = local_base_url or os.getenv(
            "LOCAL_LLM_BASE_URL", "http://192.168.0.200:8080/v1"
        )
        providers["local"] = ProviderConfig(
            name="local",
            base_url=local_url,
            api_key="none",
            models_file="local_models.txt",
            cost_per_call=False,
        )

        # Validate selection
        if provider not in providers:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Available: {list(providers.keys())}"
            )

        self.active_provider = providers[provider]
        self.provider_name = provider

        # Create client for active provider
        self.client = OpenAI(
            api_key=self.active_provider.api_key,
            base_url=self.active_provider.base_url,
        )

        # Load models for active provider
        self.models = self._load_models(self.active_provider.models_file)
        if not self.models:
            print(
                Fore.YELLOW
                + f"Warning: No models loaded from {self.active_provider.models_file}. Using default model."
                + Style.RESET_ALL
            )
            self.models = ["openai/gpt-4.1-mini-2025-04-14"]

        # Per-call billing records
        self.call_records: list[CallRecord] = []

        # Thread-safety primitives (PARALLELIZATION_SPEC v2.0 — Etapa 0):
        # `random.choice()` uses the shared global RNG and is NOT thread-safe,
        # so each LLMAnalyzer instance owns its own `random.Random()`. The
        # lock guards the list append only — `_fetch_generation_stats` and
        # `_extract_usage` run lock-free because the OpenAI httpx client is
        # thread-safe and generation-stats calls are idempotent per id.
        self._lock = threading.Lock()
        self._rng = random.Random()

        # PARALLELIZATION_SPEC v2.0 — Etapa 6 (print suppression):
        # When True, ``_record_call`` and ``get_random_model`` route their
        # human-facing prints to ``logging.debug`` instead of stdout. Set
        # by ``process_single_pdf_v2`` in parallel mode so per-call
        # output does not interleave across threads/processes.
        self.quiet = False

        # Pricing table — only used as a last-resort fallback (USD per 1 M tokens)
        self._fallback_pricing: dict[str, dict[str, float]] = {
            "qwen/qwen-turbo": {"prompt": 0.04, "completion": 0.16},
            "qwen/qwen-plus": {"prompt": 0.40, "completion": 1.20},
            "qwen/qwen-max": {"prompt": 1.60, "completion": 6.40},
            "qwen/qwen2.5-coder-7b-instruct": {"prompt": 0.03, "completion": 0.09},
            "google/gemini-2.0-flash-lite-001": {"prompt": 0.075, "completion": 0.30},
            "google/gemini-2.0-flash-001": {"prompt": 0.10, "completion": 0.40},
            "google/gemini-2.5-flash": {"prompt": 0.30, "completion": 2.50},
            "google/gemini-2.5-pro": {"prompt": 1.25, "completion": 10.00},
            "google/gemini-3-flash-preview": {"prompt": 0.50, "completion": 3.00},
            "google/gemma-3-4b-it": {"prompt": 0.04, "completion": 0.08},
            "google/gemma-3-12b-it": {"prompt": 0.04, "completion": 0.13},
            "google/gemma-2-9b-it": {"prompt": 0.03, "completion": 0.09},
            "openai/gpt-4.1-nano": {"prompt": 0.10, "completion": 0.40},
            "openai/gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
            "openai/gpt-4.1": {"prompt": 2.00, "completion": 8.00},
            "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
            "openai/gpt-4o": {"prompt": 2.50, "completion": 10.00},
            "openai/gpt-5-nano": {"prompt": 0.05, "completion": 0.40},
            "openai/gpt-5-mini": {"prompt": 0.25, "completion": 2.00},
            "x-ai/grok-4-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4.1-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4": {"prompt": 3.00, "completion": 15.00},
            "meta-llama/llama-3.1-8b-instruct": {"prompt": 0.02, "completion": 0.05},
            "meta-llama/llama-3-8b-instruct": {"prompt": 0.03, "completion": 0.04},
            "meta-llama/llama-3.2-3b-instruct": {"prompt": 0.02, "completion": 0.02},
            "anthropic/claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
            "anthropic/claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
        }

    # ------------------------------------------------------------------
    # Usage extraction from completion response
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_usage(response) -> tuple[int, int, float | None]:
        """Extract prompt tokens, completion tokens, and cost from a response.

        OpenRouter adds a non-standard ``cost`` field to ``response.usage``
        via Pydantic's ``model_extra`` mechanism.  This is returned in every
        completion response — no additional API call is required.

        Returns:
            (prompt_tokens, completion_tokens, cost_usd_or_None)
        """
        prompt_tokens = 0
        completion_tokens = 0
        cost: float | None = None

        if not (hasattr(response, "usage") and response.usage):
            return prompt_tokens, completion_tokens, cost

        usage = response.usage
        prompt_tokens = usage.prompt_tokens or 0
        completion_tokens = usage.completion_tokens or 0

        # Primary: model_extra (Pydantic v2 extra fields — most reliable path)
        try:
            extra: dict = getattr(usage, "model_extra", None) or {}
            raw_cost = extra.get("cost")
            if raw_cost is not None:
                cost = float(raw_cost)
        except Exception:
            pass

        # Secondary: try model_dump (covers edge cases where model_extra is missing)
        if cost is None:
            try:
                dump = usage.model_dump() if hasattr(usage, "model_dump") else {}
                raw_cost = dump.get("cost")
                if raw_cost is not None:
                    cost = float(raw_cost)
            except Exception:
                pass

        return prompt_tokens, completion_tokens, cost

    # ------------------------------------------------------------------
    # Generation endpoint (secondary source, rarely needed)
    # ------------------------------------------------------------------

    def _fetch_generation_stats(self, generation_id: str) -> dict | None:
        """Query the OpenRouter generation endpoint for actual billing data.

        Used only when ``response.usage.model_extra['cost']`` is unavailable.
        Returns the ``data`` dict, or *None* on failure.
        """
        headers = {"Authorization": f"Bearer {self.active_provider.api_key}"}
        params = {"id": generation_id}

        for attempt in range(1, self._GENERATION_RETRIES + 1):
            try:
                resp = requests.get(
                    self._GENERATION_URL,
                    headers=headers,
                    params=params,
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data")
                    if data and data.get("total_cost") is not None:
                        return data
                    if attempt < self._GENERATION_RETRIES:
                        time.sleep(self._GENERATION_RETRY_DELAY)
                elif resp.status_code == 404:
                    if attempt < self._GENERATION_RETRIES:
                        time.sleep(self._GENERATION_RETRY_DELAY)
                else:
                    print(
                        Fore.YELLOW
                        + f"Warning: Generation endpoint HTTP {resp.status_code} for id={generation_id}"
                        + Style.RESET_ALL
                    )
                    break
            except Exception as exc:
                print(
                    Fore.YELLOW
                    + f"Warning: Generation endpoint error (attempt {attempt}): {exc}"
                    + Style.RESET_ALL
                )
                if attempt < self._GENERATION_RETRIES:
                    time.sleep(self._GENERATION_RETRY_DELAY)

        return None

    # ------------------------------------------------------------------
    # Pricing-table fallback (last resort)
    # ------------------------------------------------------------------

    def _estimate_cost(
        self, model_name: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Estimate cost using the local pricing table."""
        model_lower = model_name.lower()
        prices = None
        for key, p in self._fallback_pricing.items():
            if key in model_lower:
                prices = p
                break
        if prices is None:
            print(
                Fore.RED
                + f"Warning: No fallback pricing for '{model_name}'. Using $2.00/$8.00 per 1M tokens (conservative default)."
                + Style.RESET_ALL
            )
            prices = {"prompt": 2.00, "completion": 8.00}
        return (prompt_tokens / 1_000_000) * prices["prompt"] + (
            completion_tokens / 1_000_000
        ) * prices["completion"]

    # ------------------------------------------------------------------
    # Core tracking method
    # ------------------------------------------------------------------

    def _record_call(
        self,
        model_name: str,
        generation_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_from_response: float | None,
        *,
        latency_s: float | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        model_version: str | None = None,
    ) -> None:
        """Store a CallRecord using the most accurate cost source available.

        For the local provider (cost_per_call=False), cost_usd is always 0.0
        and source is "local". OpenRouter cost resolution paths are skipped.
        """

        if not self.active_provider.cost_per_call:
            # Local provider — no cost tracking
            cost_usd = 0.0
            source = "local"
            self._emit(
                Fore.CYAN
                + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                + f"{completion_tokens:,} completion = $0.00000000 USD (local inference)"
                + Style.RESET_ALL
            )
        elif cost_from_response is not None and cost_from_response >= 0:
            # Best path: cost is directly in the completion response
            cost_usd = cost_from_response
            source = "openrouter"
            self._emit(
                Fore.CYAN
                + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                + f"{completion_tokens:,} completion = ${cost_usd:.8f} USD (OpenRouter response)"
                + Style.RESET_ALL
            )
        else:
            # Second path: generation endpoint
            stats = self._fetch_generation_stats(generation_id)
            if stats is not None:
                prompt_tokens = int(
                    stats.get("tokens_prompt")
                    or stats.get("native_tokens_prompt")
                    or prompt_tokens
                )
                completion_tokens = int(
                    stats.get("tokens_completion")
                    or stats.get("native_tokens_completion")
                    or completion_tokens
                )
                cost_usd = float(stats.get("total_cost", 0.0))
                source = "generation_endpoint"
                self._emit(
                    Fore.CYAN
                    + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                    + f"{completion_tokens:,} completion = ${cost_usd:.8f} USD (generation endpoint)"
                    + Style.RESET_ALL
                )
            else:
                # Last resort: price table estimation
                cost_usd = self._estimate_cost(model_name, prompt_tokens, completion_tokens)
                source = "estimate"
                self._emit(
                    Fore.YELLOW
                    + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                    + f"{completion_tokens:,} completion = ${cost_usd:.8f} USD (estimated)"
                    + Style.RESET_ALL
                )

        with self._lock:
            self.call_records.append(
                CallRecord(
                    model=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    source=source,
                    latency_s=latency_s,
                    temperature=temperature,
                    top_p=top_p,
                    model_version=model_version,
                    provider=self.provider_name,
                )
            )

    # ------------------------------------------------------------------
    # Usage summary
    # ------------------------------------------------------------------

    def get_usage_summary(self, *, records: list | None = None) -> dict:
        """Return aggregated token and cost totals.

        If *records* is provided, aggregate from that slice instead
        of ``self.call_records``.
        """
        recs = records if records is not None else self.call_records
        total_prompt = sum(r.prompt_tokens for r in recs)
        total_completion = sum(r.completion_tokens for r in recs)
        total_cost = sum(r.cost_usd for r in recs)
        return {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost_usd": total_cost,
            "calls": len(recs),
            "openrouter_calls": sum(1 for r in recs if r.source == "openrouter"),
            "generation_endpoint_calls": sum(1 for r in recs if r.source == "generation_endpoint"),
            "estimated_calls": sum(1 for r in recs if r.source == "estimate"),
        }

    def print_usage_summary(self, output_file: str | None = None, *, records: list | None = None) -> None:
        """Print token usage and cost summary to console and optionally save to a file.

        If *records* is provided, compute statistics from that slice instead
        of ``self.call_records`` (used for per-PDF summaries in Method 2).
        """
        import statistics as _stats

        call_records = records if records is not None else self.call_records

        summary = self.get_usage_summary(records=records)
        cost_str = f"${summary['total_cost_usd']:.8f} USD"

        # Count calls per source (including local)
        local_calls = sum(1 for r in call_records if r.source == "local")

        lines = [
            "=" * 70,
            "TOKEN USAGE AND COST SUMMARY",
            "=" * 70,
            f"Provider:                  {self.provider_name}",
            f"Total API calls:          {summary['calls']:,}",
        ]
        if local_calls > 0:
            lines.append(f"  - Local:                 {local_calls:,}  (cost $0.00 — local inference)")
        if summary['openrouter_calls'] > 0:
            lines.append(f"  - OpenRouter response:  {summary['openrouter_calls']:,}  (cost in response.usage — most accurate)")
        if summary['generation_endpoint_calls'] > 0:
            lines.append(f"  - Generation endpoint:  {summary['generation_endpoint_calls']:,}  (queried after response)")
        if summary['estimated_calls'] > 0:
            lines.append(f"  - Estimated:            {summary['estimated_calls']:,}  (pricing-table fallback)")
        lines += [
            "-" * 70,
            f"Prompt tokens:            {summary['prompt_tokens']:,}",
            f"Completion tokens:        {summary['completion_tokens']:,}",
            f"Total tokens:             {summary['total_tokens']:,}",
            "-" * 70,
            f"Total cost:               {cost_str}",
            "=" * 70,
        ]

        # --- LATENCY section ---
        latencies = [r.latency_s for r in call_records if r.latency_s is not None]
        lines.append("LATENCY (per LLM call, seconds)")
        lines.append("-" * 70)
        if latencies:
            lines.append(f"calls:    {len(latencies):,}")
            lines.append(f"min:      {min(latencies):.3f}")
            lines.append(f"max:      {max(latencies):.3f}")
            lines.append(f"mean:     {sum(latencies) / len(latencies):.3f}")
            if len(latencies) >= 2:
                q = _stats.quantiles(latencies, n=100, method="inclusive")
                lines.append(f"p50:      {q[49]:.3f}")
                if len(latencies) >= 20:
                    lines.append(f"p95:      {q[94]:.3f}")
                if len(latencies) >= 100:
                    lines.append(f"p99:      {q[98]:.3f}")
        else:
            lines.append("(no latency data)")
        lines.append("=" * 70)

        # --- SAMPLING & MODEL section ---
        temp_vals = [r.temperature for r in call_records if r.temperature is not None]
        top_p_vals = [r.top_p for r in call_records if r.top_p is not None]
        total_calls = len(call_records)
        na_temp = total_calls - len(temp_vals)
        na_top_p = total_calls - len(top_p_vals)

        lines.append("SAMPLING & MODEL")
        lines.append("-" * 70)
        if temp_vals:
            dominant_temp = max(set(temp_vals), key=temp_vals.count)
            temp_note = f"   (used in {len(temp_vals):,}/{total_calls:,} calls"
            if na_temp > 0:
                temp_note += f"; n/a in {na_temp:,} calls"
            temp_note += ")"
            lines.append(f"temperature: {dominant_temp}{temp_note}")
        else:
            lines.append("temperature: n/a")
        if top_p_vals:
            dominant_top_p = max(set(top_p_vals), key=top_p_vals.count)
            top_p_note = f"   (used in {len(top_p_vals):,}/{total_calls:,} calls"
            if na_top_p > 0:
                top_p_note += f"; n/a in {na_top_p:,} calls"
            top_p_note += ")"
            lines.append(f"top_p:       {dominant_top_p}{top_p_note}")
        else:
            lines.append("top_p:       n/a")
        lines.append("=" * 70)

        # --- PER-MODEL BREAKDOWN (extended with actual: + latency:) ---
        if call_records:
            model_data: dict[str, dict] = defaultdict(
                lambda: {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                    "sources": set(),
                    "versions": defaultdict(int),   # model_version -> count
                    "latencies": [],                # list of latency_s values
                }
            )
            for rec in call_records:
                m = model_data[rec.model]
                m["prompt_tokens"] += rec.prompt_tokens
                m["completion_tokens"] += rec.completion_tokens
                m["cost_usd"] += rec.cost_usd
                m["calls"] += 1
                m["sources"].add(rec.source)
                if rec.model_version:
                    m["versions"][rec.model_version] += 1
                if rec.latency_s is not None:
                    m["latencies"].append(rec.latency_s)

            lines.append("PER-MODEL BREAKDOWN")
            lines.append("-" * 70)
            for model_name, m in sorted(model_data.items()):
                src_tag = "/".join(sorted(m["sources"]))
                lines.append(f"  {model_name}")
                # actual: sub-lines
                if m["versions"]:
                    for ver, ver_count in sorted(m["versions"].items(), key=lambda x: -x[1]):
                        lines.append(f"    actual: {ver} ({ver_count:,} calls)")
                # main stats line
                lines.append(
                    f"    calls={m['calls']:,}  prompt={m['prompt_tokens']:,}  "
                    f"completion={m['completion_tokens']:,}  cost=${m['cost_usd']:.8f}  [{src_tag}]"
                )
                # latency: sub-line
                lats = m["latencies"]
                if lats:
                    lat_parts = [f"min={min(lats):.3f}", f"max={max(lats):.3f}",
                                 f"mean={sum(lats) / len(lats):.3f}"]
                    if len(lats) >= 2:
                        q = _stats.quantiles(lats, n=100, method="inclusive")
                        lat_parts.append(f"p50={q[49]:.3f}")
                        if len(lats) >= 20:
                            lat_parts.append(f"p95={q[94]:.3f}")
                        if len(lats) >= 100:
                            lat_parts.append(f"p99={q[98]:.3f}")
                    lines.append(f"    latency: {'  '.join(lat_parts)}")
            lines.append("=" * 70)

        output = "\n".join(lines)

        # Console
        print(Fore.CYAN + "\n" + output + Style.RESET_ALL)

        # File
        if output_file:
            try:
                with open(output_file, "w", encoding="utf-8") as fh:
                    fh.write(output + "\n")
                print(Fore.GREEN + f"Saved cost summary to {output_file}" + Style.RESET_ALL)
            except Exception as exc:
                print(Fore.RED + f"Error saving cost summary: {exc}" + Style.RESET_ALL)

    # ------------------------------------------------------------------
    # Per-run summary JSON (STATISTICS_SPEC v1.3 — R8)
    # ------------------------------------------------------------------

    def write_summary_json(
        self,
        output_dir,
        pdf_path,
        run_id: str,
        model_requested: str | None = None,
        *,
        category_results: dict | None = None,
        significant_paragraphs_count: int | None = None,
        records: list | None = None,
        method: str | None = None,
    ):
        """Write a <pdf_stem>_summary.json in *output_dir* for batch analysis.

        Collects aggregate data from ``self.call_records`` (or *records*
        if provided) and optional analysis-result data (category_results,
        significant_paragraphs_count) passed by the caller, then writes a
        single JSON file matching the schema in STATISTICS_SPEC.md §R8.

        If *records* is provided, aggregate from that slice instead of
        ``self.call_records`` (used for per-PDF summaries in Method 2).

        Returns the path of the written file.
        """
        import json as _json
        import statistics as _stats
        from pathlib import Path as _Path

        output_dir = _Path(output_dir)
        pdf_path = _Path(pdf_path)

        call_records = records if records is not None else self.call_records

        # --- Aggregate from call_records ---
        total_prompt = sum(r.prompt_tokens for r in call_records)
        total_completion = sum(r.completion_tokens for r in call_records)
        total_cost = sum(r.cost_usd for r in call_records)
        total_calls = len(call_records)

        # Dominant cost source (most common)
        source_counts: dict[str, int] = {}
        for r in call_records:
            source_counts[r.source] = source_counts.get(r.source, 0) + 1
        cost_source = (
            max(source_counts, key=lambda k: source_counts[k])
            if source_counts
            else "unknown"
        )

        # --- Latency ---
        latencies = [r.latency_s for r in call_records if r.latency_s is not None]
        latency_block: dict = {"count": len(latencies)}
        if latencies:
            latency_block["min_s"] = round(min(latencies), 3)
            latency_block["max_s"] = round(max(latencies), 3)
            latency_block["mean_s"] = round(sum(latencies) / len(latencies), 3)
            if len(latencies) >= 2:
                q = _stats.quantiles(latencies, n=100, method="inclusive")
                latency_block["p50_s"] = round(q[49], 3)
                if len(latencies) >= 20:
                    latency_block["p95_s"] = round(q[94], 3)
                if len(latencies) >= 100:
                    latency_block["p99_s"] = round(q[98], 3)

        # --- model_versions ---
        model_versions: dict[str, int] = {}
        for r in call_records:
            if r.model_version:
                model_versions[r.model_version] = model_versions.get(r.model_version, 0) + 1

        # --- Build summary dict ---
        summary: dict = {
            "run_id": run_id,
            "provider": self.provider_name,
            "pdf_file": pdf_path.name,
            "model_requested": model_requested or "random",
            "temperature": self.temperature,
            "top_p": self.top_p,
            "total_api_calls": total_calls,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": round(total_cost, 8),
            "cost_source": cost_source,
            "latency": latency_block,
        }

        # Method identifier (for cross-method comparison)
        if method is not None:
            summary["method"] = method

        # Optional analysis-result fields
        if significant_paragraphs_count is not None:
            summary["significant_paragraphs_count"] = significant_paragraphs_count
        if category_results is not None:
            summary["categories_found"] = len(category_results)
            summary["category_results"] = category_results
        elif significant_paragraphs_count is not None:
            summary["categories_found"] = 0

        if model_versions:
            summary["model_versions"] = dict(
                sorted(model_versions.items(), key=lambda x: -x[1])
            )

        # --- Write JSON ---
        summary_file = output_dir / f"{pdf_path.stem}_summary.json"
        try:
            summary_file.write_text(
                _json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._emit(
                Fore.GREEN + f"Saved summary JSON to {summary_file}" + Style.RESET_ALL
            )
        except Exception as exc:
            self._emit(
                Fore.RED + f"Error saving summary JSON: {exc}" + Style.RESET_ALL
            )

        return summary_file

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def _load_models(self, models_file: str) -> list[str]:
        """Load model names from a text file, ignoring comments and empty lines.

        v1.3.1 fix: inline comments (lines that start with a model name
        followed by `# some note`) are now stripped — previously the
        loader kept the full line including the `# ...` tail, which
        caused the model lookup to fail when validate_models() checked
        `cd_model in self._model_names` (the model name + the trailing
        comment were never equal to the bare model name).
        """
        models: list[str] = []
        try:
            with open(models_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    # Strip whitespace
                    line = line.strip()
                    if not line:
                        continue
                    # Skip whole-line comments
                    if line.startswith("#"):
                        continue
                    # v1.3.1 fix: strip inline comments (anything from `#` onwards)
                    # but preserve model names that legitimately contain `#`
                    # by only stripping when `#` is preceded by whitespace.
                    if " #" in line:
                        line = line.split(" #", 1)[0].strip()
                    if line:
                        models.append(line)
            print(
                Fore.CYAN
                + f"Loaded {len(models)} models from {models_file}: {', '.join(models)}"
                + Style.RESET_ALL
            )
        except FileNotFoundError:
            print(
                Fore.YELLOW
                + f"Warning: Models file '{models_file}' not found. Using default model."
                + Style.RESET_ALL
            )
        except Exception as exc:
            print(
                Fore.RED + f"Error loading models file: {exc}. Using default model." + Style.RESET_ALL
            )
        return models

    def _emit(self, text: str) -> None:
        """Print or log a message depending on the ``quiet`` flag.

        PARALLELIZATION_SPEC v2.0 — Etapa 6: in parallel mode the calling
        code sets ``self.quiet = True`` so per-call output is suppressed
        from stdout (where it would interleave across threads and processes)
        and routed to ``logging.debug`` instead.
        """
        if self.quiet:
            logging.debug(text)
        else:
            print(text)

    def get_random_model(self) -> str:
        """Select a random model from the loaded list."""
        # Use the per-instance RNG (thread-safe). `random.choice()` would
        # touch the shared global state and race under concurrent calls.
        selected_model = self._rng.choice(self.models)
        self._emit(Fore.CYAN + f"Selected model: {selected_model}" + Style.RESET_ALL)
        return selected_model

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def load_prompt(prompt_path: str) -> str:
        with open(prompt_path, "r", encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # Internal completion helper (with timing + sampling params)
    # ------------------------------------------------------------------

    def _timed_create(
        self,
        model_name: str,
        system_message: str,
        user_message: str,
    ) -> tuple:
        """Send a chat completion with timing and sampling params.

        Returns (response, latency_s, model_version).
        Raises ValueError if the model is a reasoning model and
        temperature/top_p are not 1.0 (see validate_sampling_for_model).
        """
        # Runtime safety net (warn + override, NOT raise — P6)
        temp, top_p = validate_sampling_for_model(
            model_name, self.temperature, self.top_p, strict=False
        )
        t0 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=model_name,
            temperature=temp,
            top_p=top_p,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
        )
        latency_s = time.perf_counter() - t0
        model_version = getattr(response, "model", None)
        return response, latency_s, model_version

    def _complete(
        self,
        model_name: str,
        system_message: str,
        user_message: str,
    ) -> str:
        """Send a chat completion, record accurate billing, and return the reply."""
        response, latency_s, model_version = self._timed_create(
            model_name, system_message, user_message
        )

        if not response.choices:
            raise RuntimeError("No response choices returned by the API.")

        prompt_tokens, completion_tokens, cost_from_response = self._extract_usage(response)

        self._record_call(
            model_name=model_name,
            generation_id=response.id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_from_response=cost_from_response,
            latency_s=latency_s,
            temperature=self.temperature,
            top_p=self.top_p,
            model_version=model_version,
        )

        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # Public analysis methods
    # ------------------------------------------------------------------

    def analyze(
        self,
        classified_keywords: dict,
        prompt: str,
        abstract: str | None = None,
        model_name: str | None = None,
    ) -> str:
        """Run the final category analysis prompt."""
        if model_name is None:
            model_name = self.get_random_model()
        else:
            print(Fore.CYAN + f"Using specified model: {model_name}" + Style.RESET_ALL)

        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles."
        )
        reply = self._complete(model_name, system_message, prompt)
        print(Fore.GREEN + "\nLLM response:")
        print(Style.RESET_ALL + f"\t{reply}")
        return reply

    def analyze_single_occurrence(
        self, prompt_text: str, model_name: str | None = None
    ) -> str:
        """Determine whether a single keyword occurrence is significant."""
        if model_name is None:
            model_name = self.get_random_model()
        else:
            print(Fore.CYAN + f"Using specified model: {model_name}" + Style.RESET_ALL)

        system_message = (
            "You are an expert assistant specialized in analyzing scientific articles."
        )
        return self._complete(model_name, system_message, prompt_text)

    # ------------------------------------------------------------------
    # Web-search article summary
    # ------------------------------------------------------------------

    # Models known to support grounding / web search on OpenRouter — cheapest first
    WEB_SEARCH_MODELS: list[str] = [
        "qwen/qwen-turbo",
        "google/gemini-2.0-flash-lite-001",
        "openai/gpt-4.1-nano",
        "google/gemini-2.0-flash-001",
        "openai/gpt-4o-mini",
        "x-ai/grok-4-fast",
    ]

    def fetch_article_summary(
        self, article_title: str, model_name: str | None = None
    ) -> str | None:
        """Fetch an internet-based summary for *article_title*.

        Tries each model in ``WEB_SEARCH_MODELS`` (or the specified model) and
        returns all successfully obtained summaries joined together.
        """
        prompt_template = self.load_prompt("summary_prompt.txt")
        prompt = prompt_template.replace("{article_title}", article_title)

        print(Fore.CYAN + f"Fetching article summary for: {article_title}" + Style.RESET_ALL)

        models_to_try = [model_name] if model_name else self.WEB_SEARCH_MODELS
        system_message = (
            "You are a research assistant with web browsing capabilities. "
            "Always search the web when asked about articles or papers."
        )

        _NOT_FOUND_PATTERNS = [
            "could not find", "cannot find", "not found", "no information",
            "does not appear", "unable to find", "search failed",
            "no results", "i cannot find", "i could not find",
            "i couldn't find", "don't have information",
        ]

        all_summaries: list[str] = []

        for search_model in models_to_try:
            print(Fore.CYAN + f"Trying model: {search_model}" + Style.RESET_ALL)
            try:
                response, latency_s, model_version = self._timed_create(
                    search_model, system_message, prompt
                )

                # Extract usage and record cost BEFORE content-quality checks (C2 fix).
                # Even if the content is unusable, tokens were consumed and billed.
                prompt_tokens, completion_tokens, cost_from_response = self._extract_usage(response)
                self._record_call(
                    model_name=search_model,
                    generation_id=response.id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_from_response=cost_from_response,
                    latency_s=latency_s,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    model_version=model_version,
                )

                if not response.choices:
                    print(Fore.YELLOW + f"No response choices from {search_model}" + Style.RESET_ALL)
                    continue

                llm_response = response.choices[0].message.content.strip()

                if llm_response == "SUMMARY_NOT_FOUND":
                    print(Fore.YELLOW + f"{search_model}: SUMMARY_NOT_FOUND" + Style.RESET_ALL)
                    continue

                if any(p in llm_response.lower() for p in _NOT_FOUND_PATTERNS):
                    print(Fore.YELLOW + f"{search_model}: Article not found" + Style.RESET_ALL)
                    continue

                if not llm_response:
                    print(Fore.YELLOW + f"{search_model}: Empty response" + Style.RESET_ALL)
                    continue

                print(Fore.GREEN + f"{search_model}: Found summary!" + Style.RESET_ALL)
                all_summaries.append(f"[{search_model}]\n{llm_response}")

            except Exception as exc:
                print(
                    Fore.RED + f"{search_model}: Error - {str(exc)[:120]}" + Style.RESET_ALL
                )
                continue

        if not all_summaries:
            print(Fore.RED + "No summaries obtained from any model." + Style.RESET_ALL)
            return None

        combined = "\n\n---\n\n".join(all_summaries)
        print(
            Fore.GREEN
            + f"Obtained {len(all_summaries)} summary(s) from {len(models_to_try)} model(s)."
            + Style.RESET_ALL
        )
        return combined