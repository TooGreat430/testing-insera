import json
from pathlib import Path

from row import ROW_SYSTEM_INSTRUCTION
from total import TOTAL_SYSTEM_INSTRUCTION
from container import CONTAINER_SYSTEM_INSTRUCTION
from detail import build_header_prompt, build_index_prompt, build_detail_prompt_from_index

PROMPT_FILE = Path("optimized_prompts.json")


def _load_optimized():
    if not PROMPT_FILE.exists():
        return {}
    return json.loads(PROMPT_FILE.read_text(encoding="utf-8"))


_OPT = _load_optimized()


def get_row_prompt() -> str:
    return _OPT.get("row", {}).get("optimized_prompt", ROW_SYSTEM_INSTRUCTION)


def get_header_prompt() -> str:
    return _OPT.get("header", {}).get("optimized_prompt", build_header_prompt())


def get_index_prompt(total_row: int) -> str:
    # fallback ke prompt asli dinamis
    if "index_template" not in _OPT:
        return build_index_prompt(total_row)

    template = _OPT["index_template"]["optimized_prompt"]
    return template.replace("5", str(total_row), 1)


def get_detail_prompt(total_row: int, index_slice: list, first_index: int, last_index: int) -> str:
    # untuk tahap awal, paling aman tetap gunakan builder asli
    # karena prompt ini mengandung anchor JSON runtime
    return build_detail_prompt_from_index(
        total_row=total_row,
        index_slice=index_slice,
        first_index=first_index,
        last_index=last_index,
    )


def get_total_prompt() -> str:
    return _OPT.get("total", {}).get("optimized_prompt", TOTAL_SYSTEM_INSTRUCTION)


def get_container_prompt() -> str:
    return _OPT.get("container", {}).get("optimized_prompt", CONTAINER_SYSTEM_INSTRUCTION)