from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from collections import defaultdict

import requests
from openai import OpenAI
from colorama import init, Fore, Style

init(autoreset=True)


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
    source: str  # "openrouter" from response, "generation_endpoint", or "estimate"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LLMAnalyzer:
    """Wraps OpenRouter API calls with accurate per-call cost tracking.

    Cost accuracy hierarchy (best to worst):
    1. ``response.usage.model_extra['cost']`` — returned directly in the
       completion response by OpenRouter; zero-latency, fully accurate.
    2. ``GET /api/v1/generation?id=<id>`` — queried after the call; used only
       when (1) is unavailable.
    3. Local pricing-table estimate — last resort when the API is unreachable.
    """

    # ------------------------------------------------------------------
    # OpenRouter generation-stats endpoint (secondary source)
    # ------------------------------------------------------------------
    _GENERATION_URL = "https://openrouter.ai/api/v1/generation"
    _GENERATION_RETRIES = 3
    _GENERATION_RETRY_DELAY = 1.5  # seconds

    def __init__(self, api_key: str | None = None, models_file: str = "models.txt"):
        self.api_key = api_key or os.getenv("ROUTER_API_KEY")
        if not self.api_key:
            print(Fore.RED + "Error: ROUTER_API_KEY not found in environment variables.")
            raise ValueError("ROUTER_API_KEY not found in environment variables.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"Authorization": f"Bearer {self.api_key}"},
        )
        self.models = self._load_models(models_file)
        if not self.models:
            print(
                Fore.YELLOW
                + f"Warning: No models loaded from {models_file}. Using default model."
                + Style.RESET_ALL
            )
            self.models = ["openai/gpt-4.1-mini-2025-04-14"]

        # Per-call billing records
        self.call_records: list[CallRecord] = []

        # Pricing table — only used as a last-resort fallback (USD per 1 M tokens)
        self._fallback_pricing: dict[str, dict[str, float]] = {
            "qwen/qwen-turbo": {"prompt": 0.04, "completion": 0.16},
            "qwen/qwen-plus": {"prompt": 0.40, "completion": 1.20},
            "qwen/qwen-max": {"prompt": 1.60, "completion": 6.40},
            "qwen/qwen2.5-coder-7b-instruct": {"prompt": 0.03, "completion": 0.09},
            "google/gemini-2.0-flash-lite-001": {"prompt": 0.075, "completion": 0.30},
            "google/gemini-2.0-flash-001": {"prompt": 0.10, "completion": 0.40},
            "google/gemini-2.5-flash": {"prompt": 0.15, "completion": 0.60},
            "google/gemini-2.5-pro": {"prompt": 1.25, "completion": 10.00},
            "google/gemini-3-flash-preview": {"prompt": 0.10, "completion": 0.50},
            "google/gemma-3-4b-it": {"prompt": 0.04, "completion": 0.08},
            "google/gemma-3-12b-it": {"prompt": 0.04, "completion": 0.13},
            "google/gemma-2-9b-it": {"prompt": 0.03, "completion": 0.09},
            "openai/gpt-4.1-nano": {"prompt": 0.10, "completion": 0.40},
            "openai/gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
            "openai/gpt-4.1": {"prompt": 2.00, "completion": 8.00},
            "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
            "openai/gpt-4o": {"prompt": 2.50, "completion": 10.00},
            "openai/gpt-5-nano": {"prompt": 0.05, "completion": 0.40},
            "openai/gpt-5-mini": {"prompt": 0.05, "completion": 0.40},
            "x-ai/grok-4-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4.1-fast": {"prompt": 0.20, "completion": 0.50},
            "x-ai/grok-4": {"prompt": 3.00, "completion": 15.00},
            "meta-llama/llama-3.1-8b-instruct": {"prompt": 0.02, "completion": 0.05},
            "meta-llama/llama-3-8b-instruct": {"prompt": 0.03, "completion": 0.04},
            "meta-llama/llama-3.2-3b-instruct": {"prompt": 0.02, "completion": 0.02},
            "anthropic/claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
            "anthropic/claude-3.5-sonnet": {"prompt": 6.00, "completion": 30.00},
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
        headers = {"Authorization": f"Bearer {self.api_key}"}
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
                Fore.YELLOW
                + f"Warning: No fallback pricing for '{model_name}'. Using $0.10/$0.40 per 1M."
                + Style.RESET_ALL
            )
            prices = {"prompt": 0.10, "completion": 0.40}
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
    ) -> None:
        """Store a CallRecord using the most accurate cost source available."""

        if cost_from_response is not None and cost_from_response >= 0:
            # Best path: cost is directly in the completion response
            cost_usd = cost_from_response
            source = "openrouter"
            print(
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
                print(
                    Fore.CYAN
                    + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                    + f"{completion_tokens:,} completion = ${cost_usd:.8f} USD (generation endpoint)"
                    + Style.RESET_ALL
                )
            else:
                # Last resort: price table estimation
                cost_usd = self._estimate_cost(model_name, prompt_tokens, completion_tokens)
                source = "estimate"
                print(
                    Fore.YELLOW
                    + f"    [Cost] {model_name}: {prompt_tokens:,} prompt + "
                    + f"{completion_tokens:,} completion = ${cost_usd:.8f} USD (estimated)"
                    + Style.RESET_ALL
                )

        self.call_records.append(
            CallRecord(
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                source=source,
            )
        )

    # ------------------------------------------------------------------
    # Usage summary
    # ------------------------------------------------------------------

    def get_usage_summary(self) -> dict:
        """Return aggregated token and cost totals."""
        total_prompt = sum(r.prompt_tokens for r in self.call_records)
        total_completion = sum(r.completion_tokens for r in self.call_records)
        total_cost = sum(r.cost_usd for r in self.call_records)
        return {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost_usd": total_cost,
            "calls": len(self.call_records),
            "openrouter_calls": sum(1 for r in self.call_records if r.source == "openrouter"),
            "generation_endpoint_calls": sum(1 for r in self.call_records if r.source == "generation_endpoint"),
            "estimated_calls": sum(1 for r in self.call_records if r.source == "estimate"),
        }

    def print_usage_summary(self, output_file: str | None = None) -> None:
        """Print token usage and cost summary to console and optionally save to a file."""
        summary = self.get_usage_summary()
        cost_str = f"${summary['total_cost_usd']:.8f} USD"

        lines = [
            "=" * 70,
            "TOKEN USAGE AND COST SUMMARY",
            "=" * 70,
            f"Total API calls:          {summary['calls']:,}",
            f"  - OpenRouter response:  {summary['openrouter_calls']:,}  (cost in response.usage — most accurate)",
            f"  - Generation endpoint:  {summary['generation_endpoint_calls']:,}  (queried after response)",
            f"  - Estimated:            {summary['estimated_calls']:,}  (pricing-table fallback)",
            "-" * 70,
            f"Prompt tokens:            {summary['prompt_tokens']:,}",
            f"Completion tokens:        {summary['completion_tokens']:,}",
            f"Total tokens:             {summary['total_tokens']:,}",
            "-" * 70,
            f"Total cost:               {cost_str}",
            "=" * 70,
        ]

        # Per-model breakdown
        if self.call_records:
            model_totals: dict[str, dict] = defaultdict(
                lambda: {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                    "sources": set(),
                }
            )
            for rec in self.call_records:
                m = model_totals[rec.model]
                m["prompt_tokens"] += rec.prompt_tokens
                m["completion_tokens"] += rec.completion_tokens
                m["cost_usd"] += rec.cost_usd
                m["calls"] += 1
                m["sources"].add(rec.source)

            lines.append("PER-MODEL BREAKDOWN")
            lines.append("-" * 70)
            for model_name, m in sorted(model_totals.items()):
                src_tag = "/".join(sorted(m["sources"]))
                lines.append(f"  {model_name}")
                lines.append(
                    f"    calls={m['calls']:,}  prompt={m['prompt_tokens']:,}  "
                    f"completion={m['completion_tokens']:,}  cost=${m['cost_usd']:.8f}  [{src_tag}]"
                )
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
    # Model management
    # ------------------------------------------------------------------

    def _load_models(self, models_file: str) -> list[str]:
        """Load model names from a text file, ignoring comments and empty lines."""
        models: list[str] = []
        try:
            with open(models_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
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

    def get_random_model(self) -> str:
        """Select a random model from the loaded list."""
        selected_model = random.choice(self.models)
        print(Fore.CYAN + f"Selected model: {selected_model}" + Style.RESET_ALL)
        return selected_model

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def load_prompt(prompt_path: str) -> str:
        with open(prompt_path, "r", encoding="utf-8") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # Internal completion helper
    # ------------------------------------------------------------------

    def _complete(
        self,
        model_name: str,
        system_message: str,
        user_message: str,
    ) -> str:
        """Send a chat completion, record accurate billing, and return the reply."""
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
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
                response = self.client.chat.completions.create(
                    model=search_model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt},
                    ],
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

                # Record cost for this call
                prompt_tokens, completion_tokens, cost_from_response = self._extract_usage(response)
                self._record_call(
                    model_name=search_model,
                    generation_id=response.id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_from_response=cost_from_response,
                )

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