#!/usr/bin/env python3
"""E15 unit test — LLMAnalyzer.write_summary_json() produces valid JSON
matching the STATISTICS_SPEC v1.3 §R8 schema."""

import json
import tempfile
from pathlib import Path

from llm_query import LLMAnalyzer, CallRecord


def test_write_summary_json():
    # Create analyzer with dummy key (we won't call the API)
    import os
    os.environ["ROUTER_API_KEY"] = "sk-test-fake-key-for-e15-unit-test"

    analyzer = LLMAnalyzer(temperature=0.5, top_p=0.9)

    # Manually populate call_records (bypass API)
    analyzer.call_records = [
        CallRecord(
            model="google/gemini-2.5-flash",
            prompt_tokens=1000,
            completion_tokens=50,
            cost_usd=0.000325,
            source="openrouter",
            latency_s=0.5,
            temperature=0.5,
            top_p=0.9,
            model_version="google/gemini-2.5-flash-preview-05-20",
        ),
        CallRecord(
            model="google/gemini-2.5-flash",
            prompt_tokens=2000,
            completion_tokens=100,
            cost_usd=0.000650,
            source="openrouter",
            latency_s=1.2,
            temperature=0.5,
            top_p=0.9,
            model_version="google/gemini-2.5-flash-preview-05-20",
        ),
        CallRecord(
            model="openai/gpt-4o-mini",
            prompt_tokens=500,
            completion_tokens=30,
            cost_usd=0.000095,
            source="estimate",
            latency_s=0.8,
            temperature=0.5,
            top_p=0.9,
            model_version="openai/gpt-4o-mini-2024-07-18",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        pdf_path = Path("/fake/path/NIST.SP.800-207.pdf")

        category_results = {
            "Cloud Computing": {
                "occurrences_found": 12,
                "significant_paragraphs": 8,
                "model_versions_used": ["google/gemini-2.5-flash-preview-05-20"],
            },
            "Zero Trust": {
                "occurrences_found": 5,
                "significant_paragraphs": 3,
            },
        }

        result_path = analyzer.write_summary_json(
            output_dir=output_dir,
            pdf_path=pdf_path,
            run_id="2026-06-15_14-32-01",
            model_requested="google/gemini-2.5-flash",
            category_results=category_results,
            significant_paragraphs_count=11,
        )

        # Verify file exists
        assert result_path.exists(), f"Summary JSON not written: {result_path}"
        assert result_path.name == "NIST.SP.800-207_summary.json"

        # Parse JSON
        with open(result_path) as f:
            data = json.load(f)

        # Verify all required fields per spec §R8
        required_fields = [
            "run_id", "pdf_file", "model_requested", "temperature",
            "top_p", "total_api_calls", "total_prompt_tokens",
            "total_completion_tokens", "total_cost_usd", "cost_source",
            "latency", "significant_paragraphs_count",
            "categories_found", "category_results", "model_versions",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        # Verify values
        assert data["run_id"] == "2026-06-15_14-32-01"
        assert data["pdf_file"] == "NIST.SP.800-207.pdf"
        assert data["model_requested"] == "google/gemini-2.5-flash"
        assert data["temperature"] == 0.5
        assert data["top_p"] == 0.9
        assert data["total_api_calls"] == 3
        assert data["total_prompt_tokens"] == 3500
        assert data["total_completion_tokens"] == 180
        assert abs(data["total_cost_usd"] - 0.00107) < 1e-6
        assert data["cost_source"] == "openrouter"  # 2 of 3 calls
        assert data["significant_paragraphs_count"] == 11
        assert data["categories_found"] == 2

        # Verify latency block
        lat = data["latency"]
        assert lat["count"] == 3
        assert lat["min_s"] == 0.5
        assert lat["max_s"] == 1.2
        assert abs(lat["mean_s"] - 0.833) < 0.001
        assert "p50_s" in lat  # 3 >= 2

        # Verify category_results
        cr = data["category_results"]
        assert "Cloud Computing" in cr
        assert cr["Cloud Computing"]["occurrences_found"] == 12
        assert cr["Cloud Computing"]["significant_paragraphs"] == 8
        assert "Zero Trust" in cr

        # Verify model_versions
        mv = data["model_versions"]
        assert "google/gemini-2.5-flash-preview-05-20" in mv
        assert mv["google/gemini-2.5-flash-preview-05-20"] == 2
        assert "openai/gpt-4o-mini-2024-07-18" in mv
        assert mv["openai/gpt-4o-mini-2024-07-18"] == 1

        # Verify all numeric values are numeric types (not str)
        for key in ["total_api_calls", "total_prompt_tokens", "total_completion_tokens",
                     "significant_paragraphs_count", "categories_found"]:
            assert isinstance(data[key], (int, float)), f"{key} is {type(data[key])}"

    print("E15 unit test: PASS")


if __name__ == "__main__":
    test_write_summary_json()
