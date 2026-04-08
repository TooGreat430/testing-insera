import json
from pathlib import Path

import vertexai

from row import ROW_SYSTEM_INSTRUCTION
from total import TOTAL_SYSTEM_INSTRUCTION
from container import CONTAINER_SYSTEM_INSTRUCTION
from detail import build_header_prompt, build_index_prompt, build_detail_prompt_from_index

PROJECT_ID = "import-document-automation"
OPTIMIZER_LOCATION = "us-central1"

OUT_PATH = Path("optimized_prompts.json")


def _extract_suggested_prompt(response) -> str:
    parsed = getattr(response, "parsed_response", None)
    if parsed and getattr(parsed, "suggested_prompt", None):
        return parsed.suggested_prompt

    raw = getattr(response, "raw_text_response", None)
    if raw:
        return raw

    raise RuntimeError("Optimizer response tidak mengandung suggested prompt.")


def build_prompt_sources():
    return {
        "row": ROW_SYSTEM_INSTRUCTION,
        "header": build_header_prompt(),
        "index_template": build_index_prompt(total_row=5),
        "detail_template": build_detail_prompt_from_index(
            total_row=5,
            index_slice=[
                {
                    "idx": 1,
                    "inv_page_no": 1,
                    "inv_customer_po_no": "{{inv_customer_po_no}}",
                    "inv_spart_item_no": "{{inv_spart_item_no}}",
                    "inv_description": "{{inv_description}}",
                    "inv_quantity": 1,
                    "inv_quantity_unit": "{{inv_quantity_unit}}",
                    "inv_unit_price": 1,
                    "inv_price_unit": "{{inv_price_unit}}",
                    "inv_amount": 1,
                    "pl_page_no": 1,
                    "pl_customer_po_no": "{{pl_customer_po_no}}",
                    "pl_description": "{{pl_description}}",
                    "pl_quantity": 1,
                }
            ],
            first_index=1,
            last_index=5,
        ),
        "total": TOTAL_SYSTEM_INSTRUCTION,
        "container": CONTAINER_SYSTEM_INSTRUCTION,
    }


def main():
    client = vertexai.Client(project=PROJECT_ID, location=OPTIMIZER_LOCATION)

    original_prompts = build_prompt_sources()
    optimized = {}

    for name, prompt in original_prompts.items():
        print(f"Optimizing: {name}")
        response = client.prompt_optimizer.optimize_prompt(prompt=prompt)
        optimized[name] = {
            "original_prompt": prompt,
            "optimized_prompt": _extract_suggested_prompt(response),
        }

    OUT_PATH.write_text(
        json.dumps(optimized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()