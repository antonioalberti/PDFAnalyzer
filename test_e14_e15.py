#!/usr/bin/env python3
"""E14+E15 unit test — verify write_summary_json output placement and schema.

E14: summary JSON is written inside the Results/<timestamp>/ directory,
     matching the R7 convention.
E15: summary JSON matches the STATISTICS_SPEC v1.3 §R8 schema,
     all required fields present, all numeric values are numeric types.
"""

import json
import tempfile
from pathlib import Path

from llm_query import LLMAnalyzer, CallRecord


def _make_analyzer_with_records(temp=1.0, top_p=1.0):
    """Create an LLMAnalyzer with pre-populated call_records (no API calls)."""
    import os
    os.environ.setdefault("ROUTER_API_KEY", "sk-test")
    analyzer = LLMAnalyzer(temperature=temp, top_p=top_p)
    analyzer.call_records = [
        CallRecord(
            model="google/gemini-2.5-flash",
            prompt_tokens=1000,
            completion_tokens=50,
            cost_usd=0.000325,
            source="openrouter",
            latency_s=0.5,
            temperature=temp,
            top_p=top_p,
            model_version="google/gemini-2.5-flash-preview-05-20",
        ),
        CallRecord(
            model="google/gemini-2.5-flash",
            prompt_tokens=2000,
            completion_tokens=100,
            cost_usd=0.000650,
            source="openrouter",
            latency_s=1.2,
            temperature=temp,
            top_p=top_p,
            model_version="google/gemini-2.5-flash-preview-05-20",
        ),
        CallRecord(
            model="openai/gpt-4o-mini",
            prompt_tokens=500,
            completion_tokens=30,
            cost_usd=0.000095,
            source="estimate",
            latency_s=0.8,
            temperature=temp,
            top_p=top_p,
            model_version="openai/gpt-4o-mini-2024-07-18",
        ),
    ]
    return analyzer


def test_e14_output_dir_placement():
    """E14: Summary JSON is written inside <source>/Results/<timestamp>/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = Path(tmpdir)
        # Simulate the R7 Results directory structure
        results_dir = source_dir / "Results" / "2026-06-15_14-32-01"
        results_dir.mkdir(parents=True, exist_ok=True)

        analyzer = _make_analyzer_with_records()
        pdf_path = Path("/fake/source/NIST.SP.800-207.pdf")

        result_path = analyzer.write_summary_json(
            output_dir=results_dir,
            pdf_path=pdf_path,
            run_id="2026-06-15_14-32-01",
            model_requested="google/gemini-2.5-flash",
        )

        # E14 check: file is inside the Results/<timestamp>/ directory
        assert results_dir in result_path.parents or result_path.parent == results_dir, \
            f"Summary JSON not in Results dir: {result_path} not under {results_dir}"
        assert result_path.name == "NIST.SP.800-207_summary.json"

        # Verify no stray file in the PDF's parent directory
        pdf_parent_files = list(Path("/fake/source/").glob("*_summary.json"))
        assert len(pdf_parent_files) == 0, "Leaked summary JSON to PDF parent dir"

    print("E14: PASS — summary JSON written inside Results/<timestamp>/")


def test_e15_schema_and_values():
    """E15: Summary JSON matches STATISTICS_SPEC v1.3 §R8 schema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        pdf_path = Path("/fake/path/NIST.SP.800-207.pdf")

        analyzer = _make_analyzer_with_records(temp=0.5, top_p=0.9)

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

        assert result_path.exists()
        with open(result_path) as f:
            data = json.load(f)

        # Required fields per spec §R8
        required_fields = [
            "run_id", "pdf_file", "model_requested", "temperature",
            "top_p", "total_api_calls", "total_prompt_tokens",
            "total_completion_tokens", "total_cost_usd", "cost_source",
            "latency", "significant_paragraphs_count",
            "categories_found", "category_results", "model_versions",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Value checks
        assert data["run_id"] == "2026-06-15_14-32-01"
        assert data["pdf_file"] == "NIST.SP.800-207.pdf"
        assert data["model_requested"] == "google/gemini-2.5-flash"
        assert data["temperature"] == 0.5
        assert data["top_p"] == 0.9
        assert data["total_api_calls"] == 3
        assert data["total_prompt_tokens"] == 3500
        assert data["total_completion_tokens"] == 180
        assert abs(data["total_cost_usd"] - 0.00107) < 1e-6
        assert data["cost_source"] == "openrouter"
        assert data["significant_paragraphs_count"] == 11
        assert data["categories_found"] == 2

        # Latency block
        lat = data["latency"]
        assert lat["count"] == 3
        assert lat["min_s"] == 0.5
        assert lat["max_s"] == 1.2
        assert abs(lat["mean_s"] - 0.833) < 0.001
        assert "p50_s" in lat

        # category_results structure
        cr = data["category_results"]
        assert cr["Cloud Computing"]["occurrences_found"] == 12
        assert cr["Cloud Computing"]["significant_paragraphs"] == 8
        assert cr["Zero Trust"]["occurrences_found"] == 5

        # model_versions
        mv = data["model_versions"]
        assert mv["google/gemini-2.5-flash-preview-05-20"] == 2
        assert mv["openai/gpt-4o-mini-2024-07-18"] == 1

        # All numeric values are numeric types (not strings)
        for key in ["total_api_calls", "total_prompt_tokens", "total_completion_tokens",
                     "significant_paragraphs_count", "categories_found"]:
            assert isinstance(data[key], (int, float)), f"{key} is {type(data[key])}, not numeric"

        # Latency sub-values are also numeric
        for lk in ["min_s", "max_s", "mean_s", "p50_s"]:
            if lk in lat:
                assert isinstance(lat[lk], (int, float)), f"latency.{lk} is {type(lat[lk])}"

    print("E15: PASS — summary JSON schema and values verified")


def test_e15_minimal():
    """E15: Minimal call (no category_results, no significant_paragraphs_count)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        analyzer = _make_analyzer_with_records()
        pdf_path = Path("/fake/test.pdf")

        result_path = analyzer.write_summary_json(
            output_dir=output_dir,
            pdf_path=pdf_path,
            run_id="2026-06-15_10-00-00",
            model_requested=None,  # "random" default
        )

        with open(result_path) as f:
            data = json.load(f)

        assert data["model_requested"] == "random"
        # Optional fields should be absent when not provided
        assert "significant_paragraphs_count" not in data
        assert "categories_found" not in data
        assert "category_results" not in data
        # Core fields still present
        assert "latency" in data
        assert "model_versions" in data
        assert data["total_api_calls"] == 3

    print("E15 minimal: PASS")


if __name__ == "__main__":
    test_e14_output_dir_placement()
    test_e15_schema_and_values()
    test_e15_minimal()
    print("\nAll E14+E15 tests passed.")
