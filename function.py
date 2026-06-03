import csv
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import ijson
import pymupdf as fitz
from google import genai
from google.cloud import storage
from google.genai import types
from openpyxl import Workbook
from openpyxl.styles import Alignment
from PyPDF2 import PdfMerger, PdfReader, PdfWriter

from config import *
from container import CONTAINER_SYSTEM_INSTRUCTION
from detail import (
    build_detail_prompt_from_index,
    build_header_prompt,
    build_index_prompt,
    DETAIL_CSV_FIELD_ORDER_FINAL,
    DETAIL_LINE_FIELDS,
    DETAIL_LINE_NUM_FIELDS,
    HEADER_SCHEMA_TEXT as HEADER_FIELDS,
)
from row import ROW_SYSTEM_INSTRUCTION, KARET_DELI_ROW_SYSTEM_INSTRUCTION
from vendor_detection import (
    load_vendor_prompt_text,
    normalize_vendor_id,
)

BATCH_SIZE = 30
CHENGS_DETAIL_BATCH_SIZE = 3
DETAIL_GEMINI_RECHECK_BATCH_SIZE = int(os.getenv("DETAIL_GEMINI_RECHECK_BATCH_SIZE", "30"))
test_number = 2

DETAIL_TOTAL_RECHECK_MAX_ZERO_NEGATIVE_RETRIES = int(
    os.getenv("DETAIL_TOTAL_RECHECK_MAX_ZERO_NEGATIVE_RETRIES", "4")
)

DETAIL_TOTAL_RECHECK_REPAIR_AFTER_RETRY = str(
    os.getenv("DETAIL_TOTAL_RECHECK_REPAIR_AFTER_RETRY", "true")
).strip().lower() in {"1", "true", "yes", "y"}

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

def _is_shimano_inc_vendor(vendor_id: str = "default") -> bool:
    return normalize_vendor_id(vendor_id) == "shimano_inc"

def _is_recheck_label_only_vendor(vendor_id: str = "default") -> bool:
    return normalize_vendor_id(vendor_id) in {
        "jht_carbon",
        "bafang_motor",
        "liow_ko",
        "joy"
    }

def _get_detail_csv_field_order(vendor_id: str = "default"):
    if _is_shimano_inc_vendor(vendor_id):
        return list(DETAIL_CSV_FIELD_ORDER_FINAL)

    return [
        k for k in DETAIL_CSV_FIELD_ORDER_FINAL
        if k != "inv_hs_code"
    ]

# Tambahkan vendor lain ke dalam set ini di masa depan jika butuh deduplikasi PL
DEDUPLICATE_PL_NUMERIC_VENDORS = {
    "liow_ko",
}

def _should_deduplicate_pl_numeric(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in DEDUPLICATE_PL_NUMERIC_VENDORS

def _deduplicate_pl_numeric_fields_for_vendors(rows: list, vendor_id: str = "default"):
    """
    Mencegah duplikasi field aditif PL ketika 1 baris PL dipecah ke beberapa baris Invoice secara berurutan.
    Dijalankan setelah PO Mapping agar tidak mengganggu logic child PO.
    Hanya berlaku untuk vendor yang terdaftar di DEDUPLICATE_PL_NUMERIC_VENDORS.
    """
    if not _should_deduplicate_pl_numeric(vendor_id):
        return rows
        
    last_pl_key = None
    
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        # Abaikan child PO karena nilainya sudah otomatis di-nol-kan oleh fungsi PO Split
        if row.get("_po_split_primary") is False:
            continue
            
        pl_item = str(row.get("pl_item_no") or "").strip()
        pl_qty = _to_float(row.get("pl_quantity"))
        pl_pkg = _to_float(row.get("pl_package_count"))
        pl_nw = _to_float(row.get("pl_nw"))
        pl_gw = _to_float(row.get("pl_gw"))
        pl_vol = _to_float(row.get("pl_volume"))
        
        # Abaikan jika item_no kosong atau quantity 0/null
        if not pl_item or pl_item == "null" or not pl_qty:
            last_pl_key = None
            continue
            
        # Bentuk key gabungan dari semua value PL
        current_pl_key = f"{pl_item}::{pl_qty}::{pl_pkg}::{pl_nw}::{pl_gw}::{pl_vol}"
        
        if current_pl_key == last_pl_key:
            # Duplikat item berurutan dengan semua numerik sama ditemukan, nol-kan field PL
            row["pl_quantity"] = 0
            row["pl_package_count"] = 0
            row["pl_nw"] = 0
            row["pl_gw"] = 0
            row["pl_volume"] = 0
                
            print(f"[_deduplicate_pl_numeric] Deduped PL row for item {pl_item}")
        else:
            last_pl_key = current_pl_key
            
    return rows

def _get_header_fields_for_vendor(vendor_id: str = "default"):
    if _is_shimano_inc_vendor(vendor_id):
        return [k for k in HEADER_FIELDS if k != "bl_mark_number"]

    return list(HEADER_FIELDS)

def _get_detail_batch_size_for_vendor(vendor_id: str = "default") -> int:
    """
    Batch size khusus detail extraction.

    Default = BATCH_SIZE.
    Khusus vendor chengs = 3, supaya prompt per batch lebih kecil
    dan mengurangi risiko MAX_TOKENS / output kepotong.
    """
    if normalize_vendor_id(vendor_id) == "chengs":
        return CHENGS_DETAIL_BATCH_SIZE

    return BATCH_SIZE

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
    "PCS": "PCS",
    "PC": "PCS",
    "PCE": "PCS",
    "PIECE": "PCS",
    "PIECES": "PCS",
    "H87": "PCS",

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

# FUNCTION MATCH DESCRIPTION ROW CONTINUATION

ZERO_CONTINUATION_MATCH_DESCRIPTION_FIELDS = [
    "inv_quantity",
    "inv_unit_price",
    "inv_amount",
    "pl_quantity",
    "pl_nw",
    "pl_gw",
    "pl_volume",
]

def _create_sliced_pdf_for_batch(input_pdf: str, start_page_idx: int, end_page_idx: int) -> str:
    """Memotong PDF dari halaman start_page_idx hingga end_page_idx (0-based)"""
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    total_pages = len(reader.pages)
    
    start_page_idx = max(0, start_page_idx)
    end_page_idx = min(total_pages - 1, end_page_idx)
    
    for i in range(start_page_idx, end_page_idx + 1):
        writer.add_page(reader.pages[i])
        
    out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_sliced_{start_page_idx}_{end_page_idx}.pdf")
    out.close()
    
    with open(out.name, "wb") as f:
        writer.write(f)
        
    return out.name

def _is_zero_continuation_row(row: dict) -> bool:
    """
    True hanya jika SEMUA field numeric utama bernilai 0.

    Field yang dicek:
    - inv_quantity
    - inv_unit_price
    - inv_amount
    - pl_quantity
    - pl_nw
    - pl_gw
    - pl_volume

    Catatan:
    - null / kosong tidak dianggap 0.
    - String "0", "0.0", angka 0, Decimal(0) dianggap 0.
    """
    if not isinstance(row, dict):
        return False

    for field in ZERO_CONTINUATION_MATCH_DESCRIPTION_FIELDS:
        value = _to_float(row.get(field))

        if value is None:
            return False

        if abs(value) > 1e-9:
            return False

    return True


def _inherit_match_description_for_zero_continuation_rows(rows: list):
    """
    Approach 2:
    Single-pass.

    Simpan match_description dari row parent terakhir yang BUKAN row nol.
    Jika row saat ini adalah row nol, copy match_description dari parent terakhir.
    """
    if not isinstance(rows, list):
        return rows

    parent_match_description = None
    parent_inv_seq = None
    parent_row_no = None
    changed_count = 0

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        if _is_zero_continuation_row(row):
            if not _is_null(parent_match_description):
                row["match_description"] = parent_match_description
                row["inv_seq"] = parent_inv_seq
                changed_count += 1

                print(
                    f"[ZERO_CONTINUATION_MATCH_DESCRIPTION] "
                    f"row={idx + 1} inherited_from_parent_row={parent_row_no}"
                )

            continue

        # Row bukan nol menjadi parent baru.
        current_match_description = row.get("match_description")
        current_sequence = row.get("inv_sequence")

        if not _is_null(current_match_description):
            parent_match_description = current_match_description
            parent_inv_seq = current_sequence

            parent_row_no = idx + 1
        else:
            parent_match_description = None
            parent_inv_seq = None
            parent_row_no = idx + 1

    print(
        f"[ZERO_CONTINUATION_MATCH_DESCRIPTION] "
        f"changed_rows={changed_count}"
    )

    return rows

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


def _build_karet_deli_pl_total_refocus_prompt(target_invoice_no: str) -> str:
    return f"""
ROLE:
Anda mengekstrak SATU value spesifik dari dokumen Packing List karet_deli.

TARGET INVOICE: {target_invoice_no}

TUGAS:
Cari nilai TOTAL quantity untuk invoice "{target_invoice_no}" SAJA — BUKAN GRAND TOTAL.

ATURAN KETAT:
1. Karet Deli PL bisa berisi multiple section:
   - Header utama: "No. : INS-XXX/YY"
   - "TOTAL X.XX PCS / Y.YY SETS"        ← total untuk section parent (INS-XXX/YY)
   - Sub-section header standalone: "INS-XXX/YY/ZZZ"
   - "TOTAL X.XX PCS"                    ← total untuk sub-section (INS-XXX/YY/ZZZ)
   - "GRAND TOTAL X.XX PCS / Y.YY SETS"  ← gabungan SEMUA section, JANGAN DIAMBIL

2. Untuk target invoice "{target_invoice_no}":
   - Jika target match header utama (e.g., "INS-009/26"): ambil baris TOTAL setelah item-item parent dan SEBELUM sub-section header pertama.
   - Jika target match sub-section (e.g., "INS-009/26/K100"): ambil baris TOTAL yang berada SETELAH sub-section header itu.
   - DILARANG mengambil GRAND TOTAL meskipun nilainya terlihat lebih masuk akal.

3. Jika TOTAL untuk target invoice punya lebih dari satu unit (PCS, SETS, dll), JUMLAHKAN semua nilai-nya menjadi satu angka.
   Contoh: "TOTAL 30,037.00 PCS" dan baris lanjutan "400.00 SETS" untuk parent → pl_total_quantity = 30437.

4. Output HANYA JSON, tanpa teks lain, tanpa markdown.

OUTPUT SCHEMA:
{{
  "pl_total_quantity": "number"
}}
""".strip()


def _karet_deli_refocus_pl_total_quantity(
    file_uri: str,
    all_rows: list,
    base_header_obj: dict,
    vendor_id: str,
):
    """
    Detect-then-refocused-retry untuk pl_total_quantity karet_deli.

    Trigger:
    - vendor == karet_deli
    - Dari rows hasil detail extraction (sebelum `_apply_header_to_rows` overwrite
      seragam), terdapat LEBIH DARI 1 nilai distinct untuk field pl_total_quantity.
      Itu indikasi Gemini ragu/non-deterministik antar baris dalam invoice yang sama.

    Tindakan:
    - Panggil Gemini 1x dengan prompt super-fokus minta TOTAL parent saja (BUKAN GRAND TOTAL).
    - Override base_header_obj.pl_total_quantity dengan hasil refocus.
    - Validation downstream tetap meaningful: kalau hasil refocus salah dan tidak match
      sum(pl_quantity), `_validate_packing_rows` akan flag mismatch seperti biasa.

    Return: True kalau override terjadi, False kalau tidak (caller bisa log).
    """
    if not isinstance(all_rows, list) or not all_rows:
        return False

    if not isinstance(base_header_obj, dict):
        return False

    # Kumpulkan nilai distinct pl_total_quantity dari rows.
    # Per `run_ocr` dipanggil per-group, semua row di `all_rows` punya invoice
    # yang sama, jadi tidak perlu group by inv_invoice_no lagi.
    distinct_values = set()
    for r in all_rows:
        if not isinstance(r, dict):
            continue
        v = _to_float(r.get("pl_total_quantity"))
        if v is None:
            continue
        distinct_values.add(v)

    if len(distinct_values) <= 1:
        # Konsisten antar row — Gemini tidak ragu di pass ini. Tidak perlu refocus.
        return False

    target_invoice = (
        base_header_obj.get("pl_invoice_no")
        or base_header_obj.get("inv_invoice_no")
    )
    if _is_null(target_invoice):
        return False

    target_invoice_str = str(target_invoice).strip()
    if not target_invoice_str:
        return False

    print(
        f"[KARET_DELI_PL_TOTAL_REFOCUS][TRIGGER] "
        f"invoice='{target_invoice_str}' "
        f"distinct_values={sorted(distinct_values)} "
        f"declared_header={base_header_obj.get('pl_total_quantity')}"
    )

    try:
        focused_result = _call_gemini_json_uri(
            file_uri,
            _build_karet_deli_pl_total_refocus_prompt(target_invoice_str),
            expect_array=False,
            retries=2,
            vendor_id=vendor_id,
        )
    except Exception as e:
        print(f"[KARET_DELI_PL_TOTAL_REFOCUS][FAIL] gemini call error: {repr(e)}")
        return False

    if not isinstance(focused_result, dict):
        print(f"[KARET_DELI_PL_TOTAL_REFOCUS][FAIL] result bukan dict: {focused_result}")
        return False

    new_value = _to_float(focused_result.get("pl_total_quantity"))
    if new_value is None:
        print(f"[KARET_DELI_PL_TOTAL_REFOCUS][FAIL] pl_total_quantity tidak valid: {focused_result}")
        return False

    old_value = base_header_obj.get("pl_total_quantity")
    print(
        f"[KARET_DELI_PL_TOTAL_REFOCUS][ACCEPT] "
        f"invoice='{target_invoice_str}' header_old={old_value} -> new={new_value} "
        f"(distinct_in_rows={sorted(distinct_values)})"
    )
    base_header_obj["pl_total_quantity"] = new_value
    return True


# Field total yang per-rule HARUS sama untuk semua row dalam 1 invoice_no.
# Multi-pass extraction (karet_deli multi-section PL, LLM non-determinism)
# kadang menghasilkan nilai berbeda per baris untuk field-field ini —
# misal pl_total_quantity di 1 baris 30437, baris lain 30438. Canonical-kan.
INVOICE_TOTAL_HEADER_FIELDS = (
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
)


def _canonicalize_invoice_total_headers(rows: list):
    """
    Untuk tiap inv_invoice_no group, pilih satu nilai canonical per
    total-header field, lalu tulis balik ke seluruh row di group itu.

    Strategi: majority vote (nilai paling sering muncul menang),
    tie-break ke magnitude lebih besar (defensif terhadap row partial
    extraction yang berisi 0/null/angka tidak lengkap).
    Null values diabaikan saat voting.
    """
    if not isinstance(rows, list) or not rows:
        return rows

    grouped = _group_rows_by_invoice_no(rows)

    canonical_by_group = {}

    for group_key, group_rows in grouped.items():
        canonical = {}

        for field in INVOICE_TOTAL_HEADER_FIELDS:
            counts = {}
            for row in group_rows:
                if not isinstance(row, dict):
                    continue
                v = _to_float(row.get(field))
                if v is None:
                    continue
                counts[v] = counts.get(v, 0) + 1

            if not counts:
                continue

            sorted_vals = sorted(
                counts.items(),
                key=lambda kv: (kv[1], abs(kv[0])),
                reverse=True,
            )
            canonical[field] = sorted_vals[0][0]

        canonical_by_group[group_key] = canonical

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        group_key = _get_detail_total_group_key(row, idx)
        canonical = canonical_by_group.get(group_key)
        if not canonical:
            continue
        for field, value in canonical.items():
            row[field] = value

    return rows


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
    # User-facing / CSV-facing message dibuat clean.
    # Tetap simpan label total_xxx mismatch karena dipakai untuk total issue detection.
    _append_err(row, label)

    # Detail teknis disimpan internal saja.
    row["_total_issue_debug"] = {
        "invoice_no": invoice_group,
        "actual_sum": actual_sum,
        "declared_total": declared_total,
        "gap": gap,
        "suspected_row_contribution": round(contribution_ratio, 4),
        "reason": reason,
        "row_value": None if row_value is None else row_value,
    }

    print(
        f"[TOTAL_ATTRIBUTION][CANDIDATE] "
        f"label='{label}' invoice_no={invoice_group} "
        f"sum={actual_sum} doc={declared_total} gap={gap} "
        f"ratio={round(contribution_ratio, 4)} "
        f"reason={reason} row_value={row_value}"
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

                print(
                    f"[TOTAL_ATTRIBUTION][TOP1_NOT_CONVICTED] invoice_no={invoice_group} "
                    f"field={spec['declared_field']} "
                    f"row_no={top.get('row_no')} ratio={top.get('ratio')} gap={gap} "
                    f"reason={top.get('reason')}"
                )
                continue

            # CASE 5: no candidate dari rule utama -> pakai most influential anchor
            # CASE 5:
            # Jangan pakai anchor fallback sebagai culprit.
            # Missing row / total cell error tidak boleh membuat row existing negative.
            fallback = _pick_most_influential_fallback(
                group_rows=group_rows,
                spec=spec,
                gap=gap,
            )
            if fallback:
                print(
                    f"[TOTAL_ATTRIBUTION][ANCHOR_NOT_CONVICTED] invoice_no={invoice_group} "
                    f"field={spec['declared_field']} "
                    f"row_no={fallback.get('row_no')} gap={gap} "
                    f"reason={fallback.get('reason')}"
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
    - Invoice No: <nomor>
    - INVOICE: <nomor>
    - Invoice number boleh numeric-only atau alfanumerik.
    - Jangan ambil PO number, TAX ID number, page number, quantity, carton, NW, GW, atau CBM.
    - Tolong Jangan sampai ada invoice no yang missing

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

def _extract_invoice_no_from_text_for_split(page_text: str, doc_type: str, vendor_id: str = "default") -> str:
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
        raw = re.split(r"\bDATE\b|\bPAGE\b|\bPORT\b|\bVESSEL\b|\bVOYAGE\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if not raw:
            return ""
        first_non_empty = ""
        for part in raw.splitlines():
            part = part.strip()
            if part:
                first_non_empty = part
                break
        raw = (first_non_empty or raw).strip()
        return _preprocess_invoice_no_for_grouping(raw)

    explicit_patterns = []
    if doc_type == "packing":
        explicit_patterns.extend([
            r"(?m)^\s*NO\.?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})\s*$",
            r"(?is)\bPACKING LIST\b.{0,120}?\bNO\.?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        ])

    # === GUARD KHUSUS SHIMANO ===
    if normalize_vendor_id(vendor_id) in {"shimano_inc", "shimano_singapore"}:
        explicit_patterns.append(r"(?is)\b(INS(?:PM)?[-][A-Z0-9]+)\b")
    # ============================

    explicit_patterns.extend([
        r"\bINVOICE\s*(?:NO\.?|NUMBER|#)?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bNO\.?\s*INVOICE\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bINVOICE NUMBER\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bINV\.?\s*NO\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
        r"\bINVOICE\s*NO\.?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})", 
        r"\bDOC\.?\s*NO\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,})",
    ])

    for pattern in explicit_patterns:
        for m in re.finditer(pattern, joined, flags=re.IGNORECASE):
            raw_match = m.group(1)
            normalized = _cleanup_candidate(raw_match)
            if normalized and _looks_like_invoice_no_candidate(normalized):
                return normalized

    invoice_hint_patterns = [r"\bINVOICE\b", r"\bINVOICE\s*NO\b", r"\bINVOICE\s*NUMBER\b"]

    for idx, line in enumerate(lines[:120]):
        hit = False
        for pat in invoice_hint_patterns:
            if re.search(pat, line, flags=re.IGNORECASE):
                hit = True
                break
        if not hit:
            continue

        for j in range(idx, min(idx + 20, len(lines))):
            candidate_text = lines[j]
            
            if len(candidate_text) > 30 or candidate_text.count(" ") >= 4: 
                continue
                
            if re.search(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", candidate_text):
                continue
            if "TAX ID" in candidate_text.upper() or "LC" in candidate_text.upper():
                continue
                
            candidate = _cleanup_candidate(candidate_text)
            if candidate and _looks_like_invoice_no_candidate(candidate):
                return candidate

    if doc_type == "coo":
        return ""

    generic_candidates = re.findall(r"\b[A-Z0-9][A-Z0-9\-/]{3,}\b", joined.upper())
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


def _extract_invoice_no_from_single_page_for_split(src_pdf_path: str, page_index: int, doc_type: str, vendor_id: str = "default") -> str:
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
            retries=3,
            vendor_id=vendor_id
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

def _extract_multiple_invoice_no_from_single_page_for_split(src_pdf_path: str, page_index: int, doc_type: str, vendor_id: str = "default") -> list:
    single_page_pdf = _create_single_page_pdf(src_pdf_path, page_index)
    try:
        grouping_run_prefix = f"{TMP_PREFIX.rstrip('/')}/grouping/page_split/{doc_type}/{uuid.uuid4().hex}"
        grouping_name = f"{doc_type}_page_{page_index + 1}_{uuid.uuid4().hex}"
        file_uri = _upload_temp_pdf_to_gcs(single_page_pdf, grouping_run_prefix, grouping_name)

        target_key = _get_grouping_target_key(doc_type)
        doc_label = _get_doc_label_for_prompt(doc_type)

        # 1. Prompt dipertajam untuk mencari sub-invoice / claim
        prompt = f"""
        ROLE:
        Anda mengekstrak SEMUA nomor invoice referensi dari SATU HALAMAN dokumen {doc_label}.
        Halaman ini bisa berisi lebih dari satu invoice (misalnya 2 invoice berbeda dicetak atas-bawah dalam satu lembar).

        TUGAS:
        Ambil SEMUA nilai invoice reference yang valid dari halaman ini. Kembalikan sebagai array of objects.

        ATURAN KHUSUS PENTING:
        - Selain nomor utama di header, periksa juga baris-baris item di bagian tengah/bawah halaman.
        - Terkadang ada nomor sub-invoice atau claim (contoh format: /K100, dll) yang menyempil tanpa label "Invoice No".
        - Jika Anda melihat string yang polanya mirip dengan invoice number utama (misalnya INS-...), WAJIB ekstrak string tersebut sebagai invoice number tersendiri.
        - WAJIB ekstrak invoice number SECARA UTUH termasuk SELURUH suffix bertingkat (contoh: "INS-009/26/WTB/HB" — jangan dipotong jadi "INS-009/26/WTB" atau "INS-009/26"). Suffix seperti "/HB" atau "/HL" di akhir WAJIB ikut diekstrak karena membedakan invoice yang berbeda.

        OUTPUT HANYA JSON ARRAY:
        [
          {{
            "{target_key}": "string"
          }}
        ]
        """.strip()

        obj_list = _call_gemini_json_uri(
            file_uri, prompt, expect_array=True, retries=3, vendor_id=vendor_id
        )

        keys = set()
        for obj in obj_list:
            if isinstance(obj, dict):
                raw_inv = obj.get(target_key, "null")
                if doc_type == "coo":
                    raw_inv = _cleanup_coo_invoice_no(raw_inv)
                norm = _preprocess_invoice_no_for_grouping(raw_inv)
                if norm:
                    keys.add(norm)
                    
        # 2. REGEX SAFETY NET KHUSUS KARET DELI
        # Jika LLM gagal menangkap invoice yang nyempil, Regex ini akan memaksa ambil.
        if normalize_vendor_id(vendor_id) == "karet_deli":
            try:
                import pymupdf as fitz
                import re
                src_doc = fitz.open(single_page_pdf)
                text = src_doc[0].get_text()
                
                # Regex menangkap pola INS-XXX/XX dengan suffix bertingkat (contoh: INS-009/26, INS-009/26/K100, INS-009/26/WTB/HB, INS-009/26/WTB/HL).
                # Penting: kuantor `*` agar segmen suffix bisa lebih dari satu — kalau hanya `?`, "INS-009/26/WTB/HB" akan terpotong jadi "INS-009/26/WTB" dan HB/HL ter-merge jadi satu group.
                matches = re.findall(r"\b(INS-\d{3}/\d{2}(?:/[A-Z0-9]+)*)\b", text, flags=re.IGNORECASE)
                for m in matches:
                    norm_m = _preprocess_invoice_no_for_grouping(m)
                    if norm_m and len(norm_m) > 5:
                        keys.add(norm_m)
                        
                src_doc.close()
            except Exception as e:
                print(f"[EXTRACT_MULTIPLE_INVOICE] Regex safety net failed: {e}")

        return list(keys)
    finally:
        try:
            os.remove(single_page_pdf)
        except Exception:
            pass

def _split_pdf_by_invoice_no(local_pdf_path: str, doc_type: str, vendor_id: str = "default"):
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if total_pages == 0:
        raise Exception(f"PDF {doc_type} kosong: {os.path.basename(local_pdf_path)}")

    norm_vendor = normalize_vendor_id(vendor_id)
    # Bypass LLM Trace khusus vendor berikut, langsung ke page fallback
    if norm_vendor in {"shimano_singapore", "shimano_inc", "karet_deli"}:
        print(f"[GROUPING][{doc_type.upper()}] Bypass LLM Trace khusus vendor {norm_vendor}, langsung ke page fallback")
        return _split_pdf_by_invoice_no_page_fallback(local_pdf_path, doc_type, vendor_id=vendor_id)

    try:
        traced_refs = _trace_invoice_refs_from_document(local_pdf_path, doc_type, vendor_id=vendor_id)

        if traced_refs:
            traced_entries = _build_split_entries_from_trace(
                local_pdf_path=local_pdf_path, 
                doc_type=doc_type, 
                traced_refs=traced_refs,
                vendor_id=vendor_id
            )
            if traced_entries:
                print(f"[GROUPING][PRIMARY_TRACE_OK][{doc_type.upper()}] file='{os.path.basename(local_pdf_path)}'")
                return traced_entries

        print(f"[GROUPING][PRIMARY_TRACE_EMPTY][{doc_type.upper()}] file='{os.path.basename(local_pdf_path)}' -> fallback page splitter")

    except Exception as e:
        print(f"[GROUPING][PRIMARY_TRACE_FAIL][{doc_type.upper()}] file='{os.path.basename(local_pdf_path)}' error='{e}' -> fallback page splitter")

    return _split_pdf_by_invoice_no_page_fallback(local_pdf_path, doc_type, vendor_id=vendor_id)


def _explode_doc_paths_for_grouping(paths: list, doc_type: str, vendor_id: str = "default"):
    expanded = []
    for path in paths or []:
        split_entries = _split_pdf_by_invoice_no(path, doc_type=doc_type, vendor_id=vendor_id)
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

def _trace_invoice_refs_from_document(local_pdf_path: str, doc_type: str, vendor_id: str = "default"):
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
        retries=3,
        vendor_id=vendor_id
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


def _build_split_entries_from_trace(local_pdf_path: str, doc_type: str, traced_refs: list, vendor_id: str = "default"):
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if not traced_refs:
        return []

    ordered_refs = sorted(traced_refs, key=lambda x: (x["start_page"], x["end_page"]))
    is_karet_deli = normalize_vendor_id(vendor_id) == "karet_deli"
    cleaned_refs = []

    if is_karet_deli:
        covered_pages = set()
        for ref in ordered_refs:
            start_p = ref["start_page"]
            end_p = ref["end_page"]
            if start_p < 1 or end_p > total_pages or start_p > end_p:
                continue
            covered_pages.update(range(start_p, end_p + 1))
            cleaned_refs.append(ref)
            
        if len(covered_pages) != total_pages:
            print(f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_COVERAGE_KARET_DELI] file='{os.path.basename(local_pdf_path)}'")
            return []
    else:
        prev_end = 0
        for idx, ref in enumerate(ordered_refs):
            start_page = ref["start_page"]
            end_page = ref["end_page"]

            if start_page <= prev_end:
                print(f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_OVERLAP] file='{os.path.basename(local_pdf_path)}' ref={ref}")
                return []

            expected_start = 1 if idx == 0 else (prev_end + 1)
            if start_page != expected_start:
                print(f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_GAP] file='{os.path.basename(local_pdf_path)}' expected={expected_start} actual={start_page} ref={ref}")
                return []

            cleaned_refs.append(ref)
            prev_end = end_page

        if prev_end != total_pages:
            print(f"[GROUPING][DOC_TRACE][{doc_type.upper()}][INVALID_COVERAGE] file='{os.path.basename(local_pdf_path)}' last_covered_page={prev_end} total_pages={total_pages}")
            return []

    results = []
    for ref in cleaned_refs:
        group_key = ref["invoice_no"]
        start_page = ref["start_page"]
        end_page = ref["end_page"]

        if start_page == 1 and end_page == total_pages:
            results.append({
                "group_key": group_key, "invoice_no": group_key,
                "path": local_pdf_path, "source_file": os.path.basename(local_pdf_path),
                "page_range": f"{start_page}-{end_page}",
                "is_temp": False, "doc_type": doc_type,
            })
            continue

        writer = PdfWriter()
        for i in range(start_page - 1, end_page):
            writer.add_page(reader.pages[i])

        out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{doc_type}_{_safe_output_suffix(group_key)}_{start_page}_{end_page}.pdf")
        out.close()

        with open(out.name, "wb") as f:
            writer.write(f)

        results.append({
            "group_key": group_key, "invoice_no": group_key,
            "path": out.name, "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page}-{end_page}",
            "is_temp": True, "doc_type": doc_type,
        })

    return results


def _split_pdf_by_invoice_no_page_fallback(local_pdf_path: str, doc_type: str, vendor_id: str = "default"):
    reader = PdfReader(local_pdf_path)
    total_pages = len(reader.pages)

    if total_pages == 0:
        raise Exception(f"PDF {doc_type} kosong: {os.path.basename(local_pdf_path)}")

    if doc_type == "coo":
        doc_group_key, raw_invoice_no, _ = _extract_invoice_no_for_grouping(local_pdf_path, doc_type="coo", vendor_id=vendor_id)
        only_key = _normalize_invoice_group_key(raw_invoice_no or doc_group_key)
        if not only_key:
            raise Exception(f"Gagal membaca coo_invoice_no untuk file COO: {os.path.basename(local_pdf_path)}")

        return [{
            "group_key": only_key, "invoice_no": raw_invoice_no if raw_invoice_no else only_key,
            "path": local_pdf_path, "source_file": os.path.basename(local_pdf_path),
            "page_range": f"1-{total_pages}", "is_temp": False, "doc_type": doc_type,
        }]

    is_karet_deli = normalize_vendor_id(vendor_id) == "karet_deli"
    
    if is_karet_deli:
        page_invoice_keys = []
        
        # PERBAIKAN: Ambil main key dokumen untuk fallback halaman kosong
        doc_group_key, raw_invoice_no, _ = _extract_invoice_no_for_grouping(local_pdf_path, doc_type, vendor_id=vendor_id)
        main_key = _normalize_invoice_group_key(raw_invoice_no or doc_group_key)
        
        for idx in range(total_pages):
            keys = _extract_multiple_invoice_no_from_single_page_for_split(local_pdf_path, idx, doc_type, vendor_id)
            valid_keys = [k for k in keys if k and k != "NULL"]
            
            # PERBAIKAN: Jika kosong, fallback ke main_key. 
            # DILARANG pakai last_known_keys agar sub-invoice tidak bocor ke halaman berikutnya.
            if not valid_keys:
                if main_key:
                    valid_keys = [main_key]
                    
            if not valid_keys:
                raise Exception(f"Gagal menentukan invoice number untuk file '{os.path.basename(local_pdf_path)}' ({doc_type}) hal {idx + 1}")
            
            page_invoice_keys.append(valid_keys)
            
        inv_to_pages = {}
        for page_idx, keys in enumerate(page_invoice_keys):
            for k in keys:
                inv_to_pages.setdefault(k, []).append(page_idx)
                
        results = []
        for group_key, pages in inv_to_pages.items():
            start_page = min(pages)
            end_page = max(pages)
            
            writer = PdfWriter()
            for i in range(start_page, end_page + 1):
                writer.add_page(reader.pages[i])

            out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{doc_type}_{_safe_output_suffix(group_key)}_{start_page+1}_{end_page+1}.pdf")
            out.close()
            with open(out.name, "wb") as f:
                writer.write(f)

            results.append({
                "group_key": group_key, "invoice_no": group_key,
                "path": out.name, "source_file": os.path.basename(local_pdf_path),
                "page_range": f"{start_page + 1}-{end_page + 1}",
                "is_temp": True, "doc_type": doc_type,
            })
        return results

    # Logic default untuk vendor lain
    page_invoice_keys = []
    last_known_key = ""

    src_doc = fitz.open(local_pdf_path)
    for idx in range(total_pages):
        page_text = ""
        try:
            page_text = src_doc[idx].get_text() or ""
        except Exception:
            page_text = ""

        page_key = _extract_invoice_no_from_text_for_split(page_text, doc_type=doc_type, vendor_id=vendor_id)

        if not page_key:
            page_key = _extract_invoice_no_from_single_page_for_split(local_pdf_path, idx, doc_type=doc_type, vendor_id=vendor_id)

        if not page_key and last_known_key:
            page_key = last_known_key

        if not page_key and idx == 0:
            doc_group_key, raw_invoice_no, _ = _extract_invoice_no_for_grouping(local_pdf_path, doc_type, vendor_id=vendor_id)
            page_key = _normalize_invoice_group_key(raw_invoice_no or doc_group_key)

        if not page_key:
            src_doc.close()
            raise Exception(
                f"Gagal menentukan invoice number untuk file '{os.path.basename(local_pdf_path)}' "
                f"({doc_type}) halaman ke-{idx + 1} saat split multi-section."
            )

        last_known_key = page_key
        page_invoice_keys.append(page_key)

    src_doc.close()

    segments = []
    seg_start = 0
    for idx in range(1, total_pages):
        if page_invoice_keys[idx] != page_invoice_keys[idx - 1]:
            segments.append((page_invoice_keys[seg_start], seg_start, idx - 1))
            seg_start = idx
    segments.append((page_invoice_keys[seg_start], seg_start, total_pages - 1))

    if len(segments) == 1:
        only_key, start_page, end_page = segments[0]
        return [{
            "group_key": only_key, "invoice_no": only_key,
            "path": local_pdf_path, "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page + 1}-{end_page + 1}",
            "is_temp": False, "doc_type": doc_type,
        }]

    results = []
    for group_key, start_page, end_page in segments:
        writer = PdfWriter()
        for i in range(start_page, end_page + 1):
            writer.add_page(reader.pages[i])

        out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{doc_type}_{_safe_output_suffix(group_key)}_{start_page+1}_{end_page+1}.pdf")
        out.close()

        with open(out.name, "wb") as f:
            writer.write(f)

        results.append({
            "group_key": group_key, "invoice_no": group_key,
            "path": out.name, "source_file": os.path.basename(local_pdf_path),
            "page_range": f"{start_page + 1}-{end_page + 1}",
            "is_temp": True, "doc_type": doc_type,
        })

    return results


def _extract_invoice_no_for_grouping(local_pdf_path: str, doc_type: str, vendor_id: str = "default"):
    target_key = _get_grouping_target_key(doc_type)
    doc_label = _get_doc_label_for_prompt(doc_type)

    grouping_run_prefix = f"{TMP_PREFIX.rstrip('/')}/grouping/{uuid.uuid4().hex}"
    grouping_name = f"{doc_type}_{uuid.uuid4().hex}"
    file_uri = _upload_temp_pdf_to_gcs(local_pdf_path, grouping_run_prefix, grouping_name)

    header_obj = _call_gemini_json_uri(
        file_uri,
        build_header_prompt(vendor_id=vendor_id),
        expect_array=False,
        retries=3,
        vendor_id=vendor_id
    )

    if not isinstance(header_obj, dict):
        header_obj = {}

    raw_invoice_no = header_obj.get(target_key, "null")

    if doc_type == "coo":
        raw_invoice_no = _cleanup_coo_invoice_no(raw_invoice_no)
        header_obj[target_key] = raw_invoice_no

    preprocessed_invoice_no = _preprocess_invoice_no_for_grouping(raw_invoice_no)
    group_key = _normalize_invoice_group_key(preprocessed_invoice_no)

    need_recheck = _should_force_recheck_invoice_no(doc_type, raw_invoice_no)

    if need_recheck:
        focused_prompt = _build_focused_invoice_prompt(doc_type=doc_type, target_key=target_key, doc_label=doc_label)
        focused_obj = _call_gemini_json_uri(
            file_uri,
            focused_prompt,
            expect_array=False,
            retries=3,
            vendor_id=vendor_id
        )

        if not isinstance(focused_obj, dict):
            focused_obj = {}

        focused_invoice_no = focused_obj.get(target_key, "null")
        if doc_type == "coo":
            focused_invoice_no = _cleanup_coo_invoice_no(focused_invoice_no)

        focused_preprocessed_invoice_no = _preprocess_invoice_no_for_grouping(focused_invoice_no)
        focused_group_key = _normalize_invoice_group_key(focused_preprocessed_invoice_no)

        if focused_group_key and not _should_force_recheck_invoice_no(doc_type, focused_invoice_no):
            header_obj[target_key] = focused_invoice_no
            raw_invoice_no = focused_invoice_no
            group_key = focused_group_key

    if not group_key:
        raise Exception(f"Gagal membaca {target_key} untuk file {doc_type}: {os.path.basename(local_pdf_path)}.")

    return group_key, raw_invoice_no, header_obj

def _group_docs_by_invoice_no(invoice_paths, packing_paths, coo_paths=None, vendor_id: str = "default"):
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

    invoice_entries = _explode_doc_paths_for_grouping(invoice_paths, doc_type="invoice", vendor_id=vendor_id)
    _log_extracted_invoice_refs("invoice", invoice_entries)

    for entry in invoice_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]
        grp = _ensure_group(group_key, raw_invoice_no)
        grp["invoice_paths"].append(p)
        if entry.get("is_temp"):
            grp["temp_invoice_split_paths"].append(p)

    packing_entries = _explode_doc_paths_for_grouping(packing_paths, doc_type="packing", vendor_id=vendor_id)
    _log_extracted_invoice_refs("packing", packing_entries)

    for entry in packing_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]

        if group_key not in groups:
            skipped_packing.append({"invoice_no": raw_invoice_no, "file": entry.get("source_file", os.path.basename(p))})
            continue
        groups[group_key]["packing_paths"].append(p)
        if entry.get("is_temp"):
            groups[group_key]["temp_packing_split_paths"].append(p)

    coo_entries = _explode_doc_paths_for_grouping(coo_paths, doc_type="coo", vendor_id=vendor_id)
    _log_extracted_invoice_refs("coo", coo_entries)

    for entry in coo_entries:
        p = entry["path"]
        group_key = entry["group_key"]
        raw_invoice_no = entry["invoice_no"]

        if group_key not in groups:
            skipped_coo.append({"invoice_no": raw_invoice_no, "file": entry.get("source_file", os.path.basename(p))})
            continue
        groups[group_key]["coo_paths"].append(p)
        if entry.get("is_temp"):
            groups[group_key]["temp_coo_split_paths"].append(p)

    valid_groups = {}
    for group_key, grp in groups.items():
        if not grp["packing_paths"]:
            dropped_invoice_groups.append({"invoice_no": grp["invoice_no"], "invoice_files": [os.path.basename(x) for x in grp["invoice_paths"]]})
            continue
        valid_groups[group_key] = grp

    return valid_groups

def _first_text(rows: list, key: str, default="null"):
    v = _first_non_null(rows, key)
    return default if _is_null(v) else v

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

    # =========================
    # VALIDASI LINE SUM VS DECLARED TOTAL
    # Ini yang sebelumnya belum ada.
    # Contoh:
    # pl_nw harus sama dengan pl_total_nw
    # pl_gw harus sama dengan pl_total_gw
    # dst.
    # =========================
    def _cmp_num_if_declared(left_key: str, right_key: str, eps=0.01):
        left_value = _to_float(total_obj.get(left_key))
        right_value = _to_float(total_obj.get(right_key))

        if left_value is None or right_value is None:
            return

        # Kalau declared total kosong/0 karena memang tidak ada di dokumen,
        # jangan paksa false dari default 0.
        if abs(right_value) <= eps:
            return

        if abs(left_value - right_value) > eps:
            _append_total_error(
                total_obj,
                f"Total: {left_key} != {right_key} ({left_value} vs {right_value})"
            )

    _cmp_num_if_declared("inv_quantity", "inv_total_quantity")
    _cmp_num_if_declared("inv_amount", "inv_total_amount")

    _cmp_num_if_declared("pl_quantity", "pl_total_quantity")
    _cmp_num_if_declared("pl_package_count", "pl_total_package")
    _cmp_num_if_declared("pl_nw", "pl_total_nw")
    _cmp_num_if_declared("pl_gw", "pl_total_gw")

    pl_total_volume = _to_float(total_obj.get("pl_total_volume"))
    if pl_total_volume is not None and abs(pl_total_volume) > 0.01:
        _cmp_volume_num_with_unit_fallback("pl_volume", "pl_total_volume")

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

def _split_match_description_messages(value):
    if value is None:
        return []

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return []

    return [part.strip() for part in re.split(r"\s*;\s*", s) if part and part.strip()]


_TOTAL_ISSUE_REGEX = re.compile(
    r"\btotal[_\s\-]*(quantity|amount|nw|gw|volume|package|qty|weight|nett|gross)\b"
    r"[^a-z0-9]*"
    r"(mismatch|tidak\s*(?:sesuai|cocok|sama|match)|≠|!=|diff|berbeda)",
    flags=re.IGNORECASE,
)

_TOTAL_PREFIX_REGEX = re.compile(r"^\s*total\b[\s:_\-]", flags=re.IGNORECASE)


def _is_total_issue_message(msg: str) -> bool:
    s = str(msg or "").strip()

    if not s:
        return False

    # "total: ..." atau "Total - ..." dianggap total-level issue.
    if _TOTAL_PREFIX_REGEX.match(s):
        return True

    if _TOTAL_ISSUE_REGEX.search(s):
        return True

    # Safety net: variasi wording yang belum kena regex tapi jelas total-level.
    s_low = s.lower()
    legacy_keywords = (
        "total_quantity mismatch",
        "total_amount mismatch",
        "total_nw mismatch",
        "total_gw mismatch",
        "total_volume mismatch",
        "total_package mismatch",
    )
    return any(kw in s_low for kw in legacy_keywords)


def _row_has_non_total_issue(row: dict) -> bool:
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().lower()
    match_description = row.get("match_description")

    if match_score != "false":
        return False

    messages = _split_match_description_messages(match_description)

    # Kalau false tapi tidak ada description, jangan otomatis negative.
    # Bisa terjadi karena total issue sudah diproses / field kosong.
    if not messages:
        return False

    ignored_total_metadata_prefixes = (
        "suspected_row_contribution=",
        "reason=",
        "row_value=",
        "root_cause=",
    )

    meaningful_messages = []

    for msg in messages:
        s = str(msg or "").strip().lower()
        if not s:
            continue

        if s.startswith(ignored_total_metadata_prefixes):
            continue

        meaningful_messages.append(msg)

    if not meaningful_messages:
        return False

    return any(not _is_total_issue_message(msg) for msg in meaningful_messages)


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

    ignored_total_metadata_prefixes = (
        "suspected_row_contribution=",
        "reason=",
        "row_value=",
        "root_cause=",
    )

    meaningful_messages = []

    for msg in messages:
        s = str(msg or "").strip().lower()
        if not s:
            continue

        if s.startswith(ignored_total_metadata_prefixes):
            continue

        meaningful_messages.append(msg)

    if not meaningful_messages:
        return False

    return all(_is_total_issue_message(msg) for msg in meaningful_messages)

def _row_has_any_total_issue(row: dict) -> bool:
    """
    Return True kalau row FALSE memiliki minimal 1 total issue,
    walaupun match_description juga berisi issue lain seperti missing/mismatch.

    Contoh:
    - "PackingList: total_volume mismatch; pl_description mismatch" -> True
    - "PackingList: total_gw mismatch; missing pl_item_no" -> True
    - "pl_description mismatch" -> False
    """
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().lower()
    match_description = row.get("match_description")

    if match_score != "false":
        return False

    messages = _split_match_description_messages(match_description)
    if not messages:
        return False

    ignored_total_metadata_prefixes = (
        "suspected_row_contribution=",
        "reason=",
        "row_value=",
        "root_cause=",
    )

    meaningful_messages = []

    for msg in messages:
        s = str(msg or "").strip().lower()
        if not s:
            continue

        if s.startswith(ignored_total_metadata_prefixes):
            continue

        meaningful_messages.append(msg)

    if not meaningful_messages:
        return False

    return any(_is_total_issue_message(msg) for msg in meaningful_messages)


def _finalize_audit_confidence_labels(rows: list, total_attribution=None):
    """
    Final confidence rule:

    RULE UTAMA:
    - Confidence negative/positive hanya mulai dihitung kalau ada masalah total.
    - Kalau tidak ada masalah total, semua row pure positive.
    - Non-total mismatch/missing tidak boleh membuat confidence_label menjadi negative.

    TOTAL ISSUE GROUP:
    - match_score TRUE selalu positive.
    - Row menjadi negative hanya kalau:
        1. Gemini total recheck accepted dan ada changed_fields, atau
        2. Gemini menandai row sebagai _gemini_total_issue_negative=True.
    - Selain itu positive.

    NON-TOTAL GROUP:
    - Semua row positive.
    """
    if not isinstance(rows, list):
        return rows

    total_attribution = total_attribution or {}
    total_issue_groups = set(total_attribution.get("total_issue_groups", []))

    grouped_rows = _group_rows_by_invoice_no(rows)

    # =====================================================
    # Cari group yang benar-benar punya masalah total.
    # Sumber:
    # 1. total_issue_groups dari _apply_total_contribution_scoring
    # 2. row FALSE yang match_description-nya mengandung total mismatch
    # =====================================================
    groups_with_false_total_issue = set()

    for invoice_group, group_rows in grouped_rows.items():
        has_false_total_issue = any(
            _row_has_any_total_issue(row)
            for row in group_rows
            if isinstance(row, dict)
        )

        if has_false_total_issue:
            groups_with_false_total_issue.add(invoice_group)

    confidence_total_groups = set(total_issue_groups) | set(groups_with_false_total_issue)

    # =====================================================
    # Kalau tidak ada masalah total sama sekali:
    # semua row PURE POSITIVE.
    # =====================================================
    if not confidence_total_groups:
        for row in rows:
            if isinstance(row, dict):
                row["confidence_label"] = "positive"
                row["_confidence_label_source"] = "no_total_issue"
        return rows

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        match_score = str(row.get("match_score", "")).strip().upper()
        invoice_group = _get_detail_total_group_key(row, idx)

        row_has_total_issue = (
            _row_has_any_total_issue(row)
            or _row_has_total_issue_only(row)
            or invoice_group in confidence_total_groups
        )

        if not row_has_total_issue:
            row["confidence_label"] = "positive"
            row["_confidence_label_source"] = "row_no_total_issue"
            continue

        # HARD RULE: TRUE dan CHILD PO tidak boleh negative.
        if match_score in ("TRUE", "CHILD PO"):
            row["confidence_label"] = "positive"
            row["_confidence_label_source"] = "hard_rule_match_true"
            continue

        if row.get("_gemini_total_issue_negative"):
            row["confidence_label"] = "negative"
            row["_confidence_label_source"] = "gemini_total_issue_negative"
            continue

        changed_fields = row.get("_gemini_recheck_changed_fields")
        if isinstance(changed_fields, list) and changed_fields:
            row["confidence_label"] = "negative"
            row["_confidence_label_source"] = "gemini_recheck_changed_fields"
            continue

        row["confidence_label"] = "positive"
        row["_confidence_label_source"] = "default_positive_no_gemini_signal"

    # =====================================================
    # SANITY CHECK:
    # Group yang punya total issue tapi 0 row negative.
    # Bisa terjadi kalau Gemini recheck gagal / return semua positive.
    # Log warning supaya reviewer tahu group itu perlu dicek manual.
    # =====================================================
    group_negative_count = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("confidence_label", "")).strip().lower() != "negative":
            continue
        gk = _get_detail_total_group_key(row, 0)
        group_negative_count[gk] = group_negative_count.get(gk, 0) + 1

    for group_key in confidence_total_groups:
        if group_negative_count.get(group_key, 0) == 0:
            print(
                f"[CONFIDENCE_WARN] group='{group_key}' has total issue but 0 negative rows — "
                f"Gemini recheck mungkin gagal menentukan kandidat; review manual disarankan."
            )

    return rows

def _force_min_one_negative_for_total_issue(rows: list, total_attribution=None):
    """
    DISABLED BY DESIGN.

    Negative untuk TOTAL issue harus datang dari Gemini recheck:
    - confidence_label="negative"
    - atau changed_fields / accepted field repair

    Python tidak boleh lagi memilih row negative sendiri,
    karena itu bisa berubah menjadi "asal ambil candidate".
    Jika Gemini return semua positive untuk total issue, itu sudah
    ditangkap oleh _validate_total_issue_gemini_batch_result().
    """
    return rows


def _call_gemini_uri(file_uri: str, prompt: str, extra_config: dict = None, return_response: bool = False, vendor_id: str = "default"):
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

    # =====================================================================
    # DYNAMIC MODEL ROUTING
    # =====================================================================
    norm_vendor = normalize_vendor_id(vendor_id)
    if norm_vendor in {"shimano_singapore"}:
        model_name = "gemini-2.5-flash"
    else:
        model_name = "gemini-3.1-flash-lite"

    print(f"[GEMINI_ROUTING] Menggunakan model '{model_name}' untuk vendor '{norm_vendor}'")

    response = genai_client.models.generate_content(
        model=model_name,
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

def _call_gemini_json_uri(file_uri: str, prompt: str, expect_array: bool = False, retries: int = 3, vendor_id: str = "default"):
    """
    Wrapper: panggil Gemini -> pastikan output JSON valid.
    - expect_array=True  : kalau Gemini balikin dict, kita bungkus jadi [dict]
    - retries: retry jika output bukan JSON / quota / text kosong
    """
    p = prompt
    for attempt in range(1, retries + 1):
        try:
            raw = _call_gemini_uri(file_uri, p, vendor_id=vendor_id)
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


# =========================================================
# CHUNKED INDEX EXTRACTION
# =========================================================
# Untuk dokumen dengan banyak line item, index extraction tidak boleh
# dilakukan dalam satu shot karena output JSON array akan melebihi
# max_output_tokens dan ter-truncate sehingga Gemini gagal menghasilkan
# JSON valid setelah retry.
# Solusi: pecah jadi beberapa chunk dengan range idx yang eksplisit,
# lalu gabungkan hasilnya.
#
# Trigger berbasis JUMLAH LINE ITEM (bukan vendor), supaya dokumen besar
# dari vendor apa pun otomatis ter-cover tanpa perlu maintain whitelist.

INDEX_CHUNK_TOTAL_ROW_THRESHOLD = 90
INDEX_CHUNK_SIZE = 30


def _get_index_chunk_size_for_total_row(total_row: int, vendor_id: str = "default") -> int:
    """
    Chunk size untuk INDEX extraction (bukan detail extraction).

    Return 0 = single-shot (perilaku lama, untuk dokumen kecil).
    Return INDEX_CHUNK_SIZE = chunked, dipakai kalau total_row melebihi
    threshold supaya tiap chunk JSON pendek dan aman terhadap
    max_output_tokens.

    Catatan: parameter vendor_id diterima untuk forward-compat tapi saat ini
    tidak mengubah threshold/size. Sebelumnya karet_deli sempat dipaksa pakai
    chunk lebih kecil untuk menekan drift, tapi terbukti malah membuat Gemini
    kehilangan konteks antar baris yang mirip dan menghasilkan row yang
    tidak sesuai PDF. Default sudah cukup untuk dokumen di bawah threshold.
    """
    try:
        n = int(total_row)
    except (TypeError, ValueError):
        return 0

    if n > INDEX_CHUNK_TOTAL_ROW_THRESHOLD:
        return INDEX_CHUNK_SIZE

    return 0


def _build_index_chunk_prompt(total_row: int, first_index: int, last_index: int) -> str:
    """
    Bungkus build_index_prompt dengan kontrak chunk eksplisit
    supaya Gemini hanya mengembalikan idx {first_index}..{last_index}.
    """
    base = build_index_prompt(total_row)
    expected_count = last_index - first_index + 1
    expected_indices = list(range(first_index, last_index + 1))

    chunk_contract = f"""

KONTRAK CHUNK INDEX — WAJIB DIIKUTI:
- total_row sebenarnya = {total_row}.
- Anda HANYA boleh mengeluarkan line item idx dari {first_index} sampai {last_index} (inclusive).
- Output HARUS berupa JSON ARRAY berisi TEPAT {expected_count} object.
- Object pertama WAJIB memiliki "idx" = {first_index}.
- Object terakhir WAJIB memiliki "idx" = {last_index}.
- Nilai "idx" tiap object WAJIB termasuk dalam set berikut: {expected_indices}.
- DILARANG menyertakan idx < {first_index} atau idx > {last_index}.
- Tetap gunakan urutan kemunculan di Invoice (sequential, tidak boleh skip, tidak boleh duplikat).
- Setiap object WAJIB mengisi "idx", "page", dan "page_index" sesuai aturan ANCHOR TRIO di schema utama.
- "idx" naik tepat 1 per object, dari {first_index} sampai {last_index}.
- "page_index" reset ke 1 setiap "page" berubah; dalam page yang sama "page_index" naik tepat 1 per item.
- Gunakan "page" + "page_index" sebagai SELF-CHECK sebelum commit "idx" supaya tidak ada lompat / geser / duplikat.
- Output HANYA JSON ARRAY, tanpa teks lain, tanpa markdown, tanpa code fence.
"""
    return base + chunk_contract


def _validate_index_chunk(
    chunk_items: list,
    first_index: int,
    last_index: int,
) -> list:
    # Validasi struktural chunk pakai trio (idx, page, page_index):
    # - idx harus sequential first_index..last_index, exactly expected_count items
    # - dalam grup page yang sama, page_index harus monoton naik tanpa gap
    # - (page, page_index) tidak boleh duplikat
    # Return list of issue strings; empty list = chunk valid.
    issues = []
    expected_count = last_index - first_index + 1

    if not isinstance(chunk_items, list):
        return [f"chunk bukan list (got {type(chunk_items).__name__})"]

    if len(chunk_items) != expected_count:
        issues.append(
            f"jumlah salah: expected={expected_count} got={len(chunk_items)}"
        )

    seen_idx = set()
    seen_page_pos = set()
    last_page = None
    last_page_index = None

    for i, item in enumerate(chunk_items):
        if not isinstance(item, dict):
            issues.append(f"position {i}: bukan dict")
            continue

        try:
            idx_val = int(item.get("idx"))
        except (TypeError, ValueError):
            issues.append(f"position {i}: idx invalid ({item.get('idx')!r})")
            continue

        expected_idx_at_pos = first_index + i
        if idx_val != expected_idx_at_pos:
            issues.append(
                f"position {i}: idx={idx_val} expected={expected_idx_at_pos}"
            )

        if idx_val in seen_idx:
            issues.append(f"position {i}: duplicate idx={idx_val}")
        seen_idx.add(idx_val)

        page = item.get("page")
        page_index = item.get("page_index")

        try:
            page_int = int(page) if page is not None else None
            page_index_int = int(page_index) if page_index is not None else None
        except (TypeError, ValueError):
            issues.append(
                f"position {i} idx={idx_val}: page/page_index invalid "
                f"(page={page!r} page_index={page_index!r})"
            )
            continue

        if page_int is None or page_index_int is None:
            issues.append(
                f"position {i} idx={idx_val}: page/page_index missing"
            )
            last_page = page_int
            last_page_index = page_index_int
            continue

        pp_key = (page_int, page_index_int)
        if pp_key in seen_page_pos:
            issues.append(
                f"position {i} idx={idx_val}: duplicate (page, page_index)={pp_key}"
            )
        seen_page_pos.add(pp_key)

        if last_page is not None:
            if page_int == last_page:
                # page sama → page_index harus naik tepat 1
                if last_page_index is not None and page_index_int != last_page_index + 1:
                    issues.append(
                        f"position {i} idx={idx_val}: page_index melompat "
                        f"(prev={last_page_index} now={page_index_int} di page={page_int})"
                    )
            elif page_int > last_page:
                # page baru → page_index harus reset ke 1
                if page_index_int != 1:
                    issues.append(
                        f"position {i} idx={idx_val}: page baru tapi page_index={page_index_int} "
                        f"(seharusnya 1 saat page berubah dari {last_page} ke {page_int})"
                    )
            else:
                issues.append(
                    f"position {i} idx={idx_val}: page mundur "
                    f"(prev={last_page} now={page_int})"
                )

        last_page = page_int
        last_page_index = page_index_int

    return issues


def _build_index_chunk_retry_prompt(
    total_row: int,
    first_index: int,
    last_index: int,
    issues: list,
) -> str:
    # Prompt retry yang feedback issue terdeteksi ke Gemini supaya
    # dia tahu apa yang harus diperbaiki.
    base = _build_index_chunk_prompt(total_row, first_index, last_index)
    issues_text = "\n".join(f"  - {it}" for it in issues[:20])
    feedback = f"""

PERBAIKAN — output sebelumnya melanggar kontrak. Issue yang terdeteksi:
{issues_text}

Mohon hasilkan ulang chunk ini dengan trio (idx, page, page_index) self-consistent
dan tepat {last_index - first_index + 1} object dari idx={first_index} sampai idx={last_index}.
"""
    return base + feedback


def _call_gemini_index_chunked(
    file_uri: str,
    total_row: int,
    vendor_id: str,
    chunk_size: int,
) -> list:
    """
    Panggil Gemini untuk index extraction secara chunked.
    Mengembalikan list gabungan dari semua chunk, urut sesuai idx.
    Per-chunk validasi pakai trio (idx, page, page_index); kalau gagal,
    retry chunk itu sekali dengan feedback issue terdeteksi.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size harus > 0, dapat {chunk_size}")

    all_items = []
    first_index = 1
    chunk_no = 1

    while first_index <= total_row:
        last_index = min(first_index + chunk_size - 1, total_row)

        print(
            f"[INDEX_CHUNK] chunk_no={chunk_no} "
            f"first_index={first_index} last_index={last_index} "
            f"total_row={total_row}"
        )

        prompt = _build_index_chunk_prompt(
            total_row=total_row,
            first_index=first_index,
            last_index=last_index,
        )

        chunk_items = _call_gemini_json_uri(
            file_uri,
            prompt,
            expect_array=True,
            retries=3,
            vendor_id=vendor_id,
        )

        if not isinstance(chunk_items, list):
            raise Exception(
                f"Index chunk bukan list. "
                f"chunk_no={chunk_no} first_index={first_index} last_index={last_index}"
            )

        issues = _validate_index_chunk(chunk_items, first_index, last_index)

        if issues:
            print(
                f"[INDEX_CHUNK_VALIDATE] chunk_no={chunk_no} attempt=1 "
                f"issues={len(issues)}: {issues[:5]}"
            )
            # retry sekali dengan feedback
            retry_prompt = _build_index_chunk_retry_prompt(
                total_row=total_row,
                first_index=first_index,
                last_index=last_index,
                issues=issues,
            )
            retry_items = _call_gemini_json_uri(
                file_uri,
                retry_prompt,
                expect_array=True,
                retries=3,
                vendor_id=vendor_id,
            )
            if isinstance(retry_items, list):
                retry_issues = _validate_index_chunk(retry_items, first_index, last_index)
                if len(retry_issues) < len(issues):
                    print(
                        f"[INDEX_CHUNK_VALIDATE] chunk_no={chunk_no} attempt=2 "
                        f"issues={len(retry_issues)} (was {len(issues)}) — using retry"
                    )
                    chunk_items = retry_items
                else:
                    print(
                        f"[INDEX_CHUNK_VALIDATE] chunk_no={chunk_no} attempt=2 "
                        f"issues={len(retry_issues)} (was {len(issues)}) — keeping original"
                    )

        all_items.extend(chunk_items)

        first_index = last_index + 1
        chunk_no += 1

    return all_items


def _shimano_count_line_items_from_invoice_pdf(invoice_pdf_path: str) -> int:
    # Hitung jumlah line item SHIMANO secara deterministik via pymupdf
    # text extraction. Format SHIMANO BLOCK punya ~4 label per block
    # (PART#, PRODUCT CD, HS#, SEQ#) — count median antar kandidat untuk
    # robust terhadap quirk extraction per-label.
    # Return 0 kalau gagal (caller fallback ke Gemini total_row).
    try:
        doc = fitz.open(invoice_pdf_path)
        try:
            full_text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

        # PART# tanpa "S." prefix (hindari S.PART# false match)
        n_part = len(re.findall(r'(?<![A-Za-z.])PART#', full_text))
        n_product_cd = len(re.findall(r'PRODUCT\s+CD', full_text))
        n_hs = len(re.findall(r'(?<![A-Za-z])HS#', full_text))
        n_seq = len(re.findall(r'(?<![A-Za-z])SEQ#', full_text))

        candidates = [n_part, n_product_cd, n_hs, n_seq]
        non_zero = sorted(c for c in candidates if c > 0)

        print(
            f"[SHIMANO_PART_COUNT] candidates: PART#={n_part} "
            f"PRODUCT_CD={n_product_cd} HS#={n_hs} SEQ#={n_seq}"
        )

        if not non_zero:
            return 0

        median_value = non_zero[len(non_zero) // 2]
        return int(median_value)
    except Exception as e:
        print(f"[SHIMANO_PART_COUNT] error: {e}")
        return 0


def _shimano_dedupe_index_items(index_items: list) -> list:
    # Drop duplicate anchor rows yang muncul karena chunk boundary overlap.
    # Key = (PART#, qty, amount, PO). Hanya non-empty key yang di-dedupe
    # supaya row kosong (placeholder/null) tetap aman.
    if not isinstance(index_items, list):
        return index_items

    seen_keys = set()
    deduped = []
    dropped = 0

    for item in index_items:
        if not isinstance(item, dict):
            deduped.append(item)
            continue

        part_no = str(item.get("inv_spart_item_no") or "").strip().upper()
        qty = _to_float(item.get("inv_quantity")) or 0
        amount = _to_float(item.get("inv_amount")) or 0
        po = _norm_po_number(item.get("inv_customer_po_no"))

        key = (part_no, qty, amount, po)
        # hanya treat sebagai duplicate kalau seluruh komponen key non-empty
        is_full_key = bool(part_no) and qty > 0 and bool(po)

        if is_full_key and key in seen_keys:
            print(
                f"[SHIMANO_DEDUPE] drop duplicate anchor: "
                f"PART#={part_no} qty={qty} amount={amount} po={po}"
            )
            dropped += 1
            continue

        if is_full_key:
            seen_keys.add(key)
        deduped.append(item)

    if dropped:
        print(f"[SHIMANO_DEDUPE] total dropped={dropped} kept={len(deduped)}")

    return deduped


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

    expected_indices = [int(x) for x in expected_indices]
    expected_set = set(expected_indices)

    got_indices = []
    missing_index_field_rows = []

    for pos, row in enumerate(json_array, start=1):
        idx = _get_row_expected_index(row)

        if idx is None:
            missing_index_field_rows.append(pos)
            continue

        got_indices.append(int(idx))

    got_set = set(got_indices)

    # =========================================================
    # SAFE NORMALIZATION:
    # Jika Gemini pakai zero-based indexing:
    # expected 1..30, got 0..29
    # expected 31..60, got 30..59
    # Maka geser semua index +1.
    #
    # HANYA aktif kalau:
    # - jumlah row benar
    # - semua row punya index
    # - tidak ada duplicate
    # - got_set persis expected_set yang dikurangi 1
    # =========================================================
    expected_minus_one_set = {x - 1 for x in expected_indices}

    is_clean_zero_based_shift = (
        len(json_array) == len(expected_indices)
        and not missing_index_field_rows
        and len(got_indices) == len(expected_indices)
        and len(got_set) == len(got_indices)
        and got_set == expected_minus_one_set
    )

    if is_clean_zero_based_shift:
        for row in json_array:
            original_idx = int(_get_row_expected_index(row))
            row["_expected_index"] = original_idx + 1

        got_indices = [
            int(row["_expected_index"])
            for row in json_array
        ]
        got_set = set(got_indices)

        print(
            f"[DETAIL_BATCH_INDEX_SHIFTED_PLUS_ONE] "
            f"batch_no={batch_no} "
            f"from_zero_based=true "
            f"indices={sorted(got_indices)}"
        )

    missing = sorted(expected_set - got_set)
    extra = sorted(got_set - expected_set)

    duplicate = sorted({
        idx
        for idx in got_indices
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
    vendor_id: str = "default",
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
            raw = _call_gemini_uri(file_uri_detail, p, vendor_id=vendor_id)
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

def _stream_filter_po_lines(target_po_numbers, target_item_numbers=None):
    target_po_numbers = {
        _norm_po_number(x)
        for x in (target_po_numbers or set())
        if x is not None
    }
    
    # NEW: Siapkan target items
    target_item_numbers = {
        _norm_item_compare_key(x)
        for x in (target_item_numbers or set())
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

            po_match = _norm_po_number(po_no) in target_po_numbers
            
            # NEW: Jika PO tidak match, cek apakah Item Number-nya ada di daftar target
            item_match = False
            if target_item_numbers and not po_match:
                v_art = _norm_item_compare_key(item.get("vendor_article_no") or item.get("po_vendor_article_no"))
                s_art = _norm_item_compare_key(item.get("sap_article_no") or item.get("po_sap_article_no"))
                if (v_art and v_art in target_item_numbers) or (s_art and s_art in target_item_numbers):
                    item_match = True

            # Simpan baris jika PO match ATAU Item match
            if po_match or item_match:
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

PO_SPLIT_ZERO_FIELDS = [
    # Invoice additive fields
    "inv_quantity",
    "inv_amount",
    "inv_unit_price",

    # Packing List additive fields
    "pl_quantity",
    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",

    # COO additive fields
    "coo_quantity",
    "coo_amount",
    "coo_gw",
    "coo_package_count",
]


def _zero_po_split_secondary_total_fields(row: dict):
    """
    Untuk row hasil split PO non-primary:
    - PO data tetap hidup
    - field additive invoice/PL/COO dibuat 0 agar tidak overcount
    """
    if not isinstance(row, dict):
        return row

    for field in PO_SPLIT_ZERO_FIELDS:
        if field in row:
            row[field] = 0

    return row


def _is_secondary_po_split_row(row: dict) -> bool:
    """
    Row hasil split PO selain row pertama.
    Dipakai agar validation required numeric tidak menganggap 0 sebagai missing.
    """
    return (
        isinstance(row, dict)
        and int(row.get("_po_split_count") or 0) > 1
        and row.get("_po_split_primary") is False
    )

def _inherit_inv_seq_for_secondary_po_split_rows(rows: list):
    """
    Recompute inv_seq khusus PO split.

    Rule:
    - Row normal dihitung sebagai 1 sequence.
    - Parent PO split (_po_split_primary=True) dihitung sebagai 1 sequence.
    - Child PO split (_po_split_primary=False) TIDAK dihitung sebagai sequence baru.
    - Child PO split duplicate inv_seq dari parent PO split terakhir.
    
    Contoh:
    Sebelum:
      parent item 1 = 1
      child item 1  = 1
      child item 1  = 1
      parent item 2 = 4
      child item 2  = 4

    Sesudah:
      parent item 1 = 1
      child item 1  = 1
      child item 1  = 1
      parent item 2 = 2
      child item 2  = 2
    """
    if not isinstance(rows, list):
        return rows

    seq_by_invoice = {}
    last_parent_seq_by_invoice = {}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        invoice_key = _preprocess_invoice_no_for_grouping(
            row.get("inv_invoice_no")
        )

        if not invoice_key:
            invoice_key = f"__NO_INVOICE__{idx + 1}"

        is_secondary = _is_secondary_po_split_row(row)

        # =====================================================
        # Child PO split:
        # jangan increment sequence.
        # Ikuti parent PO split terakhir di invoice yang sama.
        # =====================================================
        if is_secondary:
            parent_seq = last_parent_seq_by_invoice.get(invoice_key)

            if not _is_null(parent_seq):
                row["inv_seq"] = parent_seq

            continue

        # =====================================================
        # Row normal / parent PO split:
        # increment sequence.
        # =====================================================
        next_seq = int(seq_by_invoice.get(invoice_key, 0)) + 1
        seq_by_invoice[invoice_key] = next_seq

        row["inv_seq"] = next_seq
        last_parent_seq_by_invoice[invoice_key] = next_seq

    return rows

def _compact_inv_seq_gaps_after_po_split(rows: list):
    """
    Rapikan inv_seq setelah child PO split duplicate dari parent.

    Tujuan:
    - Tidak mengubah konsep child ikut parent.
    - Hanya menghilangkan gap numbering.
    - Kalau hasil lama 1,1,1,4,4,4,7,7,7 => jadi 1,1,1,2,2,2,3,3,3.
    - Kalau mulai dari 5: 5,5,5,8,8,8 => jadi 5,5,5,6,6,6.

    Rule:
    - Per invoice_no.
    - Setiap nilai inv_seq lama yang berbeda dianggap group item baru.
    - Group pertama mempertahankan angka pertama.
    - Group berikutnya lanjut +1.
    """
    if not isinstance(rows, list):
        return rows

    state_by_invoice = {}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        invoice_key = _preprocess_invoice_no_for_grouping(
            row.get("inv_invoice_no")
        )

        if not invoice_key:
            invoice_key = f"__NO_INVOICE__{idx + 1}"

        old_seq_raw = row.get("inv_seq")

        try:
            old_seq_key = int(old_seq_raw)
        except Exception:
            old_seq_key = str(old_seq_raw or "").strip()

        if invoice_key not in state_by_invoice:
            try:
                first_seq = int(old_seq_raw)
            except Exception:
                first_seq = 1

            state_by_invoice[invoice_key] = {
                "seq_map": {},
                "next_seq": first_seq,
            }

        state = state_by_invoice[invoice_key]
        seq_map = state["seq_map"]

        if old_seq_key not in seq_map:
            seq_map[old_seq_key] = state["next_seq"]
            state["next_seq"] += 1

        row["inv_seq"] = seq_map[old_seq_key]

    return rows


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
    split_count = len(row_matches)

    for split_index, (matched_line, alloc_qty) in enumerate(row_matches):
        new_row = dict(row)

        is_primary_split = split_index == 0

        new_row["_po_mapped"] = True
        new_row["_po_data"] = _copy_po_line_with_allocated_qty(matched_line, alloc_qty)

        # metadata internal untuk membedakan row utama vs row split tambahan
        new_row["_po_split_count"] = split_count
        new_row["_po_split_index"] = split_index + 1
        new_row["_po_split_primary"] = is_primary_split
        new_row["_po_allocated_qty"] = alloc_qty

        # IMPORTANT:
        # Kalau 1 detail row di-split ke multiple PO,
        # hanya row pertama yang membawa nilai additive.
        # Row kedua dst. dibuat 0 agar tidak overcount total invoice/packing.
        if split_count > 1 and not is_primary_split:
            _zero_po_split_secondary_total_fields(new_row)

        # selalu pakai item no asli dari PO JSON
        # po_article_value = _get_best_po_article_value(matched_line)
        # if not _is_null(po_article_value):
        #     new_row["inv_spart_item_no"] = po_article_value
        #     new_row["pl_item_no"] = po_article_value
        if matched_by == "inv_spart_item_no" and not _is_null(new_row.get("inv_spart_item_no")):
            new_row["pl_item_no"] = new_row.get("inv_spart_item_no")
        elif matched_by == "pl_item_no" and not _is_null(new_row.get("pl_item_no")):
            new_row["inv_spart_item_no"] = new_row.get("pl_item_no")

        mapped_rows.append(new_row)

    return mapped_rows, True

# Tambahkan vendor lain ke dalam set ini di masa depan
VENDORS_USING_PO_ITEM_FALLBACK = {
    "shimano_singapore",
}

def _should_use_po_item_fallback(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in VENDORS_USING_PO_ITEM_FALLBACK


def _fallback_po_item_by_qty_price(row: dict, po_lines: list) -> bool:
    """
    Fallback generik jika item number hilang/tidak valid.
    Mencocokkan berdasarkan PO No, Quantity, dan Unit Price.
    Jika ada duplikasi kandidat, pilih berdasarkan kemiripan deskripsi tertinggi.
    """
    from difflib import SequenceMatcher

    inv_po = _norm_po_number(row.get("inv_customer_po_no"))
    inv_qty = _to_float(row.get("inv_quantity"))
    inv_price = _to_float(row.get("inv_unit_price"))
    inv_desc = str(row.get("inv_description") or "").strip()

    if not inv_po or inv_qty is None or inv_price is None:
        return False

    candidates = []
    for po in po_lines:
        if not isinstance(po, dict):
            continue
            
        po_no = _norm_po_number(po.get("po_no"))
        po_qty = _to_float(po.get("po_quantity"))
        po_price_val = _to_float(po.get("po_price"))

        if po_no == inv_po and po_qty == inv_qty and po_price_val == inv_price:
            candidates.append(po)

    if not candidates:
        return False

    best_match = None
    if len(candidates) == 1:
        best_match = candidates[0]
    else:
        best_score = -1.0
        for po in candidates:
            po_text = str(po.get("po_text") or "").strip()
            score = SequenceMatcher(None, inv_desc.lower(), po_text.lower()).ratio()
            
            if score > best_score:
                best_score = score
                best_match = po

    if best_match:
        sap_article = best_match.get("po_sap_article_no")
        if sap_article and str(sap_article).strip().lower() != "null":
            normalized_sap = str(sap_article).strip()
            row["inv_spart_item_no"] = normalized_sap
            row["pl_item_no"] = normalized_sap
            return True

    return False


# =========================================================
# KUNSHAN_LANDON: RECOVER PO YANG TERSANGKUT DI inv_description
# =========================================================
# Kasus nyata kunshan_landon: Gemini gagal mengekstrak inv_customer_po_no
# karena PO number tersangkut di awal description, mis.
#   "45324149/CLM 26030220 HANGER BASKET, LANDON, -, SILVER,-, ..."
# Setelah _fill_forward, inv_customer_po_no malah inherit PO baris atasnya
# yang salah, sehingga PO mapping gagal.
# Recovery: kalau PO mapping pertama gagal, coba parse PO dari awal
# inv_description (selalu diawali '4'). Kalau re-map sukses dengan PO baru,
# update inv_customer_po_no & pl_customer_po_no, lalu bersihkan
# inv_description.

_KUNSHAN_LANDON_PO_PREFIX_REGEX = re.compile(r"^\s*(4\d+)")


def _is_kunshan_landon_vendor(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) == "kunshan_landon"


def _kunshan_landon_extract_po_from_description(desc):
    """
    Ambil leading digits (yang diawali '4') dari description.
    Kembalikan string PO candidate, atau "" jika tidak match.

    Contoh:
      "45324149/CLM 26030220 HANGER BASKET..." -> "45324149"
      "HANGER BASKET..."                       -> ""
    """
    if not isinstance(desc, str):
        return ""
    m = _KUNSHAN_LANDON_PO_PREFIX_REGEX.match(desc)
    if not m:
        return ""
    return m.group(1)


def _kunshan_landon_clean_description_after_po_recovery(desc) -> str:
    """
    Setelah PO recovery sukses, bersihkan inv_description.

    Aturan:
    1. Hapus kata pertama (sampai dan termasuk spasi pertama).
    2. Jika sisa string diawali digit, hapus kata berikutnya. Ulangi sampai
       sisa string diawali huruf alfabet (atau string habis).

    Contoh:
      "45324149/CLM 26030220 DESKRIPSI" -> "DESKRIPSI"
    """
    if not isinstance(desc, str):
        return ""

    s = desc.lstrip()

    # Step 1: hapus kata pertama
    space_idx = s.find(" ")
    if space_idx == -1:
        return ""
    s = s[space_idx + 1:].lstrip()

    # Step 2: terus hapus kata sampai diawali alfabet
    while s and s[0].isdigit():
        space_idx = s.find(" ")
        if space_idx == -1:
            return ""
        s = s[space_idx + 1:].lstrip()

    return s


def _kunshan_landon_recover_po_from_description(
    row: dict,
    po_article_index,
    po_desc_index,
    remaining_state,
):
    """
    Jalankan recovery PO khusus kunshan_landon.
    Returns (mapped_rows, success_bool).

    - mapped_rows: hasil dari _map_single_detail_row_to_po setelah recovery,
      atau None kalau recovery tidak dilakukan.
    - success_bool: True hanya kalau PO baru ditemukan DAN re-map sukses.
    Kalau gagal, state row di-rollback ke nilai semula.
    """
    if not isinstance(row, dict):
        return None, False

    original_inv_desc = row.get("inv_description")
    candidate_po = _kunshan_landon_extract_po_from_description(original_inv_desc)
    if not candidate_po:
        return None, False

    candidate_po_norm = _norm_po_number(candidate_po)
    if not candidate_po_norm:
        return None, False

    # Tidak ada gunanya retry kalau candidate sama persis dengan PO aktif.
    current_inv_po_norm = _norm_po_number(row.get("inv_customer_po_no"))
    if candidate_po_norm == current_inv_po_norm:
        return None, False

    original_inv_po = row.get("inv_customer_po_no")
    original_pl_po = row.get("pl_customer_po_no")

    row["inv_customer_po_no"] = candidate_po
    if not _is_null(original_pl_po):
        row["pl_customer_po_no"] = candidate_po

    mapped_rows, success = _map_single_detail_row_to_po(
        row=row,
        po_article_index=po_article_index,
        po_desc_index=po_desc_index,
        remaining_state=remaining_state,
    )

    if not success:
        # PO yang di-recover tidak match dengan PO master -> rollback total.
        row["inv_customer_po_no"] = original_inv_po
        row["pl_customer_po_no"] = original_pl_po
        return mapped_rows, False

    # Re-map sukses -> bersihkan inv_description.
    cleaned_desc = _kunshan_landon_clean_description_after_po_recovery(original_inv_desc)
    if cleaned_desc:
        row["inv_description"] = cleaned_desc

    # Propagate ke setiap row hasil (kalau CHILD PO split, ada lebih dari 1).
    for r in mapped_rows:
        if not isinstance(r, dict):
            continue
        r["inv_customer_po_no"] = row["inv_customer_po_no"]
        if not _is_null(original_pl_po):
            r["pl_customer_po_no"] = row["pl_customer_po_no"]
        r["inv_description"] = row["inv_description"]
        r["_kunshan_landon_po_recovered_from_description"] = True

    return mapped_rows, True


# =========================================================
# KUNSHAN_LANDON: RE-ALIGN inv_description / pl_description
# =========================================================
# Pada layout vendor ini, deskripsi panjang & multi-baris sering membuat
# Gemini MENGGESER inv_description / pl_description ke baris yang salah, atau
# mengisinya dengan kode Material. po_text di-anchor ke baris lewat kode
# Material (BUKAN deskripsi), jadi tetap selaras meski deskripsi bergeser.
# Karena itu po_text dipakai sebagai ACUAN untuk memindahkan kembali teks
# deskripsi hasil ekstraksi ke baris yang benar (teks tetap VERBATIM dari
# dokumen). po_text hanya dipakai sebagai fallback bila teks suatu baris
# benar-benar tidak bisa dipulihkan; baris yang po_text-nya kosong dibiarkan
# apa adanya (tidak dikosongkan).
#
# WAJIB dipanggil SETELAH _validate_po() karena po_text baru di-set di sana.
# Bersifat generik: tidak ada kode/produk/jumlah baris yang di-hardcode, dan
# murni post-processing sehingga TIDAK menyentuh field lain (nw/gw/volume).

_KUNSHAN_LANDON_DESC_MATCH_THRESHOLD = 0.5


def _kunshan_landon_desc_is_code_like(value, item_codes) -> bool:
    """True jika value tampak seperti kode Material (bukan teks deskripsi)."""
    if value is None:
        return True
    s = str(value).strip()
    if not s or s.lower() == "null":
        return True
    # Deskripsi asli vendor ini selalu mengandung spasi/tanda baca.
    # Kode Material berupa token alfanumerik rapat tanpa spasi.
    if " " not in s and re.fullmatch(r"[A-Za-z0-9\-_/.]+", s):
        return True
    if _norm_desc(s) in item_codes:
        return True
    return False


def _kunshan_landon_realign_one_field(group_rows: list, desc_field: str) -> int:
    """
    Selaraskan ulang satu field deskripsi untuk satu invoice group memakai
    po_text sebagai anchor. Mengembalikan jumlah sel yang diubah.
    """
    item_codes = set()
    for r in group_rows:
        for key in ("inv_spart_item_no", "pl_item_no"):
            c = _norm_desc(r.get(key))
            if c:
                item_codes.add(c)

    targets = [_norm_desc(r.get("po_text")) for r in group_rows]

    # Pool kandidat = semua teks deskripsi (verbatim) yang BUKAN kode Material.
    candidates = []  # list of (raw_text, norm_text)
    for r in group_rows:
        raw = r.get(desc_field)
        if _kunshan_landon_desc_is_code_like(raw, item_codes):
            continue
        norm = _norm_desc(raw)
        if norm:
            candidates.append((str(raw).strip(), norm))

    # Cocokkan setiap baris (target = po_text) ke kandidat terbaik secara
    # global-greedy (sim tertinggi lebih dulu, 1 baris : 1 kandidat).
    pairs = []  # (sim, row_idx, cand_idx)
    for i, tgt in enumerate(targets):
        if not tgt:
            continue
        for ci, (_, cnorm) in enumerate(candidates):
            sim = SequenceMatcher(None, tgt, cnorm).ratio()
            if sim >= _KUNSHAN_LANDON_DESC_MATCH_THRESHOLD:
                pairs.append((sim, i, ci))
    pairs.sort(key=lambda x: x[0], reverse=True)

    row_to_cand = {}
    used_rows = set()
    used_cands = set()
    for sim, i, ci in pairs:
        if i in used_rows or ci in used_cands:
            continue
        row_to_cand[i] = ci
        used_rows.add(i)
        used_cands.add(ci)

    changed = 0
    for i, r in enumerate(group_rows):
        tgt = targets[i]
        if i in row_to_cand:
            new_text = candidates[row_to_cand[i]][0]
            if new_text != r.get(desc_field):
                r[desc_field] = new_text
                changed += 1
            continue

        # Tidak ada kandidat verbatim yang cocok untuk baris ini.
        # Fallback ke po_text HANYA jika deskripsi sekarang memang tidak
        # cocok dengan baris ini (jangan menimpa deskripsi yang sudah benar).
        # Jika po_text kosong (PO tak ke-mapping), biarkan teks apa adanya.
        potext = r.get("po_text")
        if _is_null(potext) or not str(potext).strip():
            continue
        cur_norm = _norm_desc(r.get(desc_field))
        cur_sim = (
            SequenceMatcher(None, tgt, cur_norm).ratio()
            if (tgt and cur_norm) else 0.0
        )
        if cur_sim < _KUNSHAN_LANDON_DESC_MATCH_THRESHOLD:
            new_text = str(potext).strip()
            if new_text != r.get(desc_field):
                r[desc_field] = new_text
                changed += 1

    return changed


def _kunshan_landon_realign_descriptions(rows: list, vendor_id: str):
    """
    Repair deterministik untuk pergeseran inv_description / pl_description
    khusus vendor kunshan_landon. Dipanggil SETELAH _validate_po() (po_text
    sudah terisi). Tidak mengubah field selain kedua deskripsi tsb.
    """
    if not _is_kunshan_landon_vendor(vendor_id) or not isinstance(rows, list):
        return rows

    groups = {}
    order = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = str(r.get("inv_invoice_no") or "").strip()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    total_changed = 0
    for key in order:
        grp = groups[key]
        total_changed += _kunshan_landon_realign_one_field(grp, "inv_description")
        total_changed += _kunshan_landon_realign_one_field(grp, "pl_description")

    print(
        f"[KUNSHAN_LANDON_DESC_REALIGN] vendor={vendor_id} "
        f"rows={sum(len(g) for g in groups.values())} changed={total_changed}"
    )

    return rows


def _fallback_po_no_by_item_no(row: dict, po_lines: list) -> bool:
    """
    Fallback jika PO No kosong tapi Item No ada.
    Melacak Item No di data PO JSON menggunakan:
    1. Item No + Quantity
    2. Text Similarity (Description vs PO Text)
    3. Pick pertama (Sort by PO Number)
    """
    inv_item = _norm_item_compare_key(row.get("inv_spart_item_no") or row.get("pl_item_no"))
    inv_qty = _to_float(row.get("inv_quantity"))
    inv_desc = str(row.get("inv_description") or "").strip().lower()

    if not inv_item:
        return False

    # STEP 1: Filter berdasarkan Item Number
    candidates = []
    for po in po_lines:
        if not isinstance(po, dict):
            continue
            
        po_vendor_article = _norm_item_compare_key(po.get("po_vendor_article_no") or po.get("vendor_article_no"))
        po_sap_article = _norm_item_compare_key(po.get("po_sap_article_no") or po.get("sap_article_no"))
        
        if inv_item and inv_item in (po_vendor_article, po_sap_article):
            candidates.append(po)

    if not candidates:
        return False

    # STEP 2: Filter berdasarkan Quantity
    if inv_qty is not None:
        qty_candidates = [po for po in candidates if _to_float(po.get("po_quantity")) == inv_qty]
        if qty_candidates:
            candidates = qty_candidates

    # STEP 3 & 4: Skoring Text Similarity & Pick Pertama
    scored_candidates = []
    for po in candidates:
        po_text = str(po.get("po_text") or "").strip().lower()
        # Hitung rasio kemiripan deskripsi invoice dengan teks PO
        score = SequenceMatcher(None, inv_desc, po_text).ratio()
        scored_candidates.append((score, po))

    # Sort berdasarkan:
    # 1. Score Tertinggi (-x[0] agar descending)
    # 2. PO Number terkecil/pertama sebagai tie-breaker
    scored_candidates.sort(key=lambda x: (-x[0], _norm_po_number(x[1].get("po_no", ""))))

    # Ambil pemenang pertama
    if scored_candidates:
        best_po = scored_candidates[0][1]
        po_no_found = _norm_po_number(best_po.get("po_no"))
        if po_no_found:
            row["inv_customer_po_no"] = po_no_found
            row["pl_customer_po_no"] = po_no_found
            return True

    return False

# =========================================================
# VENDOR DENGAN INVOICE MERGED-CELL QTY/AMOUNT (mis. joy)
# =========================================================
# Invoice vendor seperti joy menggabungkan (merge) kolom QTY & AMOUNT untuk
# beberapa baris (PO berbeda) yang berbagi CODE/item yang sama. Akibatnya
# quantity per-baris TIDAK tersedia di invoice -- yang tercetak hanya SUBTOTAL
# per group. Packing List vendor ini memuat quantity per-baris (1:1 sejajar
# dengan invoice).
#
# Kalau inv_quantity dibaca apa adanya:
#   - Sigma inv_quantity tidak rekonsiliasi dengan total invoice (under/overcount),
#   - baris merged tidak bisa di-map ke PO line-nya masing-masing.
#
# Fix: SEBELUM PO mapping, turunkan inv_quantity per-baris dari pl_quantity yang
# sejajar, lalu hitung ulang inv_amount = inv_quantity * inv_unit_price.
VENDORS_WITH_MERGED_INVOICE_QTY = {
    "joy",
}


def _is_merged_invoice_qty_vendor(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in VENDORS_WITH_MERGED_INVOICE_QTY


def _derive_inv_qty_from_pl_for_merged_vendors(rows: list, vendor_id: str = "default"):
    """
    Khusus vendor dengan invoice merged-cell QTY/AMOUNT (lihat
    VENDORS_WITH_MERGED_INVOICE_QTY). Salin pl_quantity -> inv_quantity per baris
    dan hitung ulang inv_amount = inv_quantity * inv_unit_price.

    Dipanggil SEBELUM _map_po_to_details supaya total invoice rekonsiliasi DAN
    tiap baris bisa di-map ke PO line-nya sendiri.

    Guard (agar tidak merusak data yang sudah benar):
    - Hanya jalan untuk vendor terdaftar.
    - Hanya override jika pl_quantity valid (> 0). Jika pl_quantity null/0,
      inv_quantity dibiarkan apa adanya (mis. baris tanpa pasangan PL).
    - inv_amount hanya dihitung ulang jika inv_unit_price valid (> 0).
    """
    if not _is_merged_invoice_qty_vendor(vendor_id):
        return rows
    if not isinstance(rows, list):
        return rows

    adjusted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue

        pl_qty = _to_float(row.get("pl_quantity"))
        if pl_qty is None or pl_qty <= 1e-9:
            continue

        # inv_quantity per-baris = pl_quantity (sumber per-baris yang andal).
        if abs(pl_qty - round(pl_qty)) <= 1e-9:
            row["inv_quantity"] = int(round(pl_qty))
        else:
            row["inv_quantity"] = pl_qty

        # inv_amount = inv_quantity * inv_unit_price (Decimal, anti noise float).
        unit_price = _to_float(row.get("inv_unit_price"))
        if unit_price is not None and unit_price > 1e-9:
            amount = _to_decimal_or_zero(row["inv_quantity"]) * _to_decimal_or_zero(unit_price)
            if amount == amount.to_integral_value():
                row["inv_amount"] = int(amount)
            else:
                row["inv_amount"] = float(amount)

        adjusted += 1

    if adjusted:
        print(
            f"[MERGED_INV_QTY] vendor={normalize_vendor_id(vendor_id)} "
            f"inv_quantity diturunkan dari pl_quantity untuk {adjusted} baris"
        )

    return rows


def _is_merged_qty_collapsed_zero_row(row) -> bool:
    """
    Baris non-teratas dari satu merged-cell QTY/AMOUNT invoice yang nilainya
    sengaja di-nol-kan oleh _postprocess_inv_qty_aggregate_to_top_row. Dipakai
    agar validasi required-numeric tidak menganggap 0 sebagai missing
    (analog dengan _is_secondary_po_split_row).
    """
    return isinstance(row, dict) and row.get("_merged_qty_zero_row") is True


def _postprocess_inv_qty_aggregate_to_top_row(rows: list, vendor_id: str = "default"):
    """
    Vendor dengan invoice merged-cell QTY/AMOUNT (lihat
    VENDORS_WITH_MERGED_INVOICE_QTY, mis. joy): pada dokumen invoice, beberapa
    line item dengan produk sama digabung dalam SATU merged-cell QTY (mis. 480)
    dan SATU merged-cell AMOUNT (mis. 5760).

    _derive_inv_qty_from_pl_for_merged_vendors sengaja men-distribusi nilai itu
    per-baris (mis. 130/50/270/30) supaya tiap baris bisa di-map ke PO line-nya.
    SETELAH PO mapping selesai, fungsi ini meringkasnya kembali agar SESUAI
    tampilan dokumen invoice: nilai merged ditaruh di SATU baris (baris teratas
    group) + 0 di baris lain.

    Contoh (1 merged-cell mewakili 4 baris):
        inv_quantity: 480, 0, 0, 0   (BUKAN 130, 50, 270, 30)
        inv_amount  : 5760, 0, 0, 0

    Group = run baris BERURUTAN dengan inv_spart_item_no sama dalam satu invoice
    (persis cakupan visual satu merged-cell). Hanya menyentuh inv_quantity &
    inv_amount; field lain (PO, pl_*, deskripsi, unit price) tidak diubah.
    """
    if not _is_merged_invoice_qty_vendor(vendor_id):
        return rows
    if not isinstance(rows, list):
        return rows

    # Bangun contiguous runs berdasarkan (invoice group, inv_spart_item_no).
    runs = []
    prev_key = None
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            prev_key = None
            continue
        item_key = _normalize_code_compare_value(row.get("inv_spart_item_no"))
        if not item_key:
            prev_key = None
            continue
        key = (_get_detail_total_group_key(row, idx), item_key)
        if not runs or key != prev_key:
            runs.append([idx])
        else:
            runs[-1].append(idx)
        prev_key = key

    def _as_clean_number(dec_value):
        if dec_value == dec_value.to_integral_value():
            return int(dec_value)
        return float(dec_value)

    zeroed = 0
    for run in runs:
        if len(run) < 2:
            continue  # baris tunggal -> tidak ada merged-cell yang perlu diringkas

        # Keeper = baris teratas yang BUKAN child PO split (child memang harus 0).
        keeper = next(
            (i for i in run if not _is_secondary_po_split_row(rows[i])),
            run[0],
        )

        sum_qty = Decimal(0)
        sum_amt = Decimal(0)
        for i in run:
            sum_qty += _to_decimal_or_zero(rows[i].get("inv_quantity"))
            sum_amt += _to_decimal_or_zero(rows[i].get("inv_amount"))

        rows[keeper]["inv_quantity"] = _as_clean_number(sum_qty)
        rows[keeper]["inv_amount"] = _as_clean_number(sum_amt)

        for i in run:
            if i == keeper:
                continue
            rows[i]["inv_quantity"] = 0
            rows[i]["inv_amount"] = 0
            rows[i]["_merged_qty_zero_row"] = True
            zeroed += 1

    print(
        f"[INV_QTY_AGGREGATE_TOP_ROW] vendor={normalize_vendor_id(vendor_id)} "
        f"runs={len(runs)} zeroed_rows={zeroed}"
    )
    return rows


def _map_po_to_details(po_lines, detail_rows, vendor_id="default"): # <-- Jangan lupa param vendor_id
    po_article_index, po_desc_index = _build_po_indexes(po_lines)
    remaining_state = {}

    # Cek apakah vendor saat ini butuh fallback
    use_po_fallback = _should_use_po_item_fallback(vendor_id)

    # first pass: mapping normal
    per_input_results = []

    for row in detail_rows or []:
        
        # --- NEW: DESCRIPTION FIRST WORD FALLBACK ---
        original_inv_item = row.get("inv_spart_item_no")
        original_pl_item = row.get("pl_item_no")
        
        is_inv_null = _is_null(original_inv_item)
        is_pl_null = _is_null(original_pl_item)
        
        used_desc_fallback = False
        
        # Jika kedua item_no null, ambil kata pertama dari description
        if is_inv_null and is_pl_null:
            desc = row.get("inv_description")
            if _is_null(desc):
                desc = row.get("pl_description")
            
            if not _is_null(desc):
                words = str(desc).strip().split()
                if words:
                    first_word = words[0]
                    row["inv_spart_item_no"] = first_word
                    row["pl_item_no"] = first_word
                    used_desc_fallback = True

        # NEW: Deteksi dan timpa PO yang nyasar akibat fill_forward SEBELUM di-map
        inv_po_norm = _norm_po_number(row.get("inv_customer_po_no"))
        inv_art_norm = _norm_item_compare_key(row.get("inv_spart_item_no"))
        pl_art_norm = _norm_item_compare_key(row.get("pl_item_no"))
        art_to_check = inv_art_norm or pl_art_norm

        if inv_po_norm and art_to_check:
            exists_in_po = False
            if inv_art_norm and (inv_po_norm, inv_art_norm) in po_article_index:
                exists_in_po = True
            elif pl_art_norm and (inv_po_norm, pl_art_norm) in po_article_index:
                exists_in_po = True
                
            if not exists_in_po:
                _fallback_po_no_by_item_no(row, po_lines)

        mapped_rows, success = _map_single_detail_row_to_po(
            row=row,
            po_article_index=po_article_index,
            po_desc_index=po_desc_index,
            remaining_state=remaining_state,
        )
        
        # Revert (biarkan null kembali) jika mapping PO tetap gagal
        if used_desc_fallback and not success:
            row["inv_spart_item_no"] = original_inv_item
            row["pl_item_no"] = original_pl_item
            for r in mapped_rows:
                r["inv_spart_item_no"] = original_inv_item
                r["pl_item_no"] = original_pl_item
        # ---------------------------------------------

        # --- NEW: REVERSE FALLBACK (FIND PO BY ITEM NO) ---
        if not success and _is_null(row.get("inv_customer_po_no")):
            if _fallback_po_no_by_item_no(row, po_lines):
                # Remap ulang karena PO Number sudah berhasil ditemukan
                mapped_rows, success = _map_single_detail_row_to_po(
                    row=row,
                    po_article_index=po_article_index,
                    po_desc_index=po_desc_index,
                    remaining_state=remaining_state,
                )
        # --------------------------------------------------

        # --- NEW: KUNSHAN_LANDON PO RECOVERY FROM DESCRIPTION ---
        # Kalau PO mapping gagal, coba parse PO dari awal inv_description.
        # Lihat _kunshan_landon_recover_po_from_description untuk detail.
        if not success and _is_kunshan_landon_vendor(vendor_id):
            recovered_rows, recovered_success = _kunshan_landon_recover_po_from_description(
                row=row,
                po_article_index=po_article_index,
                po_desc_index=po_desc_index,
                remaining_state=remaining_state,
            )
            if recovered_success:
                mapped_rows = recovered_rows
                success = True
        # --------------------------------------------------------

        # --- NEW: GENERIC PO ITEM FALLBACK ---
        if not success and use_po_fallback:
            if _fallback_po_item_by_qty_price(row, po_lines):
                # Remap ulang karena item no sudah diperbaiki
                mapped_rows, success = _map_single_detail_row_to_po(
                    row=row,
                    po_article_index=po_article_index,
                    po_desc_index=po_desc_index,
                    remaining_state=remaining_state,
                )
        # ---------------------------------------
        
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

def _nullify_prefix_fields_in_rows(rows: list, prefixes: tuple):
    """
    Paksa semua kolom dengan prefix tertentu menjadi 'null'.
    Dipakai agar field BL/COO tidak berisi value kalau dokumennya tidak diupload.
    """
    if not isinstance(rows, list):
        return rows

    prefixes = tuple(prefixes or ())
    if not prefixes:
        return rows

    changed_count = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        for key in list(row.keys()):
            if str(key).startswith(prefixes):
                if row.get(key) != "null":
                    changed_count += 1
                row[key] = "null"

    print(
        f"[OPTIONAL_DOC_GUARD] "
        f"prefixes={prefixes} "
        f"changed_fields={changed_count}"
    )

    return rows


def _nullify_prefix_fields_in_dict(obj: dict, prefixes: tuple):
    if not isinstance(obj, dict):
        return obj

    prefixes = tuple(prefixes or ())
    if not prefixes:
        return obj

    for key in list(obj.keys()):
        if str(key).startswith(prefixes):
            obj[key] = "null"

    return obj


def _enforce_absent_optional_docs_empty(
    rows: list = None,
    *,
    header_obj: dict = None,
    total_rows: list = None,
    container_rows: list = None,
    has_bl_doc: bool = True,
    has_coo_doc: bool = True,
):
    """
    Jika BL / COO tidak diupload, semua kolom terkait wajib kosong/null.

    Rule:
    - has_bl_doc=False  -> semua bl_* = 'null'
    - has_coo_doc=False -> semua coo_* = 'null'
    - jika BL tidak ada, container_rows juga dikosongkan
    """
    prefixes = []

    if not has_bl_doc:
        prefixes.append("bl_")

    if not has_coo_doc:
        prefixes.append("coo_")

    prefixes = tuple(prefixes)

    if not prefixes:
        return

    _nullify_prefix_fields_in_rows(rows or [], prefixes)
    _nullify_prefix_fields_in_rows(total_rows or [], prefixes)
    _nullify_prefix_fields_in_dict(header_obj or {}, prefixes)

    # Container berasal dari BL. Kalau BL tidak diupload, jangan ada container output.
    if not has_bl_doc and isinstance(container_rows, list):
        container_rows.clear()

    print(
        f"[OPTIONAL_DOC_GUARD] "
        f"has_bl_doc={has_bl_doc} "
        f"has_coo_doc={has_coo_doc} "
        f"forced_null_prefixes={prefixes}"
    )

TOTAL_MISMATCH_LABEL_REGEX = re.compile(
    r"^(Invoice|PackingList):\s*"
    r"(total_quantity|total_amount|total_package|total_nw|total_gw|total_volume)"
    r"\s+mismatch",
    flags=re.IGNORECASE,
)


def _is_total_mismatch_message(msg: str) -> bool:
    if msg is None:
        return False

    text = str(msg).strip()
    return bool(TOTAL_MISMATCH_LABEL_REGEX.search(text))


def _canonical_match_error_key(msg: str) -> str:
    """
    Samakan key untuk error yang secara makna sama.

    Contoh yang dianggap sama:
    - PackingList: total_quantity mismatch (sum 3627.0, doc 3633.0)
    - PackingList: total_quantity mismatch

    Tujuannya:
    - detail message tetap dipertahankan
    - label pendek dari total attribution tidak double
    """
    text = str(msg or "").strip()

    # normalize whitespace
    text = re.sub(r"\s+", " ", text)

    if _is_total_mismatch_message(text):
        # buang detail trailing "(sum ..., doc ...)" untuk canonical key
        text = re.sub(r"\s*\(sum\b.*?\)\s*$", "", text, flags=re.IGNORECASE)

    return text.lower()


def _has_total_detail_message(msg: str) -> bool:
    """
    True untuk format detail:
    PackingList: total_quantity mismatch (sum 3627.0, doc 3633.0)
    """
    text = str(msg or "")
    return bool(re.search(r"\(sum\b.*?\bdoc\b.*?\)", text, flags=re.IGNORECASE))


def _split_match_description_messages(value) -> list:
    if _is_null(value):
        return []

    return [
        part.strip()
        for part in str(value).split(";")
        if part and part.strip()
    ]


def _append_err(row: dict, msg: str):
    """
    Append error ke match_description pakai '; ' dan set match_score=false.

    Dengan dedupe:
    - exact duplicate tidak ditambahkan lagi
    - total mismatch pendek tidak ditambahkan kalau versi detail sudah ada
    - kalau versi pendek sudah ada lalu versi detail datang belakangan,
      versi pendek diganti menjadi versi detail
    """
    if not isinstance(row, dict):
        return

    row["match_score"] = "false"

    prev = row.get("match_description")
    if _is_null(prev):
        row["match_description"] = msg
        return

    existing_messages = _split_match_description_messages(prev)
    new_key = _canonical_match_error_key(msg)

    for idx, existing_msg in enumerate(existing_messages):
        existing_key = _canonical_match_error_key(existing_msg)

        if existing_key != new_key:
            continue

        # Kalau existing masih generic tapi msg baru lebih detail,
        # replace supaya output menyimpan "(sum ..., doc ...)".
        if (
            _is_total_mismatch_message(msg)
            and _has_total_detail_message(msg)
            and not _has_total_detail_message(existing_msg)
        ):
            existing_messages[idx] = msg
            row["match_description"] = "; ".join(existing_messages)

        # Kalau sudah ada semantic duplicate, jangan append lagi.
        return

    existing_messages.append(msg)
    row["match_description"] = "; ".join(existing_messages)

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

# ==============================
# GENERIC VENDOR FIELD NULLIFIER
# ==============================

def _as_list(value):
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        return list(value)

    return [value]


def _postprocess_null_fields_for_vendor(
    rows: list,
    current_vendor_id: str,
    target_vendor_ids,
    columns,
    null_value="null",
    create_missing_fields: bool = False,
):
    """
    Generic postprocess:
    Null-kan kolom tertentu hanya untuk vendor tertentu.

    Args:
        rows:
            list row detail.
        current_vendor_id:
            vendor_id aktif dari flow, contoh: vendor_id.
        target_vendor_ids:
            vendor yang kena rule. Bisa string atau list.
            Contoh: "shimano" atau ["shimano", "bafang_motor"].
        columns:
            kolom yang mau di-null. Bisa string atau list.
            Contoh: "pl_volume_unit" atau ["inv_quantity", "pl_quantity"].
        null_value:
            default pakai string "null" karena codebase existing pakai format itu.
        create_missing_fields:
            False = hanya null-kan field jika field sudah ada di row.
            True = tambahkan field walaupun belum ada.
    """
    if not isinstance(rows, list):
        return rows

    normalized_current_vendor_id = normalize_vendor_id(current_vendor_id)

    normalized_target_vendor_ids = {
        normalize_vendor_id(v)
        for v in _as_list(target_vendor_ids)
        if v is not None
    }

    columns = [
        str(col).strip()
        for col in _as_list(columns)
        if col is not None and str(col).strip()
    ]

    if not normalized_target_vendor_ids or not columns:
        return rows

    if normalized_current_vendor_id not in normalized_target_vendor_ids:
        print(
            f"[VENDOR_NULL_FIELDS][SKIP] "
            f"current_vendor_id={normalized_current_vendor_id} "
            f"target_vendor_ids={sorted(normalized_target_vendor_ids)} "
            f"columns={columns}"
        )
        return rows

    updated_count = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        for column in columns:
            if create_missing_fields or column in row:
                row[column] = null_value
                updated_count += 1

    print(
        f"[VENDOR_NULL_FIELDS][APPLIED] "
        f"current_vendor_id={normalized_current_vendor_id} "
        f"target_vendor_ids={sorted(normalized_target_vendor_ids)} "
        f"columns={columns} "
        f"updated_count={updated_count}"
    )

    return rows

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
COO_PO_BACKFILL_TARGET_FIELDS = [
    "coo_description",
    "coo_hs_code",
    "coo_quantity",
    "coo_unit",
    "coo_amount",
    "coo_criteria",
    "coo_origin_country",
]

def _normalize_mode_value_key(value) -> str:
    if _is_null(value):
        return ""

    return re.sub(r"\s+", " ", str(value).strip().upper())

def _pick_most_common_non_null_value(values):
    """
    Ambil value non-null yang paling sering muncul.
    Tie-breaker: value yang pertama kali muncul di group.
    """
    counts = {}
    first_seen = {}
    originals = {}

    for idx, value in enumerate(values or []):
        if _is_null(value):
            continue

        key = _normalize_mode_value_key(value)
        if not key:
            continue

        counts[key] = counts.get(key, 0) + 1

        if key not in first_seen:
            first_seen[key] = idx
            originals[key] = value

    if not counts:
        return None

    best_key = sorted(
        counts.keys(),
        key=lambda k: (-counts[k], first_seen[k])
    )[0]

    return originals.get(best_key)

def _build_invoice_mode_map(rows: list, field_name: str) -> dict:
    """
    Group by invoice number, lalu ambil value field yang paling sering muncul
    di masing-masing invoice group.
    """
    grouped_values = {}

    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue

        invoice_group = _get_detail_total_group_key(row, idx)
        if not invoice_group:
            continue

        grouped_values.setdefault(invoice_group, []).append(row.get(field_name))

    mode_map = {}

    for invoice_group, values in grouped_values.items():
        mode_value = _pick_most_common_non_null_value(values)
        if mode_value is not None:
            mode_map[invoice_group] = mode_value

    return mode_map

def _postprocess_coo_po_only_rows_from_invoice(rows: list, vendor_id: str = "default"):
    current_vendor_id = normalize_vendor_id(vendor_id)

    if current_vendor_id != "shimano_inc":
        return

    criteria_by_invoice = _build_invoice_mode_map(rows, "coo_criteria")
    origin_country_by_invoice = _build_invoice_mode_map(rows, "coo_origin_country")

    source_map = {
        "coo_description": "inv_description",
        "coo_hs_code": "inv_hs_code",
        "coo_quantity": "inv_quantity",
        "coo_unit": "inv_quantity_unit",
        "coo_amount": "inv_amount",
    }

    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue

        if _is_null(row.get("coo_customer_po_no")):
            continue

        if not all(_is_null(row.get(k)) for k in COO_PO_BACKFILL_TARGET_FIELDS):
            continue

        for coo_key, inv_key in source_map.items():
            inv_value = row.get(inv_key)
            row[coo_key] = "null" if _is_null(inv_value) else inv_value

        invoice_group = _get_detail_total_group_key(row, idx)

        criteria_value = criteria_by_invoice.get(invoice_group)
        if criteria_value is not None:
            row["coo_criteria"] = criteria_value

        origin_country_value = origin_country_by_invoice.get(invoice_group)
        if origin_country_value is not None:
            row["coo_origin_country"] = origin_country_value

        print(
            f"[COO_PO_ONLY_BACKFILL] "
            f"invoice_no={invoice_group} "
            f"vendor_id={current_vendor_id} "
            f"coo_customer_po_no='{row.get('coo_customer_po_no')}' "
            f"criteria='{row.get('coo_criteria')}' "
            f"origin_country='{row.get('coo_origin_country')}'"
        )

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
            
        match_score = str(r.get("match_score", "")).strip().upper()
        if match_score in ("TRUE", "CHILD PO"): # <-- UBAH DISINI
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

def _apply_header_to_rows(rows: list, header_obj: dict, vendor_id: str = "default"):
    if not isinstance(header_obj, dict):
        header_obj = {}

    header_fields = _get_header_fields_for_vendor(vendor_id)

    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in header_fields:
            v = header_obj.get(k, "null")
            # overwrite biar konsisten antar row
            r[k] = v if v is not None else "null"

def _has_text_value(v) -> bool:
    return not _is_null(v)

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
        is_po_child = _is_secondary_po_split_row(row)

        if not row.get("_po_mapped"):
            if is_po_child:
                row["match_score"] = "CHILD PO" # <-- UBAH DISINI
                row["match_description"] = "null"
                row.pop("_po_data", None)
                row.pop("_po_mapped", None)
                continue

            _append_err(row, "PO item tidak ditemukan")
            row.pop("_po_data", None)
            row.pop("_po_mapped", None)
            row.pop("_po_split_count", None)
            row.pop("_po_split_index", None)
            row.pop("_po_split_primary", None)
            row.pop("_po_allocated_qty", None)
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

        if is_po_child:
            row["match_score"] = "CHILD PO" # <-- UBAH DISINI
            row["match_description"] = "null"
            row.pop("_po_data", None)
            row.pop("_po_mapped", None)
            continue

        inv_price = _to_num(row.get("inv_unit_price"))
        po_price  = _to_num(po_data.get("po_price"))
        inv_currency = str(row.get("inv_price_unit") or "").strip()
        po_currency  = str(po_data.get("po_currency") or "").strip()

        if inv_price is not None and po_price is not None and inv_price != po_price:
            _append_err(row, f"po_price mismatch (inv: {inv_price}, po: {po_price})")

        if inv_currency and po_currency and inv_currency != po_currency:
            _append_err(row, f"po_currency mismatch (inv: {inv_currency}, po: {po_currency})")

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

def _force_secondary_po_split_rows_true(rows: list):
    """
    Child row hasil split PO tidak boleh ikut validasi parent.
    Rule:
    - Child PO split selalu 'CHILD PO'
    - match_description dikosongkan/null.
    - confidence_label jadi positive.
    """
    if not isinstance(rows, list):
        return rows

    for row in rows:
        if not isinstance(row, dict):
            continue

        if not _is_secondary_po_split_row(row):
            continue

        row["match_score"] = "CHILD PO" # <-- UBAH DISINI
        row["match_description"] = "null"
        row["confidence_label"] = "positive"

        for key in [
            "_errors", "_error", "_validation_errors", "_match_errors",
            "_recheck_fields", "_recheck_original_values",
            "_gemini_recheck_changed_fields", "_gemini_total_issue_negative",
            "_force_total_issue_candidate", "_forced_total_issue_negative",
        ]:
            row.pop(key, None)

    return rows

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
            # Untuk secondary PO split, inv_quantity dan inv_amount sengaja dibuat 0
            # supaya tidak overcount. Jangan dianggap missing.
            # Idem untuk baris non-teratas merged-cell invoice (mis. joy) yang
            # nilainya diringkas ke baris teratas group.
            if (
                _is_secondary_po_split_row(r)
                or _is_merged_qty_collapsed_zero_row(r)
            ) and k in {"inv_quantity", "inv_amount", "inv_unit_price"}:
                continue

            if _is_missing_num(r.get(k)):
                _append_err(r, f"Invoice: missing {k}")

        # aritmatika: amount = qty * unit_price
        # aritmatika: amount = qty * unit_price
        # Untuk secondary PO split, inv_quantity dan inv_amount sengaja 0,
        # jadi skip formula check agar tidak false error.
        if not _is_secondary_po_split_row(r):
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


def _validate_packing_rows(rows: list, vendor_id: str = "default"):
    # Vendors whose PL never contains a MEAS'T / volume column
    _NO_VOLUME_PL_VENDORS = {"sram"}
    _skip_volume = normalize_vendor_id(vendor_id) in _NO_VOLUME_PL_VENDORS

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

        # SRAM PL never has MEAS'T data — skip volume field validation
        if _skip_volume:
            required_str = [f for f in required_str if f != "pl_volume_unit"]
            required_num = [f for f in required_num if f != "pl_volume"]

        for k in required_str:
            if _is_null(r.get(k)):
                _append_err(r, f"PackingList: missing {k}")

        for k in required_num:
            # Untuk secondary PO split, field PL additive sengaja dibuat 0
            # supaya tidak overcount total packing.
            if _is_secondary_po_split_row(r) and k in {
                "pl_quantity",
                "pl_package_count",
                "pl_nw",
                "pl_gw",
                "pl_volume",
            }:
                continue

            # Baris non-teratas merge group PL (mis. novatec): field additif
            # selain quantity sengaja di-nol-kan oleh
            # _assign_pl_merged_numerics_to_rows; jangan dianggap missing.
            if _is_merged_pl_zero_row(r) and k in {
                "pl_package_count",
                "pl_nw",
                "pl_gw",
                "pl_volume",
            }:
                continue

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

def _postprocess_coo_numeric_fields_from_pl(rows: list, eps: float = 0.01):
    """
    Sebelum validasi:
    Jika field COO numeric berbeda dari field PL pasangan,
    maka field COO mengikuti nilai PL.

    Mapping:
    - pl_quantity       -> coo_quantity
    - pl_package_count -> coo_package_count
    - pl_gw            -> coo_gw

    Ini bukan validasi, tidak append error.
    """
    if not isinstance(rows, list):
        return rows

    field_pairs = [
        ("pl_quantity", "coo_quantity"),
        ("pl_package_count", "coo_package_count"),
        ("pl_gw", "coo_gw"),
    ]

    changed_count = 0
    changed_by_field = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        for pl_field, coo_field in field_pairs:
            pl_num = _to_float(row.get(pl_field))
            coo_num = _to_float(row.get(coo_field))

            if pl_num is None or coo_num is None:
                continue

            if abs(pl_num - coo_num) <= eps:
                continue

            old_value = row.get(coo_field)
            row[coo_field] = pl_num

            changed_count += 1
            changed_by_field[coo_field] = changed_by_field.get(coo_field, 0) + 1

            print(
                f"[COO_NUMERIC_FROM_PL] "
                f"{coo_field} replaced from {old_value} to {pl_num} "
                f"using {pl_field}"
            )

    print(
        f"[COO_NUMERIC_FROM_PL] "
        f"changed_cells={changed_count} "
        f"changed_by_field={changed_by_field}"
    )

    return rows

def _doc_present(rows: list, keys: list) -> bool:
    """Dokumen dianggap tersedia kalau ada minimal 1 field kunci yang tidak null di salah satu row."""
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in keys:
            if not _is_null(r.get(k)):
                return True
    return False
def _validate_invoice_vs_packing_extra(rows: list, vendor_id: str = "default"):
    # Vendor dengan COO ter-agregat (mis. joy): nilai numerik COO sengaja
    # diringkas ke SATU baris per produk (lihat _postprocess_coo_aggregate_to_top_row),
    # jadi perbandingan PL-vs-COO per-baris (pl_gw/coo_gw, pl_package_count/
    # coo_package_count) TIDAK relevan dan akan salah-flag. Skip untuk vendor ini.
    skip_coo_numeric_compare = _is_coo_aggregate_top_row_vendor(vendor_id)

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

        if not skip_coo_numeric_compare:
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

# ==============================
# BL HEADER MAJORITY BY INVOICE
# ==============================

BL_HEADER_MAJORITY_FIELDS = [
    field for field in HEADER_FIELDS
    if str(field).startswith("bl_")
]

def _get_bl_header_majority_fields(vendor_id: str = "default"):
    """
    Field BL yang boleh diseragamkan sebagai header-level.

    Khusus shimano_inc, bl_mark_number tidak boleh ikut majority,
    karena field tersebut adalah content-level dan bisa berbeda per line item.
    """
    fields = list(BL_HEADER_MAJORITY_FIELDS)

    if _is_shimano_inc_vendor(vendor_id):
        return [field for field in fields if field != "bl_mark_number"]

    return fields

def _normalize_bl_header_value(value):
    if _is_null(value):
        return None

    s = re.sub(r"\s+", " ", str(value).strip())
    if not s:
        return None

    return s.upper()


def _pick_majority_original_value(values: list):
    """
    Ambil value mayoritas.
    Return original value, bukan normalized value.
    Kalau tie, return None supaya tidak asal replace.
    """
    counts = {}
    originals = {}
    order = []

    for value in values or []:
        key = _normalize_bl_header_value(value)
        if key is None:
            continue

        if key not in counts:
            counts[key] = 0
            originals[key] = value
            order.append(key)

        counts[key] += 1

    if not counts:
        return None

    sorted_keys = sorted(order, key=lambda k: counts[k], reverse=True)
    top_key = sorted_keys[0]
    top_count = counts[top_key]

    if len(sorted_keys) >= 2 and counts[sorted_keys[1]] == top_count:
        return None

    return originals[top_key]


def _pick_one_vote_per_invoice(group_rows: list, field: str):
    """
    Dalam 1 invoice_no bisa ada banyak detail row.
    Supaya invoice dengan banyak row tidak mendominasi,
    ambil dulu 1 value mayoritas internal untuk invoice tersebut.
    """
    values = [
        row.get(field)
        for row in group_rows or []
        if isinstance(row, dict) and not _is_null(row.get(field))
    ]

    return _pick_majority_original_value(values)


def _postprocess_bl_header_majority_by_invoice(rows: list, vendor_id: str = "default"):
    """
    Jika header BL berbeda antar invoice_no,
    replace semua value bl_* dengan mayoritas value per kolom.

    Voting:
    - 1 invoice_no = 1 vote
    - field diproses per kolom bl_*
    - kalau hasil tie, field tidak diubah
    """
    if not isinstance(rows, list) or not rows:
        return rows

    grouped_rows = _group_rows_by_invoice_no(rows)
    if not grouped_rows:
        return rows

    majority_by_field = {}

    bl_header_majority_fields = _get_bl_header_majority_fields(vendor_id)
    if not bl_header_majority_fields:
        return rows
    
    for field in bl_header_majority_fields:
        invoice_votes = []

        for _, group_rows in grouped_rows.items():
            invoice_value = _pick_one_vote_per_invoice(group_rows, field)
            if not _is_null(invoice_value):
                invoice_votes.append(invoice_value)

        majority_value = _pick_majority_original_value(invoice_votes)

        if not _is_null(majority_value):
            majority_by_field[field] = majority_value

    if not majority_by_field:
        return rows

    changed_cells = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        for field, majority_value in majority_by_field.items():
            current_key = _normalize_bl_header_value(row.get(field))
            majority_key = _normalize_bl_header_value(majority_value)

            if current_key != majority_key:
                row[field] = majority_value
                changed_cells += 1

    print(
        f"[BL_HEADER_MAJORITY] "
        f"invoice_groups={len(grouped_rows)} "
        f"majority_fields={len(majority_by_field)} "
        f"changed_cells={changed_cells}"
    )

    return rows

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
    """
    Extract kode dari bl_description.

    Rule:
    - Kode alfanumerik tetap valid: ABC123, SH-610, FR/610
    - Kode numeric-only juga valid: 610, 12345
    - Minimal panjang 3 karakter supaya angka kecil seperti 1, 2, 10
      tidak terlalu mudah dianggap kode.
    """
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

        # Minimal 3 char.
        # Contoh valid:
        # - 610
        # - A610
        # - FRAME-610
        if len(normalized) < 3:
            continue

        # Harus mengandung angka.
        # Pure text seperti FRAME / RIGID tidak dianggap code.
        if not re.search(r"\d", normalized):
            continue

        # Numeric-only sekarang VALID.
        # Jadi jangan lagi wajib ada huruf A-Z.
        # Old rule yang harus dihapus:
        # if not re.search(r"[A-Z]", normalized):
        #     continue

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


# =========================================================
# DETERMINISTIC COO LINE-ITEM MAPPING (vendor dengan COO ter-agregat)
# =========================================================
# Untuk vendor seperti joy, dokumen COO (form RCEP) meng-agregat barang
# PER PRODUK, sehingga jumlah item COO != jumlah line item invoice
# (mis. 1 item COO "751DSE 32X14" mewakili beberapa baris invoice).
# PASS 2 (optional full-doc) di-anchor ke base row invoice, jadi model
# kesulitan mem-"fan out" satu item COO ke banyak base row dalam satu
# panggilan yang juga menangani BL (menambah beban COO di sana justru
# membuat BL ikut gagal). Karena itu COO dipetakan DETERMINISTIK di Python:
#  1) Ekstrak DAFTAR item COO apa adanya (1 objek per item COO) lewat satu
#     panggilan terfokus -- struktur natural yang andal diekstrak model.
#  2) Cocokkan tiap base row ke item COO yang deskripsinya paling cocok
#     (berbasis token deskripsi + kode/model di depan). Satu item COO boleh
#     dipetakan ke banyak base row.
#  3) Nilai numerik (coo_quantity/coo_gw/coo_package_count) tetap akan
#     dinormalisasi per-baris ke Packing List oleh
#     _postprocess_coo_numeric_fields_from_pl.

VENDORS_WITH_AGGREGATED_COO = {
    "joy",
    # NOVATEC: COO form RCEP 2 halaman (Continuation Sheet) dengan 6 item
    # ter-agregat per produk. Pass gabungan INV+PL+BL+COO tidak andal membaca
    # continuation sheet -> coo_* line item null semua. Pakai extractor COO
    # terfokus yang sama seperti joy lalu petakan deterministik di Python.
    "novatec",
    # SUNTOUR SHENZHEN: dokumen sekeluarga dengan NOVATEC (forwarder MGF/ITC).
    # COO form RCEP multi-halaman (Continuation Sheet) dengan 6 item ter-agregat
    # per produk (kode item mis. GSFXCEDSZ0000533 muncul di beberapa item COO).
    "suntour_shenzhen",
}


def _is_aggregated_coo_vendor(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in VENDORS_WITH_AGGREGATED_COO


# Subset dari VENDORS_WITH_AGGREGATED_COO yang nilai NUMERIK COO-nya ditampilkan
# meng-agregat per produk pada SATU baris (baris pertama group) + 0 di baris lain,
# SESUAI dokumen COO -- BUKAN didistribusi per-baris mengikuti Packing List.
# (Tambahkan vendor lain ke sini bila ingin perilaku top-row yang sama.)
VENDORS_COO_AGGREGATE_TO_TOP_ROW = {
    "joy",
    "novatec",
}


def _is_coo_aggregate_top_row_vendor(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in VENDORS_COO_AGGREGATE_TO_TOP_ROW


# =========================================================
# VENDOR DENGAN PACKING LIST MERGED-CELL NUMERIK (mis. novatec)
# =========================================================
# Packing List vendor ini memakai merged cell untuk kolom numerik
# (TOTAL CTNS / TOTAL N.W. / TOTAL G.W. / TOTAL CBM): beberapa line item yang
# dikemas dalam carton yang sama berbagi SATU nilai agregat (AREA A), dan di sisi
# kanan dokumen ada kolom "Combined" berisi TOTAL per tipe produk (AREA B).
#
# Pada prompt detail multi-dokumen, model sering keliru membedakan AREA A vs
# AREA B (kehilangan nilai group, atau memungut nilai AREA B). Solusi: ekstraksi
# TERFOKUS hanya dokumen Packing List, lalu assignment deterministik di Python
# (cocokkan Combined QTY AREA A ke run baris yang jumlah QTY-nya sama; taruh
# agregat di baris TERATAS group + 0 di sisanya). Analog dengan jalur COO
# terfokus (_extract_coo_item_list + _map_coo_items_to_rows).
VENDORS_PL_MERGED_NUMERIC = {
    "novatec",
}


def _is_pl_merged_numeric_vendor(vendor_id: str) -> bool:
    return normalize_vendor_id(vendor_id) in VENDORS_PL_MERGED_NUMERIC


def _is_merged_pl_zero_row(row) -> bool:
    """
    Baris non-teratas dari satu merge group PL yang field numerik additif-nya
    (pl_package_count/pl_nw/pl_gw/pl_volume) sengaja di-nol-kan oleh
    _assign_pl_merged_numerics_to_rows. Dipakai agar validasi required-numeric
    tidak menganggap 0 sebagai missing (analog dengan _is_secondary_po_split_row
    dan _is_merged_qty_collapsed_zero_row).
    """
    return isinstance(row, dict) and row.get("_merged_pl_zero_row") is True


COO_ITEM_LIST_COPY_FIELDS = [
    "coo_seq",
    "coo_mark_number",
    "coo_description",
    "coo_hs_code",
    "coo_package_count",
    "coo_package_unit",
    "coo_quantity",
    "coo_unit",
    "coo_gw",
    "coo_amount",
    "coo_criteria",
    "coo_origin_country",
]


def _build_coo_item_list_prompt() -> str:
    return """
ROLE:
Anda AI IDP yang fokus mengekstrak DAFTAR ITEM dari dokumen Certificate of Origin (COO) saja.
Rule-based, deterministik, anti-halusinasi.

SUMBER:
- Baca HANYA dokumen Certificate of Origin / COO (mis. form RCEP, sering memakai Continuation Sheet beberapa halaman).
- ABAIKAN dokumen Invoice, Packing List, dan Bill of Lading.

TUGAS:
- Keluarkan SATU objek JSON untuk SETIAP item barang COO (sesuai nomor item pada "6. Item number": 1, 2, 3, ...).
- Output HANYA JSON ARRAY, tanpa teks lain. Mulai '[' diakhiri ']'.

STRUKTUR COO (form RCEP):
- Kolom "8. Number and kind of packages; and description of goods" untuk setiap item diawali frasa paket "<ANGKA-HURUF> (<N>) CARTON(S) OF" lalu diikuti deskripsi barang.
  Deskripsi dapat ter-wrap ke beberapa baris dan menyambung melintasi batas halaman; gabungkan jadi satu deskripsi utuh.
- Kolom "12." berisi DUA nilai bertumpuk: gross weight (mis. "<angka>KGS G.W.") dan quantity (mis. "<angka>SETS"/PIECES/PAIRS).

FIELD PER ITEM:
- "coo_seq": nomor item dari kolom 6 (numeric: 1, 2, 3, ...).
- "coo_mark_number": dari "7. Marks and numbers on packages"; bila hanya marks umum/global atau "N/M", isi "null".
- "coo_description": deskripsi barang dari kolom 8 SETELAH frasa paket. ABAIKAN frasa "<...> (<N>) CARTON(S) OF" dan kata generik "BICYCLE PARTS". Jangan masukkan HS code/criteria/country/quantity/GW.
- "coo_hs_code": dari "9. HS Code of the goods" (mis. format 8714.93).
- "coo_package_count": angka pada frasa paket di kolom 8 (mis. "TWENTY (20) CARTONS OF" -> 20). Prioritaskan angka di dalam kurung.
- "coo_package_unit": jenis kemasan pada frasa paket di kolom 8 (mis. "CARTONS"/"CARTON"). JANGAN SETS/PIECES/PAIRS.
- "coo_quantity": angka quantity dari kolom 12 yang berunit SETS/PIECES/PAIRS (mis. "1000SETS" -> 1000). BUKAN gross weight.
- "coo_unit": unit yang menempel pada coo_quantity (mis. "SETS"/"PIECES"/"PAIRS"). BUKAN KGS.
- "coo_gw": angka gross weight dari kolom 12 sebelum "KGS G.W."/"KG G.W." (mis. "255.6KGS G.W." -> 255.6).
- "coo_amount": isi hanya jika kolom 12 mencantumkan nilai/FOB eksplisit; jika tidak ada, "null". Jangan ambil dari invoice.
- "coo_criteria": dari "10. Origin Conferring Criterion" (mis. "PE").
- "coo_origin_country": dari "11. RCEP Country of Origin" / negara asal item (mis. "CHINA").

ATURAN:
- EKSTRAK HANYA YANG TERTULIS. Jika field tidak ada -> "null" (string) atau 0 (angka numerik).
- Tidak boleh JSON literal null -> gunakan "null".
- Tidak boleh markdown/penjelasan.

SCHEMA OUTPUT:
[
  {
    "coo_seq": number,
    "coo_mark_number": "string",
    "coo_description": "string",
    "coo_hs_code": "string",
    "coo_package_count": number,
    "coo_package_unit": "string",
    "coo_quantity": number,
    "coo_unit": "string",
    "coo_gw": number,
    "coo_amount": "string",
    "coo_criteria": "string",
    "coo_origin_country": "string"
  }
]
""".strip()


def _extract_coo_item_list(file_uri: str, vendor_id: str = "default") -> list:
    if not file_uri:
        return []

    items = _call_gemini_json_uri(
        file_uri,
        _build_coo_item_list_prompt(),
        expect_array=True,
        retries=3,
        vendor_id=vendor_id,
    )

    if not isinstance(items, list):
        return []

    cleaned = []
    for it in items:
        if not isinstance(it, dict):
            continue
        desc = _normalize_coo_description(it.get("coo_description"))
        if _is_null(desc):
            continue
        it["coo_description"] = desc
        cleaned.append(it)

    print(
        f"[COO_ITEM_LIST] vendor={normalize_vendor_id(vendor_id)} "
        f"raw={len(items)} usable={len(cleaned)}"
    )
    return cleaned


def _coo_desc_tokens(value) -> set:
    norm = _normalize_description_for_similarity(value)
    if not norm:
        return set()
    return {t for t in norm.split() if t}


def _leading_model_token(value) -> str:
    """
    Token "model/kode" pertama dari deskripsi: token dengan >= 3 char dan
    mengandung angka (mis. "751DSE", "D762TSE", "431"). Dipakai sebagai gate
    supaya row tidak lompat ke produk lain yang hanya berbagi token dimensi
    generik (mis. "32X14").
    """
    for t in _normalize_description_for_similarity(value).split():
        if len(t) >= 3 and re.search(r"\d", t):
            return t
    return ""


def _coo_item_row_match_score(coo_item: dict, row: dict):
    """
    Return (coverage, jaccard).
    - coverage = porsi token inv_description yang tertutup deskripsi item COO.
    - jaccard  = overlap / union (tie-breaker untuk item yang mirip).
    """
    coo_tokens = _coo_desc_tokens(coo_item.get("coo_description"))
    inv_tokens = _coo_desc_tokens(row.get("inv_description"))
    if not coo_tokens or not inv_tokens:
        return (0.0, 0.0)

    overlap = coo_tokens & inv_tokens
    coverage = len(overlap) / len(inv_tokens)
    jaccard = len(overlap) / len(coo_tokens | inv_tokens)
    return (coverage, jaccard)


def _map_coo_items_to_rows(
    rows: list,
    coo_items: list,
    vendor_id: str = "default",
    min_coverage: float = 0.6,
) -> list:
    """
    Petakan tiap base row ke item COO yang paling cocok (deskripsi + gate
    kode/model), lalu salin field coo_* item-level. Satu item COO boleh
    dipetakan ke banyak base row (fan-out). Row tanpa item COO yang cocok
    -> field coo_* item-level di-null-kan.
    """
    if not isinstance(rows, list) or not coo_items:
        return rows

    mapped = 0
    nulled = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        inv_model = _leading_model_token(row.get("inv_description"))

        best_item = None
        best_score = (0.0, 0.0)

        for coo_item in coo_items:
            coo_tokens = _coo_desc_tokens(coo_item.get("coo_description"))

            # Gate kode/model: token model di depan inv_description WAJIB ada
            # di deskripsi item COO. Mencegah lompat ke produk lain yang hanya
            # berbagi token dimensi generik.
            if inv_model and inv_model not in coo_tokens:
                continue

            score = _coo_item_row_match_score(coo_item, row)
            if score > best_score:
                best_score = score
                best_item = coo_item

        if best_item is not None and best_score[0] >= min_coverage:
            for field in COO_ITEM_LIST_COPY_FIELDS:
                if field in best_item:
                    row[field] = best_item.get(field)
            mapped += 1
        else:
            _nullify_coo_item_fields(row)
            nulled += 1

    print(
        f"[COO_DETERMINISTIC_MAP] vendor={normalize_vendor_id(vendor_id)} "
        f"coo_items={len(coo_items)} rows={len(rows)} "
        f"mapped={mapped} nulled={nulled}"
    )
    return rows


# Field numerik COO yang di-agregat per item pada dokumen COO.
COO_AGGREGATE_NUMERIC_FIELDS = ["coo_quantity", "coo_package_count", "coo_gw"]


def _coo_clean_number(value):
    """Bilangan bulat -> int (mis. 7 bukan 7.0); selain itu round 2 desimal."""
    f = _to_float(value)
    if f is None:
        return None
    if f == int(f):
        return int(f)
    return round(f, 2)


def _postprocess_coo_aggregate_to_top_row(rows: list, vendor_id: str = "default"):
    """
    Vendor dengan COO ter-agregat (mis. joy): dokumen COO menampilkan SATU baris
    agregat per produk (mis. "SEVEN (7) CARTONS OF ... 480SETS 103.52KGS G.W."),
    BUKAN satu nilai per line item invoice.

    _map_coo_items_to_rows mem-"fan out" nilai agregat itu (coo_quantity /
    coo_package_count / coo_gw) ke SETIAP base row yang produknya sama, sehingga
    nilai yang sama berulang di banyak baris. Fungsi ini meringkasnya kembali agar
    SESUAI tampilan dokumen COO: nilai numerik agregat hanya ditaruh di SATU baris
    (baris pertama group), baris lain dalam group = 0.

    Contoh (1 item COO mewakili 4 baris invoice):
        coo_package_count: 7, 0, 0, 0   (BUKAN 2, 1, 3, 1 hasil distribusi per-PL)

    Ini PENGGANTI _postprocess_coo_numeric_fields_from_pl untuk vendor agregat
    (yang sebaliknya men-distribusi nilai COO per-baris mengikuti Packing List).

    Group = base row dengan coo_description sama dalam satu invoice group. Hanya
    menyentuh field numerik COO; field teks COO (coo_description, coo_hs_code,
    coo_seq, dst) tetap terisi di semua baris group.
    """
    if not _is_coo_aggregate_top_row_vendor(vendor_id):
        return rows
    if not isinstance(rows, list):
        return rows

    # 1) Kelompokkan index baris per item COO (kunci: invoice group + deskripsi
    #    COO). Urutan kemunculan dipertahankan agar baris PERTAMA = baris teratas.
    groups = {}
    order = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not _row_has_meaningful_coo_item(row):
            continue
        desc_key = _normalize_description_for_similarity(row.get("coo_description"))
        if not desc_key:
            continue
        gkey = (_get_detail_total_group_key(row, idx), desc_key)
        if gkey not in groups:
            groups[gkey] = []
            order.append(gkey)
        groups[gkey].append(idx)

    zeroed = 0
    for gkey in order:
        idxs = groups[gkey]

        # 2) Nilai agregat = nilai COO yang sudah di-fan-out sama rata oleh
        #    _map_coo_items_to_rows (semua baris group bernilai sama). Pakai nilai
        #    maksimum sebagai penjaga bila satu baris sempat ter-nol-kan langkah lain.
        agg = {}
        for field in COO_AGGREGATE_NUMERIC_FIELDS:
            best = None
            for i in idxs:
                v = _to_float(rows[i].get(field))
                if v is None:
                    continue
                if best is None or v > best:
                    best = v
            agg[field] = best

        # 3) Baris pertama -> agregat; baris lain -> 0.
        for pos, i in enumerate(idxs):
            for field in COO_AGGREGATE_NUMERIC_FIELDS:
                if pos == 0:
                    cleaned = _coo_clean_number(agg.get(field))
                    if cleaned is not None:
                        rows[i][field] = cleaned
                else:
                    rows[i][field] = 0
            if pos != 0:
                zeroed += 1

    print(
        f"[COO_AGGREGATE_TOP_ROW] vendor={normalize_vendor_id(vendor_id)} "
        f"groups={len(order)} zeroed_rows={zeroed}"
    )
    return rows


# =========================================================
# EKSTRAKSI TERFOKUS PACKING LIST (vendor PL merged-cell numerik)
# =========================================================
def _build_pl_item_list_prompt() -> str:
    return """
ROLE:
Anda AI IDP yang fokus mengekstrak DAFTAR LINE ITEM dari dokumen Packing List (PL) saja.
Rule-based, deterministik, anti-halusinasi.

SUMBER:
- Baca HANYA dokumen Packing List / PL.
- ABAIKAN dokumen Invoice, Bill of Lading, dan Certificate of Origin bila ada.

STRUKTUR TABEL PL:
- Kolom utama (main table): PO NO., CODE, DESCRIPTION, QTY, UNIT, QTY/CTN,
  TOTAL CTNS, TOTAL N.W., TOTAL G.W., TOTAL CBM (urutan kolom bisa sedikit berbeda).
- Untuk sebagian baris, kolom numerik (TOTAL CTNS / TOTAL N.W. / TOTAL G.W. /
  TOTAL CBM) di-MERGE secara vertikal: beberapa baris berbagi satu carton sehingga
  sel pada baris selain pemilik nilai tampak KOSONG.
- Di sisi KANAN ada kolom "Combined" (Combined QTY / Combined N.W / Combined G.W):
    * AREA A = nilai agregat per MERGE GROUP. SELALU disertai angka TOTAL CTNS
      (mis. 1, 2) dan biasanya disertai satu nilai CBM.
    * AREA B = TOTAL untuk SELURUH baris dengan tipe produk yang sama. TANPA
      TOTAL CTNS, nilainya lebih besar. JANGAN dimasukkan ke merge_groups.

TUGAS — keluarkan SATU objek JSON (bukan array) dengan dua bagian:

1) "rows": SATU objek per VISUAL LINE ITEM main table, urut atas->bawah.
   Field per row:
   - "seq": nomor urut baris (1,2,3,...) sesuai urutan tampil.
   - "po": isi kolom "PO NO." (string apa adanya).
   - "code": isi kolom "CODE".
   - "qty": angka kolom "QTY" baris itu.
   - "unit": isi kolom "UNIT".
   - "total_ctns": angka yang BENAR-BENAR tercetak di sel "TOTAL CTNS" PADA BARIS ITU.
       Jika sel kosong (karena merged ke baris lain), isi null.
   - "total_nw": angka di sel "TOTAL N.W." PADA BARIS ITU; kosong/merged -> null.
   - "total_gw": angka di sel "TOTAL G.W." PADA BARIS ITU; kosong/merged -> null.
   - "total_cbm": angka di sel "TOTAL CBM" PADA BARIS ITU; kosong/merged -> null.
   ATURAN KETAT untuk rows:
   - Ambil HANYA angka yang BENAR-BENAR tercetak di sel main table baris itu.
   - DILARANG meminjam nilai dari baris tetangga maupun dari kolom "Combined".
   - Jika sel merged/kosong -> WAJIB null (BUKAN 0, BUKAN nilai baris lain).

2) "merge_groups": SATU objek per entri AREA A (Combined yang DISERTAI TOTAL CTNS).
   Field per group:
   - "combined_qty": nilai "Combined QTY" AREA A (jumlah QTY baris-baris dalam group).
   - "total_ctns": angka TOTAL CTNS yang menyertai AREA A tersebut.
   - "combined_nw": nilai "Combined N.W" AREA A.
   - "combined_gw": nilai "Combined G.W" AREA A.
   - "cbm": nilai CBM yang menyertai AREA A (jika ada; jika tidak, null).
   ATURAN KETAT untuk merge_groups:
   - HANYA masukkan Combined yang punya TOTAL CTNS (AREA A).
   - JANGAN masukkan Combined tanpa TOTAL CTNS (itu AREA B / total per tipe produk).
   - Jika tidak ada merge group sama sekali, isi array kosong [].

ATURAN UMUM:
- Angka sebagai angka (number). Yang tidak ada -> null.
- Output HANYA JSON valid, tanpa teks/penjelasan/markdown. Mulai '{' diakhiri '}'.

SCHEMA OUTPUT:
{
  "rows": [
    {"seq": number, "po": "string", "code": "string", "qty": number, "unit": "string",
     "total_ctns": number, "total_nw": number, "total_gw": number, "total_cbm": number}
  ],
  "merge_groups": [
    {"combined_qty": number, "total_ctns": number, "combined_nw": number, "combined_gw": number, "cbm": number}
  ]
}
""".strip()


def _extract_pl_item_list(file_uri: str, vendor_id: str = "default") -> dict:
    """Ekstraksi terfokus PL-only -> {"rows": [...], "merge_groups": [...]}."""
    if not file_uri:
        return {}

    obj = _call_gemini_json_uri(
        file_uri,
        _build_pl_item_list_prompt(),
        expect_array=False,
        retries=3,
        vendor_id=vendor_id,
    )

    if not isinstance(obj, dict):
        return {}

    rows = obj.get("rows")
    groups = obj.get("merge_groups")
    return {
        "rows": rows if isinstance(rows, list) else [],
        "merge_groups": groups if isinstance(groups, list) else [],
    }


# Field numerik PL yang ditempatkan agregat-per-group di baris teratas + 0 di sisanya.
PL_MERGED_NUMERIC_FIELDS = ["pl_package_count", "pl_nw", "pl_gw", "pl_volume"]


def _pl_num(value):
    """null/'null'/'' -> None; selain itu float (atau None bila non-numerik)."""
    if _is_null(value):
        return None
    return _to_float(value)


def _assign_pl_merged_numerics_to_rows(rows: list, pl_data: dict, vendor_id: str = "default"):
    """
    Vendor PL merged-cell numerik (lihat VENDORS_PL_MERGED_NUMERIC, mis. novatec).

    Pakai hasil ekstraksi terfokus PL (_extract_pl_item_list): per-baris main table
    + daftar AREA A merge group. Hitung nilai final per baris secara deterministik:
      - Baris standalone (punya TOTAL N.W. sendiri) -> pakai nilai main table-nya.
      - Baris merged (sel main table kosong) -> dikelompokkan jadi run yang jumlah
        QTY-nya = Combined QTY AREA A; agregat group ditaruh di baris TERATAS run,
        baris lain di-nol-kan.

    Guard anti-regresi: hasil hanya diterapkan ke `rows` (all_rows) bila total
    rekonstruksi (pkg/nw/gw/volume) cocok dengan pl_total_* dokumen DAN jumlah
    baris + QTY-nya sejajar 1:1. Bila tidak, data PL dibiarkan apa adanya.
    Hanya menyentuh PL_MERGED_NUMERIC_FIELDS.
    """
    if not _is_pl_merged_numeric_vendor(vendor_id):
        return rows
    if not isinstance(rows, list) or not isinstance(pl_data, dict):
        return rows

    pl_rows = pl_data.get("rows") or []
    pl_groups = pl_data.get("merge_groups") or []
    if not pl_rows:
        print("[PL_MERGED_NUMERIC][SKIP] focused PL rows kosong")
        return rows

    # --- 1) Normalisasi baris terfokus + klasifikasi standalone vs merged ---
    fr = []
    for it in pl_rows:
        if not isinstance(it, dict):
            continue
        nw = _pl_num(it.get("total_nw"))
        fr.append({
            "qty": _pl_num(it.get("qty")),
            "nw": nw,
            "gw": _pl_num(it.get("total_gw")),
            "ctns": _pl_num(it.get("total_ctns")),
            "cbm": _pl_num(it.get("total_cbm")),
            # standalone = sel TOTAL N.W. baris ini terisi (>0)
            "standalone": nw is not None and nw > 1e-9,
            "f_ctns": 0.0, "f_nw": 0.0, "f_gw": 0.0, "f_cbm": 0.0,
        })

    # --- 2) Normalisasi AREA A groups (wajib punya combined_qty + total_ctns) ---
    groups = []
    for g in pl_groups:
        if not isinstance(g, dict):
            continue
        cq = _pl_num(g.get("combined_qty"))
        gc = _pl_num(g.get("total_ctns"))
        if cq is None or cq <= 1e-9 or gc is None:
            continue  # tanpa TOTAL CTNS = AREA B, abaikan
        groups.append({
            "combined_qty": cq,
            "ctns": gc,
            "nw": _pl_num(g.get("combined_nw")) or 0.0,
            "gw": _pl_num(g.get("combined_gw")) or 0.0,
            "cbm": _pl_num(g.get("cbm")) or 0.0,
            "used": False,
        })

    # --- 3) Standalone -> nilai main table sendiri ---
    for r in fr:
        if r["standalone"]:
            r["f_ctns"] = r["ctns"] or 0.0
            r["f_nw"] = r["nw"] or 0.0
            r["f_gw"] = r["gw"] or 0.0
            r["f_cbm"] = r["cbm"] or 0.0

    # --- 4) Merged rows -> cocokkan ke AREA A group via jumlah QTY ---
    #     Greedy kiri->kanan: dari posisi merged pertama yang belum terpakai,
    #     cari run TERPENDEK (k>=1) yang sum(qty)-nya == combined_qty group manapun.
    #     Run terpendek lebih dulu => AREA A halus dipilih sebelum AREA B kasar.
    n = len(fr)
    i = 0
    unmatched_merged = 0
    while i < n:
        if fr[i]["standalone"]:
            i += 1
            continue
        run_end = i
        while run_end < n and not fr[run_end]["standalone"]:
            run_end += 1
        j = i
        while j < run_end:
            matched = False
            cum = 0.0
            for k in range(j, run_end):
                q = fr[k]["qty"]
                if q is None:
                    break
                cum += q
                g = next(
                    (gg for gg in groups
                     if not gg["used"] and abs(gg["combined_qty"] - cum) <= 1e-6),
                    None,
                )
                if g is not None:
                    g["used"] = True
                    fr[j]["f_ctns"] = g["ctns"]
                    fr[j]["f_nw"] = g["nw"]
                    fr[j]["f_gw"] = g["gw"]
                    fr[j]["f_cbm"] = g["cbm"]
                    for m in range(j + 1, k + 1):
                        fr[m]["f_ctns"] = fr[m]["f_nw"] = fr[m]["f_gw"] = fr[m]["f_cbm"] = 0.0
                    j = k + 1
                    matched = True
                    break
            if not matched:
                unmatched_merged += 1
                j += 1
        i = run_end

    # --- 5) Guard: rekonstruksi total harus cocok dgn pl_total_* dokumen ---
    doc_pkg = _to_float(_first_non_null_nonzero(rows, "pl_total_package"))
    doc_nw = _to_float(_first_non_null_nonzero(rows, "pl_total_nw"))
    doc_gw = _to_float(_first_non_null_nonzero(rows, "pl_total_gw"))
    doc_vol = _to_float(_first_non_null_nonzero(rows, "pl_total_volume"))

    sum_pkg = sum(r["f_ctns"] for r in fr)
    sum_nw = sum(r["f_nw"] for r in fr)
    sum_gw = sum(r["f_gw"] for r in fr)
    sum_vol = sum(r["f_cbm"] for r in fr)

    def _ok(s, d, eps=0.02):
        return d is None or abs(s - d) <= eps

    reconciled = (
        unmatched_merged == 0
        and _ok(sum_pkg, doc_pkg)
        and _ok(sum_nw, doc_nw)
        and _ok(sum_gw, doc_gw)
        and (doc_vol is None or _volume_values_match_with_conversion(sum_vol, doc_vol))
    )

    if not reconciled:
        print(
            "[PL_MERGED_NUMERIC][SKIP] rekonstruksi tidak rekonsiliasi "
            f"(unmatched_merged={unmatched_merged}; "
            f"pkg {sum_pkg}/{doc_pkg}; nw {sum_nw}/{doc_nw}; "
            f"gw {sum_gw}/{doc_gw}; vol {sum_vol}/{doc_vol}); "
            "data PL dibiarkan apa adanya"
        )
        return rows

    # --- 6) Map ke all_rows (urut, dijaga kesamaan QTY) lalu set nilai ---
    target_idx = [
        idx for idx, r in enumerate(rows)
        if isinstance(r, dict) and not _is_null(r.get("pl_item_no"))
    ]
    if len(target_idx) != len(fr):
        print(
            f"[PL_MERGED_NUMERIC][SKIP] jumlah baris all_rows ({len(target_idx)}) "
            f"!= focused PL ({len(fr)}); data PL dibiarkan apa adanya"
        )
        return rows

    for pos, idx in enumerate(target_idx):
        rq = _to_float(rows[idx].get("pl_quantity"))
        fq = fr[pos]["qty"]
        if rq is not None and fq is not None and abs(rq - fq) > 1e-6:
            print(
                f"[PL_MERGED_NUMERIC][SKIP] QTY tidak sejajar pada pos {pos} "
                f"(all_rows={rq}, focused={fq}); data PL dibiarkan apa adanya"
            )
            return rows

    def _clean(v):
        f = float(v)
        return int(f) if abs(f - round(f)) <= 1e-9 else round(f, 2)

    zeroed = 0
    for pos, idx in enumerate(target_idx):
        row = rows[idx]
        f = fr[pos]
        row["pl_package_count"] = _clean(f["f_ctns"])
        row["pl_nw"] = _clean(f["f_nw"])
        row["pl_gw"] = _clean(f["f_gw"])
        row["pl_volume"] = _clean(f["f_cbm"])
        if (not f["standalone"]) and f["f_nw"] <= 1e-9 and f["f_ctns"] <= 1e-9:
            row["_merged_pl_zero_row"] = True
            zeroed += 1
        else:
            row.pop("_merged_pl_zero_row", None)

    print(
        f"[PL_MERGED_NUMERIC] vendor={normalize_vendor_id(vendor_id)} "
        f"rows={len(fr)} groups_used={sum(1 for g in groups if g['used'])}/{len(groups)} "
        f"zeroed_rows={zeroed} applied=OK"
    )
    return rows


def _postprocess_bl_description_novatec(rows: list):
    """
    BL NOVATEC: kolom "Description of Goods" memakai NAMA KATEGORI produk
    (mis. "WHEEL SET", "RIM G24", "RIM R4 FRONT", "VALVES FOR TUBELESS TYRES")
    yang TIDAK align secara tekstual dengan inv_description terstruktur
    ("WHEELSET;NOVATEC;M30 DISC;..."). Matcher generik akan men-null-kan ~4 dari 5
    kategori karena "WHEEL SET" != "WHEELSET" dan kode "R4" terlalu pendek untuk
    dianggap code. Pemetaan kategori -> baris dilakukan model di prompt (kekuatan
    LLM untuk pencocokan semantik), jadi di sini cukup jaga sanity ringan:
    pertahankan pasangan bl_description/bl_hs_code HANYA jika bl_hs_code berformat
    HS yang masuk akal (mis. 8714.92 / 8481.80); selain itu null-kan keduanya.
    """
    hs_pattern = re.compile(r"^\d{4}\.?\d{0,2}$")
    for row in rows:
        if not isinstance(row, dict):
            continue

        bl_desc = row.get("bl_description")
        if _is_null(bl_desc):
            # tidak ada deskripsi BL -> pastikan hs juga tidak menggantung
            if not _is_null(row.get("bl_hs_code")):
                row["bl_hs_code"] = "null"
            continue

        bl_hs = row.get("bl_hs_code")
        hs_norm = "" if _is_null(bl_hs) else re.sub(r"\s+", "", str(bl_hs))
        if not hs_pattern.match(hs_norm):
            row["bl_description"] = "null"
            row["bl_hs_code"] = "null"


def _postprocess_bl_description(rows: list, threshold: float = 0.4, vendor_id: str = "default"):
    """
    Rule baru:
    - jika bl_description punya code alfanumerik ATAU numeric-only, compare code tsb ke inv_description
    - jika tidak ada di inv_description, fallback ke inv_spart_item_no / pl_item_no
    - jika bl_description tidak punya code, compare full bl_description ke inv_description
    - jika tidak ada yang match, null-kan bl_description dan bl_hs_code
    - bl_mark_number tetap dibiarkan
    """
    # NOVATEC: deskripsi BL berbasis kategori produk yang tidak bisa divalidasi
    # matcher generik (lihat _postprocess_bl_description_novatec).
    if normalize_vendor_id(vendor_id) == "novatec":
        _postprocess_bl_description_novatec(rows)
        return

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
            vendor_id=forced_vendor_id, # Masukkan vendor target pemetaan di sini
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
                    has_bl_doc=bool(bl_path),
                    has_coo_doc=bool(grp["coo_paths"]),
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

        if forced_vendor_id == "karet_deli":
            # 1. Berikan stempel urutan asli dari ekstraksi sebelum baris diacak
            for idx, r in enumerate(merged_detail_rows):
                if isinstance(r, dict):
                    r["_global_original_order"] = idx

            # 2. Urutkan berdasarkan amount agar ghost row hilang
            merged_detail_rows.sort(
                key=lambda r: (
                    _to_float(r.get("inv_amount")) or 0.0,
                    _to_float(r.get("inv_unit_price")) or 0.0
                ),
                reverse=True
            )

            unique_rows = []
            seen_sigs = set()
            dropped_null_anchor = 0
            for r in merged_detail_rows:
                if not isinstance(r, dict):
                    continue

                # Drop row kalau inv_spart_item_no DAN inv_description dua-duanya null/kosong.
                # Row seperti ini biasanya placeholder dari chunked extraction yang
                # tidak ke-fill (misal _missing_from_chunk fallback) — tidak ada
                # identitas item sama sekali, tidak ada gunanya di-keep.
                if (
                    _is_null(r.get("inv_spart_item_no"))
                    and _is_null(r.get("inv_description"))
                ):
                    dropped_null_anchor += 1
                    continue

                inv_no_raw = str(r.get("inv_invoice_no") or "").strip().upper()
                inv_no_base = inv_no_raw.split('/K')[0].strip()

                po_no = str(r.get("inv_customer_po_no") or r.get("pl_customer_po_no") or "").strip().upper()
                item_no = str(r.get("inv_spart_item_no") or r.get("pl_item_no") or "").strip()
                qty = _to_float(r.get("inv_quantity") or r.get("pl_quantity"))
                desc = str(r.get("inv_description") or "").strip().upper()[:30]

                sig = (inv_no_base, po_no, item_no, qty, desc)
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    unique_rows.append(r)

            if dropped_null_anchor:
                print(
                    f"[KARET_DELI_DEDUP] dropped {dropped_null_anchor} row(s) "
                    f"dengan inv_spart_item_no & inv_description null"
                )

            merged_detail_rows = unique_rows
            _canonicalize_invoice_total_headers(merged_detail_rows)

            # 3. Second-pass dedup: catch qty-variance stragglers dari multi-pass
            # extraction. Signature pakai (po, item, desc) TANPA qty, jadi
            # variance qty antar-pass tidak bisa ngeloloskan duplikat lagi.
            # Untuk safety supaya legitimate dupes (item sama muncul beberapa
            # kali di invoice yang sama, biasanya adjacent dalam original order)
            # tidak ke-drop, dedup hanya berlaku saat gap _global_original_order
            # antar dupe > KARET_DELI_STRAGGLER_GAP_THRESHOLD (legitimate dupes
            # biasanya gap=1, stragglers gap=50+).
            KARET_DELI_STRAGGLER_GAP_THRESHOLD = 30

            # Group rows by signature without qty
            sig_groups = {}
            for r in merged_detail_rows:
                if not isinstance(r, dict):
                    continue
                inv_no_raw = str(r.get("inv_invoice_no") or "").strip().upper()
                inv_no_base = inv_no_raw.split('/K')[0].strip()
                po_no = str(r.get("inv_customer_po_no") or r.get("pl_customer_po_no") or "").strip().upper()
                item_no = str(r.get("inv_spart_item_no") or r.get("pl_item_no") or "").strip()
                desc = str(r.get("inv_description") or "").strip().upper()[:30]
                if not po_no and not item_no and not desc:
                    continue
                key = (inv_no_base, po_no, item_no, desc)
                sig_groups.setdefault(key, []).append(r)

            stragglers_to_drop_ids = set()
            for key, group in sig_groups.items():
                if len(group) < 2:
                    continue
                # Sort by _global_original_order
                group_sorted = sorted(
                    group, key=lambda r: r.get("_global_original_order", 999999)
                )
                canonical = group_sorted[0]
                canonical_order = canonical.get("_global_original_order", 0)
                for dup in group_sorted[1:]:
                    dup_order = dup.get("_global_original_order", 0)
                    gap = dup_order - canonical_order
                    if gap > KARET_DELI_STRAGGLER_GAP_THRESHOLD:
                        stragglers_to_drop_ids.add(id(dup))
                        print(
                            f"[KARET_DELI_DEDUP] drop straggler: po={key[1]} "
                            f"item={key[2]} canonical_order={canonical_order} "
                            f"straggler_order={dup_order} gap={gap} "
                            f"canonical_qty={canonical.get('inv_quantity')} "
                            f"straggler_qty={dup.get('inv_quantity')}"
                        )

            if stragglers_to_drop_ids:
                before_count = len(merged_detail_rows)
                merged_detail_rows = [
                    r for r in merged_detail_rows
                    if id(r) not in stragglers_to_drop_ids
                ]
                print(
                    f"[KARET_DELI_DEDUP] dropped {before_count - len(merged_detail_rows)} "
                    f"straggler(s) dari multi-pass extraction (qty variance, gap > "
                    f"{KARET_DELI_STRAGGLER_GAP_THRESHOLD})"
                )

            # 4. Kembalikan urutan baris ke posisi mutlak aslinya
            merged_detail_rows.sort(key=lambda r: r.get("_global_original_order", 999999))

            print(f"[KARET_DELI_DEDUP] Reduced detail rows and restored exact original order")

            # =================================================================
            # FIX: HEAL DATA SETELAH DEDUPLIKASI (HEADER BOLONG & TOTAL ERROR)
            # =================================================================
            
            # 1. Fix Header Bolong (Forward Fill per Invoice)
            header_cache = {}
            for r in merged_detail_rows:
                inv_no = r.get("inv_invoice_no")
                v_name = r.get("inv_vendor_name")
                v_addr = r.get("inv_vendor_address")
                
                # Cari baris yang punya header valid untuk dijadikan patokan
                if inv_no and v_name and v_name != "null":
                    header_cache[inv_no] = {"name": v_name, "addr": v_addr}
            
            for r in merged_detail_rows:
                inv_no = r.get("inv_invoice_no")
                if inv_no in header_cache:
                    if _is_null(r.get("inv_vendor_name")):
                        r["inv_vendor_name"] = header_cache[inv_no]["name"]
                    if _is_null(r.get("inv_vendor_address")):
                        r["inv_vendor_address"] = header_cache[inv_no]["addr"]

            # 2. Fix Total Mismatch Error Nyasar (Re-Validasi dari Data Bersih)
            for r in merged_detail_rows:
                if not isinstance(r, dict): continue
                msgs = _split_match_description_messages(r.get("match_description"))
                
                # Hapus error mismatch bawaan dari ghost group
                kept_msgs = [m for m in msgs if "total_" not in m.lower()]
                
                if kept_msgs:
                    r["match_description"] = "; ".join(kept_msgs)
                else:
                    if str(r.get("match_score", "")).strip().upper() != "CHILD PO":
                        r["match_score"] = "true"
                    r["match_description"] = "null"

            # Kelompokkan data yang sudah bersih per invoice untuk divalidasi ulang
            rows_by_inv = {}
            for r in merged_detail_rows:
                inv_no = str(r.get("inv_invoice_no") or "unknown").strip()
                rows_by_inv.setdefault(inv_no, []).append(r)

            # Hitung ulang sum dan berikan error total yang benar-benar akurat
            for inv_no, group_rows in rows_by_inv.items():
                _validate_invoice_rows(group_rows)
                _validate_packing_rows(group_rows, vendor_id=forced_vendor_id)
            
            # Pastikan status final (TRUE/FALSE) sinkron dengan error terupdate
            _finalize_match_fields(merged_detail_rows)
            # =================================================================

        if bl_path:
            # Majority BL header antar invoice group.
            # Ini memang harus di run_grouped_ocr karena semua invoice group sudah merge di sini.
            _postprocess_bl_header_majority_by_invoice(
                merged_detail_rows,
                vendor_id=forced_vendor_id
            )

            # Hapus hanya error validasi BL lama.
            # Error Invoice / PL / COO / PO tetap dipertahankan.
            for row in merged_detail_rows:
                if not isinstance(row, dict):
                    continue

                messages = _split_match_description_messages(row.get("match_description"))

                kept_messages = [
                    msg for msg in messages
                    if not str(msg or "").strip().upper().startswith("BL:")
                ]

                if kept_messages:
                    if str(row.get("match_score", "")).strip().upper() != "CHILD PO":
                        row["match_score"] = "false"
                    row["match_description"] = "; ".join(kept_messages)
                else:
                    if str(row.get("match_score", "")).strip().upper() != "CHILD PO":
                        row["match_score"] = "true"
                    row["match_description"] = "null"

            # Validasi ulang hanya BL, karena yang berubah hanya kolom bl_*.
            _validate_bl_rows(merged_detail_rows)

            # Finalize ulang supaya match_score/confidence konsisten setelah BL revalidation.
            _finalize_match_fields(merged_detail_rows)

        detail_csv_uri = _convert_to_csv_path(
            f"output/detail/{invoice_name}_detail.csv",
            merged_detail_rows,
            field_order=_get_detail_csv_field_order(forced_vendor_id)
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

# =========================================================
# CANDIDATE-BASED GEMINI RECHECK FOR TOTAL MISMATCH
# =========================================================

DETAIL_RECHECK_CONTEXT_FIELDS = [
    "_detail_row_no",

    # invoice/group anchors
    "inv_invoice_no",
    "pl_invoice_no",
    "coo_invoice_no",
    "coo_no",

    # sequence anchors
    "inv_seq",
    "pl_seq",
    "coo_seq",

    # PO anchors
    "inv_customer_po_no",
    "pl_customer_po_no",
    "coo_customer_po_no",

    # item/article anchors
    "inv_spart_item_no",
    "inv_item_no",
    "pl_item_no",
    "coo_item_no",

    # description anchors
    "inv_description",
    "pl_description",
    "coo_description",

    # optional code anchors
    "inv_hs_code",
    "coo_hs_code",
    "bl_hs_code",
    "bl_description",

    # invoice numeric fields
    "inv_quantity",
    "inv_quantity_unit",
    "inv_unit_price",
    "inv_amount",

    # packing numeric fields
    "pl_quantity",
    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",
    "pl_weight_unit",
    "pl_volume_unit",
]

def _clean_anchor_value(value):
    if _is_null(value):
        return "null"
    return str(value).strip()


def _build_line_item_anchor_context(row: dict) -> dict:
    """
    Anchor utama agar Gemini menemukan line item yang sama di PDF
    sebelum memutuskan numeric value benar/salah.
    """
    if not isinstance(row, dict):
        return {}

    return {
        "anchor_priority": [
            "invoice_no",
            "customer_po_no",
            "item_or_article_no",
            "description",
            "hs_code",
            "sequence",
        ],
        "invoice_anchors": {
            "inv_invoice_no": _clean_anchor_value(row.get("inv_invoice_no")),
            "pl_invoice_no": _clean_anchor_value(row.get("pl_invoice_no")),
            "coo_invoice_no": _clean_anchor_value(row.get("coo_invoice_no")),
            "coo_no": _clean_anchor_value(row.get("coo_no")),
        },
        "po_anchors": {
            "inv_customer_po_no": _clean_anchor_value(row.get("inv_customer_po_no")),
            "pl_customer_po_no": _clean_anchor_value(row.get("pl_customer_po_no")),
            "coo_customer_po_no": _clean_anchor_value(row.get("coo_customer_po_no")),
        },
        "item_anchors": {
            "inv_spart_item_no": _clean_anchor_value(row.get("inv_spart_item_no")),
            "inv_item_no": _clean_anchor_value(row.get("inv_item_no")),
            "pl_item_no": _clean_anchor_value(row.get("pl_item_no")),
            "coo_item_no": _clean_anchor_value(row.get("coo_item_no")),
        },
        "description_anchors": {
            "inv_description": _clean_anchor_value(row.get("inv_description")),
            "pl_description": _clean_anchor_value(row.get("pl_description")),
            "coo_description": _clean_anchor_value(row.get("coo_description")),
        },
        "code_anchors": {
            "inv_hs_code": _clean_anchor_value(row.get("inv_hs_code")),
            "coo_hs_code": _clean_anchor_value(row.get("coo_hs_code")),
            "bl_hs_code": _clean_anchor_value(row.get("bl_hs_code")),
        },
        "sequence_anchors": {
            "inv_seq": _clean_anchor_value(row.get("inv_seq")),
            "pl_seq": _clean_anchor_value(row.get("pl_seq")),
            "coo_seq": _clean_anchor_value(row.get("coo_seq")),
            "_detail_row_no": _clean_anchor_value(row.get("_detail_row_no")),
        },
        "rule": (
            "Cari target line item di PDF menggunakan kombinasi invoice_no + PO + item/article. "
            "Jika item/article kosong, gunakan description/HS/sequence sebagai fallback. "
            "Jangan koreksi numeric field jika anchor line item tidak jelas."
        ),
    }


def _round_recheck_candidate(value, ndigits: int = 6):
    num = _to_float(value)
    if num is None:
        return None

    rounded = round(num, ndigits)

    # supaya 1.0 jadi 1, tapi 0.325 tetap 0.325
    if abs(rounded - int(rounded)) < 1e-9:
        return int(rounded)

    return rounded


def _same_recheck_value(left, right, field: str = "") -> bool:
    if field in DETAIL_RECHECK_NUM_FIELDS:
        l = _to_float(left)
        r = _to_float(right)

        if l is None and r is None:
            return True

        if l is None or r is None:
            return False

        return abs(l - r) <= 0.000001

    return str(left or "").strip() == str(right or "").strip()


def _add_candidate_value(candidates: list, candidate_type: str, value, reason: str = ""):
    """
    Candidate internal untuk membantu Gemini memilih.
    Tidak diekspor ke CSV final.
    """
    if value is None:
        return

    if isinstance(value, float):
        value = _round_recheck_candidate(value)

    for existing in candidates:
        if _same_recheck_value(existing.get("value"), value):
            return

    candidates.append({
        "candidate_type": candidate_type,
        "value": value,
        "reason": reason,
    })


def _build_recheck_total_group_plan(rows: list):
    """
    Build plan per invoice_group untuk total mismatch.

    Output:
    {
        invoice_group: {
            "fields": set(["pl_volume", ...]),
            "issues": [...],
            "field_meta": {
                "pl_volume": {
                    "declared_field": "pl_total_volume",
                    "declared_total": 2.152,
                    "actual_sum": 2.177,
                    "gap": 0.025,
                    "label": "PackingList: total_volume mismatch"
                }
            }
        }
    }

    Kenapa hitung ulang di sini?
    Supaya semua row dalam affected invoice group ikut recheck,
    bukan hanya row yang kebetulan match_score=false.
    """
    group_plan = {}
    grouped_rows = _group_rows_by_invoice_no(rows)
    eps = float(TOTAL_CONTRIBUTION_EPS)

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

            is_mismatch = False

            if spec["declared_field"] == "pl_total_volume":
                is_mismatch = not _volume_values_match_with_conversion(
                    actual_sum,
                    declared_total
                )
            else:
                is_mismatch = abs(actual_sum - declared_total) > eps

            if not is_mismatch:
                continue

            gap = actual_sum - declared_total
            row_field = spec["row_field"]

            if invoice_group not in group_plan:
                group_plan[invoice_group] = {
                    "fields": set(),
                    "issues": [],
                    "field_meta": {},
                }

            group_plan[invoice_group]["fields"].add(row_field)
            group_plan[invoice_group]["issues"].append(
                f"{spec['label']} for invoice_no={invoice_group} "
                f"(sum {actual_sum}, doc {declared_total}, gap {gap})"
            )
            group_plan[invoice_group]["field_meta"][row_field] = {
                "declared_field": spec["declared_field"],
                "declared_total": declared_total,
                "actual_sum": actual_sum,
                "gap": gap,
                "label": spec["label"],
            }

    return group_plan


def _build_row_context_for_recheck(row: dict, prev_row=None, next_row=None):
    def _pick_context(src):
        if not isinstance(src, dict):
            return None

        out = {}
        for key in DETAIL_RECHECK_CONTEXT_FIELDS:
            if key in src:
                out[key] = src.get(key)

        return out

    return {
        "current_row": _pick_context(row),
        "previous_row": _pick_context(prev_row),
        "next_row": _pick_context(next_row),
    }


def _build_candidate_values_for_field(
    row: dict,
    field: str,
    group_field_meta: dict,
):
    """
    Candidate values untuk Gemini pilih.
    Penting:
    - current_extracted selalu dikirim.
    - gap_adjust_candidate dikirim sebagai kandidat matematis, bukan kebenaran.
    - formula_candidate untuk inv_amount.
    - merge_continuation_zero untuk additive numeric field.
    """
    candidates = []

    current_value = row.get(field)
    current_num = _to_float(current_value)

    _add_candidate_value(
        candidates,
        "current_extracted",
        current_value,
        "Nilai hasil ekstraksi saat ini."
    )

    # Candidate 1: gap adjustment
    meta = group_field_meta.get(field) if isinstance(group_field_meta, dict) else None
    if meta and current_num is not None:
        gap = _to_float(meta.get("gap"))
        if gap is not None:
            suggested = current_num - gap

            # Jangan kirim candidate negatif untuk field additive.
            if suggested >= -float(TOTAL_CONTRIBUTION_EPS):
                _add_candidate_value(
                    candidates,
                    "gap_adjust_candidate",
                    _round_recheck_candidate(max(0, suggested)),
                    (
                        "Kandidat expected dari audit total mismatch. "
                        "Nilai ini akan membuat total lebih dekat/match, tetapi BUKAN jawaban pasti. "
                        "Pilih hanya jika nilai ini terlihat pada target cell PDF atau didukung layout visual."
                    )
                )

    # Candidate 2: formula khusus invoice amount
    if field == "inv_amount":
        qty = _to_float(row.get("inv_quantity"))
        unit_price = _to_float(row.get("inv_unit_price"))

        if qty is not None and unit_price is not None:
            formula_amount = qty * unit_price
            _add_candidate_value(
                candidates,
                "formula_candidate",
                _round_recheck_candidate(formula_amount),
                "Kandidat dari rumus inv_quantity * inv_unit_price."
            )

    # Candidate 3: merge-cell continuation
    if field in DETAIL_RECHECK_ADDITIVE_NUM_FIELDS:
        if current_num is not None and abs(current_num) > float(TOTAL_CONTRIBUTION_EPS):
            _add_candidate_value(
                candidates,
                "merge_continuation_zero",
                0,
                (
                    "Kandidat jika row ini adalah continuation dari merged numeric cell. "
                    "Untuk field additive, continuation row harus 0 agar value tidak terduplikat."
                )
            )

    return candidates

# =========================================================
# LAYOUT-AWARE RECHECK CONTEXT
# =========================================================

DETAIL_RECHECK_COLUMN_DEFINITIONS = {
    "pl_volume": {
        "document_type": "Packing List",
        "target_column": "Volume / CBM / Measurement / M3",
        "must_not_use_columns": [
            "NW", "N.W.", "Net Weight",
            "GW", "G.W.", "Gross Weight",
            "Package", "Carton", "CTN", "Quantity",
        ],
        "visual_hints": [
            "Biasanya berada dekat kolom NW/GW tetapi bukan kolom weight.",
            "Bisa tertulis sebagai CBM, M3, Measurement, Volume.",
            "Decimal kecil seperti 0.325 bisa terlihat seperti 0.35 jika digit tengah rapat.",
        ],
    },
    "pl_gw": {
        "document_type": "Packing List",
        "target_column": "GW / G.W. / Gross Weight",
        "must_not_use_columns": [
            "NW", "N.W.", "Net Weight",
            "Volume", "CBM", "Measurement", "M3",
            "Package", "Carton", "CTN",
        ],
        "visual_hints": [
            "GW biasanya lebih besar atau sama dengan NW.",
            "Jangan ambil angka dari kolom volume/CBM.",
        ],
    },
    "pl_nw": {
        "document_type": "Packing List",
        "target_column": "NW / N.W. / Net Weight",
        "must_not_use_columns": [
            "GW", "G.W.", "Gross Weight",
            "Volume", "CBM", "Measurement", "M3",
            "Package", "Carton", "CTN",
        ],
        "visual_hints": [
            "NW biasanya lebih kecil atau sama dengan GW.",
            "Jangan tertukar dengan GW.",
        ],
    },
    "pl_package_count": {
        "document_type": "Packing List",
        "target_column": "Package / Carton / CTN / PKGS",
        "must_not_use_columns": [
            "NW", "GW", "Volume", "CBM", "Measurement", "Quantity",
        ],
        "visual_hints": [
            "Package count biasanya integer.",
            "Jika cell merged, jangan duplikasikan package count ke continuation row.",
        ],
    },
    "pl_quantity": {
        "document_type": "Packing List",
        "target_column": "Quantity / QTY",
        "must_not_use_columns": [
            "Package", "NW", "GW", "Volume", "CBM",
        ],
        "visual_hints": [
            "Quantity bisa berbeda dari package count.",
        ],
    },
    "inv_amount": {
        "document_type": "Invoice",
        "target_column": "Amount / Total Amount",
        "must_not_use_columns": [
            "Quantity", "Unit Price", "Description",
        ],
        "visual_hints": [
            "Amount sering dapat divalidasi dari quantity * unit price.",
            "Jangan ambil unit price sebagai amount.",
        ],
    },
    "inv_quantity": {
        "document_type": "Invoice",
        "target_column": "Quantity / QTY",
        "must_not_use_columns": [
            "Unit Price", "Amount", "Description",
        ],
        "visual_hints": [
            "Quantity biasanya berada sebelum unit price dan amount.",
        ],
    },
    "inv_unit_price": {
        "document_type": "Invoice",
        "target_column": "Unit Price / Price",
        "must_not_use_columns": [
            "Quantity", "Amount", "Description",
        ],
        "visual_hints": [
            "Unit price biasanya berada sebelum amount.",
        ],
    },
}


def _get_column_context_for_field(field: str):
    return DETAIL_RECHECK_COLUMN_DEFINITIONS.get(field, {
        "document_type": "Unknown",
        "target_column": field,
        "must_not_use_columns": [],
        "visual_hints": [],
    })


def _build_layout_risk_context_for_field(field: str):
    risks = [
        {
            "risk": "value_continues_to_next_line_because_cell_is_small",
            "instruction": (
                "Jika angka turun ke baris bawah tetapi masih dalam cell yang sama, "
                "gabungkan sebagai satu value. Contoh: '0.' di line pertama dan '325' "
                "di line bawah masih bisa berarti 0.325."
            ),
        },
        {
            "risk": "page_break_split_row",
            "instruction": (
                "Jika row terpotong di akhir halaman dan lanjut di halaman berikutnya, "
                "pakai item_no/description/neighbor row untuk menentukan apakah itu masih row yang sama."
            ),
        },
        {
            "risk": "merged_cell_duplicate",
            "instruction": (
                "Jika numeric cell merged/span beberapa row, value hanya dihitung pada owner row. "
                "Continuation row harus return 0 untuk field additive numeric."
            ),
        },
        {
            "risk": "wrong_column_extraction",
            "instruction": (
                "Pastikan angka berasal dari target column, bukan kolom sebelah seperti NW/GW/package/quantity."
            ),
        },
        {
            "risk": "row_shift_previous_next",
            "instruction": (
                "Cek previous_row dan next_row. Jangan ambil value dari row sebelum/sesudah jika posisi visualnya bukan row target."
            ),
        },
        {
            "risk": "decimal_digit_confusion",
            "instruction": (
                "Periksa digit decimal dengan hati-hati. Contoh 0.325 bisa salah terbaca 0.35, "
                "3.170 bisa salah terbaca 3.110."
            ),
        },
    ]

    if field == "pl_volume":
        risks.append({
            "risk": "volume_column_confused_with_weight",
            "instruction": (
                "Untuk pl_volume, hanya gunakan kolom Volume/CBM/Measurement/M3. "
                "Jangan gunakan kolom NW atau GW."
            ),
        })

    if field in {"pl_nw", "pl_gw"}:
        risks.append({
            "risk": "nw_gw_swapped",
            "instruction": (
                "Untuk weight, cek apakah NW dan GW tertukar. GW biasanya >= NW."
            ),
        })

    return risks


def _get_declared_field_for_detail_field(field: str):
    mapping = {
        "inv_quantity": "inv_total_quantity",
        "inv_amount": "inv_total_amount",
        "pl_quantity": "pl_total_quantity",
        "pl_package_count": "pl_total_package",
        "pl_nw": "pl_total_nw",
        "pl_gw": "pl_total_gw",
        "pl_volume": "pl_total_volume",
    }
    return mapping.get(field)


def _build_field_comparison_for_recheck(row: dict, field: str, group_field_meta: dict):
    current_value = row.get(field)
    current_num = _to_float(current_value)

    meta = group_field_meta.get(field) if isinstance(group_field_meta, dict) else None

    audit_expected_candidate = None
    gap = None
    actual_sum = None
    declared_total = None

    if isinstance(meta, dict):
        gap = _to_float(meta.get("gap"))
        actual_sum = _to_float(meta.get("actual_sum"))
        declared_total = _to_float(meta.get("declared_total"))

        if current_num is not None and gap is not None:
            audit_expected_candidate = _round_recheck_candidate(current_num - gap)

    comparison = {
        "extracted_value": current_value,
        "audit_expected_candidate": audit_expected_candidate,
        "candidate_is_not_ground_truth": True,
        "candidate_reason": (
            "audit_expected_candidate dibuat dari audit total: "
            "current_value - total_gap. Ini hanya kandidat, bukan jawaban pasti."
        ),
        "total_math_context": {
            "current_group_sum": actual_sum,
            "document_total": declared_total,
            "gap": gap,
            "needed_delta_to_match_total": None if gap is None else _round_recheck_candidate(-gap),
        },
        "column_context": _get_column_context_for_field(field),
        "layout_risk_context": _build_layout_risk_context_for_field(field),
        "decision_rule": [
            "Pilih audit_expected_candidate hanya jika visual PDF mendukung kandidat tersebut.",
            "Pilih extracted_value jika extracted_value terlihat benar pada target cell.",
            "Jika target cell kosong karena merged-cell continuation, return 0.",
            "Jika angka terlihat di kolom sebelah, jangan gunakan angka itu.",
            "Jika PDF menunjukkan value lain yang bukan extracted_value atau audit_expected_candidate, return value yang benar-benar terlihat.",
        ],
    }

    if field == "inv_amount":
        qty = _to_float(row.get("inv_quantity"))
        unit_price = _to_float(row.get("inv_unit_price"))
        if qty is not None and unit_price is not None:
            comparison["formula_candidate"] = _round_recheck_candidate(qty * unit_price)
            comparison["formula_reason"] = "Kandidat dari inv_quantity * inv_unit_price."

    if field in DETAIL_RECHECK_ADDITIVE_NUM_FIELDS:
        comparison["merge_continuation_candidate"] = 0
        comparison["merge_candidate_reason"] = (
            "Jika row ini adalah continuation dari merged numeric cell, "
            "field additive numeric harus 0 agar value tidak terduplikat."
        )

    return comparison


def _build_document_audit_context(recheck_fields: list, group_plan_item: dict):
    field_meta = group_plan_item.get("field_meta", {}) if isinstance(group_plan_item, dict) else {}

    total_context = {}

    for field in recheck_fields or []:
        meta = field_meta.get(field) if isinstance(field_meta, dict) else None
        if not isinstance(meta, dict):
            continue

        total_context[field] = {
            "detail_field": field,
            "declared_total_field": meta.get("declared_field") or _get_declared_field_for_detail_field(field),
            "actual_sum_from_extraction": meta.get("actual_sum"),
            "declared_total_from_document": meta.get("declared_total"),
            "gap": meta.get("gap"),
            "issue_label": meta.get("label"),
        }

    return {
        "audit_type": "layout_aware_total_mismatch_recheck",
        "important": (
            "Recheck ini terjadi karena total mismatch. "
            "Gemini harus membandingkan extracted_value vs audit_expected_candidate "
            "dengan melihat layout visual PDF, bukan hanya matematika."
        ),
        "total_context_by_field": total_context,
    }

def _build_hard_compare_anchor_pack(row: dict, recheck_fields: list, group_field_meta: dict):
    expected_map = _build_expected_candidate_map(
        row=row,
        recheck_fields=recheck_fields,
        field_meta_map=group_field_meta or {},
    )

    return {
        "purpose": (
            "Anchor pack ini dipakai khusus untuk total mismatch recheck. "
            "Gemini harus locate row berdasarkan PO + item + sequence dulu, "
            "baru compare angka target."
        ),
        "row_locator_priority": {
            "customer_po_no": {
                "inv_customer_po_no": _compact_anchor_value(row.get("inv_customer_po_no")),
                "pl_customer_po_no": _compact_anchor_value(row.get("pl_customer_po_no")),
            },
            "item_no": {
                "inv_spart_item_no": _compact_anchor_value(row.get("inv_spart_item_no")),
                "inv_item_no": _compact_anchor_value(row.get("inv_item_no")),
                "pl_item_no": _compact_anchor_value(row.get("pl_item_no")),
            },
            "sequence": {
                "inv_seq": row.get("inv_seq"),
                "inv_sequence": row.get("inv_sequence"),
                "pl_seq": row.get("pl_seq"),
                "_invoice_group_row_index": row.get("_invoice_group_row_index"),
                "_batch_row_index": row.get("_batch_row_index"),
                "_detail_row_no": row.get("_detail_row_no"),
            },
            "description_fallback": {
                "inv_description": _compact_anchor_value(row.get("inv_description")),
                "pl_description": _compact_anchor_value(row.get("pl_description")),
            },
        },
        "expected_candidates_by_field": expected_map,
        "target_column_rules": {
            "pl_volume": "Baca hanya kolom Volume / CBM / Measurement / M3.",
            "pl_nw": "Baca hanya kolom NW / Net Weight.",
            "pl_gw": "Baca hanya kolom GW / Gross Weight.",
            "pl_package_count": "Baca hanya kolom Package / Carton / CTN.",
            "inv_amount": "Baca hanya kolom Amount.",
        },
        "negative_selection_rule": (
            "Jika batch contract mewajibkan negative, pilih primary candidate paling kuat. "
            "Jika expected_candidate paling konsisten dengan PDF/total mismatch, "
            "return confidence_label='negative'."
        ),
    }

def _build_force_one_negative_context(row: dict, recheck_fields: list, plan_item: dict, is_primary: bool):
    field_meta_map = (plan_item or {}).get("field_meta", {}) or {}

    expected_map = _build_expected_candidate_map(
        row=row,
        recheck_fields=recheck_fields,
        field_meta_map=field_meta_map,
    )

    return {
        "is_primary_candidate": bool(is_primary),
        "expected_candidates_by_field": expected_map,
        "hard_rule": (
            "Jika is_primary_candidate=true dan batch total mismatch mewajibkan negative, "
            "row ini adalah kandidat utama. Gemini WAJIB mengecek row ini paling detail. "
            "Jika semua row lain tampak positive, row primary ini tetap harus dipilih sebagai "
            "negative minimal satu field/row, kecuali row match_score TRUE."
        ),
        "layout_anchor_rule": (
            "Cari anchored line item memakai urutan ini: "
            "1) inv_customer_po_no / pl_customer_po_no, "
            "2) inv_spart_item_no / pl_item_no / item/article no, "
            "3) inv_seq / pl_seq / _invoice_group_row_index / _batch_row_index, "
            "4) description sebagai fallback. "
            "Setelah row target ditemukan, baru baca target numeric column."
        ),
        "expected_candidate_rule": (
            "expected_candidate adalah kandidat audit dari total mismatch. "
            "Jika expected_candidate paling konsisten dengan row anchor, target column, "
            "dan total mismatch, pilih expected_candidate dan set confidence_label='negative'. "
            "Jangan return semua positive pada batch yang must_return_negative_in_this_batch=true."
        ),
    }

def _is_total_issue_payload_item(item: dict) -> bool:
    if not isinstance(item, dict):
        return False

    total_issue_context = item.get("total_issue_context")
    if isinstance(total_issue_context, list) and total_issue_context:
        return True

    text = str(item.get("match_description") or "").lower()
    total_keywords = [
        "total_quantity mismatch",
        "total_amount mismatch",
        "total_package mismatch",
        "total_nw mismatch",
        "total_gw mismatch",
        "total_volume mismatch",
    ]

    return any(k in text for k in total_keywords)


def _payload_item_group_key(item: dict) -> str:
    if not isinstance(item, dict):
        return "__UNKNOWN__"

    for key in [
        "_recheck_group_key",
        "inv_invoice_no",
        "pl_invoice_no",
        "coo_invoice_no",
        "coo_no",
    ]:
        value = item.get(key)
        normalized = _preprocess_invoice_no_for_grouping(value)
        if normalized:
            return normalized

    return "__UNKNOWN__"


def _build_batch_total_issue_contract(batch: list) -> dict:
    total_items = [
        item for item in batch or []
        if _is_total_issue_payload_item(item)
    ]

    primary_items = [
        item for item in total_items
        if (
            isinstance(item.get("force_one_negative_context"), dict)
            and item["force_one_negative_context"].get("is_primary_candidate") is True
        )
    ]

    must_return_negative = bool(total_items and primary_items)

    primary_details = []
    for item in primary_items:
        primary_details.append({
            "_detail_row_no": item.get("_detail_row_no"),
            "_batch_row_index": item.get("_batch_row_index"),
            "_invoice_group_row_index": item.get("_invoice_group_row_index"),
            "recheck_fields": item.get("_recheck_fields"),
            "force_one_negative_context": item.get("force_one_negative_context"),
            "anchor_context": item.get("anchor_context"),
            "neighbor_anchor_context": item.get("neighbor_anchor_context"),
            "row_shift_risk_context": item.get("row_shift_risk_context"),
            "hard_compare_anchor_pack": item.get("hard_compare_anchor_pack"),
        })

    return {
        "total_issue_mode": bool(total_items),
        "must_return_negative_in_this_batch": must_return_negative,
        "min_negative_required": 1 if must_return_negative else 0,
        "all_positive_response_is_invalid": must_return_negative,

        "candidate_row_nos": [
            item.get("_detail_row_no") for item in total_items
        ],
        "primary_candidate_row_nos": [
            item.get("_detail_row_no") for item in primary_items
        ],
        "primary_candidate_batch_indexes": [
            item.get("_batch_row_index") for item in primary_items
        ],
        "primary_candidate_details": primary_details,

        "hard_rule": (
            "Jika must_return_negative_in_this_batch=true, "
            "Gemini WAJIB return minimal 1 row dengan confidence_label='negative'. "
            "Output semua positive/unchanged adalah INVALID."
        ),

        "row_location_rule": (
            "Untuk menentukan row yang benar, gunakan urutan anchor ini: "
            "1) inv_customer_po_no / pl_customer_po_no, "
            "2) inv_spart_item_no / pl_item_no, "
            "3) inv_seq / pl_seq, "
            "4) _invoice_group_row_index, "
            "5) _batch_row_index, "
            "6) _detail_row_no, "
            "7) previous/next row hanya sebagai pembanding."
        ),

        "comparison_rule": (
            "Jangan mulai dari mencari angka. "
            "Cari anchored line item dulu berdasarkan PO + item + sequence. "
            "Setelah target row ditemukan, baru bandingkan extracted_value, expected_candidate, "
            "dan angka visual PDF pada target column."
        ),
    }


def _batch_requires_total_negative(batch: list) -> bool:
    contract = _build_batch_total_issue_contract(batch)
    return bool(contract.get("total_issue_mode")) and int(contract.get("min_negative_required") or 0) > 0


def _repaired_row_has_allowed_change(input_item: dict, repaired_item: dict) -> bool:
    if not isinstance(input_item, dict) or not isinstance(repaired_item, dict):
        return False

    allowed_fields = _normalize_recheck_field_list(
        input_item.get("_recheck_fields") or []
    )

    for field in allowed_fields:
        if field not in repaired_item:
            continue

        old_value = input_item.get(field)
        new_value = repaired_item.get(field)

        if not _same_recheck_value(old_value, new_value, field):
            return True

    return False


def _validate_total_issue_gemini_batch_result(batch: list, repaired_batch: list, label: str = ""):
    """
    Soft validator:
    Untuk total issue batch, Gemini DIHARAPKAN return minimal 1 negative/changed
    jika visual PDF mendukung.

    Tapi kalau Gemini return semua positive/unchanged, JANGAN raise error.
    Biarkan Python safety fallback menentukan minimal 1 negative di tahap final.

    Kenapa?
    - Prompt sendiri mengizinkan semua positive jika bukti visual tidak cukup.
    - Hard guarantee sekarang ada di _force_min_one_negative_for_total_issue().
    """
    if not _batch_requires_total_negative(batch):
        return True

    if not isinstance(repaired_batch, list):
        raise Exception(f"Invalid Gemini result for total issue batch {label}: output bukan list")

    input_by_no = {}

    for item in batch or []:
        if not isinstance(item, dict):
            continue

        row_no = item.get("_detail_row_no")
        if row_no is None:
            continue

        try:
            input_by_no[int(row_no)] = item
        except Exception:
            continue

    has_negative_or_changed = False

    for repaired in repaired_batch:
        if not isinstance(repaired, dict):
            continue

        row_no = repaired.get("_detail_row_no")
        if row_no is None:
            continue

        try:
            input_item = input_by_no.get(int(row_no))
        except Exception:
            input_item = None

        confidence_label = str(
            repaired.get("confidence_label")
            or repaired.get("_gemini_recheck_decision")
            or ""
        ).strip().lower()

        changed_fields = repaired.get("changed_fields")
        if not isinstance(changed_fields, list):
            changed_fields = repaired.get("_gemini_changed_fields")

        if confidence_label == "negative":
            has_negative_or_changed = True
            break

        if isinstance(changed_fields, list) and changed_fields:
            has_negative_or_changed = True
            break

        if input_item and _repaired_row_has_allowed_change(input_item, repaired):
            has_negative_or_changed = True
            break

    if not has_negative_or_changed:
        print(
            f"[TOTAL_ISSUE_GEMINI_ZERO_CHANGE][WARN] "
            f"{label}: total_issue_mode=true tapi Gemini return semua positive/unchanged. "
            f"Accepting Gemini result; Python fallback will force min 1 negative if needed."
        )
        return False

    return True

def _compact_anchor_value(value):
    if value is None:
        return "null"

    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return "null"

    return s


def _build_line_item_anchor_context(row: dict):
    """
    Anchor untuk membedakan line item target vs previous/next row.

    Tujuan:
    - Gemini tidak boleh hanya melihat angka pl_volume.
    - Gemini harus locate row berdasarkan invoice/item/description/sequence dulu.
    - Baru baca target column di row itu.
    """
    if not isinstance(row, dict):
        return {}

    return {
        "row_identity": {
            "_detail_row_no": row.get("_detail_row_no"),
            "inv_seq": row.get("inv_seq"),
            "inv_sequence": row.get("inv_sequence"),
            "pl_seq": row.get("pl_seq"),
            "coo_seq": row.get("coo_seq"),
        },
        "invoice_anchors": {
            "inv_invoice_no": _compact_anchor_value(row.get("inv_invoice_no")),
            "pl_invoice_no": _compact_anchor_value(row.get("pl_invoice_no")),
            "coo_invoice_no": _compact_anchor_value(row.get("coo_invoice_no")),
            "coo_no": _compact_anchor_value(row.get("coo_no")),
        },
        "item_anchors": {
            "inv_item_no": _compact_anchor_value(row.get("inv_item_no")),
            "pl_item_no": _compact_anchor_value(row.get("pl_item_no")),
            "coo_item_no": _compact_anchor_value(row.get("coo_item_no")),
            "inv_customer_po_no": _compact_anchor_value(row.get("inv_customer_po_no")),
            "inv_hs_code": _compact_anchor_value(row.get("inv_hs_code")),
            "coo_hs_code": _compact_anchor_value(row.get("coo_hs_code")),
        },
        "description_anchors": {
            "inv_description": _compact_anchor_value(row.get("inv_description")),
            "pl_description": _compact_anchor_value(row.get("pl_description")),
            "coo_description": _compact_anchor_value(row.get("coo_description")),
        },
        "numeric_neighbor_anchors": {
            "inv_quantity": row.get("inv_quantity"),
            "pl_quantity": row.get("pl_quantity"),
            "pl_package_count": row.get("pl_package_count"),
            "pl_nw": row.get("pl_nw"),
            "pl_gw": row.get("pl_gw"),
            "pl_volume": row.get("pl_volume"),
        },
    }


def _build_neighbor_anchor_context(prev_row=None, row=None, next_row=None):
    return {
        "previous_anchor": _build_line_item_anchor_context(prev_row),
        "current_anchor": _build_line_item_anchor_context(row),
        "next_anchor": _build_line_item_anchor_context(next_row),
        "instruction": (
            "Gunakan current_anchor sebagai target row utama. "
            "previous_anchor dan next_anchor hanya untuk membedakan row, bukan untuk mengambil value. "
            "Jangan ambil nilai numeric dari previous/next row kecuali visual PDF menunjukkan target cell memang milik current_anchor."
        ),
    }


def _build_row_shift_risk_context(row: dict, prev_row=None, next_row=None, recheck_fields=None):
    """
    Context khusus untuk kasus value dari row index 2 kebaca sebagai index 1.
    """
    recheck_fields = recheck_fields or []

    current_anchor = _build_line_item_anchor_context(row)
    prev_anchor = _build_line_item_anchor_context(prev_row)
    next_anchor = _build_line_item_anchor_context(next_row)

    suspicious = []

    for field in recheck_fields:
        cur_val = row.get(field) if isinstance(row, dict) else None
        prev_val = prev_row.get(field) if isinstance(prev_row, dict) else None
        next_val = next_row.get(field) if isinstance(next_row, dict) else None

        if next_val is not None and _same_recheck_value(cur_val, next_val, field):
            suspicious.append({
                "field": field,
                "risk": "current_value_equals_next_row_value",
                "message": (
                    "Nilai current row sama dengan next row. "
                    "Pastikan value ini benar-benar berada di target row, bukan terbawa dari row berikutnya."
                ),
                "current_value": cur_val,
                "next_value": next_val,
            })

        if prev_val is not None and _same_recheck_value(cur_val, prev_val, field):
            suspicious.append({
                "field": field,
                "risk": "current_value_equals_previous_row_value",
                "message": (
                    "Nilai current row sama dengan previous row. "
                    "Pastikan ini bukan duplicate akibat merge/row shift."
                ),
                "current_value": cur_val,
                "previous_value": prev_val,
            })

    return {
        "risk_type": "row_shift_or_neighbor_value_leak",
        "target_row_rule": (
            "Pertama cari current_anchor di PDF. Setelah row target ditemukan, baru baca target column. "
            "Jangan cari angka dulu lalu mencocokkan ke row."
        ),
        "current_anchor": current_anchor,
        "previous_anchor": prev_anchor,
        "next_anchor": next_anchor,
        "suspicious_neighbor_values": suspicious,
    }

def _build_recheck_payload_item(
    row: dict,
    recheck_fields: list,
    group_plan_item: dict = None,
    prev_row=None,
    next_row=None,
    force_primary_candidate: bool = False,
):
    group_plan_item = group_plan_item or {}
    group_field_meta = group_plan_item.get("field_meta", {}) or {}

    field_comparison = {}
    candidate_values = {}

    for field in recheck_fields:
        field_comparison[field] = _build_field_comparison_for_recheck(
            row=row,
            field=field,
            group_field_meta=group_field_meta,
        )

        # Tetap kirim candidate_values lama agar prompt bisa pilih opsi eksplisit.
        candidate_values[field] = _build_candidate_values_for_field(
            row=row,
            field=field,
            group_field_meta=group_field_meta,
        )

    item = {
        "_detail_row_no": row.get("_detail_row_no"),
        "_recheck_fields": list(recheck_fields),
        "_recheck_group_key": (
            row.get("_recheck_group_key")
            or group_plan_item.get("group_key")
            or _get_detail_total_group_key(row, 0)
        ),

        "match_description": row.get("match_description", "null"),
        "total_issue_context": group_plan_item.get("issues", []),
        "batch_total_issue_hint": {
            "total_issue_mode": bool(group_plan_item.get("issues")),
            "primary_candidate": bool(force_primary_candidate),
            "gemini_must_return_min_one_negative_in_group": bool(force_primary_candidate),
            "rule": (
                "Jika primary_candidate=false, total issue hanya audit context. "
                "Jangan paksa negative. Semua row boleh positive jika angka visual PDF cocok."
            ),
        },
        "document_audit_context": _build_document_audit_context(
            recheck_fields=recheck_fields,
            group_plan_item=group_plan_item,
        ),

        # Context lokasi row
        "row_context": _build_row_context_for_recheck(
            row=row,
            prev_row=prev_row,
            next_row=next_row,
        ),

        # Expected vs extracted + alasan layout
        "field_comparison": field_comparison,

        # Opsi eksplisit untuk Gemini
        "candidate_values": candidate_values,

        "force_one_negative_context": _build_force_one_negative_context(
            row=row,
            recheck_fields=recheck_fields,
            plan_item=group_plan_item,
            is_primary=force_primary_candidate,
        ),

        "anchor_context": _build_line_item_anchor_context(row),

        # NEW: anchor pembanding untuk cegah salah ambil value dari index/row sebelah
        "neighbor_anchor_context": _build_neighbor_anchor_context(
            prev_row=prev_row,
            row=row,
            next_row=next_row,
        ),

        # NEW: risk context khusus row shift / salah index
        "row_shift_risk_context": _build_row_shift_risk_context(
            row=row,
            prev_row=prev_row,
            next_row=next_row,
            recheck_fields=recheck_fields,
        ),

        "hard_compare_anchor_pack": _build_hard_compare_anchor_pack(
            row=row,
            recheck_fields=recheck_fields,
            group_field_meta=group_field_meta,
        ),
    }

    # Current values untuk semua field recheck schema
    for key in DETAIL_RECHECK_FIELDS:
        value = row.get(key)

        if key in DETAIL_RECHECK_NUM_FIELDS:
            item[key] = 0 if _is_null(value) else value
        else:
            item[key] = "null" if value is None else value
    if force_primary_candidate:
        row["_force_total_issue_candidate"] = True

    return item

# =========================================================
# FORCE-ONE-CANDIDATE CONTEXT FOR GEMINI RECHECK
# =========================================================

DETAIL_RECHECK_ADDITIVE_NUM_FIELDS = {
    "inv_quantity",
    "inv_amount",
    "pl_quantity",
    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",
}


def _is_false_total_issue_row(row: dict) -> bool:
    """
    TRUE / CHILD PO tidak boleh dipaksa negative.
    Hanya FALSE + total issue yang boleh jadi primary candidate.
    """
    if not isinstance(row, dict):
        return False

    match_score = str(row.get("match_score", "")).strip().upper()
    if match_score in ("TRUE", "CHILD PO"): # <-- UBAH DISINI
        return False

    try:
        if _row_has_total_issue_only(row):
            return True
    except Exception:
        pass

    desc = str(row.get("match_description") or "").lower()
    total_keywords = [
        "total_quantity mismatch", "total_amount mismatch",
        "total_package mismatch", "total_nw mismatch",
        "total_gw mismatch", "total_volume mismatch",
    ]

    return any(k in desc for k in total_keywords)


def _expected_candidate_from_total_gap(row: dict, field: str, field_meta: dict):
    """
    expected_candidate = current_value - gap

    Contoh:
    actual_sum = 2.127
    doc_total  = 2.152
    gap        = -0.025
    current    = 0.3

    expected = 0.3 - (-0.025) = 0.325
    """
    if not isinstance(row, dict):
        return None

    if not isinstance(field_meta, dict):
        return None

    current = _to_float(row.get(field))
    gap = _to_float(field_meta.get("gap"))

    if current is None or gap is None:
        return None

    expected = current - gap

    if field in DETAIL_RECHECK_ADDITIVE_NUM_FIELDS:
        if expected < -float(TOTAL_CONTRIBUTION_EPS):
            return None
        expected = max(0, expected)

    return _round_recheck_candidate(expected)


def _build_expected_candidate_map(row: dict, recheck_fields: list, field_meta_map: dict):
    """
    Build expected candidate per field untuk dikirim ke Gemini.
    """
    result = {}

    for field in recheck_fields or []:
        meta = field_meta_map.get(field) if isinstance(field_meta_map, dict) else None
        if not isinstance(meta, dict):
            continue

        expected = _expected_candidate_from_total_gap(row, field, meta)
        if expected is None:
            continue

        extracted = row.get(field)

        if _same_recheck_value(extracted, expected, field):
            continue

        result[field] = {
            "extracted_value": extracted,
            "expected_candidate": expected,
            "actual_sum": meta.get("actual_sum"),
            "declared_total": meta.get("declared_total"),
            "gap": meta.get("gap"),
            "needed_delta": None if _to_float(meta.get("gap")) is None else _round_recheck_candidate(-_to_float(meta.get("gap"))),
            "reason": (
                "expected_candidate berasal dari total mismatch: "
                "expected_candidate = extracted_value - gap."
            ),
        }

    return result


def _score_primary_force_candidate(row: dict, recheck_fields: list, field_meta_map: dict) -> float:
    """
    Pilih row paling kuat untuk dipaksa dicek detail oleh Gemini.
    Semakin banyak field total mismatch yang punya expected_candidate pada row yang sama,
    semakin tinggi skornya.

    Contoh kuat:
    pl_nw     130.8 -> 138.98
    pl_gw     151.2 -> 161.08
    pl_volume 0.3 -> 0.325
    """
    if not _is_false_total_issue_row(row):
        return -1.0

    expected_map = _build_expected_candidate_map(
        row=row,
        recheck_fields=recheck_fields,
        field_meta_map=field_meta_map,
    )

    if not expected_map:
        return 0.0

    score = 0.0
    field_count = len(expected_map)

    # Cross-field candidate jauh lebih kuat.
    if field_count >= 2:
        score += 200.0 + field_count * 50.0
    else:
        score += 50.0

    for field, info in expected_map.items():
        extracted = _to_float(info.get("extracted_value"))
        expected = _to_float(info.get("expected_candidate"))
        gap = _to_float(info.get("gap"))

        if extracted is None or expected is None:
            continue

        # Correction kecil relatif terhadap value lebih plausible.
        if gap is not None:
            correction_share = abs(gap) / max(abs(extracted), float(TOTAL_CONTRIBUTION_EPS))
            if correction_share <= 0.35:
                score += 20.0
            if correction_share <= 0.10:
                score += 10.0

        # Field packing numeric utama.
        if field in {"pl_nw", "pl_gw", "pl_volume"}:
            score += 15.0

        # Sanity: GW >= NW jika dua-duanya ada setelah expected.
        if field == "pl_gw":
            nw_expected = expected_map.get("pl_nw", {}).get("expected_candidate")
            nw = _to_float(nw_expected if nw_expected is not None else row.get("pl_nw"))
            if nw is not None and expected >= nw:
                score += 20.0

    return score


def _pick_primary_force_candidate_row_no(group_rows: list, recheck_fields: list, plan_item: dict):
    """
    Pilih 1 primary candidate per invoice group.
    Hanya row ini yang boleh dipaksa oleh prompt jika semua row tampak positive.
    """
    field_meta_map = (plan_item or {}).get("field_meta", {}) or {}

    best_row_no = None
    best_score = -1.0

    for row in group_rows or []:
        if not isinstance(row, dict):
            continue

        score = _score_primary_force_candidate(
            row=row,
            recheck_fields=recheck_fields,
            field_meta_map=field_meta_map,
        )

        if score > best_score:
            best_score = score
            best_row_no = _safe_row_no_int(row)

    return best_row_no


def _build_detail_line_recheck_rows_payload(rows: list):
    """
    Candidate-based recheck payload.

    Perubahan penting:
    1. Kalau ada total mismatch dalam invoice group,
       SEMUA row dalam invoice group tersebut ikut recheck.
    2. Kalau lebih dari satu total mismatch,
       _recheck_fields adalah union field yang bermasalah.
    3. Setiap field dikasih candidate_values:
       - current_extracted
       - gap_adjust_candidate
       - formula_candidate jika applicable
       - merge_continuation_zero jika applicable
    """
    payload = []

    if not isinstance(rows, list):
        return payload

    total_group_plan = _build_recheck_total_group_plan(rows)
    grouped_rows = _group_rows_by_invoice_no(rows)

    included_row_nos = set()

    # =========================================================
    # PASS 1:
    # Total mismatch group-level.
    # Semua row dalam affected invoice group ikut recheck.
    # =========================================================
    for invoice_group, group_rows in grouped_rows.items():
        plan_item = total_group_plan.get(invoice_group)

        if not plan_item:
            continue

        recheck_fields = _normalize_recheck_field_list(
            list(plan_item.get("fields", []))
        )

        if not recheck_fields:
            continue

        # NEW:
        # Pilih 1 row kandidat terkuat per invoice group.
        # Hanya row ini yang boleh dipaksa Gemini jika semua row terlihat positive.
        primary_force_row_no = _pick_primary_force_candidate_row_no(
            group_rows=group_rows,
            recheck_fields=recheck_fields,
            plan_item=plan_item,
        )

        for idx, row in enumerate(group_rows):
            if not isinstance(row, dict):
                continue

            row_no = _safe_row_no_int(row)
            if row_no is None:
                continue

            prev_row = group_rows[idx - 1] if idx > 0 else None
            next_row = group_rows[idx + 1] if idx + 1 < len(group_rows) else None

            # simpan internal agar apply-result tahu field mana yang boleh dioverwrite
            row["_recheck_fields"] = list(recheck_fields)
            row["_recheck_original_values"] = {
                field: row.get(field) for field in recheck_fields
            }

            # NEW: simpan context total untuk acceptance gate
            row["_recheck_group_key"] = invoice_group
            row["_recheck_field_meta"] = {
                field: (plan_item.get("field_meta", {}) or {}).get(field)
                for field in recheck_fields
            }
            payload.append(
                _build_recheck_payload_item(
                    row=row,
                    recheck_fields=recheck_fields,
                    group_plan_item=plan_item,
                    prev_row=prev_row,
                    next_row=next_row,
                    force_primary_candidate=(row_no == primary_force_row_no),
                )
            )

            included_row_nos.add(row_no)

    # =========================================================
    # PASS 2:
    # Preserve existing behavior untuk non-total failed row.
    # Ini supaya error selain total tetap bisa direcheck seperti flow lama.
    # =========================================================
    for row in rows:
        if not isinstance(row, dict):
            continue

        row_no = _safe_row_no_int(row)
        if row_no is not None and row_no in included_row_nos:
            continue

        if row.get("match_score") != "false":
            continue

        recheck_fields = _infer_recheck_fields_from_match_description(
            row.get("match_description", "null")
        )
        recheck_fields = _normalize_recheck_field_list(recheck_fields)

        if not recheck_fields:
            continue

        row["_recheck_fields"] = list(recheck_fields)
        row["_recheck_original_values"] = {
            field: row.get(field) for field in recheck_fields
        }

        row["_recheck_group_key"] = _get_detail_total_group_key(row, 0)
        row["_recheck_field_meta"] = {}

        payload.append(
            _build_recheck_payload_item(
                row=row,
                recheck_fields=recheck_fields,
                group_plan_item={},
                prev_row=None,
                next_row=None,
            )
        )

        if row_no is not None:
            included_row_nos.add(row_no)

    return payload

def _build_detail_line_recheck_schema():
    schema = {
        "_detail_row_no": "number",
        "_recheck_fields": ["string"],
    }
    schema.update(DETAIL_RECHECK_SCHEMA)
    return schema

def _build_vendor_reference_block_for_recheck(
    vendor_id: str = "default",
    vendor_prompt_text: str = "",
) -> str:
    vendor_id = normalize_vendor_id(vendor_id)
    text = str(vendor_prompt_text or "").strip()

    if not text:
        return ""

    max_chars = int(os.getenv(
        "DETAIL_RECHECK_VENDOR_REFERENCE_MAX_CHARS",
        "6000"
    ))

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated for recheck reference]"

    return f"""
VENDOR REFERENCE ONLY:
Vendor ID: {vendor_id}

Gunakan reference vendor ini hanya untuk memahami layout dokumen:
- posisi kolom
- alias nama field
- cara baca line item
- pola invoice / packing list / COO
- unit, quantity, amount, NW, GW, volume, package

REFERENCE:
{text}

BATASAN:
- PDF visual tetap source of truth.
- Vendor reference tidak boleh override angka yang terlihat jelas di PDF.
- expected_candidate / gap_adjust_candidate hanya kandidat audit.
- Jangan set confidence_label="negative" hanya karena vendor rule.
- Untuk total mismatch, ikuti BATCH TOTAL ISSUE CONTRACT.
- Jika BATCH TOTAL ISSUE CONTRACT must_return_negative_in_this_batch=true,
  maka minimal satu primary candidate tetap wajib confidence_label="negative".
""".strip()

def _build_detail_line_recheck_prompt(
    rows_payload: list,
    strict_total_retry: bool = False,
    vendor_id: str = "default",
    vendor_prompt_text: str = "",
    zero_negative_retry_count: int = 0,
) -> str:
    schema = {
        "_detail_row_no": "number",
        "_recheck_fields": ["string"],

        "visual_reason": "string",
        "confidence_label": "positive|negative",
        "changed_fields": ["string"],

        **DETAIL_RECHECK_SCHEMA,
    }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    rows_json = json.dumps(rows_payload, ensure_ascii=False, indent=2)

    batch_contract = _build_batch_total_issue_contract(rows_payload)
    batch_contract_json = json.dumps(batch_contract, ensure_ascii=False, indent=2)

    vendor_reference_block = _build_vendor_reference_block_for_recheck(
        vendor_id=vendor_id,
        vendor_prompt_text=vendor_prompt_text,
    )

    strict_text = ""
    if strict_total_retry:
        strict_text = """
STRICT RETRY MODE - ZERO NEGATIVE RESPONSE DITOLAK:
Response sebelumnya ditolak karena batch total mismatch return semua positive/unchanged.

Pada retry ini:
- Jika BATCH TOTAL ISSUE CONTRACT memiliki must_return_negative_in_this_batch=true,
  maka output semua positive/unchanged adalah INVALID.
- Pilih minimal 1 row dari primary_candidate_row_nos.
- Set confidence_label="negative" untuk row tersebut.
- Jangan pilih row match_score TRUE.
- Jangan pilih row non-primary jika primary candidate ada.
- Jika value numeric perlu dikoreksi, return corrected value pada field terkait.
- Jika value numeric tidak diubah, tetap boleh set confidence_label="negative"
  dengan visual_reason yang menjelaskan row tersebut adalah culprit paling kuat.
"""

    zero_negative_retry_text = ""
    if zero_negative_retry_count > 0:
        zero_negative_retry_text = f"""
ZERO NEGATIVE RETRY ATTEMPT #{zero_negative_retry_count}:
Anda sebelumnya masih return semua positive/unchanged untuk batch total mismatch.

ATURAN WAJIB:
- Untuk batch dengan must_return_negative_in_this_batch=true,
  Anda HARUS return minimal 1 row confidence_label="negative".
- Jangan gunakan alasan "visual tidak cukup" untuk membuat semua row positive.
- Jika ragu, pilih primary candidate paling kuat berdasarkan:
  1) inv_customer_po_no / pl_customer_po_no
  2) inv_spart_item_no / pl_item_no
  3) inv_seq / pl_seq
  4) _invoice_group_row_index
  5) _batch_row_index
  6) expected_candidate
  7) row_context previous/current/next

CARA MEMILIH:
1. Locate row target pakai PO + item + sequence.
2. Setelah row target ditemukan, baca target numeric column.
3. Bandingkan extracted_value vs expected_candidate vs angka visual PDF.
4. Jika expected_candidate paling konsisten dengan visual PDF atau total mismatch,
   return expected_candidate dan confidence_label="negative".
5. Jika angka visual sulit dibaca tetapi primary candidate adalah kandidat paling kuat,
   tetap set confidence_label="negative" dan isi visual_reason.
"""

    return f"""
ROLE:
Anda adalah auditor detail line item berbasis visual PDF.

SOURCE OF TRUTH:
- PDF visual pada request ini adalah sumber kebenaran utama.
- ROWS adalah hasil ekstraksi sebelumnya.
- Tugas Anda adalah memverifikasi ulang nilai pada PDF, bukan hanya copy ROWS.

{vendor_reference_block}

BATCH TOTAL ISSUE CONTRACT:
{batch_contract_json}

{strict_text}

{zero_negative_retry_text}

TUGAS:
Untuk setiap row dalam ROWS:
1. Temukan line item yang benar di PDF menggunakan anchor.
2. Jangan mulai dari mencari angka numeric.
3. Setelah line item target ditemukan, baru baca target numeric field.
4. Bandingkan:
   - extracted_value dari ROWS
   - expected_candidate dari field_comparison / force_one_negative_context / hard_compare_anchor_pack
   - angka visual di PDF pada target row dan target column
5. Tulis visual_reason sebelum menentukan confidence_label.

STRICT LINE ITEM ANCHOR RULE:
- Untuk setiap row, cari line item di PDF menggunakan anchor_context dan hard_compare_anchor_pack.
- Prioritas anchor pencarian row:
  1) inv_customer_po_no / pl_customer_po_no
  2) inv_spart_item_no / pl_item_no / item/article no
  3) inv_seq / pl_seq
  4) _invoice_group_row_index
  5) _batch_row_index
  6) _detail_row_no
  7) description / HS code sebagai fallback
  8) previous/next row hanya sebagai pembanding
- Jangan verifikasi numeric field sebelum menemukan line item yang tepat.
- Jangan mengambil angka dari previous row atau next row untuk current row.

ATURAN TOTAL MISMATCH - TIDAK BOLEH SEMUA POSITIVE:
- Jika BATCH TOTAL ISSUE CONTRACT total_issue_mode=true, berarti ada mismatch antara sum detail dan total dokumen.
- Jika must_return_negative_in_this_batch=true, Gemini WAJIB return minimal 1 row negative.
- Output semua positive/unchanged pada batch ini adalah INVALID.
- Jangan gunakan alasan "visual tidak cukup" untuk mengembalikan semua positive.
- Jika ragu, pilih primary candidate paling kuat berdasarkan PO + item + sequence + expected_candidate.
- Jangan pilih row non-primary jika ada primary candidate.
- Jangan pernah mengubah row dengan match_score TRUE.

CARA COMPARE TOTAL FIELD:
- Jika total_volume mismatch, fokus ke pl_volume.
- Jika total_gw mismatch, fokus ke pl_gw.
- Jika total_nw mismatch, fokus ke pl_nw.
- Jika total_package mismatch, fokus ke pl_package_count.
- Jika total_amount mismatch invoice, fokus ke inv_amount.
- Jangan mengoreksi field lain di luar "_recheck_fields".

ATURAN KHUSUS KOLOM:
- pl_volume: baca hanya kolom Volume / CBM / Measurement / M3.
- pl_nw: baca hanya kolom NW / Net Weight.
- pl_gw: baca hanya kolom GW / Gross Weight.
- pl_package_count: baca hanya kolom Package / Carton / CTN.
- inv_amount: baca hanya kolom Amount.

ATURAN ROW SHIFT:
- Jika extracted_value terlihat milik row bawah / index berikutnya, jangan pakai untuk current row.
- Gunakan neighbor_anchor_context dan row_shift_risk_context.
- previous_row dan next_row hanya pembanding, bukan sumber value current row.

ATURAN OUTPUT:
1. Output HANYA JSON ARRAY valid, tanpa teks lain.
2. Jumlah row output HARUS sama persis dengan jumlah row input.
3. Urutan row output HARUS sama persis dengan input.
4. WAJIB pertahankan _detail_row_no.
5. WAJIB pertahankan _recheck_fields persis seperti input.
6. WAJIB isi visual_reason.
7. WAJIB isi confidence_label dengan "positive" atau "negative".
8. Jika must_return_negative_in_this_batch=true, minimal satu row primary harus confidence_label="negative".
9. Jangan return candidate_values.
10. Jangan return row_context.
11. Jangan return field_comparison.
12. Jangan return document_audit_context.
13. Jangan return total_issue_context.
14. Jangan return force_one_negative_context.
15. Jangan return anchor_context.
16. Jangan return neighbor_anchor_context.
17. Jangan return row_shift_risk_context.
18. Jangan return hard_compare_anchor_pack.
19. Jangan return field header.
20. Jangan return field po_*.
21. Untuk field di luar "_recheck_fields", copy nilai input apa adanya.
22. Jika value memang tidak ada di dokumen:
    - string -> "null"
    - number -> 0

OUTPUT SCHEMA:
{schema_json}

ROWS YANG HARUS DICEK ULANG:
{rows_json}
"""

SHIMANO_HS_CODE_EXTRACTION_BATCH_SIZE = int(
    os.getenv("SHIMANO_HS_CODE_EXTRACTION_BATCH_SIZE", "10")
)

SHIMANO_HS_CODE_CONTEXT_FIELDS = [
    "_expected_index",
    "_detail_row_no",

    "inv_invoice_no",
    "inv_item_no",
    "inv_vendor_article_no",
    "inv_customer_po_no",
    "inv_description",

    "pl_invoice_no",
    "pl_item_no",
    "pl_vendor_article_no",
    "pl_customer_po_no",
    "pl_description",

    "inv_hs_code",
]


def _normalize_inv_hs_code(value):
    if _is_null(value):
        return "null"

    s = str(value or "").strip()
    if not s or s.lower() == "null":
        return "null"

    s = re.sub(r"(?i)^\s*HS\s*#?\s*:?\s*", "", s).strip()
    s = s.strip(".,;:()[]{} ")

    # Preserve dotted HS format, contoh: 8507.60 / 8507.60.90
    m = re.search(r"\b(\d{4}(?:\.\d{1,4}){1,4}|\d{6,12})\b", s)
    if not m:
        return "null"

    return m.group(1).strip(".,;: ")


def _build_shimano_hs_code_rows_payload(rows: list):
    payload = []

    for idx, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue

        item = {}

        for key in SHIMANO_HS_CODE_CONTEXT_FIELDS:
            if key in row:
                item[key] = row.get(key)

        if "_detail_row_no" not in item or _is_null(item.get("_detail_row_no")):
            item["_detail_row_no"] = _safe_row_no_int(row) or idx

        payload.append(item)

    return payload


def _build_shimano_hs_code_prompt(rows_payload: list) -> str:
    rows_json = json.dumps(rows_payload, ensure_ascii=False, indent=2)

    return f"""
ROLE:
Anda adalah AI extractor khusus untuk vendor shimano_inc.

SOURCE OF TRUTH:
- PDF visual pada request ini adalah sumber kebenaran utama.
- ROWS adalah hasil ekstraksi detail sebelumnya dan harus dipakai sebagai anchor row.

TUGAS:
Untuk setiap row, ekstrak field tambahan:
inv_hs_code

ATURAN KHUSUS inv_hs_code:
- Cari nilai setelah kata "HS#" di dalam blok deskripsi invoice / description block.
- Contoh:
  "HS# 8507.60" => inv_hs_code = "8507.60"
- Jika tertulis "HS#8507.60", hasil tetap "8507.60".
- Jika value HS# wrap ke line bawah tetapi masih dalam description block row yang sama, gabungkan.
- Ambil hanya kode HS, tanpa kata "HS#", tanpa koma/titik/semicolon di akhir.
- Pertahankan format titik jika terlihat di PDF, misalnya "8507.60" atau "8507.60.90".
- Jangan ambil coo_hs_code.
- Jangan ambil HS code dari header, COO, summary, footer, atau row lain.
- Jangan mengarang.
- Jika "HS#" tidak ditemukan untuk row tersebut, isi "null".

ATURAN OUTPUT:
1. Output HANYA JSON ARRAY valid.
2. Jumlah row output HARUS sama persis dengan jumlah ROWS input.
3. Urutan row output HARUS sama persis dengan input.
4. WAJIB pertahankan "_detail_row_no".
5. Output hanya field:
   - _detail_row_no
   - inv_hs_code

OUTPUT SCHEMA:
[
  {{
    "_detail_row_no": "number",
    "inv_hs_code": "string"
  }}
]

ROWS:
{rows_json}
""".strip()


def _call_gemini_shimano_hs_code_once(file_uri: str, rows: list, vendor_id: str = "default"):
    if not _is_shimano_inc_vendor(vendor_id):
        return []

    rows_payload = _build_shimano_hs_code_rows_payload(rows)
    if not rows_payload:
        return []

    try:
        configured_batch_size = int(SHIMANO_HS_CODE_EXTRACTION_BATCH_SIZE)
    except Exception:
        configured_batch_size = 10

    batch_size = max(1, min(configured_batch_size, 10))
    extracted_rows = []

    def _call_hs_batch(batch: list, label: str):
        result = _call_gemini_json_uri(
            file_uri,
            _build_shimano_hs_code_prompt(batch),
            expect_array=True,
            retries=3,
            vendor_id=vendor_id # Pass vendor_id down!
        )
        return result

    for start in range(0, len(rows_payload), batch_size):
        batch = rows_payload[start:start + batch_size]

        try:
            extracted_rows.extend(
                _call_hs_batch(batch, label=f"batch_start={start + 1}")
            )
            continue

        except Exception as batch_error:
            print(
                f"[SHIMANO_HS_CODE_BATCH_WARN] "
                f"start={start + 1} size={len(batch)} "
                f"error={batch_error}; fallback single-row"
            )

        for item in batch:
            row_no = item.get("_detail_row_no") if isinstance(item, dict) else None

            try:
                extracted_rows.extend(
                    _call_hs_batch([item], label=f"row_no={row_no}")
                )
            except Exception as single_error:
                print(
                    f"[SHIMANO_HS_CODE_ROW_SKIP] "
                    f"row_no={row_no} error={single_error}"
                )

    return extracted_rows


def _apply_shimano_hs_code_result(rows: list, hs_rows: list):
    hs_by_row_no = {}

    for item in hs_rows or []:
        if not isinstance(item, dict):
            continue

        row_no = item.get("_detail_row_no")
        if row_no is None:
            continue

        try:
            hs_by_row_no[int(row_no)] = _normalize_inv_hs_code(
                item.get("inv_hs_code")
            )
        except Exception:
            continue

    for idx, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue

        row_no = _safe_row_no_int(row) or idx

        if row_no in hs_by_row_no:
            row["inv_hs_code"] = hs_by_row_no[row_no]
        elif "inv_hs_code" not in row or _is_null(row.get("inv_hs_code")):
            row["inv_hs_code"] = "null"
        else:
            row["inv_hs_code"] = _normalize_inv_hs_code(row.get("inv_hs_code"))

    return rows


def _run_shimano_hs_code_pass(file_uri: str, rows: list, vendor_id: str = "default"):
    if not _is_shimano_inc_vendor(vendor_id):
        return rows

    try:
        hs_rows = _call_gemini_shimano_hs_code_once(
            file_uri=file_uri,
            rows=rows,
            vendor_id=vendor_id,
        )

        rows = _apply_shimano_hs_code_result(rows, hs_rows)

        print(
            f"[SHIMANO_HS_CODE_PASS] "
            f"rows={len(rows or [])} extracted={len(hs_rows or [])}"
        )

    except Exception as e:
        # Jangan gagalkan OCR utama hanya karena pass tambahan gagal.
        print(f"[SHIMANO_HS_CODE_PASS][WARN] skipped: {e}")

    return rows

def _run_detail_precheck_pass(rows: list, header_obj: dict, vendor_id: str = "default"):
    _ensure_all_detail_keys(rows)

    _apply_header_to_rows(rows, header_obj if isinstance(header_obj, dict) else {}, vendor_id=vendor_id)
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
    _postprocess_coo_po_only_rows_from_invoice(rows, vendor_id=vendor_id)
    _postprocess_coo_no_and_seq(rows)

    _postprocess_bl_description(rows, vendor_id=vendor_id)
    _postprocess_bl_seller_name_similarity(rows)

    _postprocess_bl_coo_zero_to_null(rows)

    if normalize_vendor_id(vendor_id) != "liow_ko":
        _postprocess_coo_numeric_fields_from_pl(rows)
    else:
        print("[COO_NUMERIC_FROM_PL][PRECHECK] skipped for vendor liow_ko")
        
    _validate_invoice_rows(rows)
    _validate_packing_rows(rows, vendor_id=vendor_id)
    _validate_invoice_vs_packing_extra(rows, vendor_id=vendor_id)
    _validate_bl_rows(rows)
    _validate_coo_rows(rows)

    _finalize_match_fields(rows)
    return rows

def _build_detail_recheck_batches(rows_payload: list, normal_batch_size: int):
    total_groups = {}
    normal_items = []

    for item in rows_payload or []:
        if not isinstance(item, dict):
            continue

        if _is_total_issue_payload_item(item):
            group_key = _payload_item_group_key(item)
            total_groups.setdefault(group_key, []).append(item)
        else:
            normal_items.append(item)

    batches = []
    
    # Batas aman maksimum row dalam 1 prompt untuk Total Issue
    MAX_TOTAL_BATCH_SIZE = 35

    # Total issue batch: per invoice group dengan batasan chunking
    for _, group_items in total_groups.items():
        if len(group_items) > MAX_TOTAL_BATCH_SIZE:
            for i in range(0, len(group_items), MAX_TOTAL_BATCH_SIZE):
                batches.append(group_items[i:i + MAX_TOTAL_BATCH_SIZE])
        else:
            batches.append(group_items)

    # Non-total batch: tetap pakai chunk biasa
    for i in range(0, len(normal_items), normal_batch_size):
        batches.append(normal_items[i:i + normal_batch_size])

    return batches

def _repair_zero_negative_total_issue_response(batch: list, repaired_batch: list, label: str = ""):
    """
    Last-resort repair:
    Dipakai kalau Gemini sudah di-retry berkali-kali tapi tetap return semua positive.

    Tidak mengubah numeric value.
    Hanya set confidence_label='negative' pada primary candidate paling kuat
    supaya output final tidak positive semua.
    """
    if not _batch_requires_total_negative(batch):
        return repaired_batch

    if not isinstance(batch, list) or not isinstance(repaired_batch, list):
        return repaired_batch

    primary_row_no = None

    for item in batch:
        if not isinstance(item, dict):
            continue

        force_ctx = item.get("force_one_negative_context")
        if isinstance(force_ctx, dict) and force_ctx.get("is_primary_candidate") is True:
            primary_row_no = item.get("_detail_row_no")
            break

    if primary_row_no is None:
        for item in batch:
            if _is_total_issue_payload_item(item):
                primary_row_no = item.get("_detail_row_no")
                break

    if primary_row_no is None:
        return repaired_batch

    repaired_out = []

    for repaired in repaired_batch:
        if not isinstance(repaired, dict):
            repaired_out.append(repaired)
            continue

        row_no = repaired.get("_detail_row_no")

        if str(row_no) == str(primary_row_no):
            repaired = dict(repaired)
            repaired["confidence_label"] = "negative"

            reason = str(repaired.get("visual_reason") or "").strip()
            repaired["visual_reason"] = (
                (reason + " | ") if reason else ""
            ) + (
                "Forced by total mismatch recheck contract after repeated Gemini zero-negative retries. "
                "Selected primary candidate based on PO/item/sequence/expected_candidate anchors."
            )

            changed_fields = repaired.get("changed_fields")
            if not isinstance(changed_fields, list):
                repaired["changed_fields"] = []

            print(
                f"[DETAIL_RECHECK_ZERO_NEGATIVE_REPAIR] "
                f"{label} row_no={primary_row_no} "
                f"reason=gemini_retried_but_returned_all_positive"
            )

        repaired_out.append(repaired)

    return repaired_out

def _call_gemini_detail_line_recheck_once(
    file_uri: str, 
    rows: list, 
    vendor_id: str = "default", 
    vendor_prompt_text: str = "",
    total_row: int = 0,
    index_items: list = None,
    local_pdf_path: str = None,
    run_prefix: str = None
):
    rows_payload = _build_detail_line_recheck_rows_payload(rows)
    if not rows_payload:
        return []

    repaired_rows = []
    try:
        configured_batch_size = int(DETAIL_GEMINI_RECHECK_BATCH_SIZE)
    except Exception:
        configured_batch_size = 1

    batch_size = max(1, min(configured_batch_size, 5))

    def _call_recheck_batch(batch: list, label: str, strict_total_retry: bool = False, uri_override: str = file_uri):
        for batch_idx, item in enumerate(batch or []):
            if not isinstance(item, dict):
                continue
            item["_batch_row_index"] = batch_idx + 1
            pack = item.get("hard_compare_anchor_pack")
            if isinstance(pack, dict):
                row_locator = pack.get("row_locator_priority")
                if isinstance(row_locator, dict):
                    sequence = row_locator.get("sequence")
                    if isinstance(sequence, dict):
                        sequence["_batch_row_index"] = batch_idx + 1

        max_attempts = max(1, int(DETAIL_TOTAL_RECHECK_MAX_ZERO_NEGATIVE_RETRIES))
        repaired_batch = None

        for attempt in range(1, max_attempts + 1):
            zero_retry_count = max(0, attempt - 1)
            try:
                repaired_batch = _call_gemini_json_uri(
                    uri_override, # <--- MENGGUNAKAN URI OVERRIDE SLICED PDF
                    _build_detail_line_recheck_prompt(
                        batch,
                        strict_total_retry=(strict_total_retry or attempt > 1),
                        vendor_id=vendor_id,
                        vendor_prompt_text=vendor_prompt_text,
                        zero_negative_retry_count=zero_retry_count,
                    ),
                    expect_array=True,
                    retries=3,
                    vendor_id=vendor_id
                )
                
                _validate_total_issue_gemini_batch_result(batch, repaired_batch, label=label)
                return repaired_batch
            except Exception as e:
                print(f"[RECHECK_BATCH_RETRY_WARN] Attempt {attempt} gagal: {e}")
                if attempt == max_attempts:
                    if DETAIL_TOTAL_RECHECK_REPAIR_AFTER_RETRY and repaired_batch is not None:
                        return _repair_zero_negative_total_issue_response(batch, repaired_batch, label=label)
                    raise e
        return []

    batches = _build_detail_recheck_batches(rows_payload, normal_batch_size=batch_size)
    total_pdf_pages = _count_pdf_pages(local_pdf_path) if local_pdf_path else 0

    for batch_index, batch in enumerate(batches, start=1):
        label = f"batch={batch_index}"
        current_uri = file_uri
        
        # === LOGIC TRIGGER >= 90 LINE ITEMS UNTUK RECHECK ===
        is_karet_deli = normalize_vendor_id(vendor_id) == "karet_deli"
        if (total_row >= 90 or is_karet_deli) and index_items and local_pdf_path and run_prefix:
            row_nos = [int(item["_detail_row_no"]) for item in batch if item.get("_detail_row_no")]
            pages = []
            
            for r_no in row_nos:
                if 0 <= r_no - 1 < len(index_items):
                    idx_item = index_items[r_no - 1]
                    p = int(idx_item.get("page_no") or idx_item.get("page") or 0)
                    if p > 0: 
                        pages.append(p)
            
            if pages:
                min_p, max_p = min(pages), max(pages)
                start_idx = max(0, min_p - 1 - 1)
                end_idx = min(total_pdf_pages - 1, max_p - 1 + 1)
                
                sliced_local = _create_sliced_pdf_for_batch(local_pdf_path, start_idx, end_idx)
                current_uri = _upload_temp_pdf_to_gcs(
                    sliced_local, run_prefix, name=f"recheck_batch_{batch_index}_{start_idx}_{end_idx}"
                )

        try:
            r_batch = _call_recheck_batch(batch, label=label, strict_total_retry=False, uri_override=current_uri)
            if r_batch:
                repaired_rows.extend(r_batch)
        except Exception as e:
            print(f"[RECHECK_BATCH_FAIL] {label} gagal sepenuhnya: {e}")
            continue
            
    return repaired_rows

def _apply_detail_line_recheck_label_only(rows: list, repaired_rows: list):
    """
    Apply Gemini recheck hanya untuk confidence label.

    Tujuan:
    - negative / positive tetap berjalan
    - tidak replace value apa pun
    - tidak set _gemini_recheck_changed_fields
    - tidak pakai changed_fields sebagai dasar koreksi value
    """
    repaired_by_no = {}

    for repaired in repaired_rows or []:
        if not isinstance(repaired, dict):
            continue

        row_no = repaired.get("_detail_row_no")
        if row_no is None:
            continue

        try:
            repaired_by_no[int(row_no)] = repaired
        except Exception:
            continue

    if not isinstance(rows, list):
        return rows

    for row in rows:
        if not isinstance(row, dict):
            continue

        # HARD RULE:
        match_score = str(row.get("match_score", "")).strip().upper()
        if match_score in ("TRUE", "CHILD PO"): # <-- UBAH DISINI
            row["_gemini_total_issue_negative"] = False
            row.pop("_gemini_total_issue_negative_reason", None)
            row.pop("_gemini_recheck_changed_fields", None)
            row.pop("_gemini_declared_changed_fields", None)
            continue

        row_no = _safe_row_no_int(row)
        if row_no is None:
            continue

        repaired = repaired_by_no.get(row_no)
        if not repaired:
            continue

        gemini_label = str(
            repaired.get("confidence_label")
            or repaired.get("_gemini_recheck_decision")
            or ""
        ).strip().lower()

        visual_reason = (
            repaired.get("visual_reason")
            or "Gemini detail recheck label decision."
        )

        if gemini_label == "negative":
            row["_gemini_total_issue_negative"] = True
            row["_gemini_total_issue_negative_reason"] = visual_reason

            # NEW: tampung pesan saran dari Gemini ke field internal.
            # NILAI ROW TIDAK DIUBAH. Pesan ini di-append ke
            # match_description nanti oleh
            # _apply_gemini_recheck_suggestions_to_match_description(),
            # tepat sebelum _finalize_match_fields().
            #
            # ALSO NEW: stash structured meta paralel sama panjang
            # dengan messages, supaya consensus filter bisa decide
            # mana yang dibuang tanpa parse string.
            suggestion_msgs = _build_gemini_recheck_suggestion_messages(
                row, repaired
            )
            suggestion_meta = _build_gemini_recheck_suggestion_meta(
                row, repaired
            )
            if suggestion_msgs:
                existing_msgs = row.get("_gemini_recheck_suggestion_messages")
                if not isinstance(existing_msgs, list):
                    existing_msgs = []
                existing_meta = row.get("_gemini_recheck_suggestion_meta")
                if not isinstance(existing_meta, list):
                    existing_meta = []

                existing_msg_set = set(existing_msgs)
                for msg, meta in zip(suggestion_msgs, suggestion_meta):
                    if msg in existing_msg_set:
                        continue
                    existing_msgs.append(msg)
                    existing_meta.append(meta)
                    existing_msg_set.add(msg)

                row["_gemini_recheck_suggestion_messages"] = existing_msgs
                row["_gemini_recheck_suggestion_meta"] = existing_meta
                # Flag ini dipakai oleh consensus filter:
                # kalau semua suggestion ke-filter, demote
                # _gemini_total_issue_negative jadi False.
                row["_gemini_recheck_had_suggestions"] = True

        elif gemini_label == "positive":
            row["_gemini_total_issue_negative"] = False
            row["_gemini_total_issue_negative_reason"] = visual_reason

        # PENTING:
        # Jangan loop allowed_fields.
        # Jangan compare old_value vs new_value.
        # Jangan row[field] = new_value.
        # Jangan set _gemini_recheck_changed_fields.

    return rows


# =========================================================================
# NEW: Gemini recheck suggestion -> match_description
#
# Tujuan blok di bawah:
# - Gemini recheck JANGAN replace nilai numeric apa pun di row.
# - Tapi kalau Gemini bilang "negative" dengan changed_fields,
#   informasi itu tetap berguna untuk reviewer.
# - Jadi kita tampung pesan saran-nya, lalu append ke match_description
#   di akhir flow (lewat _apply_gemini_recheck_suggestions_to_match_description).
# =========================================================================

def _format_recheck_value_for_message(value) -> str:
    """Format nilai untuk ditampilkan di pesan match_description."""
    if value is None:
        return "null"

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"

    if isinstance(value, int):
        return str(value)

    s = str(value).strip()
    if not s or s.lower() == "null":
        return "null"
    return s


def _build_gemini_recheck_suggestion_messages(row: dict, repaired: dict) -> list:
    """
    Bangun list pesan saran dari hasil Gemini recheck.

    Untuk tiap field di `changed_fields` yang valid (ada di DETAIL_RECHECK_FIELDS
    dan benar-benar berbeda dengan nilai sekarang di row), buat satu pesan
    berformat:

        "Gemini recheck: {field} should be {new_value} (extracted: {old_value})"

    NILAI ROW TIDAK DIUBAH. Pesan ini hanya untuk dicatat di match_description.
    Return list of strings (kosong kalau tidak ada saran valid).
    """
    if not isinstance(row, dict) or not isinstance(repaired, dict):
        return []

    changed_fields = repaired.get("changed_fields")
    if not isinstance(changed_fields, list) or not changed_fields:
        return []

    messages = []
    for field in changed_fields:
        if not isinstance(field, str):
            continue
        if field not in DETAIL_RECHECK_FIELDS:
            continue
        if field not in repaired:
            continue

        old_value = row.get(field)
        new_value = repaired.get(field)

        # Kalau secara semantik sama (Gemini "ganti" tapi nilainya sama),
        # tidak perlu pesan saran.
        if _same_recheck_value(old_value, new_value, field):
            continue

        msg = (
            f"Gemini recheck: {field} should be "
            f"{_format_recheck_value_for_message(new_value)} "
            f"(extracted: {_format_recheck_value_for_message(old_value)})"
        )
        if msg not in messages:
            messages.append(msg)

    return messages


def _build_gemini_recheck_suggestion_meta(row: dict, repaired: dict) -> list:
    """
    Parallel helper untuk _build_gemini_recheck_suggestion_messages().

    Iterasi-nya HARUS identik supaya output kedua function ini selalu
    lockstep: index i dari messages bersesuaian dengan index i dari meta.

    Output: list of dict, tiap dict {"field", "old_value", "new_value"}.
    Dipakai oleh _filter_gemini_recheck_suggestions_by_consensus().
    """
    if not isinstance(row, dict) or not isinstance(repaired, dict):
        return []

    changed_fields = repaired.get("changed_fields")
    if not isinstance(changed_fields, list) or not changed_fields:
        return []

    metas = []
    seen_fields = set()
    for field in changed_fields:
        if not isinstance(field, str):
            continue
        if field not in DETAIL_RECHECK_FIELDS:
            continue
        if field not in repaired:
            continue
        if field in seen_fields:
            continue

        old_value = row.get(field)
        new_value = repaired.get(field)

        if _same_recheck_value(old_value, new_value, field):
            continue

        seen_fields.add(field)
        metas.append({
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        })

    return metas


def _apply_gemini_recheck_suggestions_to_match_description(rows: list):
    """
    Append pesan saran Gemini recheck (yang tadi di-stash oleh
    _apply_detail_line_recheck_label_only) ke match_description tiap row.

    Pakai _append_err() yang sudah ada supaya:
    - match_score otomatis di-set "false" untuk row yang dapat saran
    - dedupe terhadap pesan lain yang sudah ada di match_description
    - format pemisah konsisten ("; ")

    HARUS dipanggil SEBELUM _finalize_match_fields(), karena
    _finalize_match_fields() akan nuke match_description menjadi "null"
    untuk row dengan match_score == "true".
    """
    if not isinstance(rows, list):
        return

    for row in rows:
        if not isinstance(row, dict):
            continue

        msgs = row.get("_gemini_recheck_suggestion_messages")
        if not isinstance(msgs, list) or not msgs:
            continue

        for msg in msgs:
            if not isinstance(msg, str):
                continue
            msg = msg.strip()
            if not msg:
                continue
            _append_err(row, msg)


# =========================================================================
# NEW (Option D — Combine):
# Consensus-based filter untuk Gemini recheck suggestions.
#
# Tujuan:
# - Kalau 2+ row dengan signature mirip (invoice + qty + description) dapat
#   saran Gemini untuk field yang sama tapi dengan nilai berbeda, gunakan
#   nilai field di row TETANGGA YANG TIDAK DI-FLAG sebagai consensus.
# - Saran yang match consensus dipertahankan. Saran yang menyimpang
#   dari consensus dibuang.
# - Kalau tidak ada consensus (tidak ada tetangga unflagged, atau nilainya
#   campur tanpa majority), buang semua saran konflik (konservatif).
# - Row yang semua saran-nya ke-filter dan SEBELUMNYA punya saran,
#   _gemini_total_issue_negative-nya didemote ke False, supaya
#   _finalize_audit_confidence_labels nanti set confidence_label-nya
#   kembali ke "positive".
# =========================================================================

def _gemini_recheck_norm_str(v) -> str:
    """
    Normalisasi value untuk equality compare.
    - None / "null" / "nan" -> ""
    - integer / float bulat -> string integer (1.0 -> "1")
    - float pecahan -> str(value)
    - string angka -> hasil float-normalize (jadi "1.0" juga -> "1")
    - selain itu -> lowercase strip
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    s = str(v).strip()
    if s.lower() in ("null", "none", "nan", ""):
        return ""
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
        return str(f)
    except (ValueError, TypeError):
        return s.lower()


def _gemini_recheck_row_signature(row: dict):
    """
    Bangun signature tuple untuk identifikasi "row mirip" dalam invoice
    yang sama: (invoice_no, inv_quantity, inv_description prefix).

    Return None kalau row tidak punya invoice_no (cross-invoice consensus
    tidak meaningful).
    """
    if not isinstance(row, dict):
        return None
    inv_no = _gemini_recheck_norm_str(row.get("inv_invoice_no"))
    if not inv_no:
        return None
    qty = _gemini_recheck_norm_str(row.get("inv_quantity"))
    desc = _gemini_recheck_norm_str(row.get("inv_description"))[:60]
    return (inv_no, qty, desc)


def _filter_gemini_recheck_suggestions_by_consensus(rows: list):
    """
    Filter conflicting Gemini recheck suggestions menggunakan consensus
    dari row tetangga di signature yang sama.

    Lihat docstring header section di atas untuk algoritma lengkapnya.

    Harus dipanggil SEBELUM:
    - _apply_gemini_recheck_suggestions_to_match_description (supaya pesan
      false-negative tidak ke-append ke match_description)
    - _finalize_audit_confidence_labels (supaya confidence_label false-negative
      ter-demote dari "negative" balik ke "positive")
    """
    if not isinstance(rows, list) or len(rows) < 2:
        return

    # Step 1: group rows by signature
    by_sig = {}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        sig = _gemini_recheck_row_signature(row)
        if sig is None:
            continue
        by_sig.setdefault(sig, []).append((idx, row))

    # Step 2: untuk tiap group, deteksi konflik per-field dan tandai drop
    for sig, group in by_sig.items():
        if len(group) < 2:
            continue

        # Kumpulkan suggestion per field di group ini.
        # field -> list of (group_index, row, meta_dict)
        field_to_items = {}
        for gi, (row_idx, row) in enumerate(group):
            metas = row.get("_gemini_recheck_suggestion_meta")
            if not isinstance(metas, list):
                continue
            for meta in metas:
                if not isinstance(meta, dict):
                    continue
                field = meta.get("field")
                if not field:
                    continue
                field_to_items.setdefault(field, []).append((gi, row, meta))

        for field, items in field_to_items.items():
            if len(items) < 2:
                # Cuma 1 row di group ini yang punya saran untuk field
                # ini -> tidak ada konflik, biarkan.
                continue

            # Cek apakah suggested values berbeda satu sama lain.
            distinct_vals = {
                _gemini_recheck_norm_str(meta.get("new_value"))
                for (_, _, meta) in items
            }
            if len(distinct_vals) <= 1:
                # Semua saran agree -> tidak ada konflik.
                continue

            # KONFLIK. Bangun consensus dari row tetangga yang TIDAK ada
            # di flagged set untuk field ini.
            flagged_gis = {gi for (gi, _, _) in items}

            consensus_pool = []
            for gi, (row_idx, row) in enumerate(group):
                if gi in flagged_gis:
                    continue
                val = row.get(field)
                norm = _gemini_recheck_norm_str(val)
                if not norm:
                    continue
                consensus_pool.append(norm)

            consensus_value = None
            if consensus_pool:
                # Mode pakai count dictionary manual biar tidak import Counter
                tally = {}
                for v in consensus_pool:
                    tally[v] = tally.get(v, 0) + 1
                top_value, top_count = max(tally.items(), key=lambda kv: kv[1])
                if top_count * 2 > len(consensus_pool):
                    consensus_value = top_value

            # Mark drop/keep
            for (gi, row, meta) in items:
                if consensus_value is not None:
                    sug_norm = _gemini_recheck_norm_str(meta.get("new_value"))
                    if sug_norm == consensus_value:
                        # Match consensus -> keep
                        continue
                # Default: drop (kalau tidak ada consensus, atau kalau
                # sugestion ini menyimpang dari consensus)
                meta["_dropped_by_consensus_filter"] = True

    # Step 3: terapkan keputusan drop ke list messages/meta per-row,
    # dan demote _gemini_total_issue_negative kalau perlu.
    for row in rows:
        if not isinstance(row, dict):
            continue
        metas = row.get("_gemini_recheck_suggestion_meta")
        msgs = row.get("_gemini_recheck_suggestion_messages")
        had_suggestions = row.get("_gemini_recheck_had_suggestions") is True

        if not isinstance(metas, list) or not metas:
            continue
        if not isinstance(msgs, list):
            msgs = []

        new_metas = []
        new_msgs = []
        for i, meta in enumerate(metas):
            if not isinstance(meta, dict):
                continue
            if meta.get("_dropped_by_consensus_filter"):
                # Skip, sekaligus dibersihkan marker-nya (tidak perlu lagi).
                continue
            meta.pop("_dropped_by_consensus_filter", None)
            new_metas.append(meta)
            if i < len(msgs):
                new_msgs.append(msgs[i])

        row["_gemini_recheck_suggestion_meta"] = new_metas
        row["_gemini_recheck_suggestion_messages"] = new_msgs

        # Kalau row ini SEBELUMNYA punya saran tapi sekarang ke-filter
        # semua, demote negative flag. _finalize_audit_confidence_labels
        # nanti akan menyetel confidence_label kembali ke "positive".
        if had_suggestions and not new_metas:
            row["_gemini_total_issue_negative"] = False
            row.pop("_gemini_total_issue_negative_reason", None)


def _apply_detail_line_recheck_result(rows: list, repaired_rows: list):
    """
    Apply Gemini recheck dengan greedy acceptance gate.

    Fix dari bug sebelumnya:
    - Jangan accept semua perubahan Gemini sekaligus.
    - Jangan reject semua perubahan sekaligus.
    - Accept perubahan satu per satu jika perubahan itu memperbaiki total.
    - match_score TRUE tidak boleh diubah / tidak boleh diberi changed marker.
    """
    repaired_by_no = {}

    for repaired in repaired_rows or []:
        if not isinstance(repaired, dict):
            continue

        row_no = repaired.get("_detail_row_no")
        if row_no is None:
            continue

        try:
            repaired_by_no[int(row_no)] = repaired
        except Exception:
            continue

    if not isinstance(rows, list):
        return rows

    # =========================================================
    # STEP 1: Build proposals, jangan langsung apply.
    # =========================================================
    proposals = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        match_score = str(row.get("match_score", "")).strip().upper()
        if match_score in ("TRUE", "CHILD PO"): # <-- UBAH DISINI (1)
            continue

        row_no = _safe_row_no_int(row)
        if row_no is None:
            continue

        repaired = repaired_by_no.get(row_no)
        if not repaired:
            continue

        gemini_confidence_label = str(
            repaired.get("confidence_label") or ""
        ).strip().lower()

        gemini_changed_fields = repaired.get("changed_fields")
        if not isinstance(gemini_changed_fields, list):
            gemini_changed_fields = repaired.get("_gemini_changed_fields")
        if not isinstance(gemini_changed_fields, list):
            gemini_changed_fields = []

        allowed_fields = _normalize_recheck_field_list(
            row.get("_recheck_fields") or []
        )

        if not allowed_fields:
            continue

        # =====================================================
        # Simpan keputusan label dari Gemini.
        # Ini penting untuk kasus TOTAL:
        # Gemini bisa memilih row negative meskipun numeric change
        # nanti tidak masuk proposals / direject oleh greedy gate.
        # =====================================================
        gemini_label = str(
            repaired.get("confidence_label")
            or repaired.get("_gemini_recheck_decision")
            or ""
        ).strip().lower()

        if gemini_label == "negative":
            row["_gemini_total_issue_negative"] = True
            row["_gemini_total_issue_negative_reason"] = (
                repaired.get("visual_reason")
                or "Gemini marked this row negative during total issue recheck."
            )

            gemini_changed_fields = repaired.get("changed_fields")
            if isinstance(gemini_changed_fields, list):
                row["_gemini_declared_changed_fields"] = [
                    f for f in gemini_changed_fields
                    if f in allowed_fields
                ]

        for field in allowed_fields:
            if field not in repaired:
                continue

            old_value = row.get(field)
            new_value = repaired.get(field)

            if _same_recheck_value(old_value, new_value, field):
                continue

            proposals.append({
                "row": row,
                "row_index": idx,
                "row_no": row_no,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "group_key": row.get("_recheck_group_key") or _get_detail_total_group_key(row, idx),
                "field_meta": (row.get("_recheck_field_meta") or {}).get(field),
            })

    if not proposals:
        return rows

    # =========================================================
    # STEP 2: Group proposals by invoice_group + field.
    # =========================================================
    grouped_proposals = {}

    for p in proposals:
        key = (p["group_key"], p["field"])
        grouped_proposals.setdefault(key, []).append(p)

    accepted = []

    for (group_key, field), field_proposals in grouped_proposals.items():
        # Ambil metadata total mismatch.
        meta = None
        for p in field_proposals:
            if isinstance(p.get("field_meta"), dict):
                meta = p.get("field_meta")
                break

        # Non-total issue: accept seperti flow lama.
        if not meta:
            accepted.extend(field_proposals)
            continue

        declared_total = _to_float(meta.get("declared_total"))

        if declared_total is None:
            print(
                f"[RECHECK_GATE][REJECT_NO_DECLARED] group={group_key} field={field} "
                f"proposal_count={len(field_proposals)}"
            )
            continue

        # Hitung current sum dari rows saat ini.
        current_sum = 0.0
        has_value = False

        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue

            this_group = _get_detail_total_group_key(row, idx)
            if this_group != group_key:
                continue

            value = _to_float(row.get(field))
            if value is not None:
                current_sum += value
                has_value = True

        if not has_value:
            print(
                f"[RECHECK_GATE][REJECT_NO_VALUES] group={group_key} field={field} "
                f"proposal_count={len(field_proposals)}"
            )
            continue

        eps = float(TOTAL_CONTRIBUTION_EPS)
        current_gap_abs = abs(current_sum - declared_total)

        # =====================================================
        # Greedy acceptance:
        # Pilih perubahan yang memperbaiki gap satu per satu.
        # Ini menghindari kasus semua row berubah lalu semua di-reject.
        # =====================================================
        scored = []

        for p in field_proposals:
            old_num = _to_float(p.get("old_value"))
            new_num = _to_float(p.get("new_value"))

            if old_num is None:
                old_num = 0.0
            if new_num is None:
                new_num = 0.0

            delta = new_num - old_num
            after_sum = current_sum + delta
            after_gap_abs = abs(after_sum - declared_total)
            improvement = current_gap_abs - after_gap_abs

            scored.append({
                **p,
                "_delta": delta,
                "_after_sum": after_sum,
                "_after_gap_abs": after_gap_abs,
                "_improvement": improvement,
            })

        # Prioritaskan proposal yang paling memperbaiki total.
        scored.sort(
            key=lambda x: float(x.get("_improvement", 0.0) or 0.0),
            reverse=True
        )

        for p in scored:
            delta = _to_float(p.get("_delta")) or 0.0

            before_gap_abs = abs(current_sum - declared_total)
            after_sum = current_sum + delta
            after_gap_abs = abs(after_sum - declared_total)
            improvement = before_gap_abs - after_gap_abs

            # Accept kalau:
            # - total menjadi match, atau
            # - gap membaik
            total_match = after_gap_abs <= eps
            improves = improvement > eps

            if total_match or improves:
                accepted.append(p)
                current_sum = after_sum

                print(
                    f"[RECHECK_GATE][ACCEPT_ONE] group={group_key} field={field} "
                    f"row_no={p.get('row_no')} old={p.get('old_value')} new={p.get('new_value')} "
                    f"doc={declared_total} new_sum={current_sum} "
                    f"new_gap={abs(current_sum - declared_total)}"
                )

                # Kalau sudah match, stop untuk field ini.
                if abs(current_sum - declared_total) <= eps:
                    break
            else:
                print(
                    f"[RECHECK_GATE][REJECT_ONE] group={group_key} field={field} "
                    f"row_no={p.get('row_no')} old={p.get('old_value')} new={p.get('new_value')} "
                    f"doc={declared_total} before_gap={before_gap_abs} after_gap={after_gap_abs}"
                )

    # =========================================================
    # STEP 3: Apply hanya proposal yang accepted.
    # =========================================================
    for p in accepted:
        row = p["row"]

        # Safety lagi: TRUE / CHILD PO tidak boleh berubah.
        match_score = str(row.get("match_score", "")).strip().upper()
        if match_score in ("TRUE", "CHILD PO"): # <-- UBAH DISINI (2)
            continue

        field = p["field"]
        new_value = p["new_value"]

        row[field] = new_value

        existing = row.get("_gemini_recheck_changed_fields")
        if not isinstance(existing, list):
            existing = []

        if field not in existing:
            existing.append(field)

        row["_gemini_recheck_changed_fields"] = existing

    return rows

# =========================================================
# TWO-PASS OPTIONAL DOC MERGE
# PASS 1: INV + PL sebagai base
# PASS 2: FULL docs hanya untuk ambil BL/COO fields
# =========================================================

OPTIONAL_DETAIL_FIELDS = {
    "bl_description",
    "bl_hs_code",
    "bl_mark_number",

    "coo_seq",
    "coo_mark_number",
    "coo_description",
    "coo_hs_code",
    "coo_quantity",
    "coo_unit",
    "coo_package_count",
    "coo_package_unit",
    "coo_gw",
    "coo_amount",
    "coo_criteria",
    "coo_customer_po_no",
}

OPTIONAL_HEADER_PREFIXES = ("bl_", "coo_")

BASE_ANCHOR_FIELDS_FOR_OPTIONAL = [
    "_expected_index",
    "_detail_row_no",

    "inv_invoice_no",
    "inv_invoice_date",
    "inv_customer_po_no",
    "inv_spart_item_no",
    "inv_seq",
    "inv_description",
    "inv_quantity",
    "inv_quantity_unit",
    "inv_amount",

    "pl_invoice_no",
    "pl_invoice_date",
    "pl_customer_po_no",
    "pl_item_no",
    "pl_description",
    "pl_quantity",
    "pl_package_count",
    "pl_nw",
    "pl_gw",
    "pl_volume",
]


def _optional_safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _optional_row_key(row: dict):
    if not isinstance(row, dict):
        return None

    # _expected_index paling stabil karena berasal dari index item batch.
    for key in ["_expected_index", "_detail_row_no", "idx"]:
        value = _optional_safe_int(row.get(key))
        if value is not None:
            return value

    return None


def _is_meaningful_optional_value(value):
    if value is None:
        return False

    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return False
        if s.lower() == "null":
            return False

    return True


def _compact_base_rows_for_optional_anchor(base_rows: list, first_index=None, last_index=None):
    compacted = []

    for row in base_rows or []:
        if not isinstance(row, dict):
            continue

        idx = _optional_row_key(row)
        if idx is None:
            continue

        if first_index is not None and idx < int(first_index):
            continue

        if last_index is not None and idx > int(last_index):
            continue

        item = {}

        for key in BASE_ANCHOR_FIELDS_FOR_OPTIONAL:
            if key in row:
                item[key] = row.get(key)

        if "_expected_index" not in item:
            item["_expected_index"] = idx

        compacted.append(item)

    compacted.sort(key=lambda x: int(x.get("_expected_index", 0) or 0))
    return compacted


def _append_base_anchor_to_existing_prompt(existing_prompt: str, base_anchor_rows: list) -> str:
    """
    Tetap pakai prompt vendor/detail existing.
    Ini hanya menambahkan base_rows sebagai anchor supaya PASS 2 bisa mapping BL/COO
    ke row INV+PL yang sudah jadi.
    """
    base_anchor_json = json.dumps(base_anchor_rows, ensure_ascii=False)

    return f"""
{existing_prompt}

==============================
BASE_ROWS HASIL FINAL INV + PL
==============================

Gunakan BASE_ROWS berikut sebagai anchor row yang sudah final dari Invoice + Packing List.

BASE_ROWS:
{base_anchor_json}

ATURAN KHUSUS UNTUK PASS OPTIONAL:
- Prompt vendor dan schema di atas tetap berlaku.
- Jangan membuat row baru.
- Jangan menghapus row.
- Jangan mengubah urutan row.
- Output harus tetap untuk _expected_index dalam batch ini.
- Gunakan BASE_ROWS sebagai master row.
- Field inv_* dan pl_* boleh tetap diekstrak pada output, tetapi nanti sistem hanya akan memakai field bl_* dan coo_* dari PASS OPTIONAL.
- Fokus tambahan pada mapping field bl_* dan coo_* ke _expected_index yang paling cocok.
""".strip()


def _build_optional_jobs_from_base_rows(jobs: list, base_rows: list) -> list:
    optional_jobs = []

    for job in jobs or []:
        first_index = int(job["first_index"])
        last_index = int(job["last_index"])

        base_anchor_rows = _compact_base_rows_for_optional_anchor(
            base_rows=base_rows,
            first_index=first_index,
            last_index=last_index,
        )

        optional_prompt = _append_base_anchor_to_existing_prompt(
            existing_prompt=job["prompt"],
            base_anchor_rows=base_anchor_rows,
        )

        optional_jobs.append({
            **job,
            "prompt": optional_prompt,
        })

    return optional_jobs


def _merge_optional_header_into_base_header(base_header_obj: dict, optional_header_obj: dict) -> dict:
    """
    Header INV/PL dari PASS 1 tetap master.
    Header BL/COO dari full docs boleh masuk.
    """
    merged = dict(base_header_obj or {})

    if not isinstance(optional_header_obj, dict):
        return merged

    for key, value in optional_header_obj.items():
        if str(key).startswith(OPTIONAL_HEADER_PREFIXES):
            merged[key] = value

    return merged


def _merge_optional_rows_into_base_rows(base_rows: list, optional_rows: list) -> list:
    """
    Merge PASS 2 ke PASS 1.
    Hanya field OPTIONAL_DETAIL_FIELDS yang boleh masuk.
    inv_* dan pl_* dari optional_rows tidak akan pernah overwrite base_rows.
    """
    base_by_key = {}

    for row in base_rows or []:
        if not isinstance(row, dict):
            continue

        key = _optional_row_key(row)
        if key is not None:
            base_by_key[key] = row

    merged_count = 0

    for opt in optional_rows or []:
        if not isinstance(opt, dict):
            continue

        key = _optional_row_key(opt)
        if key is None:
            continue

        base = base_by_key.get(key)
        if not base:
            continue

        for field in OPTIONAL_DETAIL_FIELDS:
            if field not in opt:
                continue

            value = opt.get(field)

            # Jangan timpa value existing dengan null/kosong dari optional pass.
            if not _is_meaningful_optional_value(value):
                continue

            base[field] = value
            merged_count += 1

    print(
        f"[OPTIONAL_MERGE] "
        f"optional_rows={len(optional_rows or [])} "
        f"merged_fields={merged_count}"
    )

    return base_rows


def _run_detail_jobs(
    input_uri: str,
    run_prefix: str,
    jobs: list,
    total_row: int,
    label: str,
    batch_size: int = None,
    vendor_id: str = "default",
):
    """
    Wrapper batch detail supaya PASS 1 dan PASS 2 bisa reuse logic yang sama.
    """
    if not jobs:
        raise Exception(f"[{label}] jobs kosong")

    max_workers = max(1, len(jobs))
    results = {}

    log_batch_size = batch_size
    if log_batch_size is None:
        try:
            log_batch_size = max(len(j.get("expected_indices", [])) for j in jobs or [])
        except Exception:
            log_batch_size = BATCH_SIZE
 
    print(
        f"[{label}] OCR Batching | total_jobs={len(jobs)} "
        f"| max_workers={max_workers} "
        f"| total_row={total_row} "
        f"| batch_size={log_batch_size}"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(
                _run_one_detail_batch,
                job.get("file_uri", input_uri), # <--- UBAH BARIS INI
                run_prefix,
                job["batch_no"],
                job["prompt"],
                job["first_index"],
                job["last_index"],
                job["expected_indices"],
                vendor_id,
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
                f"[{label}][BATCH DONE] "
                f"batch_no={bn} "
                f"expected={expected_count} "
                f"actual={len(arr)}"
            )

    missing_batches = sorted({
        job["batch_no"] for job in jobs
    } - set(results.keys()))

    if missing_batches:
        raise Exception(f"[{label}] Missing detail batch results: {missing_batches}")

    rows = []
    for bn in sorted(results.keys()):
        rows.extend(results[bn])

    if not rows:
        raise Exception(f"[{label}] Tidak ada data detail hasil Gemini")

    actual_detail_count = len(rows)

    print(
        f"[{label}][DETAIL_COUNT_AFTER_BATCH] "
        f"expected={total_row} actual={actual_detail_count}"
    )

    if actual_detail_count != total_row:
        got_indices = sorted([
            int(r.get("_expected_index"))
            for r in rows
            if isinstance(r, dict) and r.get("_expected_index") is not None
        ])

        expected_indices_all = list(range(1, total_row + 1))
        missing_indices = sorted(set(expected_indices_all) - set(got_indices))
        extra_indices = sorted(set(got_indices) - set(expected_indices_all))

        raise Exception(
            f"[{label}] Detail row count mismatch after batch. "
            f"expected={total_row}, actual={actual_detail_count}, "
            f"missing_indices={missing_indices}, extra_indices={extra_indices}"
        )

    return rows

def _drop_empty_rows_for_haomeng(rows: list, vendor_id: str):
    """
    Menghapus row halusinasi khusus vendor Haomeng 
    jika inv_spart_item_no DAN inv_description kosong/null.
    """
    if normalize_vendor_id(vendor_id) != "haomeng":
        return rows
        
    cleaned_rows = []
    dropped_count = 0
    
    for row in rows:
        if not isinstance(row, dict):
            continue
            
        inv_item = str(row.get("inv_spart_item_no") or "").strip().lower()
        inv_desc = str(row.get("inv_description") or "").strip().lower()
        
        is_item_empty = (inv_item == "" or inv_item == "null")
        is_desc_empty = (inv_desc == "" or inv_desc == "null")
        
        # Jika KEDUANYA kosong, abaikan baris ini (drop)
        if is_item_empty and is_desc_empty:
            dropped_count += 1
            continue
            
        cleaned_rows.append(row)
        
    if dropped_count > 0:
        print(f"[HAOMENG_CLEANUP] Berhasil menghapus {dropped_count} baris halusinasi (item & desc kosong).")
        
    return cleaned_rows

def run_ocr(
    invoice_name,
    uploaded_pdf_paths,
    with_total_container,
    persist_output=True,
    manage_markers=True,
    forced_vendor_id=None,
    has_bl_doc=None,
    has_coo_doc=None,
):
    uploaded_pdf_paths = uploaded_pdf_paths or []

    explicit_has_bl_doc = has_bl_doc is not None
    explicit_has_coo_doc = has_coo_doc is not None

    # Infer default untuk flow lama:
    # urutan file legacy diasumsikan: invoice, packing, BL, COO
    if has_bl_doc is None:
        has_bl_doc = bool(with_total_container and len(uploaded_pdf_paths) >= 3)

    if has_coo_doc is None:
        has_coo_doc = bool(len(uploaded_pdf_paths) >= 4)

    # Preserve guard lama hanya untuk flow legacy/non-explicit.
    # Kalau caller explicit bilang file ke-3 adalah BL, jangan direject.
    if (
        not explicit_has_bl_doc
        and not explicit_has_coo_doc
        and len(uploaded_pdf_paths) == 3
        and not with_total_container
    ):
        raise Exception("COO hanya bisa diproses jika Bill of Lading juga diupload.")

    # Guard eksplisit: COO tidak boleh tanpa BL.
    if has_coo_doc and not has_bl_doc:
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
        # Default: merge semua halaman invoice/PL jadi 1 page panjang.
        # Pre-processing ini menolong Gemini melihat seluruh tabel sekaligus
        # untuk vendor dengan format tabular standar (chengs dkk).
        #
        # Khusus shimano_inc / shimano_singapore: SKIP merge ini. Format
        # invoice SHIMANO berbasis BLOK vertikal (PART#/PRODUCT CD/S.PART#
        # di kanan + CTN NO. sub-rows + baris TOTAL per blok), dengan 30+
        # halaman per invoice. Saat di-merge jadi satu page yang sangat
        # tinggi, Gemini bingung membedakan blok-blok individual dan
        # cenderung balikin halusinasi atau array kosong. Mengirim PDF
        # multi-page asli membiarkan Gemini membaca tiap halaman secara
        # alami.
        _skip_onepage_preprocess = normalize_vendor_id(forced_vendor_id) in {
            "shimano_inc",
            "shimano_singapore",
            "karet_deli",
        }

        if _skip_onepage_preprocess:
            print(
                f"[PREPROCESS] vendor_id={forced_vendor_id}: skip one-page "
                "merge, kirim PDF multi-page asli ke Gemini."
            )
            invoice_onepage_pdf = normalized_pdf_paths[0]
            packing_onepage_pdf = normalized_pdf_paths[1]
        else:
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

        # PL-only URI untuk ekstraksi terfokus packing list (vendor merged-cell
        # numerik, mis. novatec). Hanya di-upload bila vendornya butuh.
        file_uri_packing = None
        if _is_pl_merged_numeric_vendor(normalize_vendor_id(forced_vendor_id)):
            file_uri_packing = _upload_temp_pdf_to_gcs(
                packing_onepage_pdf,
                run_prefix,
                name="packing"
            )

        file_uri_full = None
        file_uri_container_bl = None

        # FULL:
        # invoice + packing pakai hasil preprocess
        # BL / COO / dokumen lain tetap original
        # Dipakai untuk optional header/detail enrichment.
        has_extra_docs = (
            len(normalized_pdf_paths) > 2
            and (has_bl_doc or has_coo_doc)
        )
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

        # CONTAINER:
        # Khusus output container, input Gemini harus hanya dokumen BL.
        # Urutan input legacy/grouped: [invoice, packing, BL, COO?]
        if with_total_container:
            if not has_bl_doc or len(normalized_pdf_paths) < 3:
                raise Exception("Output total/container membutuhkan dokumen Bill of Lading.")

            bl_pdf_for_container = _compress_pdf_if_needed(normalized_pdf_paths[2])
            if (
                bl_pdf_for_container not in temp_local_paths
                and bl_pdf_for_container != normalized_pdf_paths[2]
            ):
                temp_local_paths.append(bl_pdf_for_container)

            file_uri_container_bl = _upload_temp_pdf_to_gcs(
                bl_pdf_for_container,
                run_prefix,
                name="container_bl"
            )

        # =========================
        # TWO-PASS INPUT MODE
        # =========================
        base_detail_input_uri = file_uri_detail          # INV + PL only
        optional_detail_input_uri = file_uri_full        # INV + PL + BL/COO, jika ada

        # =========================
        # VENDOR CONTEXT
        # Dipakai sejak header pass karena shimano_inc punya aturan khusus:
        # bl_mark_number diambil dari content/detail, bukan header.
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

        print("OCR Header - BASE INV+PL")

        base_header_obj = _call_gemini_json_uri(
            file_uri_detail,
            build_header_prompt(vendor_id=vendor_id),
            expect_array=False,
            retries=3,
            vendor_id=vendor_id
        )
        if not isinstance(base_header_obj, dict):
            base_header_obj = {}

        optional_header_obj = {}

        if optional_detail_input_uri:
            print("OCR Header - OPTIONAL FULL DOCS")

            optional_header_obj = _call_gemini_json_uri(
                optional_detail_input_uri,
                build_header_prompt(vendor_id=vendor_id),
                expect_array=False,
                retries=3,
                vendor_id=vendor_id
            )
            if not isinstance(optional_header_obj, dict):
                optional_header_obj = {}

        # header_obj final:
        # - inv_* dan pl_* dari base_header_obj
        # - bl_* dan coo_* dari optional_header_obj
        header_obj = _merge_optional_header_into_base_header(
            base_header_obj=base_header_obj,
            optional_header_obj=optional_header_obj,
        )

        _enforce_absent_optional_docs_empty(
            header_obj=header_obj,
            has_bl_doc=has_bl_doc,
            has_coo_doc=has_coo_doc,
        )

        # GET TOTAL ROW FROM GEMINI
        if normalize_vendor_id(vendor_id) == "karet_deli":
            prompt_to_use = KARET_DELI_ROW_SYSTEM_INSTRUCTION
            print("[ROW_COUNT] Menggunakan prompt custom KARET_DELI_ROW_SYSTEM_INSTRUCTION")
        else:
            prompt_to_use = ROW_SYSTEM_INSTRUCTION
            
        data_row = _call_gemini_json_uri(file_uri_detail, prompt_to_use, expect_array=False, retries=3, vendor_id=vendor_id)

        if isinstance(data_row, dict) and "total_row" in data_row:
            total_row = int(data_row["total_row"])
        else:
            raise Exception(f"total_row tidak ditemukan di response: {data_row}")

        # SHIMANO: override total_row dengan deterministic PART# count via pymupdf.
        # Gemini's row.py count untuk SHIMANO unreliable karena format BLOCK
        # (bukan tabular) — variance tinggi run-to-run dan sering undercount,
        # akibatnya chunked extraction kehilangan tail items.
        # Hanya aktif untuk shimano_inc / shimano_singapore, vendor lain
        # sama sekali tidak ter-sentuh.
        if normalize_vendor_id(vendor_id) in {"shimano_inc", "shimano_singapore"}:
            invoice_pdf_for_count = normalized_pdf_paths[0]
            deterministic_total_row = _shimano_count_line_items_from_invoice_pdf(
                invoice_pdf_for_count
            )
            if deterministic_total_row > 0:
                print(
                    f"[SHIMANO_PART_COUNT] override total_row: "
                    f"gemini={total_row} -> pymupdf={deterministic_total_row}"
                )
                total_row = deterministic_total_row
            else:
                print(
                    f"[SHIMANO_PART_COUNT] pymupdf count returned 0, "
                    f"fallback ke gemini total_row={total_row}"
                )

        # NEW: INDEX extraction (anchor line item)
        # Untuk dokumen dengan banyak line item (total_row > threshold),
        # output JSON index dalam satu shot melebihi max_output_tokens
        # sehingga Gemini ter-truncate dan retry gagal.
        # Pakai chunked extraction kalau total_row melewati threshold.
        # Trigger berbasis jumlah row, BUKAN vendor, supaya dokumen besar
        # dari vendor apa pun otomatis ter-cover.
        index_chunk_size = _get_index_chunk_size_for_total_row(total_row, vendor_id=vendor_id)

        if index_chunk_size > 0:
            print(
                f"[INDEX_CHUNK_MODE] vendor_id={vendor_id} "
                f"total_row={total_row} chunk_size={index_chunk_size} "
                f"threshold={INDEX_CHUNK_TOTAL_ROW_THRESHOLD}"
            )
            index_items = _call_gemini_index_chunked(
                file_uri=file_uri_detail,
                total_row=total_row,
                vendor_id=vendor_id,
                chunk_size=index_chunk_size,
            )
        else:
            index_items = _call_gemini_json_uri(
                file_uri_detail,
                build_index_prompt(total_row),
                expect_array=True,
                retries=3,
                vendor_id=vendor_id
            )

        # fallback safety
        if not isinstance(index_items, list) or not index_items:
            raise Exception("INDEX line items kosong")

        # SHIMANO: dedupe anchor rows yang ke-duplikat karena chunk boundary overlap.
        # Gemini kadang mengulang block yang sama di akhir chunk N dan awal chunk N+1.
        # Hanya aktif untuk shimano_inc / shimano_singapore supaya blast radius nol
        # untuk vendor lain.
        if normalize_vendor_id(vendor_id) in {"shimano_inc", "shimano_singapore"}:
            before_dedupe = len(index_items)
            index_items = _shimano_dedupe_index_items(index_items)
            after_dedupe = len(index_items)
            if before_dedupe != after_dedupe:
                print(
                    f"[SHIMANO_DEDUPE] index_items: "
                    f"before={before_dedupe} after={after_dedupe} "
                    f"dropped={before_dedupe - after_dedupe}"
                )

        # kalau panjang index beda, lebih aman pakai panjang index sebagai total_row aktual
        if len(index_items) != total_row:
            print(f"[WARN] total_row={total_row} tapi index_items={len(index_items)}. Pakai len(index_items) sebagai total_row.")
            total_row = len(index_items)

        _fill_forward(index_items, "inv_customer_po_no")
        _fill_forward(index_items, "pl_customer_po_no")

        # BATCH DETAIL EXTRACTION
        detail_batch_size = _get_detail_batch_size_for_vendor(vendor_id)

        print(
            f"[DETAIL_BATCH_SIZE] "
            f"vendor_id={vendor_id} "
            f"batch_size={detail_batch_size}"
        )

        jobs = []
        first_index = 1
        batch_no = 1
        total_detail_pages = _count_pdf_pages(merged_pdf_detail)

        while first_index <= total_row:
            last_index = min(first_index + detail_batch_size - 1, total_row)
            index_slice = index_items[first_index - 1:last_index]  # 1-based -> 0-based
            expected_indices = list(range(first_index, last_index + 1))

            if len(index_slice) != len(expected_indices):
                raise Exception(f"Index slice mismatch. batch_no={batch_no}")

            prompt = build_detail_prompt_from_index(
                total_row=total_row,
                index_slice=index_slice,
                first_index=first_index,
                last_index=last_index,
                vendor_id=vendor_id,
                vendor_prompt_text=vendor_prompt_text
            )

            # === LOGIC TRIGGER >= 90 LINE ITEMS ===
            batch_file_uri = base_detail_input_uri  # Default uri (Full PDF)
            
            is_karet_deli = normalize_vendor_id(vendor_id) == "karet_deli"
            if total_row >= 90 or is_karet_deli:
                pages = [
                    int(x.get("page_no") or x.get("page", 0)) 
                    for x in index_slice 
                    if x.get("page_no") or x.get("page")
                ]
                
                if pages:
                    min_p = min(pages)
                    max_p = max(pages)
                    
                    # Potong dengan overlap +/- 1 halaman sebagai safety net
                    start_idx = max(0, min_p - 1 - 1) 
                    end_idx = min(total_detail_pages - 1, max_p - 1 + 1)
                    
                    sliced_local = _create_sliced_pdf_for_batch(merged_pdf_detail, start_idx, end_idx)
                    temp_local_paths.append(sliced_local)
                    
                    batch_file_uri = _upload_temp_pdf_to_gcs(
                        sliced_local,
                        run_prefix,
                        name=f"detail_batch_{batch_no}_{start_idx}_{end_idx}"
                    )
                    
                    prompt += (
                        f"\n\nPERHATIAN GUARDRAIL INDEKS:\n"
                        f"Anda sedang membaca POTONGAN DOKUMEN (Halaman fisik ke-{start_idx+1} sampai {end_idx+1}). "
                        f"JANGAN mereset indeks hitungan Anda dari 1! "
                        f"Tugas Anda HANYA mengekstrak line item ke-{first_index} sampai {last_index} "
                        f"secara berurutan menggunakan _expected_index yang diberikan."
                    )

            jobs.append({
                "batch_no": batch_no,
                "file_uri": batch_file_uri,
                "prompt": prompt,
                "first_index": first_index,
                "last_index": last_index,
                "expected_indices": expected_indices,
                "batch_size": detail_batch_size,
            })

            first_index = last_index + 1
            batch_no += 1

        MAX_WORKERS = max(1, len(jobs))

        # =========================================
        # PASS 1: BASE DETAIL OCR
        # Input hanya INV + PL.
        # Vendor prompt tetap sama.
        # Schema tetap sama.
        # =========================================
        all_rows = _run_detail_jobs(
            input_uri=base_detail_input_uri,
            run_prefix=f"{run_prefix}/detail_base",
            jobs=jobs,
            total_row=total_row,
            label="BASE_INV_PL",
            batch_size=detail_batch_size,
            vendor_id=vendor_id
        )

        # =========================================
        # KARET DELI: DETECT-THEN-REFOCUSED-RETRY untuk pl_total_quantity.
        # Setelah detail extraction selesai, sum(pl_quantity) dari rows
        # bisa dipakai sebagai sanity check terhadap pl_total_quantity
        # yang Gemini extract di header pass. Kalau diff kecil (≤1%),
        # kemungkinan besar Gemini salah pilih antara TOTAL parent vs
        # GRAND TOTAL — panggil Gemini 1x dengan prompt super-fokus
        # supaya pilih yang benar. Bounded 1 retry, tidak ada loop.
        # =========================================
        if normalize_vendor_id(vendor_id) == "karet_deli":
            _karet_deli_refocus_pl_total_quantity(
                file_uri=base_detail_input_uri,
                all_rows=all_rows,
                base_header_obj=base_header_obj,
                vendor_id=vendor_id,
            )
            # Sinkronkan header_obj kalau base_header_obj sudah di-update.
            # _merge_optional_header_into_base_header tidak override pl_*,
            # jadi header_obj juga harus disinkronkan manual.
            if base_header_obj.get("pl_total_quantity") != header_obj.get("pl_total_quantity"):
                header_obj["pl_total_quantity"] = base_header_obj.get("pl_total_quantity")

        # =========================================
        # PRECHECK PYTHON
        # Untuk base INV/PL, pakai base_header_obj.
        # Jangan pakai optional header supaya BL/COO tidak memengaruhi precheck INV/PL.
        # =========================================
        all_rows = _run_detail_precheck_pass(
            all_rows,
            base_header_obj,
            vendor_id=vendor_id
        )
        _assign_detail_row_numbers(all_rows)

        # =========================================
        # GEMINI RECHECK SEKALI
        # Recheck INV/PL juga HARUS pakai file_uri_detail.
        # =========================================
        repaired_rows = _call_gemini_detail_line_recheck_once(
            base_detail_input_uri,
            all_rows,
            vendor_id=vendor_id,
            vendor_prompt_text=vendor_prompt_text,
            total_row=total_row,
            index_items=index_items,
            local_pdf_path=merged_pdf_detail,
            run_prefix=run_prefix
        )

        if repaired_rows:
            if _is_recheck_label_only_vendor(vendor_id):
                all_rows = _apply_detail_line_recheck_label_only(
                    all_rows,
                    repaired_rows
                )
            else:
                all_rows = _apply_detail_line_recheck_result(
                    all_rows,
                    repaired_rows
                )

        print(
            f"[DETAIL_COUNT_AFTER_RECHECK] "
            f"expected={total_row} actual={len(all_rows)}"
        )

        if len(all_rows) != total_row:
            raise Exception(
                f"Detail row count changed after recheck. "
                f"expected={total_row}, actual={len(all_rows)}"
            )
        
        # =========================================
        # HAOMENG: DROP EMPTY ROWS (HALUSINASI)
        # Harus ditaruh di sini agar lolos pengecekan Exception di atas
        # =========================================
        all_rows = _drop_empty_rows_for_haomeng(all_rows, vendor_id)

        # =========================================
        # SHIMANO INC ONLY: HS# extraction
        # Tidak grouping ulang.
        # Jalan per invoice group karena run_grouped_ocr()
        # memanggil run_ocr() per group.
        #
        # Pakai base_detail_input_uri = INV + PL only,
        # supaya tidak salah ambil HS code dari COO/BL.
        # =========================================
        all_rows = _run_shimano_hs_code_pass(
            file_uri=base_detail_input_uri,
            rows=all_rows,
            vendor_id=vendor_id,
        )
        
        # =========================================
        # PASS 2: OPTIONAL FULL DOC OCR
        # Input full docs jika ada BL/COO.
        # Prompt vendor tetap sama, tapi ditambah base_rows sebagai anchor.
        # Hasil optional TIDAK BOLEH overwrite inv_* / pl_*.
        # =========================================
        if optional_detail_input_uri:
            try:
                print("[OPTIONAL_PASS] Start full-doc OCR for BL/COO enrichment")

                optional_jobs = _build_optional_jobs_from_base_rows(
                    jobs=jobs,
                    base_rows=all_rows,
                )

                optional_rows = _run_detail_jobs(
                    input_uri=optional_detail_input_uri,
                    run_prefix=f"{run_prefix}/detail_optional",
                    jobs=optional_jobs,
                    total_row=total_row,
                    label="OPTIONAL_FULL_DOCS",
                    batch_size=detail_batch_size,
                    vendor_id=vendor_id
                )

                all_rows = _merge_optional_rows_into_base_rows(
                    base_rows=all_rows,
                    optional_rows=optional_rows,
                )

                print("[OPTIONAL_PASS] Done")

            except Exception as e:
                # Optional docs tidak boleh menghancurkan hasil INV/PL.
                print(f"[OPTIONAL_PASS][WARN] optional BL/COO enrichment skipped: {e}")

        # =========================================================
        # DETERMINISTIC COO MAPPING (vendor COO ter-agregat, mis. joy)
        # PASS 2 di-anchor ke base row invoice sehingga sulit mem-fan-out
        # 1 item COO ke banyak baris dalam panggilan yang juga urus BL.
        # Ekstrak daftar item COO apa adanya lalu petakan di Python.
        # Gated per-vendor -> nol dampak ke vendor lain & ke mapping BL.
        # =========================================================
        if (
            has_coo_doc
            and optional_detail_input_uri
            and _is_aggregated_coo_vendor(vendor_id)
        ):
            try:
                coo_items = _extract_coo_item_list(
                    file_uri=optional_detail_input_uri,
                    vendor_id=vendor_id,
                )
                _map_coo_items_to_rows(all_rows, coo_items, vendor_id=vendor_id)
            except Exception as e:
                print(f"[COO_DETERMINISTIC_MAP][WARN] skipped: {e}")

        _enforce_absent_optional_docs_empty(
            rows=all_rows,
            header_obj=header_obj,
            has_bl_doc=has_bl_doc,
            has_coo_doc=has_coo_doc,
        )

        # =========================
        # OPTIONAL: total/container
        # =========================
        total_data = None
        container_data = None
        if with_total_container and file_uri_container_bl:
            container_data = _call_gemini_json_uri(
                file_uri_container_bl,
                CONTAINER_SYSTEM_INSTRUCTION,
                expect_array=True,
                retries=3,
                vendor_id=vendor_id
            )

            _postprocess_unit_fields(container_data)

        # =========================================
        # FLOW VALIDASI FINAL LAMA TETAP JALAN
        # =========================================
        _apply_header_to_rows(all_rows, header_obj, vendor_id=vendor_id)
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

        # KUNSHAN_LANDON: tambahkan kandidat PO yang tersangkut di awal
        # inv_description ke daftar PO yang akan di-fetch dari PO master.
        # Tanpa ini, _stream_filter_po_lines tidak akan memuat PO target
        # (mis. "45324149") sehingga recovery di _map_po_to_details
        # tidak punya data untuk mencocokkan dan otomatis di-rollback.
        if _is_kunshan_landon_vendor(vendor_id):
            for r in all_rows:
                if not isinstance(r, dict):
                    continue
                candidate = _kunshan_landon_extract_po_from_description(
                    r.get("inv_description")
                )
                if not candidate:
                    continue
                if _norm_po_number(candidate) == _norm_po_number(r.get("inv_customer_po_no")):
                    continue
                po_numbers.add(candidate)

        # NEW: Tarik PO dari JSON berdasarkan item number juga
        item_numbers = set()
        for r in all_rows:
            if not isinstance(r, dict):
                continue
            i_art = str(r.get("inv_spart_item_no") or "").strip()
            p_art = str(r.get("pl_item_no") or "").strip()
            if i_art and i_art.lower() != "null":
                item_numbers.add(i_art)
            if p_art and p_art.lower() != "null":
                item_numbers.add(p_art)

        po_lines = _stream_filter_po_lines(po_numbers, target_item_numbers=item_numbers)
        print("PO NUMBERS:", po_numbers)
        print("PO LINES FOUND:", len(po_lines))

        _recompute_seq_by_key(all_rows, "inv_invoice_no", "inv_seq")

        _postprocess_customer_po_no(all_rows)
        _postprocess_inv_description(all_rows)
        _postprocess_item_no_fields(all_rows)
        _postprocess_unit_fields(all_rows)
        if has_coo_doc:
            _postprocess_coo_description(all_rows)

            # NEW: null-kan COO item yang tidak match ke row detail
            _postprocess_coo_item_mapping(all_rows)

            # Backfill row COO yang cuma punya PO sebelum coo_seq dinomori
            _postprocess_coo_po_only_rows_from_invoice(all_rows, vendor_id=vendor_id)

            # NEW: hitung coo_seq hanya untuk row COO yang masih valid/matched
            # _postprocess_coo_no_and_seq(all_rows)

        if has_bl_doc:
            _postprocess_bl_description(all_rows, vendor_id=vendor_id)
            _postprocess_bl_seller_name_similarity(all_rows)

        _enforce_absent_optional_docs_empty(
            rows=all_rows,
            header_obj=header_obj,
            has_bl_doc=has_bl_doc,
            has_coo_doc=has_coo_doc,
        )

        # Vendor merged-cell (mis. joy): turunkan inv_quantity/inv_amount per-baris
        # dari pl_quantity SEBELUM mapping, supaya total invoice rekonsiliasi dan
        # tiap baris bisa di-map ke PO line-nya masing-masing.
        all_rows = _derive_inv_qty_from_pl_for_merged_vendors(all_rows, vendor_id=vendor_id)

        # Vendor PL merged-cell numerik (mis. novatec): ekstraksi terfokus PL-only
        # + assignment deterministik (agregat-per-group ke baris teratas, 0 di
        # sisanya). Dijalankan SEBELUM PO mapping agar all_rows masih sejajar 1:1
        # dengan baris PL (sebelum kemungkinan split PO).
        if _is_pl_merged_numeric_vendor(vendor_id) and file_uri_packing:
            try:
                pl_data = _extract_pl_item_list(
                    file_uri=file_uri_packing,
                    vendor_id=vendor_id,
                )
                _assign_pl_merged_numerics_to_rows(all_rows, pl_data, vendor_id=vendor_id)
            except Exception as e:
                print(f"[PL_MERGED_NUMERIC][WARN] skipped: {e}")

        all_rows = _map_po_to_details(po_lines, all_rows, vendor_id=vendor_id)

        all_rows = _deduplicate_pl_numeric_fields_for_vendors(all_rows, vendor_id=vendor_id)

        all_rows = _generate_inv_amount_before_validation(all_rows)

        _postprocess_bl_coo_zero_to_null(all_rows)
        _postprocess_invoice_no_consensus(all_rows)

        if has_bl_doc:
            _postprocess_bl_header_majority_by_invoice(
                all_rows,
                vendor_id=vendor_id
            )

        # all_rows = _deduplicate_detail_rows_before_validation(all_rows, vendor_id=vendor_id)

        _assign_detail_row_numbers(all_rows)
        _recompute_seq_by_key(all_rows, "inv_invoice_no", "inv_seq")

        all_rows = _inherit_inv_seq_for_secondary_po_split_rows(all_rows)

        # New logic: rapikan gap 1,1,1 -> 4,4,4 menjadi 1,1,1 -> 2,2,2.
        all_rows = _compact_inv_seq_gaps_after_po_split(all_rows)

        if has_coo_doc:
            _postprocess_coo_po_only_rows_from_invoice(all_rows)
            # _postprocess_coo_no_and_seq(all_rows)

        _enforce_absent_optional_docs_empty(
            rows=all_rows,
            header_obj=header_obj,
            has_bl_doc=has_bl_doc,
            has_coo_doc=has_coo_doc,
        )
        
        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="shimano_singapore",
            columns=["inv_total_quantity", "pl_total_quantity"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="bafang_motor",
            columns=["pl_volume_unit"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="suntour_vietnam",
            columns=["pl_volume_unit"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="suntour_shenzhen",
            columns=["pl_volume_unit"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="sram",
            columns=["pl_volume_unit"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="liow_ko",
            columns=["coo_gw_unit", "pl_weight_unit"],
        )

        _postprocess_null_fields_for_vendor(
            rows=all_rows,
            current_vendor_id=vendor_id,
            target_vendor_ids="karet_deli",
            columns=["inv_total_quantity", "pl_total_package"],
        )
 
        if _is_coo_aggregate_top_row_vendor(vendor_id):
            # COO ter-agregat (mis. joy): tampilkan nilai agregat per produk di
            # SATU baris (baris pertama group) + 0 di baris lain, sesuai dokumen
            # COO. Jangan distribusi per-baris mengikuti PL.
            _postprocess_coo_aggregate_to_top_row(all_rows, vendor_id=vendor_id)
        elif normalize_vendor_id(vendor_id) != "liow_ko":
            _postprocess_coo_numeric_fields_from_pl(all_rows)
        else:
            print("[COO_NUMERIC_FROM_PL] skipped for vendor liow_ko")

        # JOY: setelah PO mapping, ringkas inv_quantity/inv_amount merged-cell
        # ke baris teratas group (mis. 480/0/0/0), sesuai dokumen invoice.
        _postprocess_inv_qty_aggregate_to_top_row(all_rows, vendor_id=vendor_id)

        all_rows = _validate_po(all_rows)

        # KUNSHAN_LANDON: po_text baru terisi di _validate_po (anchor by Material
        # code). Sekarang selaraskan ulang inv_description / pl_description ke
        # baris yang benar. Murni post-processing teks; tidak menyentuh nw/gw/volume.
        _kunshan_landon_realign_descriptions(all_rows, vendor_id)

        _validate_invoice_rows(all_rows)
        _validate_packing_rows(all_rows, vendor_id=vendor_id)
        _validate_invoice_vs_packing_extra(all_rows, vendor_id=vendor_id)

        if has_bl_doc:
            _validate_bl_rows(all_rows)

        if has_coo_doc:
            _validate_coo_rows(all_rows)

        total_attribution = _apply_total_contribution_scoring(all_rows)

        all_rows = _force_secondary_po_split_rows_true(all_rows)

        all_rows = _inherit_inv_seq_for_secondary_po_split_rows(all_rows)
        all_rows = _compact_inv_seq_gaps_after_po_split(all_rows)

        # NEW (Option D): consensus filter — buang Gemini suggestion
        # yang konflik antar-row mirip dan tidak match consensus
        # tetangga unflagged. Ini juga demote _gemini_total_issue_negative
        # untuk row yang semua saran-nya ke-filter, sehingga
        # _finalize_audit_confidence_labels nanti mengembalikan
        # confidence_label-nya ke "positive".
        if _is_recheck_label_only_vendor(vendor_id):
            _filter_gemini_recheck_suggestions_by_consensus(all_rows)
            _apply_gemini_recheck_suggestions_to_match_description(all_rows)

        _finalize_match_fields(all_rows)

        drop_detail_columns = [
            "inv_messrs",
            "inv_messrs_address",
            "inv_gw",
            "inv_gw_unit",
            "inv_hs_code",
            "confidence_logprob",
            "confidence_margin",
            "confidence_predicted_label",
            "confidence_source",
            "audit_candidate",
            "audit_rank",
        ]

        if not _is_shimano_inc_vendor(vendor_id):
            drop_detail_columns.append("inv_hs_code")

        _drop_columns(all_rows, drop_detail_columns)

        if with_total_container:
            total_data = _build_total_from_detail_and_container(all_rows, container_data)
            total_data = _validate_total_rows(total_data, all_rows)

        _enforce_absent_optional_docs_empty(
            rows=all_rows,
            header_obj=header_obj,
            total_rows=total_data,
            container_rows=container_data,
            has_bl_doc=has_bl_doc,
            has_coo_doc=has_coo_doc,
        )

        all_rows = _finalize_audit_confidence_labels(
            all_rows,
            total_attribution=total_attribution
        )

        all_rows = _force_min_one_negative_for_total_issue(
            all_rows,
            total_attribution=total_attribution
        )


        _rename_final_fields(all_rows)
        _drop_internal_detail_fields(all_rows)

        _drop_columns(all_rows, [
            "confidence_logprob",
        ])

        for row in all_rows:
            if isinstance(row, dict):
                row.pop("_expected_index", None)

                row.pop("_recheck_fields", None)
                row.pop("_recheck_original_values", None)
                row.pop("_gemini_recheck_changed_fields", None)

                row.pop("_recheck_group_key", None)
                row.pop("_recheck_field_meta", None)

                row.pop("_force_total_issue_candidate", None)
                row.pop("_forced_total_issue_negative", None)

                # NEW
                row.pop("_gemini_total_issue_negative", None)
                row.pop("_batch_row_index", None)
                row.pop("_invoice_group_row_index", None)

                row.pop("_total_issue_debug", None)
                row.pop("_gemini_total_issue_negative_reason", None)
                row.pop("_gemini_declared_changed_fields", None)

                # NEW: bersihkan field internal pesan saran Gemini recheck.
                row.pop("_gemini_recheck_suggestion_messages", None)
                # NEW (Option D): bersihkan field internal yang dipakai
                # consensus filter.
                row.pop("_gemini_recheck_suggestion_meta", None)
                row.pop("_gemini_recheck_had_suggestions", None)

                row.pop("idx", None)
                row.pop("inv_page_no", None)
                row.pop("pl_page_no", None)
                row.pop("page", None)
                row.pop("page_index", None)
                row.pop("_confidence_label_source", None)
                row.pop("_merged_qty_zero_row", None)
                row.pop("_merged_pl_zero_row", None)

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
            field_order=_get_detail_csv_field_order(vendor_id)
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