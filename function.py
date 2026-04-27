import io 
import json 
import re 
import tempfile 
import os 
import csv 
import subprocess 
import ijson 
from urllib.parse import urlparse 
from google.cloud import storage 
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from google import genai 
from google.genai import types 
import time
import random
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import * 
from total import TOTAL_SYSTEM_INSTRUCTION 
from container import CONTAINER_SYSTEM_INSTRUCTION
from pathlib import Path
import shutil
from detail import (
    build_index_prompt,
    build_header_prompt,
    build_detail_prompt_from_index,
    HEADER_SCHEMA_TEXT as HEADER_FIELDS,      # header keys
    DETAIL_LINE_SCHEMA_TEXT,
    DETAIL_LINE_FIELDS,
    DETAIL_LINE_NUM_FIELDS,
    DETAIL_CSV_FIELD_ORDER_FINAL
)
from row import ROW_SYSTEM_INSTRUCTION 
import uuid
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import pymupdf as fitz
from vendor_detection import (
    load_vendor_prompt_text,
    normalize_vendor_id,
)

BATCH_SIZE = 30
DETAIL_GEMINI_RECHECK_BATCH_SIZE = int(os.getenv("DETAIL_GEMINI_RECHECK_BATCH_SIZE", "30"))

DETAIL_RECHECK_SCHEMA = {
    "inv_gw_unit": "string",
    "inv_quantity": "number",
    "inv_quantity_unit": "string",
    "inv_unit_price": "number",
    "inv_amount": "number",

    "pl_quantity": "number",
    "pl_package_count": "number",
    "pl_nw": "number",
    "pl_gw": "number",
    "pl_volume": "number",
}
DETAIL_RECHECK_FIELDS = list(DETAIL_RECHECK_SCHEMA.keys())
DETAIL_RECHECK_NUM_FIELDS = {
    k for k, v in DETAIL_RECHECK_SCHEMA.items()
    if str(v).strip().lower() == "number"
}

CBM_TO_CUFT = 35.3147

storage_client = storage.Client() 
genai_client = genai.Client( vertexai=True, project=PROJECT_ID, location="global", )

# ==============================
# SANITIZER: pl_package_unit
# ==============================

PL_PACKAGE_UNIT_MAP = {
    "ctn": "CT",
    "ctns": "CT",
    "carton": "CT",
    "cartons": "CT",
    "ct": "CT",

    "plt": "PX",
    "plts": "PX",
    "pallet": "PX",
    "pallets": "PX",

    "bal": "BL",
    "bale": "BL",
    "bales": "BL",

    "pxct": "PK",
    "packages": "PK"
}

TOTAL_OUTPUT_FIELDS = [
    "inv_quantity",
    "inv_amount",
    "inv_total_quantity",
    "inv_total_amount",
    "inv_total_nw",
    "inv_total_gw",
    "inv_total_volume",
    "inv_total_package",

    "pl_package_unit",
    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",
    "pl_total_quantity",
    "pl_total_amount",
    "pl_total_nw",
    "pl_total_gw",
    "pl_total_volume",
    "pl_total_package",

    "bl_shipper_name",
    "bl_shipper_address",
    "bl_no",
    "bl_date",
    "bl_consignee_name",
    "bl_consignee_address",
    "bl_consignee_tax_id",
    "bl_seller_name",
    "bl_seller_address",
    "bl_lc_number",
    "bl_notify_party",
    "bl_vessel",
    "bl_voyage_no",
    "bl_port_of_loading",
    "bl_port_of_destination",
    "bl_gw_unit",
    "bl_gw",
    "bl_volume_unit",
    "bl_volume",
    "bl_package_count",
    "bl_package_unit",
]

# saya append match fields di belakang supaya flow validasi existing tetap konsisten
TOTAL_CSV_FIELD_ORDER_FINAL = [
    "match_score",
    "match_description",
] + TOTAL_OUTPUT_FIELDS

TOTAL_NUM_FIELDS = {
    "inv_quantity",
    "inv_amount",
    "inv_total_quantity",
    "inv_total_amount",
    "inv_total_nw",
    "inv_total_gw",
    "inv_total_volume",
    "inv_total_package",

    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",
    "pl_total_quantity",
    "pl_total_amount",
    "pl_total_nw",
    "pl_total_gw",
    "pl_total_volume",
    "pl_total_package",

    "bl_gw",
    "bl_volume",
    "bl_package_count",
}

# ==============================
# SANITIZER: generic quantity/unit normalizer
# ==============================

UNIT_CONVERSION_MAP = {
    "PCS": "PC",
    "PCE": "PC",
    "PIECE": "PC",
    "PIECES": "PC",
    "H87": "PC",

    "SETS": "SET",

    "NPR": "PRS",
    "PAIRS": "PRS",

    "GROSS": "GRO",

    "BTL": "BT",
    "BOT": "BT",

    "KGS": "KG",
    "KGM": "KG",

    "DRM": "DR",
    "DRUM": "DR",

    "BAREL": "BLL",
    "BARREL": "BLL",
}

TOTAL_DETAIL_AGG_FIELDS = [
    "inv_total_quantity",
    "inv_total_amount",
    "inv_total_nw",
    "inv_total_gw",
    "inv_total_volume",
    "inv_total_package",

    "pl_total_quantity",
    "pl_total_amount",
    "pl_total_nw",
    "pl_total_gw",
    "pl_total_volume",
    "pl_total_package",
]

def _get_detail_total_group_key(row: dict, row_index: int) -> str:
    """
    Group key untuk agregasi total per invoice.
    Prioritas: inv_invoice_no -> pl_invoice_no -> coo_invoice_no -> coo_no
    """
    if not isinstance(row, dict):
        return f"__ROW_{row_index + 1}"

    candidate_keys = [
        "inv_invoice_no",
        "pl_invoice_no",
        "coo_invoice_no",
        "coo_no",
    ]

    for key in candidate_keys:
        normalized = _preprocess_invoice_no_for_grouping(row.get(key))
        if normalized:
            return normalized

    return f"__ROW_{row_index + 1}"


def _pick_best_total_value(existing_value, candidate_value):
    """
    Untuk 1 invoice yang sama, field total sering terulang di setiap row.
    Kita pilih satu nilai terbaik:
    - abaikan null
    - kalau existing kosong, pakai candidate
    - kalau dua-duanya ada, ambil nilai dengan magnitude lebih besar
      supaya row 0/null kalah oleh row yang berisi total sebenarnya
    """
    existing_num = _to_float(existing_value)
    candidate_num = _to_float(candidate_value)

    if candidate_num is None:
        return existing_num

    if existing_num is None:
        return candidate_num

    if abs(candidate_num) > abs(existing_num):
        return candidate_num

    return existing_num


def _aggregate_total_fields_from_detail_rows(detail_rows: list) -> dict:
    """
    Agregasi field-field yang mengandung 'total':
    - dedup dulu per invoice
    - lalu sum antar invoice

    Kenapa tidak langsung sum semua row?
    Karena untuk invoice yang sama, nilai inv_total_xx / pl_total_xx
    biasanya terulang di banyak line item. Kalau langsung dijumlahkan
    semua row, hasilnya akan overcount.
    """
    grouped_totals = {}

    for idx, row in enumerate(detail_rows or []):
        if not isinstance(row, dict):
            continue

        group_key = _get_detail_total_group_key(row, idx)

        if group_key not in grouped_totals:
            grouped_totals[group_key] = {
                field: None for field in TOTAL_DETAIL_AGG_FIELDS
            }

        for field in TOTAL_DETAIL_AGG_FIELDS:
            grouped_totals[group_key][field] = _pick_best_total_value(
                grouped_totals[group_key].get(field),
                row.get(field)
            )

    aggregated = {field: 0.0 for field in TOTAL_DETAIL_AGG_FIELDS}

    for _, invoice_bucket in grouped_totals.items():
        for field in TOTAL_DETAIL_AGG_FIELDS:
            value = _to_float(invoice_bucket.get(field))
            if value is not None:
                aggregated[field] += value

    return aggregated

TOTAL_CONTRIBUTION_EPS = float(
    os.getenv("TOTAL_CONTRIBUTION_EPS", "0.01")
)

TOTAL_CONTRIBUTION_STRONG_RATIO = float(
    os.getenv("TOTAL_CONTRIBUTION_STRONG_RATIO", "0.70")
)

TOTAL_CONTRIBUTION_TOP2_RATIO = float(
    os.getenv("TOTAL_CONTRIBUTION_TOP2_RATIO", "0.85")
)


def _group_rows_by_invoice_no(rows: list):
    grouped = {}

    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue

        group_key = _get_detail_total_group_key(row, idx)
        grouped.setdefault(group_key, []).append(row)

    return grouped


def _get_declared_total_from_group_rows(group_rows: list, declared_field: str):
    best_value = None

    for row in group_rows:
        if not isinstance(row, dict):
            continue

        best_value = _pick_best_total_value(
            best_value,
            row.get(declared_field)
        )

    return _to_float(best_value)


def _get_total_contribution_specs():
    return [
        {
            "name": "invoice_total_quantity",
            "row_field": "inv_quantity",
            "declared_field": "inv_total_quantity",
            "label": "Invoice: total_quantity mismatch",
        },
        {
            "name": "invoice_total_amount",
            "row_field": "inv_amount",
            "declared_field": "inv_total_amount",
            "label": "Invoice: total_amount mismatch",
        },
        {
            "name": "packing_total_quantity",
            "row_field": "pl_quantity",
            "declared_field": "pl_total_quantity",
            "label": "PackingList: total_quantity mismatch",
        },
        {
            "name": "packing_total_package",
            "row_field": "pl_package_count",
            "declared_field": "pl_total_package",
            "label": "PackingList: total_package mismatch",
        },
        {
            "name": "packing_total_nw",
            "row_field": "pl_nw",
            "declared_field": "pl_total_nw",
            "label": "PackingList: total_nw mismatch",
        },
        {
            "name": "packing_total_gw",
            "row_field": "pl_gw",
            "declared_field": "pl_total_gw",
            "label": "PackingList: total_gw mismatch",
        },
        {
            "name": "packing_total_volume",
            "row_field": "pl_volume",
            "declared_field": "pl_total_volume",
            "label": "PackingList: total_volume mismatch",
        },
    ]


def _get_row_total_contribution_ratio(row: dict, spec: dict, gap: float):
    row_field = spec["row_field"]
    eps = float(TOTAL_CONTRIBUTION_EPS)

    row_value = _to_float(row.get(row_field))
    best_ratio = 0.0
    best_reason = None

    if row_value is None or abs(gap) <= eps:
        return best_ratio, best_reason, row_value

    # =========================================================
    # SKENARIO 1:
    # row dihapus dari sum
    # Cocok untuk duplicate / merge-cell / over-total
    # =========================================================
    gap_after_remove = gap - row_value
    improvement_remove = abs(gap) - abs(gap_after_remove)

    if improvement_remove > 0:
        ratio_remove = min(1.0, improvement_remove / abs(gap))
        best_ratio = ratio_remove
        best_reason = "remove_row_value"

    # =========================================================
    # SKENARIO 2:
    # row dikoreksi sebesar gap
    # Cocok untuk salah ekstrak row-level:
    # contoh 1266.789 -> 1264.45 karena gap = 2.339
    # corrected_value = row_value - gap
    # =========================================================
    corrected_value = row_value - gap

    plausible_adjust = True

    # tidak boleh jadi negatif
    if corrected_value < -eps:
        plausible_adjust = False

    # gap tidak boleh terlalu besar dibanding nilai row
    # supaya tidak terlalu agresif
    correction_share = abs(gap) / max(abs(row_value), eps)
    if correction_share > 0.35:
        plausible_adjust = False

    # sanity check untuk NW/GW
    if plausible_adjust and row_field == "pl_gw":
        nw = _to_float(row.get("pl_nw"))
        if nw is not None and corrected_value + eps < nw:
            plausible_adjust = False

    if plausible_adjust and row_field == "pl_nw":
        gw = _to_float(row.get("pl_gw"))
        if gw is not None and corrected_value - eps > gw:
            plausible_adjust = False

    if plausible_adjust:
        # makin kecil porsi koreksinya terhadap row_value,
        # makin kuat kandidatnya
        ratio_adjust = 1.0 - min(1.0, correction_share)

        if ratio_adjust > best_ratio:
            best_ratio = ratio_adjust
            best_reason = "adjust_row_by_gap"

    # =========================================================
    # SKENARIO 3:
    # khusus inv_amount -> koreksi pakai qty * unit_price
    # =========================================================
    if row_field == "inv_amount":
        qty = _to_float(row.get("inv_quantity"))
        unit_price = _to_float(row.get("inv_unit_price"))
        amount = _to_float(row.get("inv_amount"))

        if qty is not None and unit_price is not None and amount is not None:
            recomputed_amount = qty * unit_price
            delta = recomputed_amount - amount
            gap_after_recompute = gap + delta
            improvement_recompute = abs(gap) - abs(gap_after_recompute)

            if improvement_recompute > 0:
                ratio_recompute = min(1.0, improvement_recompute / abs(gap))
                if ratio_recompute > best_ratio:
                    best_ratio = ratio_recompute
                    best_reason = "recompute_inv_amount"

    return best_ratio, best_reason, row_value


def _append_total_contribution_error(
    row: dict,
    label: str,
    invoice_group: str,
    actual_sum: float,
    declared_total: float,
    gap: float,
    contribution_ratio: float,
    reason: str,
    row_value,
):
    row_value_text = "null" if row_value is None else row_value
    _append_err(
        row,
        f"{label} for invoice_no={invoice_group} "
        f"(sum {actual_sum}, doc {declared_total}, gap {gap}); "
        f"suspected_row_contribution={round(contribution_ratio, 4)} "
        f"reason={reason} row_value={row_value_text}"
    )


def _safe_row_no_int(row: dict):
    try:
        return int(row.get("_detail_row_no"))
    except Exception:
        return None

def _apply_selected_total_culprits(
    selected_candidates: list,
    spec: dict,
    invoice_group: str,
    actual_sum: float,
    declared_total: float,
    gap: float,
    culprit_row_nos: set,
    culprit_groups: set,
):
    added_any = False

    for cand in selected_candidates or []:
        _append_total_contribution_error(
            row=cand["row"],
            label=spec["label"],
            invoice_group=invoice_group,
            actual_sum=actual_sum,
            declared_total=declared_total,
            gap=gap,
            contribution_ratio=float(cand.get("ratio", 0.0) or 0.0),
            reason=str(cand.get("reason") or "total_culprit"),
            row_value=cand.get("row_value"),
        )

        row_no = cand.get("row_no")
        if row_no is not None:
            culprit_row_nos.add(row_no)
            added_any = True

    if added_any:
        culprit_groups.add(invoice_group)

    return added_any


def _select_greedy_multi_row_candidates(candidates: list, gap: float, eps: float, max_rows: int = 5):
    """
    Cocok untuk kasus duplicate / merge-cell / total berlebih yang culprit-nya > 2 row.
    Hanya pakai candidate remove_row_value.
    """
    remove_candidates = [
        c for c in (candidates or [])
        if c.get("reason") == "remove_row_value" and _to_float(c.get("row_value")) is not None
    ]

    if len(remove_candidates) < 2:
        return []

    selected = []
    remaining_gap = gap

    for cand in remove_candidates:
        if len(selected) >= max_rows:
            break

        row_value = _to_float(cand.get("row_value"))
        if row_value is None:
            continue

        new_gap = remaining_gap - row_value

        # hanya ambil kalau removal row membuat gap lebih kecil
        if abs(new_gap) < abs(remaining_gap):
            selected.append(cand)
            remaining_gap = new_gap

        if abs(remaining_gap) <= eps:
            break

    if len(selected) < 2:
        return []

    original_abs_gap = max(abs(gap), eps)
    improvement_ratio = (abs(gap) - abs(remaining_gap)) / original_abs_gap

    # jangan terlalu agresif
    if improvement_ratio < 0.50:
        return []

    return selected


def _pick_most_influential_fallback(group_rows: list, spec: dict, gap: float):
    """
    Fallback untuk:
    - salah ekstrak tapi tidak ketemu exact culprit
    - missing extraction suspected
    - under-total / over-total yang tidak bisa dijelaskan oleh rule utama
    """
    best = None

    def _consider(candidate: dict):
        nonlocal best
        if not candidate:
            return
        if best is None or float(candidate["impact"]) > float(best["impact"]):
            best = candidate

    for row in group_rows or []:
        if not isinstance(row, dict):
            continue

        row_no = _safe_row_no_int(row)
        row_value = _to_float(row.get(spec["row_field"]))

        # fallback umum: row dengan magnitude paling besar
        if row_value is not None:
            _consider({
                "ratio": 0.0,
                "reason": "forced_absmax_fallback",
                "row_value": row_value,
                "row": row,
                "row_no": row_no,
                "impact": abs(row_value),
            })

        # fallback khusus inv_amount: delta dari qty * unit_price
        if spec["row_field"] == "inv_amount":
            qty = _to_float(row.get("inv_quantity"))
            unit_price = _to_float(row.get("inv_unit_price"))
            amount = _to_float(row.get("inv_amount"))

            if qty is not None and unit_price is not None and amount is not None:
                recomputed_amount = qty * unit_price
                delta = abs(recomputed_amount - amount)

                if delta > 0:
                    _consider({
                        "ratio": 0.0,
                        "reason": "forced_recompute_delta_fallback",
                        "row_value": amount,
                        "row": row,
                        "row_no": row_no,
                        "impact": delta,
                    })

    if best is None:
        return None

    best.pop("impact", None)
    return best

def _select_strong_row_correction_candidates(
    candidates: list,
    max_rows: int = 5,
    min_ratio: float = 0.85,
    relative_window: float = 0.03,
):
    """
    Prioritas untuk kasus salah ekstrak row-level:
    contoh:
    - hasil ekstrak 1266.789
    - seharusnya 1264.45
    - gap total = 2.339
    => row ini lebih masuk akal dikoreksi sebesar gap,
       bukan dihapus seluruh nilainya.

    Ambil 1..N candidate correction terkuat yang skornya masih dekat
    dengan top candidate.
    """
    correction_reasons = {
        "adjust_row_by_gap",
        "recompute_inv_amount",
    }

    correction_candidates = [
        c for c in (candidates or [])
        if c.get("reason") in correction_reasons
    ]

    if not correction_candidates:
        return []

    correction_candidates.sort(
        key=lambda x: float(x.get("ratio", 0.0) or 0.0),
        reverse=True
    )

    top_ratio = float(correction_candidates[0].get("ratio", 0.0) or 0.0)
    if top_ratio < min_ratio:
        return []

    selected = []
    seen_row_nos = set()

    for cand in correction_candidates:
        ratio = float(cand.get("ratio", 0.0) or 0.0)
        row_no = cand.get("row_no")

        if row_no is not None and row_no in seen_row_nos:
            continue

        if (top_ratio - ratio) > relative_window:
            break

        selected.append(cand)

        if row_no is not None:
            seen_row_nos.add(row_no)

        if len(selected) >= max_rows:
            break

    return selected

def _apply_total_contribution_scoring(rows: list):
    """
    Total mismatch attribution PER invoice_no.

    Return:
    {
        "total_issue_groups": set(...),
        "culprit_row_nos": set(...),
        "culprit_groups": set(...),
    }
    """
    total_issue_groups = set()
    culprit_row_nos = set()
    culprit_groups = set()

    grouped_rows = _group_rows_by_invoice_no(rows)

    eps = float(TOTAL_CONTRIBUTION_EPS)
    strong_ratio = float(TOTAL_CONTRIBUTION_STRONG_RATIO)
    top2_ratio = float(TOTAL_CONTRIBUTION_TOP2_RATIO)

    for invoice_group, group_rows in grouped_rows.items():
        for spec in _get_total_contribution_specs():
            declared_total = _get_declared_total_from_group_rows(
                group_rows,
                spec["declared_field"]
            )

            if declared_total is None:
                continue

            actual_sum = 0.0
            has_actual = False

            for row in group_rows:
                if not isinstance(row, dict):
                    continue

                value = _to_float(row.get(spec["row_field"]))
                if value is not None:
                    actual_sum += value
                    has_actual = True

            if not has_actual:
                continue

            if spec["declared_field"] == "pl_total_volume":
                if _volume_values_match_with_conversion(actual_sum, declared_total):
                    continue
            else:
                if abs(actual_sum - declared_total) <= eps:
                    continue

            gap = actual_sum - declared_total
            total_issue_groups.add(invoice_group)

            candidates = []

            for row in group_rows:
                if not isinstance(row, dict):
                    continue

                ratio, reason, row_value = _get_row_total_contribution_ratio(
                    row,
                    spec,
                    gap
                )

                if ratio <= 0:
                    continue

                candidates.append({
                    "ratio": ratio,
                    "reason": reason,
                    "row_value": row_value,
                    "row": row,
                    "row_no": _safe_row_no_int(row),
                })

            candidates.sort(key=lambda x: x["ratio"], reverse=True)

            # =========================================================
            # PRIORITAS 0:
            # salah ekstrak row-level (partial correction by gap)
            # diprioritaskan sebelum greedy duplicate removal
            # =========================================================
            correction_selected = _select_strong_row_correction_candidates(
                candidates=candidates,
                max_rows=min(5, max(1, len(group_rows))),
                min_ratio=max(0.85, strong_ratio),
                relative_window=0.03,
            )
            if correction_selected:
                correction_selected = [
                    {
                        **cand,
                        "reason": f"{cand.get('reason', 'adjust_row_by_gap')}_priority"
                    }
                    for cand in correction_selected
                ]

                _apply_selected_total_culprits(
                    correction_selected,
                    spec,
                    invoice_group,
                    actual_sum,
                    declared_total,
                    gap,
                    culprit_row_nos,
                    culprit_groups,
                )
                continue

            # =========================================================
            # PRIORITAS 1:
            # Kalau gap > 0, utamakan greedy multi-row dulu
            # untuk handle duplicate / merge-cell / total berlebih
            # =========================================================
            if gap > 0:
                greedy_selected = _select_greedy_multi_row_candidates(
                    candidates=candidates,
                    gap=gap,
                    eps=eps,
                    max_rows=min(5, max(2, len(group_rows)))
                )
                if greedy_selected:
                    greedy_selected = [
                        {
                            **cand,
                            "reason": f"{cand.get('reason', 'remove_row_value')}_greedy_multi"
                        }
                        for cand in greedy_selected
                    ]

                    _apply_selected_total_culprits(
                        greedy_selected,
                        spec,
                        invoice_group,
                        actual_sum,
                        declared_total,
                        gap,
                        culprit_row_nos,
                        culprit_groups,
                    )
                    continue

            # CASE 2: strong single culprit
            if candidates and candidates[0]["ratio"] >= strong_ratio:
                top = candidates[0]
                _apply_selected_total_culprits(
                    [top],
                    spec,
                    invoice_group,
                    actual_sum,
                    declared_total,
                    gap,
                    culprit_row_nos,
                    culprit_groups,
                )
                continue

            # CASE 3: strong top-2 culprit
            if len(candidates) >= 2:
                combined_top2 = candidates[0]["ratio"] + candidates[1]["ratio"]
                if combined_top2 >= top2_ratio:
                    _apply_selected_total_culprits(
                        candidates[:2],
                        spec,
                        invoice_group,
                        actual_sum,
                        declared_total,
                        gap,
                        culprit_row_nos,
                        culprit_groups,
                    )
                    continue

            # CASE 4: fallback wajib -> minimal 1 kandidat paling kuat
            if candidates:
                top = dict(candidates[0])
                forced_reason = top.get("reason") or "forced_top1_candidate"
                top["reason"] = f"{forced_reason}_fallback_min1"

                _apply_selected_total_culprits(
                    [top],
                    spec,
                    invoice_group,
                    actual_sum,
                    declared_total,
                    gap,
                    culprit_row_nos,
                    culprit_groups,
                )

                print(
                    f"[TOTAL_ATTRIBUTION][FORCED_TOP1] invoice_no={invoice_group} "
                    f"field={spec['declared_field']} "
                    f"row_no={top['row_no']} ratio={top['ratio']} gap={gap}"
                )
                continue

            # CASE 5: no candidate dari rule utama -> pakai most influential anchor
            fallback = _pick_most_influential_fallback(
                group_rows=group_rows,
                spec=spec,
                gap=gap,
            )
            if fallback:
                fallback["reason"] = (
                    f"{fallback.get('reason', 'forced_absmax_fallback')}"
                    f"_missing_or_under_anchor"
                )

                _apply_selected_total_culprits(
                    [fallback],
                    spec,
                    invoice_group,
                    actual_sum,
                    declared_total,
                    gap,
                    culprit_row_nos,
                    culprit_groups,
                )

                print(
                    f"[TOTAL_ATTRIBUTION][ANCHOR_FALLBACK] invoice_no={invoice_group} "
                    f"field={spec['declared_field']} "
                    f"row_no={fallback['row_no']} gap={gap} "
                    f"reason={fallback['reason']}"
                )
                continue

            print(
                f"[TOTAL_ATTRIBUTION] invoice_no={invoice_group} "
                f"field={spec['declared_field']} "
                f"actual_sum={actual_sum} declared_total={declared_total} gap={gap} "
                f"root_cause=no_candidate_found"
            )

    return {
        "total_issue_groups": total_issue_groups,
        "culprit_row_nos": culprit_row_nos,
        "culprit_groups": culprit_groups,
    }

PACKAGE_MULTI_SEPARATORS_REGEX = r"[\/&,;+]|(?:\band\b)"

def _normalize_package_unit_token(value):
    if value is None:
        return ""

    s = str(value).strip().lower()
    if s == "" or s == "null":
        return ""

    s = re.sub(r"[^a-z]", "", s)
    return s

def _convert_single_package_unit_token(token: str) -> str:
    if not token:
        return ""

    # alias tambahan
    if token in {"pt", "pts"}:
        return "PT"

    mapped = PL_PACKAGE_UNIT_MAP.get(token)
    if mapped:
        return mapped

    return token.upper()

def _sanitize_package_unit(value):
    """
    Rules:
    - Jika ada 2 unit atau lebih -> PK
      contoh:
        PT/CT
        PT&CT
        PT, CT
        PT + CT
        PT and CT
    - Jika hanya 1 unit -> convert normal
    """
    if value is None:
        return "null"

    raw = str(value).strip()
    if raw == "" or raw.lower() == "null":
        return "null"

    parts = re.split(PACKAGE_MULTI_SEPARATORS_REGEX, raw, flags=re.IGNORECASE)

    normalized_tokens = []
    for part in parts:
        token = _normalize_package_unit_token(part)
        if not token:
            continue

        converted = _convert_single_package_unit_token(token)
        if converted and converted not in normalized_tokens:
            normalized_tokens.append(converted)

    if len(normalized_tokens) >= 2:
        return "PK"

    if len(normalized_tokens) == 1:
        return normalized_tokens[0]

    # fallback: treat as single value
    normalized = _normalize_package_unit_token(raw)

    if normalized in {"pt", "pts"}:
        return "PT"

    mapped = PL_PACKAGE_UNIT_MAP.get(normalized)
    if mapped:
        return mapped

    return raw

INVOICE_NO_COMPARE_CANONICAL_MAP = {
    "0": "0", "O": "0", "Q": "0", "D": "0",
    "1": "1", "I": "1", "L": "1",
    "5": "5", "S": "5",
    "8": "8", "B": "8",
}

def _norm_invoice_compare_key(value):
    s = _preprocess_invoice_no_for_grouping(value)
    if not s:
        return ""

    return "".join(INVOICE_NO_COMPARE_CANONICAL_MAP.get(ch, ch) for ch in s)


def _same_invoice_no(a, b) -> bool:
    left = _norm_invoice_compare_key(a)
    right = _norm_invoice_compare_key(b)

    if not left or not right:
        return False

    return left == right




def _invoice_no_similarity(a, b) -> float:
    """
    Similarity untuk invoice number setelah normalisasi compare key.
    Dipakai untuk kasus beda tipis karena OCR/extraction:
    - 123 vs 12Z
    - ABC001 vs A8C001
    """
    left = _norm_invoice_compare_key(a)
    right = _norm_invoice_compare_key(b)

    if not left or not right:
        return 0.0

    if left == right:
        return 1.0

    return SequenceMatcher(None, left, right).ratio()


def _invoice_no_close_enough(a, b, threshold: float = 0.85) -> bool:
    return _invoice_no_similarity(a, b) >= threshold


def _pick_consensus_invoice_no(row: dict):
    inv_no = row.get("inv_invoice_no")
    pl_no = row.get("pl_invoice_no")
    coo_no = row.get("coo_invoice_no")

    inv_ok = not _is_null(inv_no)
    pl_ok = not _is_null(pl_no)
    coo_ok = not _is_null(coo_no)

    # =========================================================
    # CASE 1:
    # COO tidak ada / tidak berhasil grouping.
    # Patokan hanya INV + PL.
    #
    # Jika INV dan PL beda sedikit karena OCR/extraction,
    # tetap pakai PL sebagai source of truth.
    # =========================================================
    if inv_ok and pl_ok and not coo_ok:
        return str(pl_no).strip(), "inv+pl_no_coo_use_pl"

    # Kalau invoice kosong tapi PL ada, tetap pakai PL.
    if (not inv_ok) and pl_ok and not coo_ok:
        return str(pl_no).strip(), "pl_only_no_coo"

    # =========================================================
    # CASE 2:
    # Ketiga dokumen ada.
    # Gunakan majority voting.
    #
    # Contoh:
    # INV: 123, PL: 123, COO: 12Z
    # => COO ikut INV/PL = 123
    #
    # Kalau INV/COO sama, PL ikut INV/COO.
    # Kalau PL/COO sama, INV ikut PL/COO.
    # =========================================================
    if inv_ok and pl_ok and coo_ok:
        inv_pl_same = _same_invoice_no(inv_no, pl_no)
        inv_coo_same = _same_invoice_no(inv_no, coo_no)
        pl_coo_same = _same_invoice_no(pl_no, coo_no)

        if inv_pl_same:
            return str(pl_no).strip(), "majority_inv+pl"

        if inv_coo_same:
            return str(inv_no).strip(), "majority_inv+coo"

        if pl_coo_same:
            return str(pl_no).strip(), "majority_pl+coo"

        # =====================================================
        # CASE 3:
        # Ketiganya tidak exact-match, tapi ada 2 yang close.
        # Pilih pasangan paling mirip.
        #
        # Tie breaker:
        # - prefer PL jika PL termasuk dalam pasangan terbaik
        # - karena request: kalau INV vs PL beda dikit dan COO tidak ada,
        #   PL jadi patokan; untuk 3 dokumen pun PL lebih dipercaya
        #   saat similarity sama-sama kuat.
        # =====================================================
        candidates = [
            ("inv+pl_close", inv_no, pl_no, _invoice_no_similarity(inv_no, pl_no)),
            ("inv+coo_close", inv_no, coo_no, _invoice_no_similarity(inv_no, coo_no)),
            ("pl+coo_close", pl_no, coo_no, _invoice_no_similarity(pl_no, coo_no)),
        ]

        candidates = [x for x in candidates if x[3] >= 0.85]

        if candidates:
            candidates.sort(
                key=lambda x: (
                    x[3],
                    1 if x[0] in {"inv+pl_close", "pl+coo_close"} else 0
                ),
                reverse=True
            )

            source, left_value, right_value, score = candidates[0]

            if source in {"inv+pl_close", "pl+coo_close"}:
                return str(pl_no).strip(), source

            return str(inv_no).strip(), source

        # Tidak ada consensus yang aman.
        return None, None

    # =========================================================
    # CASE 4:
    # Partial fallback selain no-COO.
    # =========================================================
    if pl_ok and coo_ok:
        if _same_invoice_no(pl_no, coo_no) or _invoice_no_close_enough(pl_no, coo_no):
            return str(pl_no).strip(), "pl+coo_partial"

    if inv_ok and coo_ok:
        if _same_invoice_no(inv_no, coo_no) or _invoice_no_close_enough(inv_no, coo_no):
            return str(inv_no).strip(), "inv+coo_partial"

    if inv_ok and pl_ok:
        # Walaupun beda tipis, pakai PL.
        if _same_invoice_no(inv_no, pl_no) or _invoice_no_close_enough(inv_no, pl_no):
            return str(pl_no).strip(), "inv+pl_partial_use_pl"

    return None, None


def _postprocess_invoice_no_consensus(rows: list):
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        consensus_value, consensus_source = _pick_consensus_invoice_no(row)
        if not consensus_value:
            continue

        inv_ok = not _is_null(row.get("inv_invoice_no"))
        pl_ok = not _is_null(row.get("pl_invoice_no"))
        coo_ok = not _is_null(row.get("coo_invoice_no"))

        # Jangan membuat COO seolah-olah ada kalau memang COO tidak ada.
        # Jadi coo_invoice_no hanya diisi kalau sebelumnya memang ada value COO.
        if inv_ok:
            row["inv_invoice_no"] = consensus_value

        if pl_ok:
            row["pl_invoice_no"] = consensus_value

        if coo_ok:
            row["coo_invoice_no"] = consensus_value

        print(
            f"[INVOICE_NO_CONSENSUS] "
            f"source={consensus_source} "
            f"consensus='{consensus_value}' "
            f"inv_ok={inv_ok} pl_ok={pl_ok} coo_ok={coo_ok}"
        )

def _postprocess_package_unit_fields(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "pl_package_unit" in row:
            row["pl_package_unit"] = _sanitize_package_unit(
                row.get("pl_package_unit")
            )

        if "coo_package_unit" in row:
            row["coo_package_unit"] = _sanitize_package_unit(
                row.get("coo_package_unit")
            )

def _normalize_unit_key(value):
    """
    Normalisasi untuk kebutuhan converter:
    - trim
    - uppercase
    - buang semua selain A-Z dan 0-9
    Contoh:
    - ' pcs '   -> 'PCS'
    - 'Piece.'  -> 'PIECE'
    - 'kgm'     -> 'KGM'
    """
    if value is None:
        return ""

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return ""

    s = s.upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def _convert_unit_value(value):
    """
    Convert value B -> A setelah dinormalisasi.
    Kalau tidak ada mapping, kembalikan value yang sudah dinormalisasi.
    Kalau kosong/null, return 'null'
    """
    normalized = _normalize_unit_key(value)

    if normalized == "":
        return "null"

    return UNIT_CONVERSION_MAP.get(normalized, normalized)

def _postprocess_unit_fields(rows: list):
    UNIT_FIELDS = [
        "inv_quantity_unit",
        "pl_weight_unit",
        "pl_volume_unit",
        "coo_unit",
        "coo_gw_unit",
        "bl_gw_unit",
        "bl_volume_unit",
    ]

    for row in rows:
        if not isinstance(row, dict):
            continue

        for key in UNIT_FIELDS:
            if key in row:
                row[key] = _convert_unit_value(row.get(key))

def _preprocess_invoice_no_for_grouping(value):
    """
    Preprocessing khusus invoice_no sebelum grouping.
    Rule:
    - trim
    - uppercase
    - hapus semua whitespace
    - pertahankan huruf, angka, dash, slash
    Contoh:
      SHXM22-2512000 393 -> SHXM22-2512000393
    """
    if value is None:
        return ""

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return ""

    s = s.upper()

    # gabungkan kalau ada spasi di tengah invoice_no
    s = re.sub(r"\s+", "", s)

    # pertahankan A-Z, 0-9, dash, slash
    s = re.sub(r"[^A-Z0-9\-/]", "", s)

    return s


def _normalize_invoice_group_key(value):
    return _preprocess_invoice_no_for_grouping(value)


def _safe_output_suffix(value: str) -> str:
    raw = str(value or "").strip()
    if raw == "" or raw.lower() == "null":
        return uuid.uuid4().hex[:8]

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return safe or uuid.uuid4().hex[:8]


def _get_grouping_target_key(doc_type: str) -> str:
    key_field_map = {
        "invoice": "inv_invoice_no",
        "packing": "pl_invoice_no",
        "coo": "coo_invoice_no",
    }
    if doc_type not in key_field_map:
        raise Exception(f"doc_type tidak didukung: {doc_type}")
    return key_field_map[doc_type]


def _get_doc_label_for_prompt(doc_type: str) -> str:
    label_map = {
        "invoice": "INVOICE",
        "packing": "PACKING LIST",
        "coo": "CERTIFICATE OF ORIGIN",
    }
    if doc_type not in label_map:
        raise Exception(f"doc_type tidak didukung: {doc_type}")
    return label_map[doc_type]


def _looks_like_invoice_no_candidate(value: str) -> bool:
    s = _preprocess_invoice_no_for_grouping(value)

    if not s:
        return False
    if len(s) < 4 or len(s) > 80:
        return False

    # cukup harus mengandung angka, huruf opsional
    if not re.search(r"\d", s):
        return False

    blacklist = {
        "INVOICE", "DATE", "PAGE", "USD", "LC", "TERM",
        "COMMODITY", "ORIGIN", "INCOTERMS", "PACKINGLIST",
        "CERTIFICATEOFORIGIN", "COO"
    }
    if s in blacklist:
        return False

    return True

def _cleanup_coo_invoice_no(value: str) -> str:
    s = str(value or "").strip().upper()
    if not s or s == "NULL":
        return "null"

    # buang tanggal umum
    s = re.sub(
        r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\.?\s+\d{1,2},?\s+\d{4}\b",
        "",
        s
    )

    # gabungkan whitespace / line break
    s = re.sub(r"\s+", "", s).strip()

    # kalau kebaca certificate number, tolak
    if s.startswith("RC"):
        return "null"

    return s or "null"

def _should_force_recheck_invoice_no(doc_type: str, raw_invoice_no: str) -> bool:
    normalized = _preprocess_invoice_no_for_grouping(raw_invoice_no)
    raw_upper = str(raw_invoice_no or "").strip().upper()

    if not normalized:
        return True

    if not _looks_like_invoice_no_candidate(normalized):
        return True

    if doc_type == "coo":
        if raw_upper.startswith("RC"):
            return True

        if re.search(r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b", raw_upper):
            if len(normalized) < 8:
                return True

        suspicious_keywords = [
            "CERTIFICATE",
            "VERIFICATION",
            "COUNTRY",
            "ORIGIN",
            "VESSEL",
            "VOYAGE",
            "PORT",
            "HS CODE",
            "G.W",
            "GROSS WEIGHT",
        ]
        if any(keyword in raw_upper for keyword in suspicious_keywords):
            return True

    return False


def _build_focused_invoice_prompt(doc_type: str, target_key: str, doc_label: str) -> str:
    if doc_type == "coo":
        return f"""
ROLE:
Anda hanya mengekstrak SATU field dari dokumen COO/RCEP:
{target_key}

TUGAS:
Ambil nomor invoice referensi yang tertulis pada dokumen COO.

ATURAN PALING PENTING:
- Baca tata letak VISUAL PDF, bukan urutan text OCR linear.
- Fokus ke KOLOM 13 dengan label:
  "Invoice number(s) and date of invoice(s)"
- Kolom ini biasanya berada di sisi PALING KANAN tabel utama COO.
- Ambil HANYA invoice number.
- Abaikan tanggal invoice walaupun berada dalam sel yang sama.
- Jika invoice number terpecah ke beberapa baris, gabungkan semua fragmennya tanpa spasi.
- Invoice number boleh numeric-only atau alfanumerik.
- Invoice number valid tidak harus mengandung huruf.
- Hasil tidak boleh diawali RC bila itu certificate number.

OUTPUT HANYA JSON:
{{
  "{target_key}": "string"
}}
""".strip()

    # 2) bikin prompt fallback single-page bercabang per doc_type, jangan COO-only
    if doc_type == "packing":
        return f"""
    ROLE:
    Anda hanya mengekstrak nomor invoice referensi dari dokumen PACKING LIST.

    TUGAS:
    Ambil SATU nilai {target_key} yang benar-benar merupakan invoice reference pada packing list.

    ATURAN:
    - Fokus pada HEADER dokumen, terutama area paling atas.
    - Prioritaskan format seperti:
    - NO.: <nomor>
    - NO <nomor>
    - NUMBER: <nomor>
    - Invoice number boleh numeric-only atau alfanumerik.
    - Jangan ambil PO number, TAX ID number, page number, quantity, carton, NW, GW, atau CBM.

    OUTPUT HANYA JSON:
    {{
    "{target_key}": "string"
    }}
    """.strip()

    return f"""
ROLE:
Anda hanya mengekstrak nomor invoice referensi dari dokumen {doc_label}.

TUGAS:
Ambil SATU nilai {target_key} yang benar-benar merupakan invoice reference dokumen.

ATURAN:
- Fokus pada area header / judul / metadata dokumen.
- Jangan ambil PO number, item number, page number, date, quantity, amount, atau reference lain yang bukan invoice number.
- Jika nilai invoice number terpotong ke beberapa baris, gabungkan menjadi satu nilai utuh.
- Invoice number boleh numeric-only atau alfanumerik.
- Invoice number valid tidak harus mengandung huruf.

OUTPUT HANYA JSON:
{{
  "{target_key}": "string"
}}
""".strip()

def _extract_invoice_no_from_text_for_split(page_text: str, doc_type: str) -> str:
    """
    Fast path: ambil invoice no referensi dari text page tanpa Gemini.
    Berlaku untuk invoice / packing / coo.
    """
    if not page_text:
        return ""

    text = str(page_text).replace("\r", "\n")
    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]
    joined = "\n".join(lines[:200])

    def _cleanup_candidate(raw_value: str) -> str:
        if raw_value is None:
            return ""

        raw = str(raw_value).strip()
        if not raw:
            return ""

        raw = re.split(
            r"\bDATE\b|\bPAGE\b|\bPORT\b|\bVESSEL\b|\bVOYAGE\b",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip()

        if not raw:
            return ""

        first_non_empty = ""
        for part in raw.splitlines():
            part = part.strip()
            if part:
                first_non_empty = part
                break

        raw = (first_non_empty or raw).strip()
        if not raw:
            return ""

        return _preprocess_invoice_no_for_grouping(raw)

    # pola berbasis label eksplisit
    explicit_patterns = []

    if doc_type == "packing":
        explicit_patterns.extend([
            r"(?m)^\s*NO\.?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})\s*$",
            r"(?is)\bPACKING LIST\b.{0,120}?\bNO\.?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        ])

    explicit_patterns.extend([
        r"\bINVOICE\s*(?:NO\.?|NUMBER|#)?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bNO\.?\s*INVOICE\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bINVOICE NUMBER\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bINV\.?\s*NO\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
    ])

    for pattern in explicit_patterns:
        for m in re.finditer(pattern, joined, flags=re.IGNORECASE):
            raw_match = m.group(1)
            normalized = _cleanup_candidate(raw_match)

            print(
                f"[GROUPING][FAST_PATH][{doc_type.upper()}] "
                f"raw_match='{raw_match}' normalized='{normalized}'"
            )

            if normalized and _looks_like_invoice_no_candidate(normalized):
                return normalized

    # pola layout: cari line yang mengandung keyword INVOICE lalu lihat 20 line berikutnya
    invoice_hint_patterns = [
        r"\bINVOICE\b",
        r"\bINVOICE\s*NO\b",
        r"\bINVOICE\s*NUMBER\b",
    ]

    for idx, line in enumerate(lines[:120]):
        hit = False
        for pat in invoice_hint_patterns:
            if re.search(pat, line, flags=re.IGNORECASE):
                hit = True
                break

        if not hit:
            continue

        for j in range(idx + 1, min(idx + 20, len(lines))):
            candidate = _cleanup_candidate(lines[j])
            if candidate and _looks_like_invoice_no_candidate(candidate):
                return candidate
                
    if doc_type == "coo":
        return ""

    # fallback regex generik
    generic_candidates = re.findall(
        r"\b[A-Z0-9][A-Z0-9\-/]{3,}\b",
        joined.upper()
    )
    for cand in generic_candidates:
        normalized = _cleanup_candidate(cand)
        if normalized and _looks_like_invoice_no_candidate(normalized):
            return normalized

    return ""


def _create_single_page_pdf(src_pdf_path: str, page_index: int) -> str:
    reader = PdfReader(src_pdf_path)
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])

    out = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=f"_page_{page_index + 1}.pdf"
    )
    out.close()

    with open(out.name, "wb") as f:
        writer.write(f)

    return out.name


def _extract_invoice_no_from_single_page_for_split(src_pdf_path: str, page_index: int, doc_type: str) -> str:
    """
    Slow path fallback: jika regex text gagal, pakai Gemini untuk 1 halaman saja.
    Berlaku untuk invoice / packing / coo.
    """
    single_page_pdf = _create_single_page_pdf(src_pdf_path, page_index)

    try:
        grouping_run_prefix = f"{TMP_PREFIX.rstrip('/')}/grouping/page_split/{doc_type}/{uuid.uuid4().hex}"
        grouping_name = f"{doc_type}_page_{page_index + 1}_{uuid.uuid4().hex}"
        file_uri = _upload_temp_pdf_to_gcs(single_page_pdf, grouping_run_prefix, grouping_name)

        target_key = _get_grouping_target_key(doc_type)
        doc_label = _get_doc_label_for_prompt(doc_type)

        prompt = f"""
        ROLE:
        Anda hanya mengekstrak nomor invoice referensi dari SATU HALAMAN dokumen {doc_label}.

        TUGAS:
        Ambil SATU nilai invoice reference yang valid dari halaman ini.

        ATURAN KHUSUS UNTUK COO/RCEP:
        - Prioritaskan kolom "Invoice number(s) and date of invoice(s)".
        - Jika sel tersebut berisi beberapa baris:
        - gabungkan bagian invoice number yang valid
        - abaikan tanggal invoice di bawahnya
        - Invoice number boleh numeric-only atau alfanumerik.
        - Invoice number valid tidak harus mengandung huruf.
        - Jika halaman ini adalah continuation sheet dan invoice number tidak muncul eksplisit, isi "null".
        - Jika dokumen COO memiliki invoice number pada kolom 13 yang setelah normalisasi sama dengan inv_invoice_no,
        maka dokumen COO tersebut WAJIB dipakai untuk ekstraksi field COO item-level.
        - Nilai invoice number pada COO boleh terpotong ke beberapa baris dan harus digabung.
        - Contoh:
        SHXM22-2512000
        393
        DEC. 31, 2025
        => coo_invoice_no = "SHXM22-2512000393"
        - Contoh:
        260116001
        JAN. 16, 2026
        => coo_invoice_no = "260116001"
        - Jangan isi semua field COO sebagai null hanya karena invoice number pada COO ditulis split multiline.

        JANGAN AMBIL:
        - Certificate No.
        - Form RCEP
        - verification number
        - page number
        - HS code
        - quantity
        - gross weight
        - country of origin
        - PO number
        - date

        OUTPUT HANYA JSON object valid.

        OUTPUT SCHEMA:
        {{
        "{target_key}": "string"
        }}
        """

        obj = _call_gemini_json_uri(
            file_uri,
            prompt,
            expect_array=False,
            retries=3
        )

        raw_invoice_no = "null"
        if isinstance(obj, dict):
            raw_invoice_no = obj.get(target_key, "null")

        if doc_type == "coo":
            raw_invoice_no = _cleanup_coo_invoice_no(raw_invoice_no)

        return _preprocess_invoice_no_for_grouping(raw_invoice_no)

    finally:
        try:
            os.remove(single_page_pdf)
        except Exception:
            pass


def _split_pdf_by_invoice_no(local_pdf_path: str, doc_type: str):
    """
    Primary:
      1) Gemini whole-document trace -> invoice_no + page_range
    Fallback:
      2) page-by-page extraction lama
    """
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if total_pages == 0:
        raise Exception(f"PDF {doc_type} kosong: {os.path.basename(local_pdf_path)}")

    # =========================
    # PRIMARY: WHOLE-DOCUMENT TRACE
    # =========================
    try:
        traced_refs = _trace_invoice_refs_from_document(local_pdf_path, doc_type)

        if traced_refs:
            traced_entries = _build_split_entries_from_trace(
                local_pdf_path=local_pdf_path,
                doc_type=doc_type,
                traced_refs=traced_refs,
            )

            if traced_entries:
                print(
                    f"[GROUPING][PRIMARY_TRACE_OK][{doc_type.upper()}] "
                    f"file='{os.path.basename(local_pdf_path)}'"
                )
                return traced_entries

        print(
            f"[GROUPING][PRIMARY_TRACE_EMPTY][{doc_type.upper()}] "
            f"file='{os.path.basename(local_pdf_path)}' -> fallback page splitter"
        )

    except Exception as e:
        print(
            f"[GROUPING][PRIMARY_TRACE_FAIL][{doc_type.upper()}] "
            f"file='{os.path.basename(local_pdf_path)}' error='{e}' "
            f"-> fallback page splitter"
        )

    # =========================
    # FALLBACK: PAGE-BY-PAGE
    # =========================
    return _split_pdf_by_invoice_no_page_fallback(local_pdf_path, doc_type)


def _explode_doc_paths_for_grouping(paths: list, doc_type: str):
    expanded = []

    for path in paths or []:
        split_entries = _split_pdf_by_invoice_no(path, doc_type=doc_type)
        expanded.extend(split_entries)

    return expanded

def _log_extracted_invoice_refs(doc_type: str, entries: list):
    """
    Print ringkasan invoice reference yang berhasil diekstrak
    dari hasil explode/split dokumen.
    """
    label_map = {
        "invoice": "inv_invoice_no",
        "packing": "pl_invoice_no",
        "coo": "coo_invoice_no",
    }
    target_label = label_map.get(doc_type, "invoice_no")

    extracted = []
    for entry in entries or []:
        extracted.append({
            "source_file": entry.get("source_file"),
            "page_range": entry.get("page_range"),
            target_label: entry.get("invoice_no"),
            "temp_split": entry.get("is_temp", False),
        })

    print(
        f"[GROUPING][EXTRACTED_SUMMARY][{doc_type.upper()}] "
        f"count={len(extracted)} values={extracted}"
    )

def _trace_invoice_refs_from_document(local_pdf_path: str, doc_type: str):
    """
    Primary splitter:
    Minta Gemini membaca seluruh dokumen dan mengembalikan semua invoice reference
    beserta page range-nya.

    Output normalized:
    [
      {
        "invoice_no": "ABC123",
        "start_page": 1,
        "end_page": 2,
      },
      ...
    ]
    """
    target_key = _get_grouping_target_key(doc_type)
    doc_label = _get_doc_label_for_prompt(doc_type)

    grouping_run_prefix = f"{TMP_PREFIX.rstrip('/')}/grouping/doc_trace/{doc_type}/{uuid.uuid4().hex}"
    grouping_name = f"{doc_type}_trace_{uuid.uuid4().hex}"
    file_uri = _upload_temp_pdf_to_gcs(local_pdf_path, grouping_run_prefix, grouping_name)

    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    prompt = f"""
ROLE:
Anda bertugas membaca SELURUH dokumen {doc_label} dan menelusuri SEMUA invoice number
yang direferensikan di dokumen tersebut, beserta rentang halaman masing-masing.

TUJUAN:
- Jika 1 dokumen hanya mereferensikan 1 invoice number -> kembalikan 1 object.
- Jika 1 dokumen mereferensikan beberapa invoice number -> kembalikan beberapa object.
- Setiap object HARUS punya page range yang benar: start_page dan end_page.
- start_page dan end_page menggunakan nomor halaman 1-based.

ATURAN:
- Untuk doc_type = invoice:
  ambil invoice number dari dokumen invoice.
- Untuk doc_type = packing:
  ambil invoice number yang direferensikan pada packing list.
- Untuk doc_type = coo:
  ambil invoice number yang direferensikan pada COO.

- Jangan ambil PO number.
- Jangan ambil packing list number.
- Jangan ambil COO number.
- Jangan ambil LC number.
- Jangan ambil page number.
- Jangan mengarang page range.
- Jika sebuah invoice number berlanjut ke halaman berikutnya, gabungkan dalam 1 range.
- Jika halaman lanjutan tidak menuliskan ulang invoice number, tetap masukkan ke range invoice sebelumnya.
- Semua invoice number pasti mengacu ke field: {target_key}
- Output HANYA JSON OBJECT valid tanpa teks lain.
- Jangan mengembalikan invoice_refs kosong jika dokumen mengandung invoice reference.
- Semua halaman harus tercakup dalam salah satu range jika dokumen memang valid.

OUTPUT SCHEMA:
{{
  "invoice_refs": [
    {{
      "{target_key}": "string",
      "start_page": "number",
      "end_page": "number"
    }}
  ]
}}

VALIDATION RULE:
- start_page >= 1
- end_page >= start_page
- end_page <= {total_pages}
- Jika hanya ada 1 invoice reference untuk seluruh dokumen, start_page=1 dan end_page={total_pages}
"""

    obj = _call_gemini_json_uri(
        file_uri,
        prompt,
        expect_array=False,
        retries=3
    )

    refs = []
    if isinstance(obj, dict):
        refs = obj.get("invoice_refs", [])

    if not isinstance(refs, list):
        refs = []

    normalized = []
    for item in refs:
        if not isinstance(item, dict):
            continue

        raw_invoice_no = item.get(target_key, "null")
        invoice_no = _preprocess_invoice_no_for_grouping(raw_invoice_no)

        try:
            start_page = int(item.get("start_page"))
        except Exception:
            start_page = 0

        try:
            end_page = int(item.get("end_page"))
        except Exception:
            end_page = 0

        if not invoice_no:
            continue
        if start_page < 1 or end_page < start_page or end_page > total_pages:
            continue

        normalized.append({
            "invoice_no": invoice_no,
            "start_page": start_page,
            "end_page": end_page,
        })

    # sort & dedup exact duplicates
    normalized = sorted(
        normalized,
        key=lambda x: (x["start_page"], x["end_page"], x["invoice_no"])
    )

    deduped = []
    seen = set()
    for x in normalized:
        key = (x["invoice_no"], x["start_page"], x["end_page"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(x)

    print(
        f"[GROUPING][DOC_TRACE][{doc_type.upper()}] "
        f"file='{os.path.basename(local_pdf_path)}' "
        f"invoice_refs={deduped}"
    )

    return deduped


def _build_split_entries_from_trace(local_pdf_path: str, doc_type: str, traced_refs: list):
    """
    Ubah hasil trace whole-document menjadi entry split PDF.
    Validasi:
    - harus ascending
    - tidak boleh overlap
    - harus cover SEMUA halaman tanpa gap
    """
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if not traced_refs:
        return []

    ordered_refs = sorted(traced_refs, key=lambda x: (x["start_page"], x["end_page"]))

    prev_end = 0
    cleaned_refs = []

    for idx, ref in enumerate(ordered_refs):
        start_page = ref["start_page"]
        end_page = ref["end_page"]
        invoice_no = ref["invoice_no"]

        # overlap check
        if start_page <= prev_end:
            print(
                f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_OVERLAP] "
                f"file='{os.path.basename(local_pdf_path)}' ref={ref}"
            )
            return []

        # gap check: page berikutnya harus langsung nyambung
        expected_start = 1 if idx == 0 else (prev_end + 1)
        if start_page != expected_start:
            print(
                f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_GAP] "
                f"file='{os.path.basename(local_pdf_path)}' "
                f"expected_start={expected_start} actual_start={start_page} ref={ref}"
            )
            return []

        cleaned_refs.append(ref)
        prev_end = end_page

    # final coverage check: halaman terakhir harus menutup seluruh dokumen
    if prev_end != total_pages:
        print(
            f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_COVERAGE] "
            f"file='{os.path.basename(local_pdf_path)}' "
            f"last_covered_page={prev_end} total_pages={total_pages}"
        )
        return []

    results = []

    for ref in cleaned_refs:
        group_key = ref["invoice_no"]
        start_page = ref["start_page"]
        end_page = ref["end_page"]

        # kalau satu trace menutup seluruh file, aman pakai file asli
        if start_page == 1 and end_page == total_pages:
            results.append({
                "group_key": group_key,
                "invoice_no": group_key,
                "path": local_pdf_path,
                "source_file": os.path.basename(local_pdf_path),
                "page_range": f"{start_page}-{end_page}",
                "is_temp": False,
                "doc_type": doc_type,
            })
            continue

        writer = PdfWriter()
        for i in range(start_page - 1, end_page):
            writer.add_page(reader.pages[i])

        out = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f"_{doc_type}_{_safe_output_suffix(group_key)}_{start_page}_{end_page}.pdf"
        )
        out.close()

        with open(out.name, "wb") as f:
            writer.write(f)

        results.append({
            "group_key": group_key,
            "invoice_no": group_key,
            "path": out.name,
            "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page}-{end_page}",
            "is_temp": True,
            "doc_type": doc_type,
        })

    print(
        f"[GROUPING][DOC_TRACE_SPLIT][{doc_type.upper()}] "
        f"file='{os.path.basename(local_pdf_path)}' "
        f"segments={[{'invoice_no': r['invoice_no'], 'page_range': r['page_range']} for r in results]}"
    )

    return results


def _split_pdf_by_invoice_no_page_fallback(local_pdf_path: str, doc_type: str):
    """
    Fallback lama: page-by-page extraction.
    Dipakai hanya jika whole-document trace gagal / tidak valid.
    """
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if total_pages == 0:
        raise Exception(f"PDF {doc_type} kosong: {os.path.basename(local_pdf_path)}")

    # KHUSUS COO:
    # jika trace whole-document gagal, fallback HARUS treat 1 file COO
    # sebagai 1 invoice reference document-level.
    # Jangan split page-by-page, karena continuation sheet biasanya tidak
    # menampilkan ulang invoice_no dan body table bisa memunculkan SKU.
    if doc_type == "coo":
        doc_group_key, raw_invoice_no, _ = _extract_invoice_no_for_grouping(
            local_pdf_path,
            doc_type="coo"
        )
        only_key = _normalize_invoice_group_key(raw_invoice_no or doc_group_key)

        if not only_key:
            raise Exception(
                f"Gagal membaca coo_invoice_no untuk file COO: {os.path.basename(local_pdf_path)}"
            )

        print(
            f"[GROUPING][COO_PAGE_FALLBACK][SINGLE_DOC_KEY] "
            f"file='{os.path.basename(local_pdf_path)}' "
            f"coo_invoice_no='{raw_invoice_no}' "
            f"group_key='{only_key}'"
        )

        return [{
            "group_key": only_key,
            "invoice_no": raw_invoice_no if raw_invoice_no else only_key,
            "path": local_pdf_path,
            "source_file": os.path.basename(local_pdf_path),
            "page_range": f"1-{total_pages}",
            "is_temp": False,
            "doc_type": doc_type,
        }]

    page_invoice_keys = []
    last_known_key = ""

    for idx, page in enumerate(reader.pages):
        page_text = ""
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""

        page_key = _extract_invoice_no_from_text_for_split(page_text, doc_type=doc_type)

        if not page_key:
            page_key = _extract_invoice_no_from_single_page_for_split(local_pdf_path, idx, doc_type=doc_type)

        if not page_key and last_known_key:
            page_key = last_known_key

        if not page_key and idx == 0:
            doc_group_key, raw_invoice_no, _ = _extract_invoice_no_for_grouping(local_pdf_path, doc_type)
            page_key = _normalize_invoice_group_key(raw_invoice_no or doc_group_key)

        if not page_key:
            raise Exception(
                f"Gagal menentukan invoice number untuk file '{os.path.basename(local_pdf_path)}' "
                f"({doc_type}) halaman ke-{idx + 1} saat split multi-section."
            )

        last_known_key = page_key
        page_invoice_keys.append(page_key)

        print(
            f"[GROUPING][PAGE_KEY][{doc_type.upper()}] "
            f"file='{os.path.basename(local_pdf_path)}' "
            f"page={idx + 1} "
            f"extracted_invoice_no='{page_key}'"
        )

    segments = []
    seg_start = 0

    for idx in range(1, total_pages):
        if page_invoice_keys[idx] != page_invoice_keys[idx - 1]:
            segments.append((page_invoice_keys[seg_start], seg_start, idx - 1))
            seg_start = idx

    segments.append((page_invoice_keys[seg_start], seg_start, total_pages - 1))

    print(
        f"[GROUPING][PAGE_KEYS][{doc_type.upper()}] "
        f"file='{os.path.basename(local_pdf_path)}' "
        f"page_invoice_keys={page_invoice_keys}"
    )

    if len(segments) == 1:
        only_key, start_page, end_page = segments[0]
        return [{
            "group_key": only_key,
            "invoice_no": only_key,
            "path": local_pdf_path,
            "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page + 1}-{end_page + 1}",
            "is_temp": False,
            "doc_type": doc_type,
        }]

    results = []

    for group_key, start_page, end_page in segments:
        writer = PdfWriter()

        for i in range(start_page, end_page + 1):
            writer.add_page(reader.pages[i])

        out = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f"_{doc_type}_{_safe_output_suffix(group_key)}_{start_page+1}_{end_page+1}.pdf"
        )
        out.close()

        with open(out.name, "wb") as f:
            writer.write(f)

        results.append({
            "group_key": group_key,
            "invoice_no": group_key,
            "path": out.name,
            "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page + 1}-{end_page + 1}",
            "is_temp": True,
            "doc_type": doc_type,
        })

    print(
        f"[GROUPING][{doc_type.upper()}_SPLIT][PAGE_FALLBACK] file='{os.path.basename(local_pdf_path)}' "
        f"segments={[{'invoice_no': r['invoice_no'], 'page_range': r['page_range']} for r in results]}"
    )

    return results


def _extract_invoice_no_for_grouping(local_pdf_path: str, doc_type: str):
    """
    Grouping key extractor.
    Berlaku untuk invoice / packing / coo.

    Flow:
    - PASS 1: pakai build_header_prompt()
    - PASS 2: re-check pakai focused prompt jika hasil PASS 1 kosong ATAU suspicious
    """

    target_key = _get_grouping_target_key(doc_type)
    doc_label = _get_doc_label_for_prompt(doc_type)

    grouping_run_prefix = f"{TMP_PREFIX.rstrip('/')}/grouping/{uuid.uuid4().hex}"
    grouping_name = f"{doc_type}_{uuid.uuid4().hex}"
    file_uri = _upload_temp_pdf_to_gcs(local_pdf_path, grouping_run_prefix, grouping_name)

    # PASS 1
    header_obj = _call_gemini_json_uri(
        file_uri,
        build_header_prompt(),
        expect_array=False,
        retries=3
    )

    if not isinstance(header_obj, dict):
        header_obj = {}

    raw_invoice_no = header_obj.get(target_key, "null")

    if doc_type == "coo":
        raw_invoice_no = _cleanup_coo_invoice_no(raw_invoice_no)
        header_obj[target_key] = raw_invoice_no

    preprocessed_invoice_no = _preprocess_invoice_no_for_grouping(raw_invoice_no)
    group_key = _normalize_invoice_group_key(preprocessed_invoice_no)

    print(
        f"[GROUPING][READ][{doc_type.upper()}] "
        f"{target_key} raw='{raw_invoice_no}' "
        f"preprocessed='{preprocessed_invoice_no}' "
        f"group_key='{group_key}' "
        f"file='{os.path.basename(local_pdf_path)}'"
    )

    # PASS 2
    need_recheck = _should_force_recheck_invoice_no(doc_type, raw_invoice_no)

    if need_recheck:
        focused_prompt = _build_focused_invoice_prompt(
            doc_type=doc_type,
            target_key=target_key,
            doc_label=doc_label,
        )

        focused_obj = _call_gemini_json_uri(
            file_uri,
            focused_prompt,
            expect_array=False,
            retries=3
        )

        if not isinstance(focused_obj, dict):
            focused_obj = {}

        focused_invoice_no = focused_obj.get(target_key, "null")

        if doc_type == "coo":
            focused_invoice_no = _cleanup_coo_invoice_no(focused_invoice_no)

        focused_preprocessed_invoice_no = _preprocess_invoice_no_for_grouping(focused_invoice_no)
        focused_group_key = _normalize_invoice_group_key(focused_preprocessed_invoice_no)

        print(
            f"[GROUPING][RECHECK_CANDIDATE][{doc_type.upper()}] "
            f"{target_key} raw='{focused_invoice_no}' "
            f"preprocessed='{focused_preprocessed_invoice_no}' "
            f"group_key='{focused_group_key}' "
            f"file='{os.path.basename(local_pdf_path)}'"
        )

        if focused_group_key and not _should_force_recheck_invoice_no(doc_type, focused_invoice_no):
            header_obj[target_key] = focused_invoice_no
            raw_invoice_no = focused_invoice_no
            group_key = focused_group_key

            print(
                f"[GROUPING][RECHECK_ACCEPTED][{doc_type.upper()}] "
                f"{target_key} raw='{focused_invoice_no}' "
                f"preprocessed='{focused_preprocessed_invoice_no}' "
                f"group_key='{focused_group_key}' "
                f"file='{os.path.basename(local_pdf_path)}'"
            )

    if not group_key:
        raise Exception(
            f"Gagal membaca {target_key} untuk file {doc_type}: {os.path.basename(local_pdf_path)}. "
            f"Invoice reference number tidak berhasil diekstrak saat grouping."
        )

    return group_key, raw_invoice_no, header_obj

def _group_docs_by_invoice_no(invoice_paths, packing_paths, coo_paths=None):
    coo_paths = coo_paths or []

    groups = {}
    skipped_packing = []
    skipped_coo = []
    dropped_invoice_groups = []

    def _ensure_group(group_key, raw_invoice_no):
        if group_key not in groups:
            groups[group_key] = {
                "invoice_no": raw_invoice_no if not _is_null(raw_invoice_no) else group_key,
                "invoice_paths": [],
                "packing_paths": [],
                "coo_paths": [],
                "temp_invoice_split_paths": [],
                "temp_packing_split_paths": [],
                "temp_coo_split_paths": [],
            }
        return groups[group_key]

    # =========================
    # INVOICE = MASTER
    # =========================
    invoice_entries = _explode_doc_paths_for_grouping(invoice_paths, doc_type="invoice")
    _log_extracted_invoice_refs("invoice", invoice_entries)

    for entry in invoice_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]

        if not group_key:
            raise Exception(
                f"Gagal membaca inv_invoice_no untuk file invoice: "
                f"{entry.get('source_file') or os.path.basename(p)}"
            )

        print(
            f"[GROUPING][INVOICE] "
            f"source_file='{entry.get('source_file', os.path.basename(p))}' "
            f"page_range='{entry.get('page_range', 'unknown')}' "
            f"inv_invoice_no='{raw_invoice_no}' "
            f"group_key='{group_key}' "
            f"temp_split={entry.get('is_temp', False)}"
        )

        grp = _ensure_group(group_key, raw_invoice_no)
        grp["invoice_paths"].append(p)

        if entry.get("is_temp"):
            grp["temp_invoice_split_paths"].append(p)

    # =========================
    # PACKING -> juga bisa multi invoice dalam 1 file
    # =========================
    packing_entries = _explode_doc_paths_for_grouping(packing_paths, doc_type="packing")
    _log_extracted_invoice_refs("packing", packing_entries)

    for entry in packing_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]

        if not group_key:
            raise Exception(
                f"Gagal membaca pl_invoice_no untuk file packing list: "
                f"{entry.get('source_file') or os.path.basename(p)}"
            )

        print(
            f"[GROUPING][PACKING] "
            f"source_file='{entry.get('source_file', os.path.basename(p))}' "
            f"page_range='{entry.get('page_range', 'unknown')}' "
            f"pl_invoice_no='{raw_invoice_no}' "
            f"group_key='{group_key}' "
            f"temp_split={entry.get('is_temp', False)}"
        )

        if group_key not in groups:
            skipped_packing.append({
                "invoice_no": raw_invoice_no,
                "file": entry.get("source_file", os.path.basename(p)),
                "page_range": entry.get("page_range", "unknown"),
            })
            print(
                f"[GROUPING][SKIP] Packing List '{entry.get('source_file', os.path.basename(p))}' "
                f"page_range='{entry.get('page_range', 'unknown')}' "
                f"dengan invoice_no '{raw_invoice_no}' tidak punya pasangan invoice."
            )
            continue

        groups[group_key]["packing_paths"].append(p)

        if entry.get("is_temp"):
            groups[group_key]["temp_packing_split_paths"].append(p)

    # =========================
    # COO -> juga bisa multi invoice dalam 1 file
    # =========================
    coo_entries = _explode_doc_paths_for_grouping(coo_paths, doc_type="coo")
    _log_extracted_invoice_refs("coo", coo_entries)

    for entry in coo_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]

        if not group_key:
            raise Exception(
                f"Gagal membaca coo_invoice_no untuk file COO: "
                f"{entry.get('source_file') or os.path.basename(p)}"
            )

        print(
            f"[GROUPING][COO] "
            f"source_file='{entry.get('source_file', os.path.basename(p))}' "
            f"page_range='{entry.get('page_range', 'unknown')}' "
            f"coo_invoice_no='{raw_invoice_no}' "
            f"group_key='{group_key}' "
            f"temp_split={entry.get('is_temp', False)}"
        )

        if group_key not in groups:
            skipped_coo.append({
                "invoice_no": raw_invoice_no,
                "file": entry.get("source_file", os.path.basename(p)),
                "page_range": entry.get("page_range", "unknown"),
            })
            print(
                f"[GROUPING][SKIP] COO '{entry.get('source_file', os.path.basename(p))}' "
                f"page_range='{entry.get('page_range', 'unknown')}' "
                f"dengan invoice_no '{raw_invoice_no}' tidak punya pasangan invoice."
            )
            continue

        groups[group_key]["coo_paths"].append(p)

        if entry.get("is_temp"):
            groups[group_key]["temp_coo_split_paths"].append(p)

    # =========================
    # invoice group yang tidak punya packing -> DROP
    # =========================
    valid_groups = {}
    for group_key, grp in groups.items():
        if not grp["packing_paths"]:
            dropped_invoice_groups.append({
                "invoice_no": grp["invoice_no"],
                "invoice_files": [os.path.basename(x) for x in grp["invoice_paths"]],
            })
            print(
                f"[GROUPING][DROP] Invoice group '{grp['invoice_no']}' "
                f"dibuang karena tidak punya pasangan packing list."
            )
            continue

        valid_groups[group_key] = grp

    print(f"[GROUPING] valid_groups={len(valid_groups)}")
    if skipped_packing:
        print(f"[GROUPING] skipped_packing={skipped_packing}")
    if skipped_coo:
        print(f"[GROUPING] skipped_coo={skipped_coo}")
    if dropped_invoice_groups:
        print(f"[GROUPING] dropped_invoice_groups={dropped_invoice_groups}")

    if not valid_groups:
        raise Exception("Tidak ada pasangan Invoice + Packing List yang valid untuk diproses.")

    return valid_groups

def _first_text(rows: list, key: str, default="null"):
    v = _first_non_null(rows, key)
    return default if _is_null(v) else v

def _first_number(rows: list, key: str, default=0):
    v = _first_non_null_nonzero(rows, key)
    n = _to_float(v)
    return default if n is None else n

def _ensure_total_keys(total_obj: dict):
    for k in TOTAL_OUTPUT_FIELDS:
        if k in total_obj and total_obj[k] is not None:
            continue
        if k in TOTAL_NUM_FIELDS:
            total_obj[k] = 0
        else:
            total_obj[k] = "null"

def _normalize_compare_text(v):
    if _is_null(v):
        return ""
    return re.sub(r"\s+", " ", str(v).strip().upper())
    
def _sum_numeric(rows: list, key: str) -> float:
    total = 0.0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        v = _to_float(r.get(key))
        if v is not None:
            total += v
    return total
def _build_total_from_detail_and_container(detail_rows: list, container_rows):
    if container_rows is None:
        return None

    if isinstance(container_rows, dict):
        container_rows = [container_rows]

    if not isinstance(container_rows, list):
        raise Exception("container_data tidak valid untuk membentuk total")

    container_rows = [r for r in container_rows if isinstance(r, dict)]

    if not container_rows:
        raise Exception("container_data kosong, total tidak bisa dibentuk")

    aggregated_total_fields = _aggregate_total_fields_from_detail_rows(detail_rows)

    total_obj = {
        # =========================
        # DETAIL
        # =========================
        "match_score": "true",
        "match_description": "null",

        "inv_quantity": _sum_numeric(detail_rows, "inv_quantity"),
        "inv_amount": _sum_numeric(detail_rows, "inv_amount"),

        "inv_total_quantity": aggregated_total_fields["inv_total_quantity"],
        "inv_total_amount": aggregated_total_fields["inv_total_amount"],
        "inv_total_nw": aggregated_total_fields["inv_total_nw"],
        "inv_total_gw": aggregated_total_fields["inv_total_gw"],
        "inv_total_volume": aggregated_total_fields["inv_total_volume"],
        "inv_total_package": aggregated_total_fields["inv_total_package"],

        "pl_package_unit": _first_text(detail_rows, "pl_package_unit"),
        "pl_package_count": _sum_numeric(detail_rows, "pl_package_count"),
        "pl_nw": _sum_numeric(detail_rows, "pl_nw"),
        "pl_gw": _sum_numeric(detail_rows, "pl_gw"),
        "pl_volume": _sum_numeric(detail_rows, "pl_volume"),

        "pl_total_quantity": aggregated_total_fields["pl_total_quantity"],
        "pl_total_amount": aggregated_total_fields["pl_total_amount"],
        "pl_total_nw": aggregated_total_fields["pl_total_nw"],
        "pl_total_gw": aggregated_total_fields["pl_total_gw"],
        "pl_total_volume": aggregated_total_fields["pl_total_volume"],
        "pl_total_package": aggregated_total_fields["pl_total_package"],

        # =========================
        # CONTAINER
        # =========================
        "bl_shipper_name": _first_text(container_rows, "bl_shipper_name"),
        "bl_shipper_address": _first_text(container_rows, "bl_shipper_address"),
        "bl_no": _first_text(container_rows, "bl_no"),
        "bl_date": _first_text(container_rows, "bl_date"),
        "bl_consignee_name": _first_text(container_rows, "bl_consignee_name"),
        "bl_consignee_address": _first_text(container_rows, "bl_consignee_address"),
        "bl_consignee_tax_id": _first_text(container_rows, "bl_consignee_tax_id"),
        "bl_seller_name": _first_text(container_rows, "bl_seller_name"),
        "bl_seller_address": _first_text(container_rows, "bl_seller_address"),
        "bl_lc_number": _first_text(container_rows, "bl_lc_number"),
        "bl_notify_party": _first_text(container_rows, "bl_notify_party"),
        "bl_vessel": _first_text(container_rows, "bl_vessel"),
        "bl_voyage_no": _first_text(container_rows, "bl_voyage_no"),
        "bl_port_of_loading": _first_text(container_rows, "bl_port_of_loading"),
        "bl_port_of_destination": _first_text(container_rows, "bl_port_of_destination"),
        "bl_gw_unit": _convert_unit_value(_first_text(container_rows, "bl_gw_unit")),
        "bl_gw": _sum_numeric(container_rows, "bl_gw"),
        "bl_volume_unit": _convert_unit_value(_first_text(container_rows, "bl_volume_unit")),
        "bl_volume": _sum_numeric(container_rows, "bl_volume"),
        "bl_package_count": _sum_numeric(container_rows, "bl_package_count"),
        "bl_package_unit": _first_text(container_rows, "bl_package_unit"),
    }

    _ensure_total_keys(total_obj)

    return [total_obj]

def _volume_values_match_with_conversion(left_value, right_value, eps=None, factor=CBM_TO_CUFT):
    lv = _to_float(left_value)
    rv = _to_float(right_value)

    if lv is None or rv is None:
        return False

    # toleransi kecil untuk rounding OCR / pembulatan dokumen
    if eps is None:
        eps = max(0.01, max(abs(lv), abs(rv)) * 0.0001)

    if abs(lv - rv) <= eps:
        return True

    if abs(lv - (rv * factor)) <= eps:
        return True

    if abs(lv - (rv / factor)) <= eps:
        return True

    return False
DETAIL_ROW_DEDUP_COMPARE_FIELDS = [
    "inv_customer_po_no",
    "inv_spart_item_no",
    "inv_quantity",
    "inv_unit_price",
    "pl_customer_po_no",
    "pl_spart_item_no",   # alias -> pl_item_no bila field ini tidak ada
    "pl_package_count",
    "pl_quantity",
    "pl_nw",
    "pl_gw",
    "pl_volume",
]

DETAIL_ROW_DEDUP_NUM_FIELDS = {
    "inv_quantity",
    "inv_unit_price",
    "pl_package_count",
    "pl_quantity",
    "pl_nw",
    "pl_gw",
    "pl_volume",
}


def _get_detail_dedup_raw_value(row: dict, field: str):
    if not isinstance(row, dict):
        return None

    # alias karena di codebase saat ini field packing item = pl_item_no
    if field == "pl_spart_item_no":
        if "pl_spart_item_no" in row:
            return row.get("pl_spart_item_no")
        return row.get("pl_item_no")

    return row.get(field)


def _normalize_detail_dedup_numeric(value):
    if _is_null(value):
        return "null"

    raw = str(value).strip().replace(",", "")
    if raw == "":
        return "null"

    try:
        d = Decimal(raw)
    except Exception:
        try:
            return str(float(raw))
        except Exception:
            return raw

    # samakan 10, 10.0, 10.000 -> "10"
    normalized = format(d.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _normalize_detail_dedup_text(value):
    if _is_null(value):
        return "null"

    s = str(value).strip().upper()
    if s == "":
        return "null"

    # supaya "A  B" == "A B"
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_detail_dedup_value(field: str, value):
    if field in DETAIL_ROW_DEDUP_NUM_FIELDS:
        return _normalize_detail_dedup_numeric(value)

    return _normalize_detail_dedup_text(value)


def _build_detail_dedup_key(row: dict):
    return tuple(
        _normalize_detail_dedup_value(
            field,
            _get_detail_dedup_raw_value(row, field)
        )
        for field in DETAIL_ROW_DEDUP_COMPARE_FIELDS
    )

def _should_deduplicate_detail_rows(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in {
        "bafang_motor",
        "jht_carbon",
        "tangsan_jinhengtong",
        "kunshan_landon",
        "ningbo_fordario"
    }

def _deduplicate_detail_rows_before_validation(rows: list, vendor_id: str = "default"):
    if not isinstance(rows, list):
        return rows

    normalized_vendor_id = normalize_vendor_id(vendor_id)

    if not _should_deduplicate_detail_rows(normalized_vendor_id):
        print(
            f"[DETAIL_DEDUP][SKIP] vendor_id={vendor_id} "
            f"normalized_vendor_id={normalized_vendor_id}"
        )
        return rows

    deduped = []
    seen = set()
    removed = 0

    for idx, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            deduped.append(row)
            continue

        key = _build_detail_dedup_key(row)

        # fail-safe: jangan collapse row yang semua key pembandingnya kosong/null
        if all(v == "null" for v in key):
            deduped.append(row)
            continue

        if key in seen:
            removed += 1
            print(
                f"[DETAIL_DEDUP][DROP] vendor_id={normalized_vendor_id} "
                f"row_no={idx} key={key}"
            )
            continue

        seen.add(key)
        deduped.append(row)

    print(
        f"[DETAIL_DEDUP] vendor_id={normalized_vendor_id} "
        f"before={len(rows)} after={len(deduped)} removed={removed}"
    )
    return deduped

def _validate_total_rows(total_data, detail_rows: list):
    if total_data is None:
        return None

    if isinstance(total_data, dict):
        total_data = [total_data]

    if not isinstance(total_data, list) or not total_data or not isinstance(total_data[0], dict):
        raise Exception("Output total tidak valid")

    if len(total_data) != 1:
        raise Exception(f"Output total harus tepat 1 baris, ditemukan {len(total_data)} baris")

    total_obj = total_data[0]
    _ensure_total_keys(total_obj)

    total_obj["match_score"] = "true"
    total_obj["match_description"] = "null"

    aggregated_total_fields = _aggregate_total_fields_from_detail_rows(detail_rows)

    def _cmp_num(left_key: str, right_key: str, eps=0.01):
        lv = _to_float(total_obj.get(left_key))
        rv = _to_float(total_obj.get(right_key))
        if lv is None or rv is None:
            return
        if abs(lv - rv) > eps:
            _append_total_error(
                total_obj,
                f"Total: {left_key} != {right_key} ({lv} vs {rv})"
            )

    def _cmp_num_to_value(left_key: str, expected_value, expected_label: str, eps=0.01):
        actual_value = _to_float(total_obj.get(left_key))
        expected_num = _to_float(expected_value)

        if actual_value is None:
            actual_value = 0
        if expected_num is None:
            expected_num = 0

        if abs(actual_value - expected_num) > eps:
            _append_total_error(
                total_obj,
                f"Total: {left_key} != {expected_label} ({actual_value} vs {expected_num})"
            )

    def _cmp_text(left_label: str, left_val, right_label: str, right_val):
        if _is_null(left_val) or _is_null(right_val):
            return
        if _normalize_compare_text(left_val) != _normalize_compare_text(right_val):
            _append_total_error(
                total_obj,
                f"Total: {left_label} != {right_label} ({left_val} vs {right_val})"
            )

    def _cmp_volume_num_with_unit_fallback(left_key: str, right_key: str, eps=None, factor=35.3147):
        lv = _to_float(total_obj.get(left_key))
        rv = _to_float(total_obj.get(right_key))
        if lv is None or rv is None:
            return False

        if eps is None:
            eps = max(0.01, max(abs(lv), abs(rv)) * 0.0001)

        if abs(lv - rv) <= eps:
            return True

        multiplied = rv * factor
        if abs(lv - multiplied) <= eps:
            return True

        divided = rv / factor
        if abs(lv - divided) <= eps:
            return True

        _append_total_error(
            total_obj,
            f"Total: {left_key} != {right_key} even after volume conversion check "
            f"({lv} vs {rv}; {right_key}*{factor}={multiplied}; {right_key}/{factor}={divided})"
        )
        return False

    # =========================
    # VALIDASI KHUSUS KOLOM TOTAL
    # Untuk multiple invoice: total per invoice dijumlahkan dulu
    # =========================
    for field in TOTAL_DETAIL_AGG_FIELDS:
        _cmp_num_to_value(
            field,
            aggregated_total_fields.get(field, 0),
            f"aggregated_detail[{field}]"
        )

    # existing checks
    _cmp_num("bl_package_count", "pl_package_count")

    _cmp_text(
        "bl_package_unit",
        total_obj.get("bl_package_unit"),
        "pl_package_unit",
        total_obj.get("pl_package_unit")
    )

    _cmp_num("bl_gw", "pl_gw")

    _cmp_text(
        "bl_gw_unit",
        total_obj.get("bl_gw_unit"),
        "pl_weight_unit",
        _first_non_null(detail_rows, "pl_weight_unit")
    )

    pl_total_volume = _to_float(total_obj.get("pl_total_volume"))
    if pl_total_volume is not None:
        volume_match = _cmp_volume_num_with_unit_fallback("bl_volume", "pl_total_volume")
    else:
        volume_match = _cmp_volume_num_with_unit_fallback("bl_volume", "pl_volume")

    bl_volume_unit = total_obj.get("bl_volume_unit")
    pl_volume_unit = _first_non_null(detail_rows, "pl_volume_unit")

    if not _is_null(bl_volume_unit) and not _is_null(pl_volume_unit):
        if _normalize_compare_text(bl_volume_unit) == _normalize_compare_text(pl_volume_unit):
            pass
        else:
            if not volume_match:
                _append_total_error(
                    total_obj,
                    f"Total: bl_volume_unit != pl_volume_unit ({bl_volume_unit} vs {pl_volume_unit})"
                )

    if total_obj.get("match_score") == "true":
        total_obj["match_description"] = "null"

    return total_data

def _normalize_alpha_lower(value):
    """
    Normalize dulu jadi huruf kecil dan hanya alphabet.
    Contoh:
    - 'CTN' -> 'ctn'
    - 'Cartons ' -> 'cartons'
    - 'PALLETS.' -> 'pallets'
    """
    if value is None:
        return ""

    s = str(value).strip()

    if s == "" or s.lower() == "null":
        return ""

    s = s.lower()
    s = re.sub(r"[^a-z]", "", s)  # hanya alphabet kecil

    return s

def _sanitize_pl_package_unit(value):
    """
    Compare pakai normalized value,
    tapi insert output final sesuai requirement.
    Kalau tidak ketemu mapping, kembalikan value asli.
    """
    if value is None:
        return "null"

    raw = str(value).strip()

    if raw == "" or raw.lower() == "null":
        return "null"

    normalized = _normalize_alpha_lower(raw)

    if normalized in PL_PACKAGE_UNIT_MAP:
        return PL_PACKAGE_UNIT_MAP[normalized]

    return raw

# tambahkan dekat area vendor-specific postprocess
FORCE_PL_VOLUME_X_PACKAGE_COUNT_VENDORS = {
    "jht",
}


def _should_force_pl_volume_x_package_count(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in FORCE_PL_VOLUME_X_PACKAGE_COUNT_VENDORS

def _pl_volume_total_tolerance(expected_total, ratio=0.25, abs_floor=0.01):
    """
    Toleransi compare pl_volume terhadap pl_total_volume.
    Default:
    - +/- 25% dari pl_total_volume
    - minimal 0.01 untuk rounding kecil
    """
    expected = _to_float(expected_total)

    if expected is None:
        return None

    return max(abs(expected) * ratio, abs_floor)


def _postprocess_pl_volume(rows: list, vendor_id: str = "default"):
    should_multiply = _should_force_pl_volume_x_package_count(vendor_id)

    print(
        f"[PL_VOLUME_POSTPROCESS] vendor_id={vendor_id} "
        f"should_multiply={should_multiply}"
    )

    if not should_multiply:
        return

    if not isinstance(rows, list) or not rows:
        return

    aggregated_total_fields = _aggregate_total_fields_from_detail_rows(rows or [])
    pl_total_volume = _to_float(aggregated_total_fields.get("pl_total_volume"))

    if pl_total_volume is None or pl_total_volume == 0:
        print(
            "[PL_VOLUME_POSTPROCESS][SKIP] "
            f"pl_total_volume unavailable/zero: {pl_total_volume}"
        )
        return

    raw_sum = 0.0
    multiplied_sum = 0.0
    valid_row_count = 0

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        pl_volume = _to_float(row.get("pl_volume"))
        pl_package_count = _to_float(row.get("pl_package_count"))

        if pl_volume is None:
            continue

        raw_sum += pl_volume

        if pl_package_count is not None and pl_package_count > 0:
            multiplied_sum += pl_volume * pl_package_count
        else:
            multiplied_sum += pl_volume

        valid_row_count += 1

    if valid_row_count == 0:
        print("[PL_VOLUME_POSTPROCESS][SKIP] no valid pl_volume rows")
        return

    tolerance = _pl_volume_total_tolerance(pl_total_volume, ratio=0.25)

    raw_diff = abs(raw_sum - pl_total_volume)
    multiplied_diff = abs(multiplied_sum - pl_total_volume)

    raw_matches = raw_diff <= tolerance
    multiplied_matches = multiplied_diff <= tolerance

    print(
        "[PL_VOLUME_POSTPROCESS][DECISION] "
        f"raw_sum={raw_sum} "
        f"multiplied_sum={multiplied_sum} "
        f"pl_total_volume={pl_total_volume} "
        f"tolerance={tolerance} "
        f"raw_diff={raw_diff} "
        f"multiplied_diff={multiplied_diff} "
        f"raw_matches={raw_matches} "
        f"multiplied_matches={multiplied_matches}"
    )

    # =========================================================
    # Pilih kandidat yang PALING DEKAT ke pl_total_volume.
    #
    # - raw_sum         = sum(pl_volume)
    # - multiplied_sum  = sum(pl_volume * pl_package_count)
    #
    # Jika multiplied lebih dekat, override pl_volume per row
    # menjadi pl_volume * pl_package_count.
    # Jika raw lebih dekat atau sama dekat, keep raw untuk avoid
    # double multiply.
    # =========================================================
    if multiplied_diff < raw_diff:
        print(
            "[PL_VOLUME_POSTPROCESS][APPLY_MULTIPLY_CLOSEST] "
            "sum(pl_volume * pl_package_count) is closer to pl_total_volume; "
            "override valid row pl_volume values"
        )

        for idx, row in enumerate(rows or [], start=1):
            if not isinstance(row, dict):
                continue

            pl_volume = _to_float(row.get("pl_volume"))
            pl_package_count = _to_float(row.get("pl_package_count"))

            if pl_volume is None or pl_package_count is None or pl_package_count <= 0:
                continue

            old_value = pl_volume
            new_value = pl_volume * pl_package_count
            row["pl_volume"] = new_value

            print(
                "[PL_VOLUME_POSTPROCESS][ROW_MULTIPLY_CLOSEST] "
                f"row_no={idx} "
                f"old_pl_volume={old_value} "
                f"pl_package_count={pl_package_count} "
                f"new_pl_volume={new_value}"
            )

        return

    print(
        "[PL_VOLUME_POSTPROCESS][KEEP_RAW_CLOSEST] "
        "sum(pl_volume) is closer or equal to pl_total_volume; keep raw values"
    )
    return

FORCE_CT_VENDORS = {
    "haomeng",
    "suntour_vietnam",
    "suntour_shenzhen",
}

def _should_force_ct_pl_package_unit(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in FORCE_CT_VENDORS


def _postprocess_pl_package_unit(rows: list, vendor_id: str = "default"):
    force_ct = _should_force_ct_pl_package_unit(vendor_id)

    print(f"[PL_PACKAGE_UNIT] vendor_id={vendor_id} force_ct={force_ct}")

    for row in rows:
        if not isinstance(row, dict):
            continue

        row["pl_package_unit"] = _sanitize_pl_package_unit(
            row.get("pl_package_unit")
        )

        if force_ct:
            row["pl_package_unit"] = "CT"

def _normalize_running_name(invoice_name: str) -> str:
    return str(invoice_name).strip().replace("/", "_").replace("\\", "_")

def _running_lock_path(invoice_name: str, report_type: str) -> str:
    safe_name = _normalize_running_name(invoice_name)
    return f"{TMP_PREFIX.rstrip('/')}/running/{report_type}/{safe_name}_{report_type}.lock"

def create_running_markers(invoice_name: str, with_total_container: bool):
    bucket = storage_client.bucket(BUCKET_NAME)

    report_types = ["detail"]
    if with_total_container:
        report_types.extend(["total", "container"])

    for report_type in report_types:
        blob_path = _running_lock_path(invoice_name, report_type)
        bucket.blob(blob_path).upload_from_string(
            "RUNNING",
            content_type="text/plain"
        )

def delete_running_markers(invoice_name: str, with_total_container: bool):
    bucket = storage_client.bucket(BUCKET_NAME)

    report_types = ["detail"]
    if with_total_container:
        report_types.extend(["total", "container"])

    for report_type in report_types:
        blob = bucket.blob(_running_lock_path(invoice_name, report_type))
        try:
            if blob.exists():
                blob.delete()
        except Exception:
            pass

# ============================== # JSON SAFE PARSER # ============================== 
def _parse_json_safe(raw_text):
    if not raw_text:
        raise Exception("Gemini returned empty response")

    s = raw_text.strip()

    # strip code fences kalau ada
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()

    # 1) coba direct
    try:
        return json.loads(s)
    except:
        pass

    # 2) cari JSON pertama yang valid (handle prefix "Here is ...")
    decoder = json.JSONDecoder()

    # PRIORITAS: coba mulai dari '[' dulu (array)
    idx_arr = s.find("[")
    if idx_arr != -1:
        try:
            obj, _ = decoder.raw_decode(s[idx_arr:])
            return obj
        except:
            pass

    # lalu coba mulai dari '{' (object)
    idx_obj = s.find("{")
    if idx_obj != -1:
        try:
            obj, _ = decoder.raw_decode(s[idx_obj:])
            return obj
        except:
            pass

    # 3) fallback regex: ARRAY dulu baru OBJECT
    match_arr = re.search(r"\[.*\]", s, re.DOTALL)
    if match_arr:
        try:
            return json.loads(match_arr.group())
        except:
            pass

    match_obj = re.search(r"\{.*\}", s, re.DOTALL)
    if match_obj:
        try:
            return json.loads(match_obj.group())
        except:
            pass

    raise Exception(f"Gemini output bukan JSON valid:\n{s[:1000]}")


# ==============================
# MERGE PDF
# ==============================

# ==============================
# MERGE PDF PAGES TO ONE PAGE
# ==============================

def _merge_pdf_pages_to_one_page(input_pdf: str, output_pdf: str, gap: float = 0):
    src = fitz.open(input_pdf)

    widths = [page.rect.width for page in src]
    heights = [page.rect.height for page in src]

    max_width = max(widths)
    total_height = sum(heights) + gap * (src.page_count - 1)

    out = fitz.open()
    new_page = out.new_page(width=max_width, height=total_height)

    current_y = 0
    for i, page in enumerate(src):
        rect = page.rect
        x0 = (max_width - rect.width) / 2
        target = fitz.Rect(x0, current_y, x0 + rect.width, current_y + rect.height)
        new_page.show_pdf_page(target, src, i)
        current_y += rect.height + gap

    out.save(output_pdf, garbage=4, deflate=True)
    out.close()
    src.close()


def _preprocess_invoice_or_pl_to_one_page(input_pdf: str, suffix_name: str):
    """
    Merge 1 file PDF multi-page menjadi 1 halaman panjang.
    Dipakai hanya untuk invoice dan packing list.
    """
    out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{suffix_name}_onepage.pdf")
    out.close()

    _merge_pdf_pages_to_one_page(
        input_pdf=input_pdf,
        output_pdf=out.name,
        gap=0
    )

    return out.name

# ==============================
# REMOVE TRULY BLANK PAGES
# ==============================

def _safe_get_object(obj):
    try:
        return obj.get_object()
    except Exception:
        return obj

def _page_has_text(page) -> bool:
    """
    Keep page kalau ada teks sekecil apa pun.
    Kalau text extraction error, pilih aman: anggap ada isi.
    """
    try:
        text = page.extract_text() or ""
        return bool(text.strip())
    except Exception:
        return True  # conservative: jangan hapus kalau ragu

def _page_has_annotations(page) -> bool:
    """
    Kalau ada annot/stamp/comment/form appearance, jangan dihapus.
    """
    try:
        annots = page.get("/Annots")
        return bool(annots)
    except Exception:
        return True  # conservative

def _page_has_xobject_or_image(page) -> bool:
    """
    Jangan hapus page yang punya image atau form XObject.
    Form XObject ikut dicek karena kadang image/isi page dibungkus di sana.
    """
    try:
        resources = _safe_get_object(page.get("/Resources"))
        if not resources:
            return False

        xobj = _safe_get_object(resources.get("/XObject"))
        if not xobj:
            return False

        for _, ref in xobj.items():
            obj = _safe_get_object(ref)
            if not obj:
                continue

            subtype = obj.get("/Subtype")
            if subtype in ("/Image", "/Form"):
                return True

        return False
    except Exception:
        return True  # conservative

def _page_has_nonempty_content_stream(page) -> bool:
    """
    Pure blank page biasanya tidak punya /Contents atau stream-nya benar-benar kosong.
    Kalau stream ada isinya sedikit pun, page dipertahankan.
    """
    try:
        contents = page.get_contents()
        if contents is None:
            return False

        # Bisa single stream atau list of streams
        if isinstance(contents, list):
            chunks = []
            for c in contents:
                c = _safe_get_object(c)
                if c is None:
                    continue
                data = c.get_data()
                if data:
                    chunks.append(data)
            raw = b"".join(chunks)
        else:
            contents = _safe_get_object(contents)
            raw = contents.get_data() if contents else b""

        if raw is None:
            return False

        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="ignore")

        return bool(raw.strip())
    except Exception:
        return True  # conservative

def _is_truly_blank_page(page) -> bool:
    """
    HANYA true kalau page benar-benar kosong.
    - Ada teks 1-2 kata? => TIDAK blank
    - Ada foto/image? => TIDAK blank
    - Ada anotasi/stamp? => TIDAK blank
    - Ada content stream sekecil apa pun? => TIDAK blank
    """
    if _page_has_text(page):
        return False

    if _page_has_annotations(page):
        return False

    if _page_has_xobject_or_image(page):
        return False

    if _page_has_nonempty_content_stream(page):
        return False

    return True

def _remove_truly_blank_pages(input_path: str) -> str:
    """
    Hapus hanya halaman yang benar-benar kosong dari PDF hasil merge.
    Jika tidak ada yang dihapus, return path asli.
    Jika semua halaman terdeteksi kosong, return path asli (fail-safe).
    """
    reader = PdfReader(input_path)
    writer = PdfWriter()

    removed_count = 0

    for page in reader.pages:
        if _is_truly_blank_page(page):
            removed_count += 1
            continue
        writer.add_page(page)

    # tidak ada halaman yang dihapus
    if removed_count == 0:
        return input_path

    # fail-safe: jangan hasilkan PDF kosong
    if len(writer.pages) == 0:
        return input_path

    out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    out.close()

    with open(out.name, "wb") as f:
        writer.write(f)

    return out.name

def _merge_pdfs(pdf_paths):
    merger = PdfMerger()

    for p in pdf_paths:
        merger.append(p)

    out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    out.close()

    merger.write(out.name)
    merger.close()

    cleaned_path = _remove_truly_blank_pages(out.name)

    # kalau hasil cleaning bikin file baru, hapus file merge mentah
    if cleaned_path != out.name:
        try:
            os.remove(out.name)
        except Exception:
            pass

    return cleaned_path

# ==============================
# COMPRESS PDF
# ==============================

def _compress_pdf_if_needed(input_path, max_mb=45):
    size_mb = os.path.getsize(input_path) / (1024 * 1024)

    if size_mb <= max_mb:
        return input_path

    compressed_path = input_path.replace(".pdf", "_compressed.pdf")

    cmd = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/ebook",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={compressed_path}",
        input_path,
    ]

    subprocess.run(cmd, check=True)

    return compressed_path

import csv
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment
from PyPDF2 import PdfReader

RAW_MARKUP_MARKERS = [
    "content-type:",
    "multipart/mixed",
    "quoted-printable",
    "<html",
    "<!doctype",
    "style type=",
    ".c0 {",
]

def _count_pdf_pages(pdf_path: str) -> int:
    reader = PdfReader(pdf_path)
    return len(reader.pages)

def _get_soffice_path() -> str:
    soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_path:
        raise Exception(
            "LibreOffice headless tidak ditemukan. "
            "Install libreoffice/soffice agar file xls/xlsx/csv bisa dikonversi ke PDF."
        )
    return soffice_path

def _run_soffice_convert(local_input_path: str, out_dir: str, convert_to: str):
    soffice_path = _get_soffice_path()

    profile_dir = tempfile.mkdtemp(prefix="lo-profile-")
    profile_uri = Path(profile_dir).as_uri()

    try:
        cmd = [
            soffice_path,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--nologo",
            "--nolockcheck",
            "--nodefault",
            "--convert-to", convert_to,
            "--outdir", out_dir,
            local_input_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(
                f"Gagal convert file ke PDF. stdout={result.stdout} stderr={result.stderr}"
            )
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

def _find_first_output_file(out_dir: str, ext: str) -> str:
    files = [
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.lower().endswith(ext.lower())
    ]
    if not files:
        raise Exception(f"Konversi selesai tapi file output {ext} tidak ditemukan.")
    files.sort()
    return files[0]

def _csv_to_xlsx(local_csv_path: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    with open(local_csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            ws.append(row)

    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    out_path = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx").name
    wb.save(out_path)
    return out_path

def _xls_to_xlsx(local_xls_path: str) -> str:
    out_dir = tempfile.mkdtemp(prefix="xls-to-xlsx-")
    _run_soffice_convert(local_xls_path, out_dir, "xlsx")
    return _find_first_output_file(out_dir, ".xlsx")

def _pdf_contains_raw_markup(pdf_path: str) -> bool:
    try:
        reader = PdfReader(pdf_path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:2]).lower()
        return any(marker in text for marker in RAW_MARKUP_MARKERS)
    except Exception:
        return False

def _validate_spreadsheet_pdf_result(pdf_path: str, source_name: str):
    total_pages = _count_pdf_pages(pdf_path)

    if total_pages == 0:
        raise Exception(f"Hasil convert PDF untuk '{source_name}' kosong.")

    if _pdf_contains_raw_markup(pdf_path):
        raise Exception(
            f"Hasil convert PDF untuk '{source_name}' masih berisi markup HTML/MIME."
        )

def _ensure_input_is_pdf(src_path: str) -> str:
    ext = Path(src_path).suffix.lower()

    if ext == ".pdf":
        return src_path

    if ext not in [".xls", ".xlsx", ".csv"]:
        raise Exception(f"Format file tidak didukung: {src_path}")

    temp_created = []

    try:
        source_for_pdf = src_path

        if ext == ".csv":
            source_for_pdf = _csv_to_xlsx(src_path)
            temp_created.append(source_for_pdf)

        elif ext == ".xls":
            source_for_pdf = _xls_to_xlsx(src_path)
            temp_created.append(source_for_pdf)

        out_dir = tempfile.mkdtemp(prefix="sheet-to-pdf-")
        temp_created.append(out_dir)

        _run_soffice_convert(
            source_for_pdf,
            out_dir,
            "pdf:calc_pdf_Export"
        )

        produced_pdf = _find_first_output_file(out_dir, ".pdf")

        final_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        final_pdf.close()
        shutil.copy2(produced_pdf, final_pdf.name)

        _validate_spreadsheet_pdf_result(final_pdf.name, os.path.basename(src_path))

        return final_pdf.name

    except Exception:
        for p in temp_created:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        raise

# ==============================
# UPLOAD PDF TO GCS
# ==============================

def _upload_temp_pdf_to_gcs(local_path: str, run_prefix: str, name: str) -> str:
    bucket = storage_client.bucket(BUCKET_NAME)
    blob_path = f"{run_prefix}/inputs/{name}.pdf"
    bucket.blob(blob_path).upload_from_filename(local_path)
    return f"gs://{BUCKET_NAME}/{blob_path}"

def _extract_text_from_gemini_response(response):
    # 1) shortcut kalau SDK punya .text
    try:
        if getattr(response, "text", None):
            return response.text.strip()
    except Exception:
        pass

    # 2) telusuri candidates -> content -> parts -> text
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                txt = getattr(part, "text", None)
                if txt and str(txt).strip():
                    return str(txt).strip()
    except Exception:
        pass

    return ""


def _get_obj_value(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj.get(name)
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _clamp(value, low, high):
    return max(low, min(high, value))

def _is_nonempty_issue_text(value) -> bool:
    if value is None:
        return False

    s = str(value).strip().lower()
    return s not in {"", "null", "none"}


def _row_has_hard_issue(row: dict) -> bool:
    """
    Hard issue = bukti keras row bermasalah.
    """
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().lower()
    match_description = row.get("match_description")

    if match_score == "false":
        return True

    if _is_nonempty_issue_text(match_description):
        return True

    return False


def _has_total_issue(total_data) -> bool:
    if total_data is None:
        return False

    if isinstance(total_data, dict):
        total_data = [total_data]

    if not isinstance(total_data, list) or not total_data:
        return False

    total_row = total_data[0]
    if not isinstance(total_row, dict):
        return False

    match_score = str(total_row.get("match_score", "")).strip().lower()
    match_description = total_row.get("match_description")

    if match_score == "false":
        return True

    if _is_nonempty_issue_text(match_description):
        return True

    return False

def _split_match_description_messages(value):
    if value is None:
        return []

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return []

    return [part.strip() for part in re.split(r"\s*;\s*", s) if part and part.strip()]


def _is_total_issue_message(msg: str) -> bool:
    s = str(msg or "").strip().lower()

    if not s:
        return False

    if s.startswith("total:"):
        return True

    total_keywords = [
        "total_quantity mismatch",
        "total_amount mismatch",
        "total_nw mismatch",
        "total_gw mismatch",
        "total_volume mismatch",
        "total_package mismatch",
    ]

    return any(keyword in s for keyword in total_keywords)


def _row_has_non_total_issue(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().lower()
    match_description = row.get("match_description")

    if match_score != "false":
        return False

    messages = _split_match_description_messages(match_description)
    if not messages:
        return True

    return any(not _is_total_issue_message(msg) for msg in messages)


def _row_has_total_issue_only(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().lower()
    match_description = row.get("match_description")

    if match_score != "false":
        return False

    messages = _split_match_description_messages(match_description)
    if not messages:
        return False

    return all(_is_total_issue_message(msg) for msg in messages)


def _finalize_audit_confidence_labels(rows: list, total_attribution=None):
    """
    Final rule:

    1) Jika ada NON-TOTAL issue -> NEGATIVE
    2) Jika issue TOTAL dan culprit berhasil ditemukan:
       - culprit row -> NEGATIVE
       - row lain di invoice yang sama -> POSITIVE
    3) Jika issue TOTAL tapi culprit belum ketemu yakin:
       - NEUTRAL
    4) Jika tidak ada issue apa pun -> POSITIVE
    """
    if not isinstance(rows, list):
        return rows

    total_attribution = total_attribution or {}
    total_issue_groups = set(total_attribution.get("total_issue_groups", []))
    culprit_row_nos = set(total_attribution.get("culprit_row_nos", []))
    culprit_groups = set(total_attribution.get("culprit_groups", []))

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        invoice_group = _get_detail_total_group_key(row, idx)
        row_no = _safe_row_no_int(row)

        row["confidence_label"] = "positive"

        if _row_has_non_total_issue(row):
            row["confidence_label"] = "negative"
            continue

        if invoice_group in total_issue_groups:
            if invoice_group in culprit_groups:
                if row_no is not None and row_no in culprit_row_nos:
                    row["confidence_label"] = "negative"
                else:
                    row["confidence_label"] = "positive"
            else:
                row["confidence_label"] = "neutral"
            continue

        if _row_has_total_issue_only(row):
            row["confidence_label"] = "neutral"
            continue

        row["confidence_label"] = "positive"

    return rows


def _normalize_confidence_band(value: str) -> str:
    s = str(value or "").strip().upper()
    if s in DETAIL_CONFIDENCE_ENUM_VALUES:
        return s
    m = re.search(r"[1-5]", s)
    return m.group(0) if m else ""


def _extract_confidence_logprob_from_response(response):
    candidates = _get_obj_value(response, "candidates", default=[]) or []
    if not candidates:
        return None

    first_candidate = candidates[0]
    logprobs_result = _get_obj_value(first_candidate, "logprobs_result", "logprobsResult")

    chosen_candidates = _get_obj_value(
        logprobs_result,
        "chosen_candidates",
        "chosenCandidates",
        default=[]
    ) or []

    for chosen in chosen_candidates:
        token = _get_obj_value(chosen, "token", default="")
        logprob = _get_obj_value(chosen, "log_probability", "logProbability")
        if logprob is None:
            continue
        if str(token).strip() == "":
            continue
        try:
            return float(logprob)
        except Exception:
            continue

    avg_logprobs = _get_obj_value(first_candidate, "avg_logprobs", "avgLogprobs")
    if avg_logprobs is not None:
        try:
            return float(avg_logprobs)
        except Exception:
            pass

    return None


def _fallback_confidence_score(row: dict) -> int:
    return 78 if str(row.get("match_score", "")).strip().lower() == "true" else 35


def _confidence_score_from_band_and_logprob(band: str, chosen_logprob, match_score: str):
    band = _normalize_confidence_band(band)
    if not band:
        return 0

    low, high = DETAIL_CONFIDENCE_SCORE_RANGES.get(band, (0, 0))

    probability = 0.5
    if chosen_logprob is not None:
        try:
            probability = math.exp(float(chosen_logprob))
        except Exception:
            probability = 0.5

    probability = _clamp(probability, 0.0, 1.0)
    score = int(round(low + ((high - low) * probability)))
    score = _clamp(score, 1, 100)

    if str(match_score or "").strip().lower() == "false":
        score = min(score, 49)

    return score


def _build_detail_confidence_row_payload(row: dict) -> dict:
    excluded_fields = {"confidence_score", "confidence_band", "confidence_logprob"}

    preferred_order = [
        "_detail_row_no",
        "match_score",
        "match_description",
        "inv_invoice_no",
        "pl_invoice_no",
        "coo_invoice_no",
    ] + [k for k in DETAIL_LINE_FIELDS if k not in excluded_fields]

    payload = {}
    seen = set()

    for key in preferred_order:
        if key in seen:
            continue
        seen.add(key)

        if key not in row:
            continue

        value = row.get(key)

        if key in DETAIL_LINE_NUM_FIELDS:
            if value is None:
                value = 0
        else:
            if value is None:
                value = "null"

        payload[key] = value

    return payload


def _build_detail_confidence_prompt(row: dict) -> str:
    row_payload = _build_detail_confidence_row_payload(row)
    row_json = json.dumps(row_payload, ensure_ascii=False, indent=2)

    return f"""
ROLE:
Anda adalah AI reviewer untuk menilai 1 line item hasil ekstraksi.
PDF pada request ini adalah source of truth utama.

TUGAS:
Klasifikasikan row ini menjadi:
- positive = row ini benar / cocok secara keseluruhan terhadap PDF
- negative = row ini tidak cukup yakin, salah mapping, salah angka, salah pasangan row, atau gagal validasi

ATURAN:
- Nilai confidence adalah untuk KESELURUHAN row, bukan per-field.
- Missing value boleh tetap positive jika memang value itu tidak ada di dokumen.
- Jika match_score=false atau match_description berisi error validasi, negative lebih tepat kecuali bukti PDF sangat kuat.
- Output HARUS hanya salah satu enum ini: positive / negative

ROW JSON:
{row_json}
""".strip()


def _call_gemini_uri(file_uri: str, prompt: str, extra_config: dict = None, return_response: bool = False):
    parts = [
        types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
        types.Part.from_text(text=prompt),
    ]

    config_kwargs = {
        "temperature": 0,
        "top_p": 0,
        "seed": 42,
        "candidate_count": 1,
        "max_output_tokens": 65535,
    }
    if extra_config:
        config_kwargs.update(extra_config)

    response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(**config_kwargs),
    )

    if not response:
        raise Exception("Empty response from Gemini")

    print(f"(Gemini Run ID: {response.response_id})")

    try:
        candidates = getattr(response, "candidates", None)
        print(f"[GEMINI_DEBUG] candidates_count={0 if not candidates else len(candidates)}")

        if candidates:
            c0 = candidates[0]
            print(f"[GEMINI_DEBUG] finish_reason={getattr(c0, 'finish_reason', None)}")
            print(f"[GEMINI_DEBUG] safety_ratings={getattr(c0, 'safety_ratings', None)}")

            content = getattr(c0, "content", None)
            parts_obj = getattr(content, "parts", None) if content else None
            print(f"[GEMINI_DEBUG] parts={parts_obj}")
    except Exception as dbg_e:
        print(f"[GEMINI_DEBUG] failed_to_dump_response={repr(dbg_e)}")

    text_output = _extract_text_from_gemini_response(response)
    if not text_output:
        raise Exception("Gemini response tidak mengandung text")

    if return_response:
        return text_output, response

    return text_output

def _call_gemini_response_uri(file_uri: str, prompt: str, extra_config: dict = None):
    parts = [
        types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
        types.Part.from_text(text=prompt),
    ]

    config_kwargs = {
        "temperature": 0,
        "top_p": 0,
        "seed": 42,
        "candidate_count": 1,
        "max_output_tokens": 65535,
    }
    if extra_config:
        config_kwargs.update(extra_config)

    response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(**config_kwargs),
    )

    if not response:
        raise Exception("Empty response from Gemini")

    print(f"(Gemini Run ID: {response.response_id})")
    return response

def _call_gemini_json_uri(file_uri: str, prompt: str, expect_array: bool = False, retries: int = 3):
    """
    Wrapper: panggil Gemini -> pastikan output JSON valid.
    - expect_array=True  : kalau Gemini balikin dict, kita bungkus jadi [dict]
    - retries: retry jika output bukan JSON / quota / text kosong
    """
    p = prompt
    for attempt in range(1, retries + 1):
        try:
            raw = _call_gemini_uri(file_uri, p)
            obj = _parse_json_safe(raw)

            if expect_array and isinstance(obj, dict):
                obj = [obj]

            return obj

        except Exception as e:
            msg = str(e).lower()

            if "gemini response tidak mengandung text" in msg:
                time.sleep(0.8 * attempt)
                continue

            if ("bukan json valid" in msg) or ("not json" in msg) or ("not valid json" in msg):
                p = prompt + """
                PENTING:
                - Output HANYA JSON valid, tanpa teks lain.
                - Jika ARRAY: WAJIB mulai '[' dan akhir ']'
                - Jika OBJECT: WAJIB mulai '{' dan akhir '}'
                - Jika data tidak ditemukan: isi "null" / 0 sesuai skema
                """
                time.sleep(0.5 * attempt)
                continue

            if ("429" in msg) or ("resource_exhausted" in msg) or ("rate" in msg) or ("quota" in msg):
                time.sleep((2 ** attempt) + random.random())
                continue

            raise

    raise Exception("Gemini gagal menghasilkan JSON setelah retry")

def _build_detail_batch_contract_prompt(
    batch_no: int,
    expected_indices: list,
    first_index: int,
    last_index: int,
) -> str:
    return f"""

KONTRAK OUTPUT DETAIL BATCH — WAJIB DIIKUTI:
- Ini adalah batch_no={batch_no}.
- Range line item batch ini adalah {first_index} sampai {last_index}.
- Output HARUS berupa JSON ARRAY valid.
- Output HARUS berisi tepat {len(expected_indices)} object.
- WAJIB ada satu object untuk setiap _expected_index berikut:
  {expected_indices}
- Setiap object WAJIB memiliki field "_expected_index" bertipe number.
- Nilai "_expected_index" WAJIB sama dengan nomor line item yang diekstrak.
- Jangan skip line item.
- Jangan gabungkan beberapa line item menjadi satu object.
- Jangan membuat summary.
- Jangan menghapus row walaupun sebagian field kosong.
- Jika suatu field tidak ditemukan di dokumen:
  - field string isi "null"
  - field number isi 0
"""


def _get_row_expected_index(row: dict):
    if not isinstance(row, dict):
        return None

    candidate_keys = [
        "_expected_index",
        "expected_index",
        "line_item_index",
        "index",
        "row_index",
    ]

    for key in candidate_keys:
        try:
            value = row.get(key)
            if value is None:
                continue
            return int(value)
        except Exception:
            continue

    return None


def _validate_detail_batch_rows(
    json_array,
    batch_no: int,
    expected_indices: list,
):
    if isinstance(json_array, dict):
        raise Exception(
            f"Batch {batch_no} returned dict, expected JSON array "
            f"with {len(expected_indices)} rows"
        )

    if not isinstance(json_array, list):
        raise Exception("Batch result bukan array")

    expected_set = set(int(x) for x in expected_indices)

    got_indices = []
    missing_index_field_rows = []

    for pos, row in enumerate(json_array, start=1):
        idx = _get_row_expected_index(row)

        if idx is None:
            missing_index_field_rows.append(pos)
            continue

        got_indices.append(idx)

    got_set = set(got_indices)

    missing = sorted(expected_set - got_set)
    extra = sorted(got_set - expected_set)
    duplicate = sorted({
        idx for idx in got_indices
        if got_indices.count(idx) > 1
    })

    errors = []

    if len(json_array) != len(expected_indices):
        errors.append(
            f"expected_count={len(expected_indices)} actual_count={len(json_array)}"
        )

    if missing_index_field_rows:
        errors.append(
            f"rows_missing_expected_index={missing_index_field_rows}"
        )

    if missing:
        errors.append(f"missing_indices={missing}")

    if extra:
        errors.append(f"extra_indices={extra}")

    if duplicate:
        errors.append(f"duplicate_indices={duplicate}")

    if errors:
        raise Exception(
            f"DETAIL_BATCH_COUNT_MISMATCH batch_no={batch_no}; "
            + "; ".join(errors)
        )

    for row in json_array:
        row["_expected_index"] = int(_get_row_expected_index(row))

    json_array.sort(key=lambda r: int(r.get("_expected_index")))

    return json_array

def _run_one_detail_batch(
    file_uri_detail: str,
    run_prefix: str,
    batch_no: int,
    prompt: str,
    first_index: int,
    last_index: int,
    expected_indices: list,
):
    base_contract = _build_detail_batch_contract_prompt(
        batch_no=batch_no,
        expected_indices=expected_indices,
        first_index=first_index,
        last_index=last_index,
    )

    p = prompt + base_contract
    last_error = None

    for attempt in range(1, 5):
        try:
            raw = _call_gemini_uri(file_uri_detail, p)
            json_array = _parse_json_safe(raw)

            json_array = _validate_detail_batch_rows(
                json_array=json_array,
                batch_no=batch_no,
                expected_indices=expected_indices,
            )

            _save_batch_tmp(run_prefix, batch_no, json_array)

            print(
                f"[DETAIL_BATCH_OK] "
                f"batch_no={batch_no} "
                f"expected={len(expected_indices)} "
                f"actual={len(json_array)} "
                f"indices={[r.get('_expected_index') for r in json_array]}"
            )

            return (batch_no, json_array)

        except Exception as e:
            last_error = e
            msg = str(e).lower()

            is_json_error = (
                "bukan json valid" in msg
                or "not json" in msg
                or "not valid json" in msg
                or "batch result bukan array" in msg
                or "returned dict" in msg
            )

            is_count_error = "detail_batch_count_mismatch" in msg

            is_quota_error = (
                "429" in msg
                or "resource_exhausted" in msg
                or "rate" in msg
                or "quota" in msg
            )

            print(
                f"[DETAIL_BATCH_RETRY] "
                f"batch_no={batch_no} "
                f"attempt={attempt} "
                f"error={e}"
            )

            if is_quota_error:
                time.sleep((2 ** attempt) + random.random())
                continue

            if is_json_error or is_count_error:
                p = prompt + base_contract + f"""

OUTPUT SEBELUMNYA SALAH DAN HARUS DIULANG.

ERROR:
{str(e)}

PERBAIKI:
- Output HARUS JSON ARRAY valid.
- Output HARUS tepat {len(expected_indices)} object.
- Setiap object WAJIB punya "_expected_index".
- _expected_index yang wajib ada:
  {expected_indices}
- Jangan return object tunggal.
- Jangan skip row.
- Jangan merge row.
- Jangan summary.
"""
                time.sleep(0.8 * attempt)
                continue

            raise

    raise Exception(
        f"Batch {batch_no} gagal menghasilkan row lengkap setelah retry. "
        f"range={first_index}-{last_index}, "
        f"expected_count={len(expected_indices)}, "
        f"last_error={last_error}"
    )

# ==============================
# SAVE BATCH TMP
# ==============================

def _save_batch_tmp(run_prefix: str, batch_no: int, json_array: list):
    if not isinstance(json_array, list):
        raise Exception("Batch result bukan array")

    bucket = storage_client.bucket(BUCKET_NAME)
    blob_path = f"{run_prefix}/batches/batch_{batch_no}.json"

    bucket.blob(blob_path).upload_from_string(
        json.dumps(json_array, indent=2),
        content_type="application/json"
    )

def _save_run_meta(run_prefix: str, invoice_name: str, with_total_container: bool):
    bucket = storage_client.bucket(BUCKET_NAME)
    payload = {
        "invoice_name": invoice_name,
        "with_total_container": bool(with_total_container),
    }
    bucket.blob(f"{run_prefix}/meta.json").upload_from_string(
        json.dumps(payload),
        content_type="application/json"
    )

# ==============================
# GET PO JSON URI (DIRECT FROM GCS)
# ==============================

def _get_po_json_uri():

    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=f"{PO_PREFIX}/"))

    json_files = [
        b for b in blobs
        if b.name.endswith(".json") and not b.name.endswith("/")
    ]

    if not json_files:
        raise Exception("PO JSON tidak ditemukan di folder po/")

    if len(json_files) > 1:
        raise Exception("Lebih dari 1 PO JSON ditemukan. Harus hanya 1 file.")

    po_blob = json_files[0]

    # 🔥 LANGSUNG RETURN URI ASLI
    return f"gs://{BUCKET_NAME}/{po_blob.name}"

# ==============================
# FILTER PO JSON
# ==============================

def _norm_po_number(x):
    if x is None:
        return ""
    s = str(x).strip()
    s = re.sub(r"\D", "", s)  # ambil angka saja
    return s.lstrip("0")      # buang leading zero

def _stream_filter_po_lines(target_po_numbers):
    target_po_numbers = {
        _norm_po_number(x)
        for x in (target_po_numbers or set())
        if x is not None
    }

    po_uri = _get_po_json_uri()
    parsed = urlparse(po_uri)

    bucket = storage_client.bucket(parsed.netloc)
    blob = bucket.blob(parsed.path.lstrip("/"))

    matched = []
    with blob.open("rb") as f:
        for item in ijson.items(f, "item"):
            po_no = item.get("po_no")
            if po_no is None:
                continue

            if _norm_po_number(po_no) in target_po_numbers:
                matched.append(item)

    return matched

# ==============================
# PO MAPPING
# ==============================

def _norm_key(x):
    if x is None:
        return ""
    s = str(x).strip().upper()
    s = re.sub(r"\s+", "", s)          # hapus spasi
    s = re.sub(r"[^A-Z0-9]", "", s)    # hapus dash, slash, dll
    return s

def _norm_desc(x):
    """
    Normalisasi description/text untuk matching.
    - uppercase
    - buang spasi & karakter non-alphanumeric
    """
    if x is None:
        return ""
    s = str(x).strip().upper()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def _get_extracted_qty_for_po(row: dict):
    """
    Prioritas quantity untuk logic PO:
    1) inv_quantity
    2) pl_quantity
    """
    if not isinstance(row, dict):
        return None

    q = _to_float(row.get("inv_quantity"))
    if q is not None:
        return q

    q = _to_float(row.get("pl_quantity"))
    if q is not None:
        return q

    return None


def _copy_po_line_with_allocated_qty(po_line: dict, allocated_qty):
    """
    Copy PO line dan isi po_quantity dengan qty yang benar-benar teralokasi ke row ini,
    BUKAN sisa.
    """
    copied = dict(po_line or {})

    if allocated_qty is None:
        copied["po_quantity"] = po_line.get("po_quantity", "null") if isinstance(po_line, dict) else "null"
        return copied

    if abs(allocated_qty - round(allocated_qty)) <= 1e-9:
        copied["po_quantity"] = int(round(allocated_qty))
    else:
        copied["po_quantity"] = allocated_qty

    return copied


def _pick_closest_remaining_candidate(candidates, target_qty):
    """
    candidates: list of dict
      {
        "idx": int,
        "line": dict,
        "remaining_qty": float
      }

    Rule:
    - pilih remaining_qty yang paling dekat ke target_qty
    - tie-break: remaining_qty lebih besar menang
    - tie-break akhir: idx lebih kecil menang
    """
    if not candidates:
        return None

    if target_qty is None:
        return sorted(
            candidates,
            key=lambda x: (
                float("inf") if x.get("remaining_qty") is None else -x.get("remaining_qty", 0),
                x["idx"]
            )
        )[0]

    def _sort_key(item):
        remaining_qty = item.get("remaining_qty")
        if remaining_qty is None:
            return (float("inf"), float("inf"), item["idx"])

        return (
            abs(remaining_qty - target_qty),
            -remaining_qty,
            item["idx"],
        )

    return sorted(candidates, key=_sort_key)[0]


def _po_line_sort_key(po_line: dict):
    raw = po_line.get("po_line")
    try:
        return (0, int(str(raw).strip()))
    except Exception:
        return (1, str(raw or ""))

PO_ITEM_NO_FIELDS = [
    "vendor_article_no",
    "po_vendor_article_no",
    "sap_article_no",
    "po_sap_article_no",
]

ITEM_CODE_CONFUSABLE_MAP = {
    "0": ["0", "O", "Q", "D"],
    "O": ["O", "0", "Q", "D"],
    "Q": ["Q", "0", "O"],
    "D": ["D", "0", "O"],

    "1": ["1", "I", "L"],
    "I": ["I", "1", "L"],
    "L": ["L", "1", "I"],

    "2": ["2", "Z"],
    "Z": ["Z", "2"],

    "5": ["5", "S"],
    "S": ["S", "5"],

    "6": ["6", "G"],
    "G": ["G", "6"],

    "8": ["8", "B"],
    "B": ["B", "8"],
}

ITEM_CODE_CONFUSABLE_GROUPS = [
    ("0", "O", "Q", "D"),
    ("1", "I", "L"),
    ("2", "Z"),
    ("5", "S"),
    ("6", "G"),
    ("8", "B"),
]

ITEM_CODE_CANONICAL_MAP = {}
for group in ITEM_CODE_CONFUSABLE_GROUPS:
    canonical = group[0]
    for ch in group:
        ITEM_CODE_CANONICAL_MAP[ch] = canonical

MAX_ITEM_CODE_VARIANTS = 128


def _norm_item_code_signature(x):
    s = _norm_key(x)
    if not s:
        return ""

    out = []
    for ch in s:
        out.append(ITEM_CODE_CANONICAL_MAP.get(ch, ch))
    return "".join(out)


def _generate_confusable_item_code_variants(value, max_variants=MAX_ITEM_CODE_VARIANTS):
    s = _norm_key(value)
    if not s:
        return []

    char_options = []
    for ch in s:
        options = ITEM_CODE_CONFUSABLE_MAP.get(ch, [ch])

        dedup = []
        seen = set()
        for opt in options:
            if opt not in seen:
                seen.add(opt)
                dedup.append(opt)

        char_options.append(dedup)

    variants = []
    current = []

    def dfs(idx):
        if len(variants) >= max_variants:
            return

        if idx >= len(char_options):
            variants.append("".join(current))
            return

        for opt in char_options[idx]:
            current.append(opt)
            dfs(idx + 1)
            current.pop()

            if len(variants) >= max_variants:
                return

    dfs(0)

    exact = _norm_key(value)
    ordered = []
    seen = set()

    if exact:
        ordered.append(exact)
        seen.add(exact)

    for v in variants:
        if not v or v in seen:
            continue
        ordered.append(v)
        seen.add(v)

    return ordered


def _item_code_similarity(left, right):
    l_exact = _norm_key(left)
    r_exact = _norm_key(right)

    if not l_exact or not r_exact:
        return 0.0

    if l_exact == r_exact:
        return 1.0

    l_sig = _norm_item_code_signature(left)
    r_sig = _norm_item_code_signature(right)

    if l_sig and r_sig and l_sig == r_sig:
        return 0.98

    return SequenceMatcher(None, l_exact, r_exact).ratio()


def _extract_po_item_no_entries(line: dict):
    entries = []
    seen_exact = set()

    if not isinstance(line, dict):
        return entries

    for field in PO_ITEM_NO_FIELDS:
        raw = line.get(field)
        exact = _norm_key(raw)
        if not exact:
            continue
        if exact in seen_exact:
            continue

        seen_exact.add(exact)

        entries.append({
            "field": field,
            "raw_item_no": str(raw).strip(),
            "exact_key": exact,
            "signature_key": _norm_item_code_signature(raw),
        })

    return entries


def _get_primary_po_item_no(line: dict):
    for field in PO_ITEM_NO_FIELDS:
        raw = line.get(field) if isinstance(line, dict) else None
        if not _is_null(raw):
            return str(raw).strip()
    return "null"


def _dedup_po_candidate_entries(entries):
    deduped = []
    seen = set()

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue

        key = (
            entry.get("idx"),
            entry.get("matched_field"),
            entry.get("raw_item_no"),
            _norm_po_number(entry.get("line", {}).get("po_no")) if isinstance(entry.get("line"), dict) else "",
            str(entry.get("line", {}).get("po_line")) if isinstance(entry.get("line"), dict) else "",
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(entry)

    return deduped


def _build_po_item_indexes(po_lines):
    po_article_exact_index = {}
    po_article_signature_index = {}
    po_desc_index = {}

    for idx, line in enumerate(po_lines or []):
        po_no_norm = _norm_po_number(line.get("po_no"))
        if not po_no_norm:
            continue

        for item_entry in _extract_po_item_no_entries(line):
            entry = {
                "idx": idx,
                "line": dict(line),
                "matched_field": item_entry["field"],
                "raw_item_no": item_entry["raw_item_no"],
                "exact_key": item_entry["exact_key"],
                "signature_key": item_entry["signature_key"],
            }

            po_article_exact_index.setdefault(
                (po_no_norm, item_entry["exact_key"]), []
            ).append(entry)

            if item_entry["signature_key"]:
                po_article_signature_index.setdefault(
                    (po_no_norm, item_entry["signature_key"]), []
                ).append(entry)

        d_norm = _norm_desc(line.get("po_text"))
        if d_norm:
            po_desc_index.setdefault((po_no_norm, d_norm), []).append({
                "idx": idx,
                "line": dict(line),
                "matched_field": "po_text",
                "raw_item_no": _get_primary_po_item_no(line),
                "exact_key": _norm_key(_get_primary_po_item_no(line)),
                "signature_key": _norm_item_code_signature(_get_primary_po_item_no(line)),
            })

    return po_article_exact_index, po_article_signature_index, po_desc_index


def _lookup_po_candidates_by_item_code(
    po_no_norm: str,
    raw_item_code,
    po_article_exact_index,
    po_article_signature_index,
):
    exact_key = _norm_key(raw_item_code)
    signature_key = _norm_item_code_signature(raw_item_code)

    candidates = []

    if exact_key:
        candidates.extend(
            po_article_exact_index.get((po_no_norm, exact_key), [])
        )

    for variant in _generate_confusable_item_code_variants(raw_item_code):
        if not variant or variant == exact_key:
            continue

        candidates.extend(
            po_article_exact_index.get((po_no_norm, variant), [])
        )

    if signature_key:
        candidates.extend(
            po_article_signature_index.get((po_no_norm, signature_key), [])
        )

    return _dedup_po_candidate_entries(candidates)


def _group_candidates_by_raw_item_no(candidates):
    grouped = {}
    for entry in candidates or []:
        raw_item_no = entry.get("raw_item_no") or "null"
        grouped.setdefault(raw_item_no, []).append(entry)
    return grouped


def _resolve_confusable_candidates(candidates, source_item_code, inv_desc_norm, extracted_qty):
    candidates = _dedup_po_candidate_entries(candidates)
    if not candidates:
        return []

    grouped = _group_candidates_by_raw_item_no(candidates)

    if len(grouped) == 1:
        return candidates

    if inv_desc_norm:
        desc_hits = [
            c for c in candidates
            if _norm_desc(c.get("line", {}).get("po_text")) == inv_desc_norm
        ]
        desc_grouped = _group_candidates_by_raw_item_no(desc_hits)
        if desc_hits and len(desc_grouped) == 1:
            return desc_hits

    if extracted_qty is not None:
        qty_hits = []
        for c in candidates:
            po_qty = _to_float(c.get("line", {}).get("po_quantity"))
            if po_qty is None:
                continue
            if abs(po_qty - extracted_qty) <= 1e-9:
                qty_hits.append(c)

        qty_grouped = _group_candidates_by_raw_item_no(qty_hits)
        if qty_hits and len(qty_grouped) == 1:
            return qty_hits

    ranked = []
    for raw_item_no, group in grouped.items():
        sim = _item_code_similarity(source_item_code, raw_item_no)
        ranked.append((sim, raw_item_no, group))

    ranked = sorted(ranked, key=lambda x: x[0], reverse=True)

    if ranked:
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        if top[0] >= 0.92 and (second is None or (top[0] - second[0]) >= 0.03):
            return top[2]

    return []


def _copy_po_line_with_allocated_qty(po_line: dict, allocated_qty):
    copied = dict(po_line or {})

    if allocated_qty is None:
        copied["po_quantity"] = po_line.get("po_quantity", "null") if isinstance(po_line, dict) else "null"
        return copied

    if abs(allocated_qty - round(allocated_qty)) <= 1e-9:
        copied["po_quantity"] = int(round(allocated_qty))
    else:
        copied["po_quantity"] = allocated_qty

    return copied

def _get_best_po_article_value(po_line: dict):
    if not isinstance(po_line, dict):
        return "null"

    for key in [
        "vendor_article_no",
        "po_vendor_article_no",
        "sap_article_no",
        "po_sap_article_no",
    ]:
        value = po_line.get(key)
        if not _is_null(value):
            return str(value).strip()

    return "null"


def _get_mapped_po_no_from_result_rows(result_rows: list):
    for row in result_rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("_po_mapped") != True:
            continue

        po_data = row.get("_po_data")
        if isinstance(po_data, dict) and not _is_null(po_data.get("po_no")):
            return str(po_data.get("po_no")).strip()

    return "null"


def _same_invoice_context_for_neighbor_po(current_row: dict, neighbor_row: dict) -> bool:
    if not isinstance(current_row, dict) or not isinstance(neighbor_row, dict):
        return False

    compare_keys = [
        "inv_invoice_no",
        "pl_invoice_no",
        "coo_invoice_no",
    ]

    for key in compare_keys:
        a = _norm_key(current_row.get(key))
        b = _norm_key(neighbor_row.get(key))
        if a and b:
            return a == b

    # fallback longgar kalau header invoice_no tidak ada
    a_date = str(current_row.get("inv_invoice_date", "")).strip()
    b_date = str(neighbor_row.get("inv_invoice_date", "")).strip()

    if a_date and b_date and a_date == b_date:
        return True

    return False

ITEM_CODE_COMPARE_CANONICAL_MAP = {
    "8": "8",
    "B": "8",

    "0": "0",
    "O": "0",
    "Q": "0",
    "D": "0",

    "1": "1",
    "I": "1",
    "L": "1",

    "2": "2",
    "Z": "2",

    "5": "5",
    "S": "5",

    "6": "6",
    "G": "6",
}

def _norm_item_compare_key(value):
    s = _norm_key(value)
    if not s:
        return ""

    out = []
    for ch in s:
        out.append(ITEM_CODE_COMPARE_CANONICAL_MAP.get(ch, ch))
    return "".join(out)

def _build_po_indexes(po_lines):
    po_article_index = {}
    po_desc_index = {}

    for idx, line in enumerate(po_lines or []):
        if not isinstance(line, dict):
            continue

        po_no_norm = _norm_po_number(line.get("po_no"))
        if not po_no_norm:
            continue

        article_values = [
            line.get("vendor_article_no"),
            line.get("po_vendor_article_no"),
            line.get("sap_article_no"),
            line.get("po_sap_article_no"),
        ]

        for article_value in article_values:
            a_norm = _norm_item_compare_key(article_value)
            if a_norm:
                po_article_index.setdefault((po_no_norm, a_norm), []).append((idx, line))

        d_norm = _norm_desc(line.get("po_text"))
        if d_norm:
            po_desc_index.setdefault((po_no_norm, d_norm), []).append((idx, line))

    return po_article_index, po_desc_index


def _map_single_detail_row_to_po(
    row,
    po_article_index,
    po_desc_index,
    remaining_state,
):
    if not isinstance(row, dict):
        return [row], False

    inv_po_norm = _norm_po_number(row.get("inv_customer_po_no"))
    inv_article_norm = _norm_item_compare_key(row.get("inv_spart_item_no"))
    pl_article_norm = _norm_item_compare_key(row.get("pl_item_no"))
    inv_desc_norm = _norm_desc(row.get("inv_description"))
    extracted_qty = _get_extracted_qty_for_po(row)

    if not inv_po_norm:
        failed_row = dict(row)
        failed_row["_po_mapped"] = False
        return [failed_row], False

    matched_by = None
    bucket_key = None
    candidates = []

    if inv_article_norm:
        candidates = po_article_index.get((inv_po_norm, inv_article_norm), [])
        if candidates:
            matched_by = "inv_spart_item_no"
            bucket_key = (inv_po_norm, "ARTICLE", inv_article_norm)

    if not candidates and pl_article_norm:
        candidates = po_article_index.get((inv_po_norm, pl_article_norm), [])
        if candidates:
            matched_by = "pl_item_no"
            bucket_key = (inv_po_norm, "ARTICLE", pl_article_norm)

    if not candidates and inv_desc_norm:
        candidates = po_desc_index.get((inv_po_norm, inv_desc_norm), [])
        if candidates:
            matched_by = "description"
            bucket_key = (inv_po_norm, "DESC", inv_desc_norm)

    if not candidates:
        failed_row = dict(row)
        failed_row["_po_mapped"] = False
        return [failed_row], False

    if bucket_key not in remaining_state:
        bucket_candidates = []
        for idx, line in candidates:
            qty = _to_float(line.get("po_quantity"))
            bucket_candidates.append({
                "idx": idx,
                "line": dict(line),
                "remaining_qty": 0.0 if qty is None else qty,
            })

        remaining_state[bucket_key] = bucket_candidates

    bucket_candidates = remaining_state[bucket_key]

    available = [
        item for item in bucket_candidates
        if (item.get("remaining_qty") or 0.0) > 1e-9
    ]

    if not available:
        failed_row = dict(row)
        failed_row["_po_mapped"] = False
        return [failed_row], False

    row_matches = []

    if extracted_qty is None:
        chosen = _pick_closest_remaining_candidate(available, None)
        if chosen is None:
            failed_row = dict(row)
            failed_row["_po_mapped"] = False
            return [failed_row], False

        alloc_qty = chosen["remaining_qty"]
        if alloc_qty > 1e-9:
            chosen["remaining_qty"] = 0.0
            row_matches.append((chosen["line"], alloc_qty))

    else:
        remaining_target = extracted_qty

        while remaining_target > 1e-9:
            available = [
                item for item in bucket_candidates
                if (item.get("remaining_qty") or 0.0) > 1e-9
            ]

            if not available:
                break

            chosen = _pick_closest_remaining_candidate(available, remaining_target)
            if chosen is None:
                break

            chosen_remaining = chosen.get("remaining_qty") or 0.0
            if chosen_remaining <= 1e-9:
                break

            alloc_qty = min(remaining_target, chosen_remaining)
            if alloc_qty <= 1e-9:
                break

            row_matches.append((chosen["line"], alloc_qty))
            chosen["remaining_qty"] = max(chosen_remaining - alloc_qty, 0.0)
            remaining_target = max(remaining_target - alloc_qty, 0.0)

    if not row_matches:
        failed_row = dict(row)
        failed_row["_po_mapped"] = False
        return [failed_row], False

    row_matches = sorted(row_matches, key=lambda x: _po_line_sort_key(x[0]))

    mapped_rows = []

    for matched_line, alloc_qty in row_matches:
        new_row = dict(row)
        new_row["_po_mapped"] = True
        new_row["_po_data"] = _copy_po_line_with_allocated_qty(matched_line, alloc_qty)

        # selalu pakai item no asli dari PO JSON
        po_article_value = _get_best_po_article_value(matched_line)
        if not _is_null(po_article_value):
            new_row["inv_spart_item_no"] = po_article_value
            new_row["pl_item_no"] = po_article_value
        else:
            if matched_by == "inv_spart_item_no" and not _is_null(new_row.get("inv_spart_item_no")):
                new_row["pl_item_no"] = new_row.get("inv_spart_item_no")
            elif matched_by == "pl_item_no" and not _is_null(new_row.get("pl_item_no")):
                new_row["inv_spart_item_no"] = new_row.get("pl_item_no")

        mapped_rows.append(new_row)

    return mapped_rows, True

def _map_po_to_details(po_lines, detail_rows):
    po_article_index, po_desc_index = _build_po_indexes(po_lines)
    remaining_state = {}

    # first pass: mapping normal
    per_input_results = []

    for row in detail_rows or []:
        mapped_rows, _ = _map_single_detail_row_to_po(
            row=row,
            po_article_index=po_article_index,
            po_desc_index=po_desc_index,
            remaining_state=remaining_state,
        )
        per_input_results.append(mapped_rows)

    # second pass: neighbor fallback
    # rule:
    # - hanya untuk row yang gagal
    # - prioritas line atas dulu, baru bawah
    # - kalau neighbor berhasil map, copy PO dari neighbor lalu remap ulang
    for i, original_row in enumerate(detail_rows or []):
        current_result_rows = per_input_results[i]

        already_mapped = any(
            isinstance(r, dict) and r.get("_po_mapped") == True
            for r in current_result_rows
        )
        if already_mapped:
            continue

        if not isinstance(original_row, dict):
            continue

        has_item_no = (
            not _is_null(original_row.get("inv_spart_item_no")) or
            not _is_null(original_row.get("pl_item_no"))
        )
        if not has_item_no:
            continue

        for direction, neighbor_idx in [("up", i - 1), ("down", i + 1)]:
            if neighbor_idx < 0 or neighbor_idx >= len(per_input_results):
                continue

            neighbor_result_rows = per_input_results[neighbor_idx]
            neighbor_mapped = any(
                isinstance(r, dict) and r.get("_po_mapped") == True
                for r in neighbor_result_rows
            )
            if not neighbor_mapped:
                continue

            neighbor_anchor_row = None
            for r in neighbor_result_rows:
                if isinstance(r, dict) and r.get("_po_mapped") == True:
                    neighbor_anchor_row = r
                    break

            if neighbor_anchor_row is None:
                continue

            if not _same_invoice_context_for_neighbor_po(original_row, neighbor_anchor_row):
                continue

            inherited_po_no = _get_mapped_po_no_from_result_rows(neighbor_result_rows)
            if _is_null(inherited_po_no):
                continue

            patched_row = dict(original_row)
            patched_row["inv_customer_po_no"] = inherited_po_no
            patched_row["pl_customer_po_no"] = inherited_po_no

            remapped_rows, success = _map_single_detail_row_to_po(
                row=patched_row,
                po_article_index=po_article_index,
                po_desc_index=po_desc_index,
                remaining_state=remaining_state,
            )

            if success:
                for rr in remapped_rows:
                    if isinstance(rr, dict):
                        rr["_po_neighbor_fallback"] = True
                        rr["_po_neighbor_direction"] = direction
                        rr["_po_neighbor_inherited_po_no"] = inherited_po_no

                per_input_results[i] = remapped_rows
                break

    # flatten sesuai urutan line item asli
    expanded_rows = []
    for result_rows in per_input_results:
        expanded_rows.extend(result_rows)

    return expanded_rows

# =========================================================
# VALIDATE PO DATA
# =========================================================

def _to_num(x):
    if x is None:
        return None
    try:
        return float(str(x).strip().replace(",", ""))
    except:
        return None

def _is_null(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.lower() == "null"

def _append_err(row: dict, msg: str):
    """Append error ke match_description pakai '; ' dan set match_score=false."""
    if not isinstance(row, dict):
        return
    row["match_score"] = "false"
    prev = row.get("match_description")
    if _is_null(prev):
        row["match_description"] = msg
    else:
        row["match_description"] = f"{prev}; {msg}"

def _reset_match_fields(rows: list):
    """Karena Gemini tidak validasi lagi, kita reset supaya Python yang menentukan."""
    for r in rows:
        if isinstance(r, dict):
            r["match_score"] = "true"
            r["match_description"] = "null"

def _to_float(v):
    if _is_null(v):
        return None
    try:
        return float(str(v).strip().replace(",", ""))
    except:
        return None

def _nearly_equal(a, b, eps=1e-6):
    if a is None or b is None:
        return False
    return abs(a - b) <= eps

def _first_non_null(rows: list, key: str):
    for r in rows:
        if isinstance(r, dict) and not _is_null(r.get(key)):
            return r.get(key)
    return None

def _first_non_null_nonzero(rows: list, key: str):
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get(key)
        if _is_null(v):
            continue
        # treat 0 sebagai missing untuk total fields
        if _is_missing_num(v):
            continue
        return v
    return None

def _normalize_customer_po_no(value):
    """
    Rules:
    - 'No.C25-1544U/45323564'   -> '45323564'
    - '45323564-1'              -> '45323564'
    - 'No.C25-1544U/45323564-1' -> '45323564'

    Kalau tidak match pola target, kembalikan value asli yang sudah di-trim.
    """
    if value is None:
        return "null"

    raw = str(value).strip()

    if raw == "" or raw.lower() == "null":
        return "null"

    # Prioritas: ambil bagian setelah slash terakhir
    candidate = raw.split("/")[-1].strip()

    # Kasus:
    # - 45323564
    # - 45323564-1
    m = re.fullmatch(r"(\d+)(?:-\d+)?", candidate)
    if m:
        return m.group(1)

    # Fallback: cari digit terakhir yang relevan di seluruh string
    m = re.search(r"(\d+)(?:-\d+)?\s*$", raw)
    if m:
        return m.group(1)

    return raw


def _postprocess_customer_po_no(rows: list):
    """
    Terapkan ke SEMUA field yang namanya berakhiran customer_po_no,
    jadi future-proof kalau nanti ada field baru.
    """
    for row in rows:
        if not isinstance(row, dict):
            continue

        for key in list(row.keys()):
            if key.endswith("customer_po_no"):
                row[key] = _normalize_customer_po_no(row.get(key))

def _fill_forward(rows: list, key: str):
    """Rule: kalau 'null' pakai nilai terakhir yang valid dari row sebelumnya."""
    last = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get(key)
        if not _is_null(v):
            last = v
        else:
            if last is not None:
                r[key] = last

def _fill_inv_price_unit_from_amount_unit(rows: list):
    """
    Jika inv_price_unit = null/kosong, isi dengan inv_amount_unit (kalau ada).
    """
    for r in rows:
        if not isinstance(r, dict):
            continue

        if _is_null(r.get("inv_price_unit")) and not _is_null(r.get("inv_amount_unit")):
            r["inv_price_unit"] = r.get("inv_amount_unit")

def _to_decimal_or_zero(value) -> Decimal:
    """
    Konversi aman ke Decimal.
    None / empty / 'null' / non-numeric -> Decimal('0').
    """
    if value is None:
        return Decimal("0")

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    raw = str(value).strip()
    if raw == "" or raw.lower() == "null":
        return Decimal("0")

    raw = raw.replace(",", "")

    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _generate_inv_amount_before_validation(rows: list):
    """
    Rule inv_amount:
    - kalau inv_amount null/kosong -> jangan generate, biarkan apa adanya
    - kalau inv_amount = 0 -> biarkan 0
    - kalau inv_amount ada nilainya dan bukan 0 -> apply math rule:
      inv_amount = inv_quantity * inv_unit_price
    """
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        current_amount = row.get("inv_amount")

        # kalau null / kosong -> skip
        if _is_null(current_amount):
            continue

        # kalau 0 -> biarkan apa adanya
        if _is_zero_like(current_amount):
            continue

        qty = _to_decimal_or_zero(row.get("inv_quantity"))
        unit_price = _to_decimal_or_zero(row.get("inv_unit_price"))
        amount = qty * unit_price

        if amount == amount.to_integral_value():
            row["inv_amount"] = int(amount)
        else:
            row["inv_amount"] = float(amount)

    return rows

def _recompute_seq_by_key(rows: list, group_key: str, seq_key: str):
    """Hitung ulang seq global berdasarkan group_key (misal inv_customer_po_no)."""
    counter = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        g = r.get(group_key)
        if _is_null(g):
            r[seq_key] = 0
            continue
        gk = str(g).strip()
        counter[gk] = counter.get(gk, 0) + 1
        r[seq_key] = counter[gk]

COO_ITEM_LEVEL_FIELDS = [
    "coo_seq",
    "coo_description",
    "coo_hs_code",
    "coo_quantity",
    "coo_unit",
    "coo_criteria",
    "coo_origin_country",
    "coo_amount_unit",
    "coo_amount",
    "coo_gw_unit",
    "coo_gw",
    "coo_package_count",
    "coo_package_unit",
]

def _row_has_meaningful_coo_item(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    item_fields = [
        "coo_description",
        "coo_hs_code",
        "coo_quantity",
        "coo_unit",
        "coo_criteria",
        "coo_origin_country",
        "coo_amount",
        "coo_gw",
        "coo_package_count",
    ]

    return any(not _is_null(row.get(k)) for k in item_fields)

def _nullify_coo_item_fields(row: dict):
    for k in COO_ITEM_LEVEL_FIELDS:
        row[k] = "null"

def _coo_item_matches_row(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    coo_desc = row.get("coo_description")
    coo_hs = row.get("coo_hs_code")
    coo_qty = row.get("coo_quantity")

    inv_desc = row.get("inv_description")
    inv_item = row.get("inv_spart_item_no")
    pl_item = row.get("pl_item_no")
    inv_hs = row.get("inv_hs_code")
    inv_qty = row.get("inv_quantity")

    # 1) code-based match dari deskripsi COO
    coo_codes = _extract_bl_description_codes(coo_desc)

    code_match = any(
        _code_exists_in_value(code, inv_desc) or
        _code_exists_in_value(code, inv_item) or
        _code_exists_in_value(code, pl_item)
        for code in coo_codes
    )

    # 2) fallback description contains
    desc_match = False
    if not code_match:
        desc_match = (
            _text_exists_in_description(coo_desc, inv_desc) or
            _text_exists_in_description(inv_desc, coo_desc)
        )

    # 3) optional support: HS + qty
    hs_match = False
    if not _is_null(coo_hs) and not _is_null(inv_hs):
        hs_match = _normalize_code_compare_value(coo_hs) == _normalize_code_compare_value(inv_hs)

    qty_match = False
    coo_qty_num = _to_float(coo_qty)
    inv_qty_num = _to_float(inv_qty)
    if coo_qty_num is not None and inv_qty_num is not None:
        qty_match = abs(coo_qty_num - inv_qty_num) <= 0.01

    # aturan utama:
    # - kalau ada code match -> match
    # - kalau desc match + (hs match atau qty match) -> match
    # - kalau hanya hs+qty tanpa desc/code, boleh dianggap match konservatif
    if code_match:
        return True

    if desc_match and (hs_match or qty_match):
        return True

    if hs_match and qty_match:
        return True

    return False

def _postprocess_coo_item_mapping(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        # kalau row ini bahkan tidak punya payload COO item-level, biarkan
        if not _row_has_meaningful_coo_item(row):
            continue

        if not _coo_item_matches_row(row):
            _nullify_coo_item_fields(row)

def _has_all_required_coo_seq_fields(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    required_fields = [
        "coo_description",
    ]

    return all(not _is_null(row.get(k)) for k in required_fields)

def _postprocess_coo_no_and_seq(rows: list):
    coo_keys_presence = [
        "coo_form_type",
        "coo_invoice_no",
        "coo_invoice_date",
        "coo_origin_country",
        "coo_hs_code",
        "coo_description",
    ]

    has_coo = _doc_present(rows, coo_keys_presence)
    active_rows = []

    for r in rows or []:
        if not isinstance(r, dict):
            continue

        if not has_coo:
            r["coo_seq"] = "null"
            continue

        # isi coo_no dulu kalau kosong
        if _is_null(r.get("coo_no")) and not _is_null(r.get("coo_invoice_no")):
            r["coo_no"] = str(r.get("inv_invoice_no")).strip()

        desc_missing = _is_null(r.get("coo_description"))
        hs_missing = _is_null(r.get("coo_hs_code"))
        qty_missing = _is_null(r.get("coo_quantity"))
        amount_missing = _is_null(r.get("coo_amount"))

        # RULE 1:
        # kalau 4 field inti COO item semuanya null,
        # maka coo_seq = null dan coo_origin_country = null
        if desc_missing and hs_missing and qty_missing and amount_missing:
            r["coo_seq"] = "null"
            r["coo_origin_country"] = "null"
            continue

        # RULE 2:
        # numbering hanya untuk row yang punya SEMUA field inti
        if not _has_all_required_coo_seq_fields(r):
            r["coo_seq"] = "null"
            continue

        active_rows.append(r)

    if active_rows:
        _recompute_seq_by_key(active_rows, "coo_no", "coo_seq")

    return rows

def _finalize_match_fields(rows: list):
    """Pastikan konsistensi match_description."""
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("match_score") == "true":
            r["match_description"] = "null"
        else:
            if _is_null(r.get("match_description")):
                r["match_description"] = "Validation failed"

def _drop_columns(rows: list, cols: list):
    for r in rows:
        if isinstance(r, dict):
            for c in cols:
                r.pop(c, None)

# ==============================
# ENSURE ALL KEYS EXIST (ANTI HILANG KOLOM)
# ==============================

ALL_DETAIL_FIELDS = list(HEADER_FIELDS) + list(DETAIL_LINE_FIELDS) + ["match_score", "match_description"]

def _normalize_compare_prefix(value, max_len=20):
    """
    Normalisasi untuk compare:
    - uppercase
    - buang semua selain huruf A-Z
    - ambil 20 huruf pertama
    """
    if _is_null(value):
        return ""

    s = str(value).upper().strip()
    s = re.sub(r"[^A-Z]", "", s)

    return s[:max_len]

def _ensure_all_detail_keys(rows: list):
    """
    Pastikan setiap row punya SEMUA kolom (header + content + match fields).
    - string missing => "null"
    - number missing => 0
    """
    for r in rows:
        if not isinstance(r, dict):
            continue

        for k in ALL_DETAIL_FIELDS:
            if k in r and r[k] is not None:
                continue

            if k in DETAIL_LINE_NUM_FIELDS:
                r[k] = 0
            else:
                r[k] = "null"

def _is_missing_num(v) -> bool:
    """
    Untuk field numeric wajib: treat 0 sebagai missing (biar tidak lolos palsu).
    """
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in ("", "null"):
        return True
    try:
        return float(str(v).strip().replace(",", "")) == 0.0
    except:
        return True

def _apply_header_to_rows(rows: list, header_obj: dict):
    if not isinstance(header_obj, dict):
        header_obj = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in HEADER_FIELDS:
            v = header_obj.get(k, "null")
            # overwrite biar konsisten antar row
            r[k] = v if v is not None else "null"

def _has_text_value(v) -> bool:
    return not _is_null(v)

def _has_num_value(v) -> bool:
    return _to_float(v) is not None

def _compare_text_values(row: dict, left_value, right_value, err_msg: str, normalize_fn=None):
    """
    Rule:
    - jika salah satu sisi null/kosong -> skip, tidak perlu check
    - kalau dua-duanya ada -> compare
    """
    if not _has_text_value(left_value) or not _has_text_value(right_value):
        return

    lv = left_value
    rv = right_value

    if normalize_fn is not None:
        lv = normalize_fn(lv)
        rv = normalize_fn(rv)

    if lv != rv:
        _append_err(row, err_msg)

def _compare_num_values(row: dict, left_value, right_value, err_msg: str, eps=0.01):
    """
    Rule:
    - jika salah satu sisi null / bukan angka -> skip, tidak perlu check
    - kalau dua-duanya ada -> compare numerik
    """
    lv = _to_float(left_value)
    rv = _to_float(right_value)

    if lv is None or rv is None:
        return

    if abs(lv - rv) > eps:
        _append_err(row, err_msg)

def _validate_po(detail_rows):
    for row in detail_rows:
        if not row.get("_po_mapped"):
            _append_err(row, "PO item tidak ditemukan")
            row.pop("_po_data", None)
            row.pop("_po_mapped", None)
            continue

        po_data = row.get("_po_data") or {}

        vendor_article = po_data.get("vendor_article_no") or po_data.get("po_vendor_article_no")
        sap_article = po_data.get("sap_article_no") or po_data.get("po_sap_article_no")
        final_vendor_article = vendor_article or sap_article or "null"

        row["po_no"] = po_data.get("po_no", "null")
        row["po_vendor_article_no"] = final_vendor_article
        row["po_text"] = po_data.get("po_text", "null")
        row["po_sap_article_no"] = sap_article or "null"
        row["po_line"] = po_data.get("po_line", "null")
        row["po_quantity"] = po_data.get("po_quantity", "null")
        row["po_unit"] = _convert_unit_value(po_data.get("po_unit"))
        row["po_price"] = po_data.get("po_price", "null")
        row["po_currency"] = po_data.get("po_currency", "null")
        row["po_info_record_price"] = po_data.get("po_info_record_price", "null")
        row["po_info_record_currency"] = po_data.get("po_info_record_currency", "null")

        inv_price = _to_num(row.get("inv_unit_price"))
        po_price  = _to_num(po_data.get("po_price"))

        inv_currency = str(row.get("inv_price_unit") or "").strip()
        po_currency  = str(po_data.get("po_currency") or "").strip()

        if inv_price is not None and po_price is not None and inv_price != po_price:
            _append_err(row, f"po_price mismatch (inv: {inv_price}, po: {po_price})")

        if inv_currency and po_currency and inv_currency != po_currency:
            _append_err(row, f"po_currency mismatch (inv: {inv_currency}, po: {po_currency})")

        # validasi unit quantity invoice vs unit PO
        inv_qty_unit = _convert_unit_value(row.get("inv_quantity_unit"))
        po_unit = _convert_unit_value(po_data.get("po_unit"))

        if not _is_null(inv_qty_unit) and not _is_null(po_unit):
            if inv_qty_unit != po_unit:
                _append_err(
                    row,
                    f"po_unit mismatch (inv_quantity_unit: {inv_qty_unit}, po_unit: {po_unit})"
                )

        row.pop("_po_data", None)
        row.pop("_po_mapped", None)

    return detail_rows

def _validate_invoice_rows(rows: list):
    required = [
        "inv_invoice_no","inv_invoice_date","inv_customer_po_no","inv_vendor_name",
        "inv_vendor_address","inv_spart_item_no","inv_description","inv_quantity",
        "inv_quantity_unit","inv_unit_price","inv_price_unit","inv_amount","inv_amount_unit",
    ]

    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            continue

        # required fields
        required_str = [
            "inv_invoice_no","inv_invoice_date","inv_customer_po_no","inv_vendor_name",
            "inv_vendor_address","inv_spart_item_no","inv_description",
            "inv_quantity_unit","inv_price_unit","inv_amount_unit",
        ]
        required_num = ["inv_quantity","inv_unit_price","inv_amount"]

        for k in required_str:
            if _is_null(r.get(k)):
                _append_err(r, f"Invoice: missing {k}")

        for k in required_num:
            if _is_missing_num(r.get(k)):
                _append_err(r, f"Invoice: missing {k}")

        # aritmatika: amount = qty * unit_price
        qty = _to_float(r.get("inv_quantity"))
        up  = _to_float(r.get("inv_unit_price"))
        amt = _to_float(r.get("inv_amount"))
        if qty is not None and up is not None and amt is not None:
            expected = qty * up
            # toleransi 0.01 untuk rounding
            if abs(expected - amt) > 0.01:
                _append_err(r, f"Invoice: inv_amount != inv_quantity*inv_unit_price (exp {expected}, got {amt})")

    # validasi total (pakai declared total di dokumen yang diekstrak Gemini)
    declared_qty = _to_float(_first_non_null_nonzero(rows, "inv_total_quantity"))
    declared_amt = _to_float(_first_non_null_nonzero(rows, "inv_total_amount"))

    sum_qty = 0.0
    sum_amt = 0.0
    qty_ok = False
    amt_ok = False

    for r in rows:
        if not isinstance(r, dict):
            continue
        q = _to_float(r.get("inv_quantity"))
        a = _to_float(r.get("inv_amount"))
        if q is not None:
            sum_qty += q
            qty_ok = True
        if a is not None:
            sum_amt += a
            amt_ok = True

    # apply ke semua row (biar match_score konsisten per row)
    for r in rows:
        if not isinstance(r, dict):
            continue
        if declared_qty is not None and qty_ok and abs(sum_qty - declared_qty) > 0.01:
            _append_err(r, f"Invoice: total_quantity mismatch (sum {sum_qty}, doc {declared_qty})")
        if declared_amt is not None and amt_ok and abs(sum_amt - declared_amt) > 0.01:
            _append_err(r, f"Invoice: total_amount mismatch (sum {sum_amt}, doc {declared_amt})")

def _normalize_pt_insera_sena_name(value):
    if value is None:
        return ""

    s = str(value).strip().upper()
    if s == "" or s == "NULL":
        return ""

    # buang punctuation jadi spasi
    s = re.sub(r"[^A-Z0-9]+", " ", s)

    # samakan variasi legal entity
    s = re.sub(r"\bPERSEROAN\s+TERBATAS\b", "PT", s)

    # satukan variasi INSERASENA / INSERA SENA
    s = re.sub(r"\bINSERASENA\b", "INSERA SENA", s)

    # rapikan spasi
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _is_pt_insera_sena_name(value) -> bool:
    s = _normalize_pt_insera_sena_name(value)
    if not s:
        return False

    if "PT" not in s:
        return False

    return ("INSERA SENA" in s) or ("INSERA" in s and "SENA" in s)


def _validate_packing_rows(rows: list):
    required = [
        "pl_invoice_no","pl_invoice_date","pl_messrs","pl_messrs_address","pl_item_no",
        "pl_description","pl_quantity","pl_package_unit","pl_package_count","pl_weight_unit",
        "pl_nw","pl_gw","pl_volume_unit","pl_volume"
    ]

    # normalize PT Insera Sena
    def norm(s):
        if _is_null(s): 
            return ""
        
        s = str(s).upper().strip()
        
        # hapus punctuation
        s = re.sub(r"[^\w\s]", "", s)

        # normalisasi PERSEROAN TERBATAS -> PT
        s = re.sub(r"\bPERSEROAN\s+TERBATAS\b", "PT", s)

        # normalisasi INSERASENA -> INSERA SENA
        s = re.sub(r"\bINSERASENA\b", "INSERA SENA", s)

        # rapiin spasi
        s = re.sub(r"\s+", " ", s)

        return s

    for r in rows:
        if not isinstance(r, dict):
            continue

        required_str = [
            "pl_invoice_no","pl_invoice_date","pl_messrs","pl_messrs_address",
            "pl_package_unit","pl_weight_unit","pl_volume_unit","pl_item_no"
        ]
        required_num = ["pl_quantity","pl_package_count","pl_nw","pl_gw","pl_volume"]

        for k in required_str:
            if _is_null(r.get(k)):
                _append_err(r, f"PackingList: missing {k}")

        for k in required_num:
            if _is_missing_num(r.get(k)):
                _append_err(r, f"PackingList: missing {k}")

        # PL harus match Invoice
        if not _is_null(r.get("pl_invoice_no")) and not _is_null(r.get("inv_invoice_no")):
            if str(r["pl_invoice_no"]).strip() != str(r["inv_invoice_no"]).strip():
                _append_err(r, "PackingList: pl_invoice_no != inv_invoice_no")

        if not _is_null(r.get("pl_invoice_date")) and not _is_null(r.get("inv_invoice_date")):
            if str(r["pl_invoice_date"]).strip() != str(r["inv_invoice_date"]).strip():
                _append_err(r, "PackingList: pl_invoice_date != inv_invoice_date")

        if not _is_null(r.get("pl_messrs")) and not _is_pt_insera_sena_name(r.get("pl_messrs")):
            _append_err(
                r,
                f"PackingList: pl_messrs bukan PT Insera Sena (got {r.get('pl_messrs')})"
            )

    # totals PL
    declared_qty = _to_float(_first_non_null_nonzero(rows, "pl_total_quantity"))
    declared_nw  = _to_float(_first_non_null_nonzero(rows, "pl_total_nw"))
    declared_gw  = _to_float(_first_non_null_nonzero(rows, "pl_total_gw"))
    declared_vol = _to_float(_first_non_null_nonzero(rows, "pl_total_volume"))
    declared_pkg = _to_float(_first_non_null_nonzero(rows, "pl_total_package"))

    sum_qty = sum(_to_float(r.get("pl_quantity")) or 0.0 for r in rows if isinstance(r, dict))
    sum_nw  = sum(_to_float(r.get("pl_nw")) or 0.0 for r in rows if isinstance(r, dict))
    sum_gw  = sum(_to_float(r.get("pl_gw")) or 0.0 for r in rows if isinstance(r, dict))
    sum_vol = sum(_to_float(r.get("pl_volume")) or 0.0 for r in rows if isinstance(r, dict))
    sum_pkg = sum(_to_float(r.get("pl_package_count")) or 0.0 for r in rows if isinstance(r, dict))

    for r in rows:
        if not isinstance(r, dict):
            continue
        if declared_qty is not None and abs(sum_qty - declared_qty) > 0.01:
            _append_err(r, f"PackingList: total_quantity mismatch (sum {sum_qty}, doc {declared_qty})")
        if declared_nw is not None and abs(sum_nw - declared_nw) > 0.01:
            _append_err(r, f"PackingList: total_nw mismatch (sum {sum_nw}, doc {declared_nw})")
        if declared_gw is not None and abs(sum_gw - declared_gw) > 0.01:
            _append_err(r, f"PackingList: total_gw mismatch (sum {sum_gw}, doc {declared_gw})")
        if declared_vol is not None and not _volume_values_match_with_conversion(sum_vol, declared_vol):
            _append_err(
                r,
                f"PackingList: total_volume mismatch "
                f"(sum {sum_vol}, doc {declared_vol})"
            )
        if declared_pkg is not None and abs(sum_pkg - declared_pkg) > 0.01:
            _append_err(r, f"PackingList: total_package mismatch (sum {sum_pkg}, doc {declared_pkg})")



def _doc_present(rows: list, keys: list) -> bool:
    """Dokumen dianggap tersedia kalau ada minimal 1 field kunci yang tidak null di salah satu row."""
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in keys:
            if not _is_null(r.get(k)):
                return True
    return False
def _validate_invoice_vs_packing_extra(rows: list):
    def norm_prefix_20(s):
        return _normalize_compare_prefix(s, 20)

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    for r in rows:
        if not isinstance(r, dict):
            continue

        inv_messrs = r.get("inv_messrs")
        pl_messrs = r.get("pl_messrs")

        same_known_company = (
            _is_pt_insera_sena_name(inv_messrs) and
            _is_pt_insera_sena_name(pl_messrs)
        )

        if not same_known_company:
            _compare_text_values(
                r,
                inv_messrs,
                pl_messrs,
                "Invoice vs PL: inv_messrs != pl_messrs",
                normalize_fn=norm_prefix_20
            )

        inv_messrs_address = r.get("inv_messrs_address")
        pl_messrs_address = r.get("pl_messrs_address")
        _compare_text_values(
            r,
            inv_messrs_address,
            pl_messrs_address,
            f"Invoice vs PL: inv_messrs_address != pl_messrs_address "
            f"(inv {inv_messrs_address}, pl {pl_messrs_address})",
            normalize_fn=norm_prefix_20
        )

        pl_gw = r.get("pl_gw")
        coo_gw = r.get("coo_gw")
        _compare_num_values(
            r,
            pl_gw,
            coo_gw,
            f"PL vs COO: pl_gw != coo_gw (PL {_to_float(pl_gw)}, coo {_to_float(coo_gw)})"
        )

        pl_package_count = r.get("pl_package_count")
        coo_package_count = r.get("coo_package_count")
        _compare_num_values(
            r,
            pl_package_count,
            coo_package_count,
            f"PL vs COO: pl_package_count != coo_package_count "
            f"(PL {_to_float(pl_package_count)}, coo {_to_float(coo_package_count)})"
        )

        _compare_text_values(
            r,
            r.get("pl_weight_unit"),
            r.get("coo_gw_unit"),
            "Invoice vs COO: pl_weight_unit != coo_gw_unit",
            normalize_fn=norm
        )

def _normalize_company_name_for_similarity(value):
    """
    Normalisasi nama company untuk compare BL seller vs invoice vendor:
    - uppercase
    - hapus punctuation
    - buang suffix badan usaha umum
    - rapikan spasi
    """
    if value is None:
        return ""

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return ""

    s = s.upper()

    # buang punctuation jadi spasi
    s = re.sub(r"[^A-Z0-9]+", " ", s)

    # hapus common legal suffix
    stopwords = {
        "CO", "COMPANY", "LTD", "LIMITED", "INC", "CORP", "CORPORATION",
        "LLC", "PTE", "PT", "TBK", "CV", "BHD", "SDN"
    }

    tokens = [tok for tok in s.split() if tok not in stopwords]
    s = " ".join(tokens)
    s = re.sub(r"\s+", " ", s).strip()

    return s


def _company_name_similarity(left, right) -> float:
    """
    Rule:
    1. exact normalized -> 1.0
    2. containment -> 1.0
    3. token overlap tinggi -> 1.0
    4. fallback SequenceMatcher
    """
    l = _normalize_company_name_for_similarity(left)
    r = _normalize_company_name_for_similarity(right)

    if not l or not r:
        return 0.0

    if l == r:
        return 1.0

    l_flat = l.replace(" ", "")
    r_flat = r.replace(" ", "")

    # kasus seperti:
    # HAOMENG BICYCLE SHANGHAI
    # PROWHEEL HAOMENG BICYCLE SHANGHAI
    if len(l_flat) >= 12 and l_flat in r_flat:
        return 1.0
    if len(r_flat) >= 12 and r_flat in l_flat:
        return 1.0

    l_tokens = set(l.split())
    r_tokens = set(r.split())

    if l_tokens and r_tokens:
        overlap = len(l_tokens & r_tokens) / min(len(l_tokens), len(r_tokens))
        if overlap >= 0.8 and min(len(l_tokens), len(r_tokens)) >= 2:
            return 1.0

    return SequenceMatcher(None, l_flat, r_flat).ratio()


def _postprocess_bl_seller_name_similarity(rows: list, threshold: float = 0.88):
    """
    Kalau bl_seller_name sangat mirip dengan inv_vendor_name,
    samakan nilainya supaya validasi exact compare existing tetap lolos.
    """
    for row in rows:
        if not isinstance(row, dict):
            continue

        inv_vendor_name = row.get("inv_vendor_name")
        bl_seller_name = row.get("bl_seller_name")

        if _is_null(inv_vendor_name) or _is_null(bl_seller_name):
            continue

        sim = _company_name_similarity(inv_vendor_name, bl_seller_name)

        if sim >= threshold:
            row["bl_seller_name"] = inv_vendor_name

def _validate_bl_rows(rows: list):
    """
    Implement rule dari prompt:
    - Seller fallback: jika bl_seller_* null -> pakai bl_shipper_*
    - LC logic: jika consignee mengandung 'BANK' -> LC
      fallback consignee untuk LC: pakai notify party
    - Required fields jika BL tersedia
    - Seller harus sama dengan inv_vendor_name
    """
    bl_keys_presence = ["bl_no", "bl_date", "bl_shipper_name", "bl_consignee_name", "bl_vessel"]
    if not _doc_present(rows, bl_keys_presence):
        return

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    def norm_prefix_20(s):
        return _normalize_compare_prefix(s, 20)

    required = [
        "bl_shipper_name",
        "bl_shipper_address",
        "bl_no",
        "bl_date",
        "bl_consignee_name",
        "bl_consignee_address",
        "bl_vessel",
        "bl_voyage_no",
        "bl_port_of_loading",
        "bl_port_of_destination",
    ]

    for r in rows:
        if not isinstance(r, dict):
            continue

        if _is_null(r.get("bl_seller_name")):
            if not _is_null(r.get("bl_shipper_name")):
                r["bl_seller_name"] = r.get("bl_shipper_name")
        if _is_null(r.get("bl_seller_address")):
            if not _is_null(r.get("bl_shipper_address")):
                r["bl_seller_address"] = r.get("bl_shipper_address")

        is_lc = "BANK" in norm(r.get("bl_consignee_name"))

        if is_lc:
            if not _is_null(r.get("bl_notify_party")):
                if _is_null(r.get("bl_consignee_name")):
                    r["bl_consignee_name"] = r.get("bl_notify_party")
                if _is_null(r.get("bl_consignee_address")):
                    r["bl_consignee_address"] = r.get("bl_notify_party")

        for k in required:
            if _is_null(r.get(k)):
                _append_err(r, f"BL: missing {k}")

        # seller compare 20 huruf pertama setelah normalisasi
        inv_vendor_name = r.get("inv_vendor_name")
        bl_seller_name = r.get("bl_seller_name")

        if not _is_null(inv_vendor_name) and not _is_null(bl_seller_name):
            sim = _company_name_similarity(inv_vendor_name, bl_seller_name)

            if sim >= 0.88:
                # samakan value supaya downstream compare / output konsisten
                r["bl_seller_name"] = inv_vendor_name
            else:
                _append_err(
                    r,
                    f"BL: bl_seller_name != inv_vendor_name "
                    f"(inv {inv_vendor_name}, bl {bl_seller_name}, sim {round(sim, 4)})"
                )


def _validate_coo_rows(rows: list):
    coo_keys_presence = ["coo_no", "coo_form_type", "coo_invoice_no", "coo_origin_country", "coo_hs_code"]
    if not _doc_present(rows, coo_keys_presence):
        return

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    required = [
        "coo_no",
        "coo_form_type",
        "coo_invoice_no",
        "coo_invoice_date",
        "coo_shipper_name",
        "coo_shipper_address",
        "coo_consignee_name",
        "coo_consignee_address",
        "coo_seq",
        "coo_description",
        "coo_hs_code",
        "coo_quantity",
        "coo_unit",
        "coo_criteria",
        "coo_origin_country",
    ]

    for r in rows:
        if not isinstance(r, dict):
            continue

        # NEW:
        # kalau row ini tidak punya COO item yang berhasil match,
        # jangan divalidasi sebagai COO row
        if not _row_has_meaningful_coo_item(r):
            continue

        for k in required:
            if _is_null(r.get(k)):
                _append_err(r, f"COO: missing {k}")

        crit = norm(r.get("coo_criteria"))
        ...

# ==============================
# (NEW) MAP PO -> TOTAL
# ==============================
def _append_total_error(total_obj, msg):
    total_obj["match_score"] = "false"
    prev = total_obj.get("match_description") or "null"
    if prev == "null":
        total_obj["match_description"] = msg
    else:
        total_obj["match_description"] = prev + "; " + msg

def _map_po_to_total(total_data, po_lines, po_numbers_from_detail):
    """
    total_data bisa dict atau list[dict]
    Kita isi/validasi field PO di TOTAL berdasarkan po_lines yang relevan.
    """
    if total_data is None:
        return None

    # normalize dict -> list
    if isinstance(total_data, dict):
        total_data = [total_data]

    if not isinstance(total_data, list) or not total_data or not isinstance(total_data[0], dict):
        return total_data

    total_obj = total_data[0]
    total_obj.setdefault("match_score", "true")
    total_obj.setdefault("match_description", "null")

    po_numbers = {
        _norm_po_number(p)
        for p in po_numbers_from_detail
        if p is not None and _norm_po_number(p)
    }
    if not po_numbers:
        _append_total_error(total_obj, "PO number tidak ditemukan pada output detail")
        return total_data

    lines = [
        l for l in po_lines
        if _norm_po_number(l.get("po_no")) in po_numbers
    ]
    if not lines:
        _append_total_error(total_obj, "PO lines tidak ditemukan di master PO JSON")
        return total_data

    # contoh isi: total po_quantity = sum
    qty_sum = 0.0
    qty_found = False
    for l in lines:
        q = l.get("po_quantity")
        if q is None:
            continue
        try:
            qty_sum += float(str(q).strip())
            qty_found = True
        except:
            pass

    # contoh isi: po_price harus unik
    price_set = set()
    for l in lines:
        p = l.get("po_price")
        if p is None:
            continue
        try:
            price_set.add(float(str(p).strip()))
        except:
            pass

    expected_price = None
    if len(price_set) == 1:
        expected_price = list(price_set)[0]
    elif len(price_set) > 1:
        _append_total_error(total_obj, "PO memiliki lebih dari 1 po_price (ambiguous untuk total)")

    # fill kalau kosong/null
    if total_obj.get("po_quantity") in (None, "", "null") and qty_found:
        total_obj["po_quantity"] = qty_sum

    if total_obj.get("po_price") in (None, "", "null") and expected_price is not None:
        total_obj["po_price"] = expected_price

    return total_data


def _rename_final_fields(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        # pindahin + hapus lama
        if "inv_spart_item_no" in row:
            row["inv_vendor_article_no"] = row.pop("inv_spart_item_no")

        if "pl_item_no" in row:
            row["pl_vendor_article_no"] = row.pop("pl_item_no")

# ==============================
# (NEW) CONVERT TO CSV -> CUSTOM FOLDER/PATH
# ==============================
def _convert_to_csv_path(blob_path, rows, field_order=None):
    if rows is None:
        raise Exception("Tidak ada data untuk CSV")

    # normalize dict -> list
    if isinstance(rows, dict):
        rows = [rows]

    if not isinstance(rows, list) or not rows:
        raise Exception("Tidak ada data untuk CSV")

    # union keys (preserve insertion order)
    union_keys = []
    seen = set()
    for r in rows:
        if isinstance(r, dict):
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    union_keys.append(k)

    if field_order:
        # 1) mulai dari order yang kamu mau
        keys = []
        used = set()
        for k in field_order:
            if k not in used:
                keys.append(k)
                used.add(k)

        # 2) append sisanya biar tidak error kalau ada kolom ekstra
        for k in union_keys:
            if k not in used:
                keys.append(k)
                used.add(k)
    else:
        # fallback logic lama (match_* di depan)
        priority = ["match_score", "match_description"]
        front = [k for k in priority if k in union_keys]
        rest = [k for k in union_keys if k not in set(front)]
        keys = front + rest

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    with open(tmp_file.name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r if isinstance(r, dict) else {})

    bucket = storage_client.bucket(BUCKET_NAME)
    bucket.blob(blob_path).upload_from_filename(tmp_file.name)

    return f"gs://{BUCKET_NAME}/{blob_path}"


# =========================================================
# CONVERT TO CSV
# =========================================================

def _convert_to_csv(invoice_name, rows):

    if not rows:
        raise Exception("Tidak ada data untuk CSV")

    keys = rows[0].keys()

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")

    with open(tmp_file.name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    bucket = storage_client.bucket(BUCKET_NAME)
    blob_path = f"output/{invoice_name}.csv"

    bucket.blob(blob_path).upload_from_filename(tmp_file.name)

    return f"gs://{BUCKET_NAME}/{blob_path}"

def _is_zero_like(value) -> bool:
    """
    Anggap zero jika:
    - int/float 0
    - string seperti: '0', '0.0', '000', '000.00', '0,000'
    Tidak menganggap text lain seperti '000123' sebagai zero.
    """
    if value is None:
        return False

    if isinstance(value, (int, float)):
        return float(value) == 0.0

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return False

    normalized = s.replace(",", "")
    return bool(re.fullmatch(r"[+-]?0+(?:\.0+)?", normalized))


def _postprocess_bl_coo_zero_to_null(rows: list):
    """
    Hanya untuk field prefix bl_ dan coo_:
    jika valuenya 0 -> ubah jadi 'null'
    """
    for row in rows:
        if not isinstance(row, dict):
            continue

        for key in list(row.keys()):
            if key.startswith("bl_") or key.startswith("coo_"):
                if _is_zero_like(row.get(key)):
                    row[key] = "null"

def _remove_code_prefix(value):
    """
    Hapus prefix CODE: di awal value.

    Contoh:
    - CODE:CWSPWA10BPP006 -> CWSPWA10BPP006
    - code: CWSPWA10BPP006 -> CWSPWA10BPP006
    """
    if value is None:
        return "null"

    s = str(value).strip()

    if s == "" or s.lower() == "null":
        return "null"

    s = re.sub(r"^\s*CODE\s*:\s*", "", s, flags=re.IGNORECASE).strip()

    return s if s else "null"

def _normalize_inv_description(value):
    """
    Khusus inv_description:
    - jika di awal ada pola CODE:<item_no>, hapus bagian itu saja
    - item_no bisa berubah-ubah, jadi tidak hardcode

    Contoh:
    - CODE:CWSPWA10BPP006 A10BPP(13),3/32*30T*114mm,CR ST BK
      -> A10BPP(13),3/32*30T*114mm,CR ST BK
    - code:ABC123 Remark test
      -> Remark test
    """
    if value is None:
        return "null"

    s = str(value).strip()

    if s == "" or s.lower() == "null":
        return "null"

    # hapus token CODE:<kode> di awal string
    s = re.sub(
        r"^\s*CODE\s*:\s*\S+\s*",
        "",
        s,
        flags=re.IGNORECASE
    )

    s = re.sub(r"\s{2,}", " ", s).strip()

    return s if s else "null"

def _postprocess_inv_description(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "inv_description" in row:
            row["inv_description"] = _normalize_inv_description(
                row.get("inv_description")
            )

def _normalize_item_no_whitespace(value):
    """
    Rules:
    - hapus prefix CODE:
    - gabungkan semua whitespace
    - jika suffix terakhir adalah 'O' / 'o' (huruf), ubah jadi '0' (angka)
    - jika suffix terakhir adalah 'R' dan belum ada '-R', ubah jadi '-R'

    Contoh:
    - 'CODE:CWSPWA10BPP006' -> 'CWSPWA10BPP006'
    - 'BAXVLPLG388020O'     -> 'BAXVLPLG3880200'
    - 'BAXVLPLG388020R'     -> 'BAXVLPLG388020-R'
    """
    if value is None:
        return "null"

    s = _remove_code_prefix(value)

    if s == "" or s.lower() == "null":
        return "null"

    # hapus semua whitespace
    s = re.sub(r"[\s\u00A0]+", "", s)

    # jika karakter terakhir adalah huruf O/o, ubah jadi angka 0
    if re.fullmatch(r".*[Oo]", s):
        s = s[:-1] + "0"

    # jika berakhir dengan R dan sebelumnya belum '-R', sisipkan dash sebelum R
    if re.fullmatch(r".+[^-]R", s):
        s = s[:-1] + "-R"

    return s

def _normalize_coo_description(value):
    """
    Ambil isi setelah pola quantity + OF.

    Contoh:
    ONE HUNDRED (100) CARTONS OF
    HUB D761DSE 32X14 BLACK W/O
    LOGO 9X108X100 270:112 ANO
    BLACK W/O LOGO W/WARNING LOGO

    ->

    HUB D761DSE 32X14 BLACK W/O
    LOGO 9X108X100 270:112 ANO
    BLACK W/O LOGO W/WARNING LOGO
    """
    if value is None:
        return "null"

    s = str(value).strip()

    if s == "" or s.lower() == "null":
        return "null"

    patterns = [
        # contoh: ONE HUNDRED (100) CARTONS OF ...
        r"^\s*(?:[A-Z][A-Z\s\-/&,\.]*\s+)?\(\s*\d+\s*\)\s+[A-Z0-9][A-Z0-9\s\-/&,\.]*?\bOF\b\s*",
        # contoh: 100 CARTONS OF ...
        r"^\s*\d+\s+[A-Z0-9][A-Z0-9\s\-/&,\.]*?\bOF\b\s*",
    ]

    for pattern in patterns:
        m = re.match(pattern, s, flags=re.IGNORECASE | re.DOTALL)
        if m:
            cleaned = s[m.end():].strip()
            return cleaned if cleaned else s

    return s


def _postprocess_coo_description(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "coo_description" in row:
            row["coo_description"] = _normalize_coo_description(
                row.get("coo_description")
            )

def _get_description_head_segment(value):
    normalized = _normalize_description_for_similarity(value)
    if not normalized:
        return ""

    # ambil bagian awal sebelum separator utama
    parts = re.split(r"\s*;\s*|\s+W/O\s+|\s+W/\s+|\s+\(\s*OPTION\s*\)\s*", normalized, maxsplit=1)
    head = parts[0].strip()
    return head


def _is_generic_bl_description_match(bl_desc, inv_desc) -> bool:
    bl_norm = _normalize_description_for_similarity(bl_desc)
    inv_head = _get_description_head_segment(inv_desc)

    if not bl_norm or not inv_head:
        return False

    if inv_head == bl_norm:
        return True

    return bool(re.match(rf"^{re.escape(bl_norm)}(?:\s|$)", inv_head))

def _normalize_description_for_similarity(value):
    if value is None:
        return ""

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return ""

    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_code_compare_value(value):
    if value is None:
        return ""

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return ""

    s = s.upper()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Z0-9\-/]", "", s)
    return s


def _extract_bl_description_codes(value):
    if value is None:
        return []

    raw = str(value).strip()
    if raw == "" or raw.lower() == "null":
        return []

    s = raw.upper()
    raw_tokens = re.findall(r"\b[A-Z0-9][A-Z0-9\-/]*\b", s)

    codes = []
    seen = set()

    for token in raw_tokens:
        normalized = _normalize_code_compare_value(token)
        if not normalized:
            continue
        if len(normalized) < 3:
            continue
        if not re.search(r"[A-Z]", normalized):
            continue
        if not re.search(r"\d", normalized):
            continue
        if normalized in seen:
            continue

        seen.add(normalized)
        codes.append(normalized)

    return codes


def _text_exists_in_description(needle, haystack) -> bool:
    return _is_generic_bl_description_match(needle, haystack)


def _code_exists_in_value(code, value) -> bool:
    normalized_code = _normalize_code_compare_value(code)
    normalized_value = _normalize_code_compare_value(value)

    if not normalized_code or not normalized_value:
        return False

    return normalized_code in normalized_value

def _postprocess_bl_description(rows: list, threshold: float = 0.4):
    """
    Rule baru:
    - jika bl_description punya code alfanumerik, compare code tsb ke inv_description
    - jika tidak ada di inv_description, fallback ke inv_spart_item_no / pl_item_no
    - jika bl_description tidak punya code, compare full bl_description ke inv_description
    - jika tidak ada yang match, null-kan bl_description dan bl_hs_code
    - bl_mark_number tetap dibiarkan

    threshold dipertahankan hanya untuk backward compatibility.
    """
    for row in rows:
        if not isinstance(row, dict):
            continue

        bl_desc = row.get("bl_description")
        if _is_null(bl_desc):
            continue

        inv_desc = row.get("inv_description")
        inv_spart_item_no = row.get("inv_spart_item_no")
        pl_item_no = row.get("pl_item_no")

        matched = False
        extracted_codes = _extract_bl_description_codes(bl_desc)

        if extracted_codes:
            for code in extracted_codes:
                if _code_exists_in_value(code, inv_desc):
                    matched = True
                    break

                if _code_exists_in_value(code, inv_spart_item_no):
                    matched = True
                    break

                if _code_exists_in_value(code, pl_item_no):
                    matched = True
                    break
        else:
            matched = _text_exists_in_description(bl_desc, inv_desc)

        if not matched:
            row["bl_description"] = "null"
            row["bl_hs_code"] = "null"


def _postprocess_item_no_fields(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "inv_spart_item_no" in row:
            row["inv_spart_item_no"] = _normalize_item_no_whitespace(
                row.get("inv_spart_item_no")
            )

        if "pl_item_no" in row:
            row["pl_item_no"] = _normalize_item_no_whitespace(
                row.get("pl_item_no")
            )


# ==============================
# MAIN RUN OCR
# ==============================

def run_grouped_ocr(invoice_name, uploaded_docs, with_total_container, forced_vendor_id=None):
    """
    uploaded_docs format:
    {
        "invoice_paths": [...],
        "packing_paths": [...],
        "bl_path": "/tmp/xxx.pdf" | None,
        "coo_paths": [...],
    }

    Flow baru:
    - grouping Invoice + PL + COO by invoice_no
    - BL global, dipakai ke semua group
    - tiap group diproses in-memory
    - final output tetap hanya:
      1 detail file
      1 total file
      1 container file
    """
    invoice_paths = uploaded_docs.get("invoice_paths") or []
    packing_paths = uploaded_docs.get("packing_paths") or []
    bl_path = uploaded_docs.get("bl_path")
    coo_paths = uploaded_docs.get("coo_paths") or []

    forced_vendor_id = normalize_vendor_id(
        forced_vendor_id or uploaded_docs.get("forced_vendor_id")
    )

    if not invoice_paths:
        raise Exception("invoice_paths kosong")
    if not packing_paths:
        raise Exception("packing_paths kosong")

    create_running_markers(invoice_name, with_total_container)

    merged_detail_rows = []
    global_container_rows = []

    try:
        groups = _group_docs_by_invoice_no(
            invoice_paths=invoice_paths,
            packing_paths=packing_paths,
            coo_paths=coo_paths,
        )

        total_groups = len(groups)
        print(f"[GROUPING] total_groups={total_groups}")
        for gk, grp in groups.items():
            print(
                f"[GROUPING] key={gk} invoice_no={grp['invoice_no']} "
                f"invoice={len(grp['invoice_paths'])} "
                f"packing={len(grp['packing_paths'])} "
                f"coo={len(grp['coo_paths'])}"
            )

        for _, grp in sorted(groups.items(), key=lambda item: str(item[1]["invoice_no"])):
            temp_group_paths = []

            temp_group_paths.extend(grp.get("temp_invoice_split_paths") or [])
            temp_group_paths.extend(grp.get("temp_packing_split_paths") or [])
            temp_group_paths.extend(grp.get("temp_coo_split_paths") or [])

            try:
                merged_invoice_pdf = _merge_pdfs(grp["invoice_paths"])
                temp_group_paths.append(merged_invoice_pdf)

                merged_packing_pdf = _merge_pdfs(grp["packing_paths"])
                temp_group_paths.append(merged_packing_pdf)

                grouped_pdf_paths = [
                    merged_invoice_pdf,
                    merged_packing_pdf,
                ]

                # BL global (1 file untuk semua OCR)
                if bl_path:
                    grouped_pdf_paths.append(bl_path)

                # COO per invoice group
                if grp["coo_paths"]:
                    merged_coo_pdf = _merge_pdfs(grp["coo_paths"])
                    temp_group_paths.append(merged_coo_pdf)
                    grouped_pdf_paths.append(merged_coo_pdf)

                group_output_name = (
                    f"{invoice_name}__{_safe_output_suffix(grp['invoice_no'])}"
                    if total_groups > 1
                    else (invoice_name or _safe_output_suffix(grp["invoice_no"]))
                )

                print(f"[GROUPING] run_ocr(in-memory) -> {group_output_name}")

                result = run_ocr(
                    invoice_name=group_output_name,
                    uploaded_pdf_paths=grouped_pdf_paths,
                    with_total_container=with_total_container,
                    persist_output=False,
                    manage_markers=False,
                    forced_vendor_id=forced_vendor_id,
                )

                merged_detail_rows.extend(result.get("detail_rows") or [])

                # BL cuma 1 global -> container cukup ambil sekali
                if with_total_container and not global_container_rows:
                    global_container_rows = result.get("container_rows") or []

            finally:
                for p in temp_group_paths:
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass

        if not merged_detail_rows:
            raise Exception("Tidak ada hasil detail gabungan")

        detail_csv_uri = _convert_to_csv_path(
            f"output/detail/{invoice_name}_detail.csv",
            merged_detail_rows,
            field_order=DETAIL_CSV_FIELD_ORDER_FINAL
        )

        total_csv_uri = None
        container_csv_uri = None

        if with_total_container and global_container_rows:
            total_data = _build_total_from_detail_and_container(
                merged_detail_rows,
                global_container_rows
            )
            total_data = _validate_total_rows(total_data, merged_detail_rows)

            total_csv_uri = _convert_to_csv_path(
                f"output/total/{invoice_name}_total.csv",
                total_data,
                field_order=TOTAL_CSV_FIELD_ORDER_FINAL
            )

            container_csv_uri = _convert_to_csv_path(
                f"output/container/{invoice_name}_container.csv",
                global_container_rows
            )

        return {
            "detail_csv": detail_csv_uri,
            "total_csv": total_csv_uri,
            "container_csv": container_csv_uri,
        }

    finally:
        try:
            delete_running_markers(invoice_name, with_total_container)
        except Exception:
            pass

def _assign_detail_row_numbers(rows: list):
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        row["_detail_row_no"] = idx


def _drop_internal_detail_fields(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        for key in DETAIL_RECHECK_INTERNAL_FIELDS:
            row.pop(key, None)

        for key in list(row.keys()):
            if str(key).startswith("_po_"):
                row.pop(key, None)
DETAIL_RECHECK_INTERNAL_FIELDS = [
    "_detail_row_no",
    "_recheck_fields",
    "_po_neighbor_fallback",
    "_po_neighbor_direction",
    "_po_neighbor_inherited_po_no",
]

def _normalize_recheck_field_list(fields):
    if not fields:
        return []

    seen = set()
    result = []

    for f in fields:
        if not f:
            continue
        if f not in DETAIL_RECHECK_FIELDS:
            continue
        if f in seen:
            continue
        seen.add(f)
        result.append(f)

    return result


def _infer_recheck_fields_from_match_description(match_description: str):
    """
    Infer field mana yang perlu dicek ulang dari match_description existing.
    Tidak mengubah validator lama, hanya parsing string error yang sudah ada.
    """

    text = str(match_description or "").strip()
    if text == "" or text.lower() == "null":
        return []

    failed = []

    # 1) missing field langsung
    # contoh:
    # Invoice: missing inv_quantity
    # PackingList: missing pl_volume
    # COO: missing coo_gw
    missing_hits = re.findall(r"\bmissing\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", text, flags=re.IGNORECASE)
    failed.extend(missing_hits)

    # 2) formula invoice
    if "inv_amount != inv_quantity*inv_unit_price" in text:
        failed.extend(["inv_amount", "inv_quantity", "inv_unit_price"])

    # 3) compare row-level yang relevan ke recheck fields
    compare_map = {
        "pl_gw != coo_gw": ["pl_gw"],
        "pl_package_count != coo_package_count": ["pl_package_count"],
        "coo_quantity != inv_quantity": ["inv_quantity"],
        "coo_amount != inv_amount": ["inv_amount"],
        "coo_unit != inv_quantity_unit": ["inv_quantity_unit"],
    }

    upper_text = text.upper()
    for needle, fields in compare_map.items():
        if needle.upper() in upper_text:
            failed.extend(fields)

    # 4) total mismatch -> map ke field kandidat yang memang boleh direcheck
    total_map = {
        "INVOICE: TOTAL_QUANTITY MISMATCH": ["inv_quantity"],
        "INVOICE: TOTAL_AMOUNT MISMATCH": ["inv_amount", "inv_quantity", "inv_unit_price"],

        "PACKINGLIST: TOTAL_QUANTITY MISMATCH": ["pl_quantity"],
        "PACKINGLIST: TOTAL_NW MISMATCH": ["pl_nw"],
        "PACKINGLIST: TOTAL_GW MISMATCH": ["pl_gw"],
        "PACKINGLIST: TOTAL_VOLUME MISMATCH": ["pl_volume"],
        "PACKINGLIST: TOTAL_PACKAGE MISMATCH": ["pl_package_count"],
    }

    for needle, fields in total_map.items():
        if needle in upper_text:
            failed.extend(fields)

    failed = _normalize_recheck_field_list(failed)

    # fallback konservatif:
    # kalau gagal infer apa pun, tetap pakai semua field recheck lama
    if not failed:
        return list(DETAIL_RECHECK_FIELDS)

    return failed

def _build_detail_line_recheck_rows_payload(rows: list):
    payload = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        if row.get("match_score") != "false":
            continue

        recheck_fields = _infer_recheck_fields_from_match_description(
            row.get("match_description", "null")
        )

        # simpan internal agar apply-result tahu field mana yang boleh dioverwrite
        row["_recheck_fields"] = list(recheck_fields)

        item = {
            "_detail_row_no": row.get("_detail_row_no"),
            "_recheck_fields": list(recheck_fields),
            "match_description": row.get("match_description", "null"),
        }

        # tetap kirim field lama supaya prompt punya konteks,
        # tapi nanti apply-result hanya boleh overwrite field dalam _recheck_fields
        for key in DETAIL_RECHECK_FIELDS:
            value = row.get(key)

            if key in DETAIL_RECHECK_NUM_FIELDS:
                item[key] = 0 if _is_null(value) else value
            else:
                item[key] = "null" if value is None else value

        payload.append(item)

    return payload

def _build_detail_line_recheck_schema():
    schema = {
        "_detail_row_no": "number",
        "_recheck_fields": ["string"],
    }
    schema.update(DETAIL_RECHECK_SCHEMA)
    return schema


def _build_detail_line_recheck_prompt(rows_payload: list) -> str:
    schema_json = json.dumps(_build_detail_line_recheck_schema(), ensure_ascii=False, indent=2)
    rows_json = json.dumps(rows_payload, ensure_ascii=False, indent=2)

    return f"""
ROLE:
Anda adalah AI validator-checker untuk OUTPUT DETAIL OCR.

SOURCE OF TRUTH:
- PDF pada request ini adalah sumber kebenaran utama.
- JSON rows di bawah adalah hasil ekstraksi awal.
- Setiap row di bawah SUDAH gagal precheck Python.
- match_description adalah alasan kenapa row tersebut gagal.
- Setiap row memiliki "_recheck_fields".
- Anda HANYA boleh mengoreksi field yang namanya ada di "_recheck_fields" untuk row tersebut.
- Untuk field lain yang tidak ada di "_recheck_fields", WAJIB kembalikan nilai yang sama persis seperti input row.
- Jangan menebak field lain.

TUGAS:
- Cek ulang HANYA row-row yang diberikan.
- Cek ulang HANYA field-field berikut:
  1. inv_gw_unit
  2. inv_quantity
  3. inv_quantity_unit
  4. inv_unit_price
  5. inv_amount
  6. pl_quantity
  7. pl_package_count
  8. pl_nw
  9. pl_gw
  10. pl_volume
- JANGAN ubah field lain selain 10 field di atas.
- Header TIDAK boleh disentuh.
- Gunakan match_description sebagai petunjuk field mana yang perlu diperiksa.

ATURAN KETAT:
1) Output HANYA JSON ARRAY valid, tanpa teks lain.
2) Jumlah row output HARUS sama persis dengan jumlah row input.
3) Urutan row output HARUS sama persis dengan input.
4) WAJIB pertahankan _detail_row_no.
5) Jangan buat row baru.
6) Jangan hapus row.
7) Jangan return field header lain.
8) Jangan return field po_*.
9) Jika value memang tidak ada di dokumen:
   - string -> "null"
   - number -> 0
10) "_recheck_fields" WAJIB dipertahankan persis seperti input.
11) Untuk field di luar "_recheck_fields", copy nilai input apa adanya.

OUTPUT SCHEMA:
{schema_json}

FAILED ROWS YANG HARUS DICEK ULANG:
{rows_json}
"""

def _run_detail_precheck_pass(rows: list, header_obj: dict, vendor_id: str = "default"):
    _ensure_all_detail_keys(rows)

    _apply_header_to_rows(rows, header_obj if isinstance(header_obj, dict) else {})
    _postprocess_package_unit_fields(rows)
    _postprocess_pl_package_unit(rows, vendor_id=vendor_id)
    _postprocess_pl_volume(rows, vendor_id=vendor_id)

    _reset_match_fields(rows)

    _fill_forward(rows, "inv_customer_po_no")
    _postprocess_customer_po_no(rows)
    _fill_inv_price_unit_from_amount_unit(rows)

    _recompute_seq_by_key(rows, "inv_invoice_no", "inv_seq")

    _postprocess_customer_po_no(rows)
    _postprocess_inv_description(rows)
    _postprocess_item_no_fields(rows)
    _postprocess_unit_fields(rows)
    _postprocess_coo_description(rows)

    _postprocess_coo_item_mapping(rows)
    _postprocess_coo_no_and_seq(rows)

    _postprocess_bl_description(rows)
    _postprocess_bl_seller_name_similarity(rows)

    _postprocess_bl_coo_zero_to_null(rows)

    _validate_invoice_rows(rows)
    _validate_packing_rows(rows)
    _validate_invoice_vs_packing_extra(rows)
    _validate_bl_rows(rows)
    _validate_coo_rows(rows)

    _finalize_match_fields(rows)
    return rows


def _call_gemini_detail_line_recheck_once(file_uri: str, rows: list):
    rows_payload = _build_detail_line_recheck_rows_payload(rows)

    if not rows_payload:
        return []

    repaired_rows = []
    batch_size = max(1, DETAIL_GEMINI_RECHECK_BATCH_SIZE)

    for start in range(0, len(rows_payload), batch_size):
        batch = rows_payload[start:start + batch_size]

        repaired_batch = _call_gemini_json_uri(
            file_uri,
            _build_detail_line_recheck_prompt(batch),
            expect_array=True,
            retries=3
        )

        if not isinstance(repaired_batch, list):
            raise Exception("Gemini detail line recheck output bukan array")

        if len(repaired_batch) != len(batch):
            raise Exception(
                f"Gemini detail line recheck count mismatch. expected={len(batch)} got={len(repaired_batch)}"
            )

        repaired_rows.extend(repaired_batch)

    return repaired_rows


def _apply_detail_line_recheck_result(rows: list, repaired_rows: list):
    repaired_by_no = {}

    for repaired in repaired_rows or []:
        if not isinstance(repaired, dict):
            continue

        row_no = repaired.get("_detail_row_no")
        if row_no is None:
            continue

        repaired_by_no[int(row_no)] = repaired

    for row in rows:
        if not isinstance(row, dict):
            continue

        row_no = row.get("_detail_row_no")
        if row_no is None:
            continue

        repaired = repaired_by_no.get(int(row_no))
        if not repaired:
            continue

        allowed_fields = _normalize_recheck_field_list(
            row.get("_recheck_fields") or []
        )
        allowed_fields = _normalize_recheck_field_list(row.get("_recheck_fields") or [])
        if not allowed_fields:
            continue

        for key in allowed_fields:
            if key in repaired:
                row[key] = repaired.get(key)

    return rows

def run_ocr(
    invoice_name,
    uploaded_pdf_paths,
    with_total_container,
    persist_output=True,
    manage_markers=True,
    forced_vendor_id=None,
):

    # Guard backend supaya COO tidak pernah diproses tanpa Bill of Lading.
    # Kontrak dari UI: jika ada 3 file tetapi with_total_container=False,
    # maka file ke-3 adalah COO tanpa BL dan harus ditolak.
    if len(uploaded_pdf_paths) == 3 and not with_total_container:
        raise Exception("COO hanya bisa diproses jika Bill of Lading juga diupload.")

    normalized_pdf_paths = []
    temp_local_paths = []
    all_rows = []
    header_obj = {}
    total_data = None
    container_data = None
    po_lines = []
    po_numbers = set()

    run_id = uuid.uuid4().hex
    prefix = TMP_PREFIX.rstrip("/")
    run_prefix = f"{prefix}/{run_id}"

    if manage_markers:
        create_running_markers(invoice_name, with_total_container)

    bucket = storage_client.bucket(BUCKET_NAME)

    try:
        for p in uploaded_pdf_paths:
            normalized = _ensure_input_is_pdf(p)
            normalized_pdf_paths.append(normalized)

            if os.path.abspath(str(normalized)) != os.path.abspath(str(p)):
                temp_local_paths.append(normalized)

        # DETAIL: invoice+packing saja (2 file pertama dari UI)
        if len(normalized_pdf_paths) < 2:
            raise Exception("Minimal harus ada 2 file: invoice dan packing list.")

        # ==========================================
        # PREPROCESS HANYA INVOICE + PACKING LIST
        # ==========================================
        invoice_onepage_pdf = _preprocess_invoice_or_pl_to_one_page(
            normalized_pdf_paths[0],
            "invoice"
        )
        temp_local_paths.append(invoice_onepage_pdf)

        packing_onepage_pdf = _preprocess_invoice_or_pl_to_one_page(
            normalized_pdf_paths[1],
            "packing"
        )
        temp_local_paths.append(packing_onepage_pdf)

        preprocessed_detail_inputs = [
            invoice_onepage_pdf,
            packing_onepage_pdf,
        ]

        # DETAIL: invoice + packing yang sudah di-merge jadi 1 page masing-masing
        merged_pdf_detail = _merge_pdfs(preprocessed_detail_inputs)
        temp_local_paths.append(merged_pdf_detail)

        merged_pdf_detail = _compress_pdf_if_needed(merged_pdf_detail)
        if merged_pdf_detail not in temp_local_paths:
            temp_local_paths.append(merged_pdf_detail)

        file_uri_detail = _upload_temp_pdf_to_gcs(
            merged_pdf_detail,
            run_prefix,
            name="detail"
        )

        file_uri_full = None

        # FULL:
        # invoice + packing pakai hasil preprocess
        # BL / COO / dokumen lain tetap original
        has_extra_docs = len(normalized_pdf_paths) > 2
        if has_extra_docs:
            full_input_paths = [
                invoice_onepage_pdf,
                packing_onepage_pdf,
            ] + normalized_pdf_paths[2:]

            merged_pdf_full = _merge_pdfs(full_input_paths)
            temp_local_paths.append(merged_pdf_full)

            merged_pdf_full = _compress_pdf_if_needed(merged_pdf_full)
            if merged_pdf_full not in temp_local_paths:
                temp_local_paths.append(merged_pdf_full)

            file_uri_full = _upload_temp_pdf_to_gcs(
                merged_pdf_full,
                run_prefix,
                name="full"
            )

        detail_input_uri = file_uri_full if file_uri_full else file_uri_detail

        print("OCR Header")

        header_obj = _call_gemini_json_uri(
            detail_input_uri,
            build_header_prompt(),
            expect_array=False,
            retries=3
        )
        if not isinstance(header_obj, dict):
            header_obj = {}

        # GET TOTAL ROW FROM GEMINI
        data_row = _call_gemini_json_uri(file_uri_detail, ROW_SYSTEM_INSTRUCTION, expect_array=False, retries=3)

        if isinstance(data_row, dict) and "total_row" in data_row:
            total_row = int(data_row["total_row"])
        else:
            raise Exception(f"total_row tidak ditemukan di response: {data_row}")

        # NEW: INDEX extraction (anchor line item)
        index_items = _call_gemini_json_uri(
            file_uri_detail,
            build_index_prompt(total_row),
            expect_array=True,
            retries=3
        )

        # fallback safety
        if not isinstance(index_items, list) or not index_items:
            raise Exception("INDEX line items kosong")

        # kalau panjang index beda, lebih aman pakai panjang index sebagai total_row aktual
        if len(index_items) != total_row:
            print(f"[WARN] total_row={total_row} tapi index_items={len(index_items)}. Pakai len(index_items) sebagai total_row.")
            total_row = len(index_items)

        _fill_forward(index_items, "inv_customer_po_no")
        _fill_forward(index_items, "pl_customer_po_no")

        # =========================
        # VENDOR CONTEXT
        # =========================
        vendor_id = normalize_vendor_id(forced_vendor_id)

        if vendor_id == "default":
            raise Exception("Vendor wajib dipilih dari UI. forced_vendor_id kosong atau tidak valid.")

        vendor_prompt_text = load_vendor_prompt_text(vendor_id)
        vendor_source = "ui"

        print(
            f"[VENDOR CONTEXT] vendor_id={vendor_id} "
            f"vendor_source={vendor_source} forced_vendor_id={forced_vendor_id}"
        )

        # BATCH DETAIL EXTRACTION
        jobs = []
        first_index = 1
        batch_no = 1

        while first_index <= total_row:
            last_index = min(first_index + BATCH_SIZE - 1, total_row)

            index_slice = index_items[first_index - 1:last_index]  # 1-based -> 0-based
            expected_indices = list(range(first_index, last_index + 1))

            if len(index_slice) != len(expected_indices):
                raise Exception(
                    f"Index slice mismatch. "
                    f"batch_no={batch_no}, "
                    f"first_index={first_index}, "
                    f"last_index={last_index}, "
                    f"index_slice_len={len(index_slice)}, "
                    f"expected_len={len(expected_indices)}"
                )

            prompt = build_detail_prompt_from_index(
                total_row=total_row,
                index_slice=index_slice,
                first_index=first_index,
                last_index=last_index,
                vendor_id=vendor_id,
                vendor_prompt_text=vendor_prompt_text
            )

            jobs.append({
                "batch_no": batch_no,
                "prompt": prompt,
                "first_index": first_index,
                "last_index": last_index,
                "expected_indices": expected_indices,
            })

            first_index = last_index + 1
            batch_no += 1

        MAX_WORKERS = max(1, len(jobs))

        results = {}

        print(
            f"OCR Batching | total_jobs={len(jobs)} "
            f"| max_workers={MAX_WORKERS} "
            f"| total_row={total_row} "
            f"| batch_size={BATCH_SIZE}"
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [
                ex.submit(
                    _run_one_detail_batch,
                    detail_input_uri,
                    run_prefix,
                    job["batch_no"],
                    job["prompt"],
                    job["first_index"],
                    job["last_index"],
                    job["expected_indices"],
                )
                for job in jobs
            ]

            for f in as_completed(futures):
                bn, arr = f.result()
                results[bn] = arr

                expected_count = len(next(
                    job["expected_indices"]
                    for job in jobs
                    if job["batch_no"] == bn
                ))

                print(
                    f"[BATCH DONE] "
                    f"batch_no={bn} "
                    f"expected={expected_count} "
                    f"actual={len(arr)}"
                )

        missing_batches = sorted({
            job["batch_no"] for job in jobs
        } - set(results.keys()))

        if missing_batches:
            raise Exception(f"Missing detail batch results: {missing_batches}")

        all_rows = []
        for bn in sorted(results.keys()):
            all_rows.extend(results[bn])

        if not all_rows:
            raise Exception("Tidak ada data detail hasil Gemini")

        actual_detail_count = len(all_rows)

        print(
            f"[DETAIL_COUNT_AFTER_BATCH] "
            f"expected={total_row} actual={actual_detail_count}"
        )

        if actual_detail_count != total_row:
            got_indices = sorted([
                int(r.get("_expected_index"))
                for r in all_rows
                if isinstance(r, dict) and r.get("_expected_index") is not None
            ])

            expected_indices_all = list(range(1, total_row + 1))
            missing_indices = sorted(set(expected_indices_all) - set(got_indices))
            extra_indices = sorted(set(got_indices) - set(expected_indices_all))

            raise Exception(
                f"Detail row count mismatch after batch. "
                f"expected={total_row}, actual={actual_detail_count}, "
                f"missing_indices={missing_indices}, extra_indices={extra_indices}"
            )

        # =========================================
        # PRECHECK PYTHON
        # isi match_score + match_description
        # hanya untuk menentukan row gagal
        # =========================================
        all_rows = _run_detail_precheck_pass(all_rows, header_obj, vendor_id=vendor_id)
        _assign_detail_row_numbers(all_rows)

        # =========================================
        # GEMINI RECHECK SEKALI
        # HANYA untuk row yang match_score == false
        # =========================================
        repaired_rows = _call_gemini_detail_line_recheck_once(
            detail_input_uri,
            all_rows
        )

        if repaired_rows:
            all_rows = _apply_detail_line_recheck_result(all_rows, repaired_rows)

        print(
            f"[DETAIL_COUNT_AFTER_RECHECK] "
            f"expected={total_row} actual={len(all_rows)}"
        )

        if len(all_rows) != total_row:
            raise Exception(
                f"Detail row count changed after recheck. "
                f"expected={total_row}, actual={len(all_rows)}"
            )

        # =========================
        # OPTIONAL: total/container
        # =========================
        total_data = None
        container_data = None
        if with_total_container:
            container_data = _call_gemini_json_uri(
                file_uri_full,
                CONTAINER_SYSTEM_INSTRUCTION,
                expect_array=True,
                retries=3
            )

            _postprocess_unit_fields(container_data)

        # =========================================
        # FLOW VALIDASI FINAL LAMA TETAP JALAN
        # =========================================
        _apply_header_to_rows(all_rows, header_obj)
        _postprocess_pl_volume(all_rows, vendor_id=vendor_id)
        _postprocess_pl_package_unit(all_rows, vendor_id=vendor_id)
        _postprocess_package_unit_fields(all_rows)

        _reset_match_fields(all_rows)

        _fill_forward(all_rows, "inv_customer_po_no")
        _postprocess_customer_po_no(all_rows)
        _fill_inv_price_unit_from_amount_unit(all_rows)

        po_numbers = {
            str(r.get("inv_customer_po_no")).strip()
            for r in all_rows
            if isinstance(r, dict) and not _is_null(r.get("inv_customer_po_no"))
        }
        po_lines = _stream_filter_po_lines(po_numbers)
        print("PO NUMBERS:", po_numbers)
        print("PO LINES FOUND:", len(po_lines))

        _recompute_seq_by_key(all_rows, "inv_invoice_no", "inv_seq")

        _postprocess_customer_po_no(all_rows)
        _postprocess_inv_description(all_rows)
        _postprocess_item_no_fields(all_rows)
        _postprocess_unit_fields(all_rows)
        _postprocess_coo_description(all_rows)

        # NEW: null-kan COO item yang tidak match ke row detail
        _postprocess_coo_item_mapping(all_rows)

        # NEW: hitung coo_seq hanya untuk row COO yang masih valid/matched
        _postprocess_coo_no_and_seq(all_rows)

        _postprocess_bl_description(all_rows)
        _postprocess_bl_seller_name_similarity(all_rows)

        all_rows = _map_po_to_details(po_lines, all_rows)
        all_rows = _generate_inv_amount_before_validation(all_rows)

        _postprocess_bl_coo_zero_to_null(all_rows)
        _postprocess_invoice_no_consensus(all_rows)

        all_rows = _deduplicate_detail_rows_before_validation(all_rows, vendor_id=vendor_id)

        _assign_detail_row_numbers(all_rows)
        _recompute_seq_by_key(all_rows, "inv_invoice_no", "inv_seq")
        _postprocess_coo_no_and_seq(all_rows)

        all_rows = _validate_po(all_rows)

        _validate_invoice_rows(all_rows)
        _validate_packing_rows(all_rows)
        _validate_invoice_vs_packing_extra(all_rows)

        _validate_bl_rows(all_rows)
        _validate_coo_rows(all_rows)

        total_attribution = _apply_total_contribution_scoring(all_rows)

        _finalize_match_fields(all_rows)

        _drop_columns(all_rows, [
            "inv_messrs",
            "inv_messrs_address",
            "inv_gw",
            "inv_gw_unit",
            "confidence_logprob",
            "confidence_margin",
            "confidence_predicted_label",
            "confidence_source",
            "audit_candidate",
            "audit_rank",
        ])

        if with_total_container:
            total_data = _build_total_from_detail_and_container(all_rows, container_data)
            total_data = _validate_total_rows(total_data, all_rows)

        all_rows = _finalize_audit_confidence_labels(
            all_rows,
            total_attribution=total_attribution
        )

        _rename_final_fields(all_rows)
        _drop_internal_detail_fields(all_rows)

        for row in all_rows:
            if isinstance(row, dict):
                row.pop("_expected_index", None)

        # =========================
        # FINAL RESULT OBJECT
        # =========================
        result = {
            "detail_rows": all_rows,
            "total_rows": total_data if total_data is not None else [],
            "container_rows": container_data if container_data is not None else [],
        }

        if not persist_output:
            return result

        detail_csv_uri = _convert_to_csv_path(
            f"output/detail/{invoice_name}_detail.csv",
            result["detail_rows"],
            field_order=DETAIL_CSV_FIELD_ORDER_FINAL
        )

        total_csv_uri = None
        if result["total_rows"]:
            total_csv_uri = _convert_to_csv_path(
                f"output/total/{invoice_name}_total.csv",
                result["total_rows"],
                field_order=TOTAL_CSV_FIELD_ORDER_FINAL
            )

        container_csv_uri = None
        if result["container_rows"]:
            container_csv_uri = _convert_to_csv_path(
                f"output/container/{invoice_name}_container.csv",
                result["container_rows"]
            )

        result.update({
            "detail_csv": detail_csv_uri,
            "total_csv": total_csv_uri,
            "container_csv": container_csv_uri,
        })

        return result

    finally:
        if manage_markers:
            try:
                delete_running_markers(invoice_name, with_total_container)
            except Exception:
                pass

        for blob in bucket.list_blobs(prefix=f"{run_prefix}/"):
            blob.delete()

        for p in temp_local_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass