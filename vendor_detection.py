import os
import re
from difflib import SequenceMatcher
import importlib.util
from pathlib import Path

VENDOR_LIST = [
    "jht_carbon",
    "jht",
    "tangsan_jinhengtong",
    "joy",
    "kunshan_landon",
    "shimano_inc",
    "novatec",
    "suntour_shenzhen",
    "suntour_vietnam",
    "bafang_motor",
    "ningbo_fordario",
    "ningbo_julong",
    "jiangsiu_huajiu",
    "fox",
    "haomeng",
    "to_ho",
    "velo_kunshan",
    "velo_enterprise",
    "shimano_singapore",
    "liow_ko",
    "auriga",
    "hl_shenzhen",
]

VENDOR_DISPLAY_NAME_MAP = {
    "jht_carbon": "JHT Carbon",
    "jht": "JHT",
    "tangsan_jinhengtong": "Tangsan Jinhengtong",
    "joy": "Joy",
    "kunshan_landon": "Kunshan Landon",
    "shimano_inc": "Shimano Inc",
    "novatec": "Novatec",
    "suntour_shenzhen": "Suntour Shenzhen",
    "suntour_vietnam": "Suntour Vietnam",
    "bafang_motor": "Bafang Motor",
    "ningbo_fordario": "Ningbo Fordario",
    "ningbo_julong": "Ningbo Julong",
    "jiangsiu_huajiu": "Jiangsiu Huajiu",
    "fox": "Fox",
    "haomeng": "Haomeng",
    "to_ho": "To Ho",
    "velo_kunshan": "Velo Kunshan",
    "velo_enterprise": "Velo Enterprise",
    "shimano_singapore": "Shimano Singapore",
    "liow_ko": "Liow Ko",
    "auriga": "Auriga",
    "hl_shenzhen": "HL Shenzhen",
}

BASE_DIR = Path(__file__).resolve().parent
VENDOR_PROMPT_DIR = Path(
    os.getenv("VENDOR_PROMPT_DIR", str(BASE_DIR / "vendor_prompt"))
)


def normalize_vendor_id(vendor_id: str) -> str:
    vendor_id = str(vendor_id or "").strip().lower()
    if vendor_id in VENDOR_LIST:
        return vendor_id
    return "default"


def get_vendor_display_name(vendor_id: str) -> str:
    vendor_id = normalize_vendor_id(vendor_id)
    return VENDOR_DISPLAY_NAME_MAP.get(
        vendor_id,
        str(vendor_id).replace("_", " ").strip().title()
    )


def _normalize_search_text(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _compact_search_text(value: str) -> str:
    return _normalize_search_text(value).replace(" ", "")


def _build_vendor_search_candidates(vendor_id: str) -> list:
    label = get_vendor_display_name(vendor_id)
    parts = [
        label,
        vendor_id,
        label.replace(" ", ""),
        vendor_id.replace("_", " "),
        vendor_id.replace("_", ""),
    ]

    seen = set()
    candidates = []
    for part in parts:
        normalized = _normalize_search_text(part)
        compact = _compact_search_text(part)
        for item in [normalized, compact]:
            if item and item not in seen:
                seen.add(item)
                candidates.append(item)

    return candidates


def _score_vendor_match(query: str, vendor_id: str) -> tuple:
    normalized_query = _normalize_search_text(query)
    compact_query = _compact_search_text(query)

    if not normalized_query:
        return (1, 1.0)

    best_bucket = -1
    best_ratio = 0.0

    for candidate in _build_vendor_search_candidates(vendor_id):
        ratio = SequenceMatcher(None, compact_query, candidate).ratio()
        bucket = 0

        if candidate == compact_query:
            bucket = 6
        elif candidate.startswith(compact_query):
            bucket = 5
        elif compact_query in candidate:
            bucket = 4
        else:
            candidate_tokens = candidate.split()
            if any(token.startswith(compact_query) for token in candidate_tokens):
                bucket = 3
            elif any(compact_query in token for token in candidate_tokens):
                bucket = 2
            elif ratio >= 0.45:
                bucket = 1

        if bucket > best_bucket or (bucket == best_bucket and ratio > best_ratio):
            best_bucket = bucket
            best_ratio = ratio

    return (best_bucket, best_ratio)


def search_vendor_options(query: str = "", include_default: bool = False, limit: int = 10) -> list:
    vendor_ids = list(VENDOR_LIST)
    if include_default:
        vendor_ids = ["default"] + vendor_ids

    normalized_query = _normalize_search_text(query)
    scored = []

    for vendor_id in vendor_ids:
        bucket, ratio = _score_vendor_match(normalized_query, vendor_id)
        if normalized_query and bucket < 1:
            continue

        scored.append((bucket, ratio, get_vendor_display_name(vendor_id), vendor_id))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2].lower()))
    return [vendor_id for _, _, _, vendor_id in scored[:limit]]


def _load_module_from_path(py_path: str):
    module_name = f"_vendor_prompt_{Path(py_path).stem}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)

    if spec is None or spec.loader is None:
        raise Exception(f"Gagal load module: {py_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_vendor_prompt_text(vendor_id: str) -> str:
    vendor_id = normalize_vendor_id(vendor_id)

    if vendor_id == "default":
        return ""

    py_path = VENDOR_PROMPT_DIR / f"{vendor_id}.py"
    if not py_path.exists():
        print(f"[VENDOR PROMPT] file tidak ditemukan untuk vendor_id={vendor_id} path={py_path}")
        return ""

    module = _load_module_from_path(str(py_path))

    for attr_name in dir(module):
        if attr_name.endswith("_PROMPT"):
            value = getattr(module, attr_name)
            if isinstance(value, str) and value.strip():
                print(f"[VENDOR PROMPT] loaded constant={attr_name} vendor_id={vendor_id}")
                return value.strip()

    print(f"[VENDOR PROMPT] tidak ada *_PROMPT yang valid untuk vendor_id={vendor_id}")
    return ""