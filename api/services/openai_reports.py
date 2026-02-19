"""OpenAI-backed text generation for monthly reports.

- Uses the Responses API over raw HTTPS (no SDK dependency).
- If OPENAI_API_KEY is not set, functions return None.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests


def _get_api_key() -> Optional[str]:
    return os.getenv("OPENAI_API_KEY")


def generate_llm_sections(
    *,
    month: str,
    threshold_price: int,
    channel: str,
    crawl_schedule: str,
    platforms: list[str],
    seller_metrics: list[dict],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    api_key = _get_api_key()
    if not api_key:
        return None

    model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "executive_summary": {"type": "string"},
            "seller_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "seller_name_std": {"type": "string"},
                        "platform": {"type": "string"},
                        "recommended_sentence": {"type": "string"},
                        "caution_sentence": {"type": "string"},
                    },
                    "required": [
                        "seller_name_std",
                        "platform",
                        "recommended_sentence",
                        "caution_sentence",
                    ],
                },
            },
            "patterns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "evidence_sellers": {"type": "array", "items": {"type": "string"}},
                        "caution": {"type": "string"},
                    },
                    "required": ["title", "description", "evidence_sellers", "caution"],
                },
            },
            "data_quality_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["executive_summary", "seller_recommendations", "patterns", "data_quality_notes"],
    }

    system_rules = (
        "You are writing a monthly internal report for price monitoring.\n"
        "Hard rules:\n"
        "1) Do NOT recalculate or change any numbers. Use numbers exactly as given.\n"
        "2) Do NOT claim any definitive cause. Use cautious language and always include 'within the observed range'.\n"
        "3) Every recommendation sentence MUST include a number and a timestamp from the input (min price/time or last below time).\n"
        "4) Mention uncertainty explicitly when needed.\n"
        "5) Output must be valid JSON that matches the given JSON schema.\n"
    )

    user_payload = {
        "month": month,
        "threshold": threshold_price,
        "crawl_schedule": crawl_schedule,
        "platforms": platforms,
        "channel": channel,
        "seller_metrics": seller_metrics,
    }

    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_rules},
            {
                "role": "user",
                "content": "Generate the LLM sections for the report using ONLY the provided JSON input.\n\nINPUT JSON:\n"
                + json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "strict": True,
                "schema": schema,
            }
        },
    }

    resp = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    output_text = data.get("output_text")
    if not output_text:
        for item in data.get("output", []) or []:
            if item.get("type") == "output_text":
                output_text = item.get("text")
                break

    if not output_text:
        return None

    return json.loads(output_text)
