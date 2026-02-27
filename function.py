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
from PyPDF2 import PdfMerger 
from google import genai 
from google.genai import types 
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import * 
from total import TOTAL_SYSTEM_INSTRUCTION 
from container import CONTAINER_SYSTEM_INSTRUCTION 
from detail import build_detail_prompt 
from row import ROW_SYSTEM_INSTRUCTION 
import uuid

BATCH_SIZE = 5 
storage_client = storage.Client() 
genai_client = genai.Client( vertexai=True, project=PROJECT_ID, location=LOCATION, ) 

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

def _merge_pdfs(pdf_paths):
    merger = PdfMerger()

    for p in pdf_paths:
        merger.append(p)

    out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    merger.write(out.name)
    merger.close()

    return out.name

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

# ==============================
# UPLOAD PDF TO GCS
# ==============================

def _upload_temp_pdf_to_gcs(local_path: str, run_prefix: str, name: str) -> str:
    bucket = storage_client.bucket(BUCKET_NAME)
    blob_path = f"{run_prefix}/inputs/{name}.pdf"
    bucket.blob(blob_path).upload_from_filename(local_path)
    return f"gs://{BUCKET_NAME}/{blob_path}"

def _call_gemini_uri(file_uri: str, prompt: str):
    parts = [
        types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
        types.Part.from_text(text=prompt),
    ]

    response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            temperature=0,
            top_p=1,
            max_output_tokens=65535,
        ),
    )

    if not response:
        raise Exception("Empty response from Gemini")

    if hasattr(response, "text") and response.text:
        return response.text.strip()

    if getattr(response, "candidates", None):
        content = response.candidates[0].content
        parts_resp = getattr(content, "parts", None) or []
        text_output = ""
        for p in parts_resp:
            if hasattr(p, "text") and p.text:
                text_output += p.text
        if text_output.strip():
            return text_output.strip()

    raise Exception("Gemini response tidak mengandung text")

def _call_gemini_json_uri(file_uri: str, prompt: str, expect_array: bool = False, retries: int = 3):
    """
    Wrapper: panggil Gemini -> pastikan output JSON valid.
    - expect_array=True  : kalau Gemini balikin dict, kita bungkus jadi [dict]
    - retries: retry jika output bukan JSON / quota
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

            # retry kalau output bukan JSON
            if ("bukan json valid" in msg) or ("not json" in msg) or ("not valid json" in msg):
                p = prompt + """
                PENTING:
                - Output HANYA JSON valid, tanpa teks lain.
                - Jika ARRAY: WAJIB mulai '[' dan akhir ']'
                - Jika OBJECT: WAJIB mulai '{' dan akhir '}'
                - Jika data tidak ditemukan: isi "null" / 0 sesuai skema
                """
                time.sleep(0.5)
                continue

            # retry quota
            if ("429" in msg) or ("resource_exhausted" in msg) or ("rate" in msg) or ("quota" in msg):
                time.sleep((2 ** attempt) + random.random())
                continue

            raise

    raise Exception("Gemini gagal menghasilkan JSON setelah retry")

def _run_one_detail_batch(file_uri_detail: str, run_prefix: str, batch_no: int, prompt: str):
    p = prompt
    for attempt in range(1, 4):
        try:
            raw = _call_gemini_uri(file_uri_detail, p)
            json_array = _parse_json_safe(raw)

            if isinstance(json_array, dict):
                json_array = [json_array]
            if not isinstance(json_array, list):
                raise Exception("Batch result bukan array")

            _save_batch_tmp(run_prefix, batch_no, json_array)
            return (batch_no, json_array)

        except Exception as e:
            msg = str(e).lower()

            # ✅ retry kalau output bukan JSON
            if ("bukan json valid" in msg) or ("not json" in msg) or ("not valid json" in msg):
                p = prompt + """
                PENTING SEKALI:
                - Output WAJIB dimulai dengan '[' dan diakhiri dengan ']'
                - Output HANYA JSON ARRAY (tanpa teks lain)
                - Jika data tidak ditemukan, isi string "null" / angka 0 sesuai skema
                """
                time.sleep(0.5)
                continue

            # retry quota
            if ("429" in msg) or ("resource_exhausted" in msg) or ("rate" in msg) or ("quota" in msg):
                time.sleep((2 ** attempt) + random.random())
                continue

            raise

    raise Exception(f"Batch {batch_no} gagal setelah retry")

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

def _map_po_to_details(po_lines, detail_rows):
    """
    Join key:
    - inv_customer_po_no  <-> po_no
    - inv_spart_item_no   <-> vendor_article_no OR sap_article_no

    Normalisasi hanya untuk matching.
    Data yang dipakai untuk output tetap value asli (po_line asli).
    """

    # index: (po_no_norm, article_norm) -> list of (idx_in_po_lines, po_line_asli)
    po_index = {}

    for idx, line in enumerate(po_lines):
        po_no_norm = _norm_po_number(line.get("po_no"))
        if not po_no_norm:
            continue

        v_norm = _norm_key(line.get("vendor_article_no") or line.get("po_vendor_article_no"))
        s_norm = _norm_key(line.get("sap_article_no") or line.get("po_sap_article_no"))

        if v_norm:
            po_index.setdefault((po_no_norm, v_norm), []).append((idx, line))
        if s_norm:
            po_index.setdefault((po_no_norm, s_norm), []).append((idx, line))

    used = set()  # (po_no_norm, idx_in_po_lines)

    for row in detail_rows:
        if not isinstance(row, dict):
            continue

        inv_po_raw = row.get("inv_customer_po_no")
        inv_article_raw = row.get("inv_spart_item_no")

        inv_po_norm = _norm_po_number(inv_po_raw)      # ✅ ganti ini
        inv_article_norm = _norm_key(inv_article_raw)

        if not inv_po_norm or not inv_article_norm:
            row["_po_mapped"] = False
            continue

        candidates = po_index.get((inv_po_norm, inv_article_norm), [])
        chosen = None
        chosen_key = None

        for idx, po_line in candidates:
            key = (inv_po_norm, idx)   
            if key in used:
                continue
            chosen = po_line          # ✅ PO line ASLI
            chosen_key = key
            break

        if chosen:
            used.add(chosen_key)
            row["_po_mapped"] = True
            row["_po_data"] = chosen  # ✅ simpan ASLI untuk dipakai _validate_po
        else:
            row["_po_mapped"] = False

    return detail_rows

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
        row["po_unit"] = po_data.get("po_unit", "null")
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
        for k in required:
            if _is_null(r.get(k)):
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
    declared_qty = _to_float(_first_non_null(rows, "inv_total_quantity"))
    declared_amt = _to_float(_first_non_null(rows, "inv_total_amount"))

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


def _validate_packing_rows(rows: list):
    required = [
        "pl_invoice_no","pl_invoice_date","pl_messrs","pl_messrs_address","pl_item_no",
        "pl_description","pl_quantity","pl_package_unit","pl_package_count","pl_weight_unit",
        "pl_nw","pl_gw","pl_volume_unit","pl_volume"
    ]

    # normalize PT Insera Sena
    def norm(s):
        if _is_null(s): return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    for r in rows:
        if not isinstance(r, dict):
            continue

        for k in required:
            if _is_null(r.get(k)):
                _append_err(r, f"PackingList: missing {k}")

        # PL harus match Invoice
        if not _is_null(r.get("pl_invoice_no")) and not _is_null(r.get("inv_invoice_no")):
            if str(r["pl_invoice_no"]).strip() != str(r["inv_invoice_no"]).strip():
                _append_err(r, "PackingList: pl_invoice_no != inv_invoice_no")

        if not _is_null(r.get("pl_invoice_date")) and not _is_null(r.get("inv_invoice_date")):
            if str(r["pl_invoice_date"]).strip() != str(r["inv_invoice_date"]).strip():
                _append_err(r, "PackingList: pl_invoice_date != inv_invoice_date")

        if norm(r.get("pl_messrs")) and "PT INSERA SENA" not in norm(r.get("pl_messrs")):
            _append_err(r, "PackingList: pl_messrs bukan PT Insera Sena")

    # totals PL
    declared_qty = _to_float(_first_non_null(rows, "pl_total_quantity"))
    declared_nw  = _to_float(_first_non_null(rows, "pl_total_nw"))
    declared_gw  = _to_float(_first_non_null(rows, "pl_total_gw"))
    declared_vol = _to_float(_first_non_null(rows, "pl_total_volume"))
    declared_pkg = _to_float(_first_non_null(rows, "pl_total_package"))

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
        if declared_vol is not None and abs(sum_vol - declared_vol) > 0.01:
            _append_err(r, f"PackingList: total_volume mismatch (sum {sum_vol}, doc {declared_vol})")
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
    """
    Validasi tambahan:
    - inv_messrs == pl_messrs
    - inv_messrs_address == pl_messrs_address
    - inv_gw == coo_gw
    - inv_gw_unit == coo_gw_unit
    """

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    for r in rows:
        if not isinstance(r, dict):
            continue

        # inv_messrs vs pl_messrs
        if not _is_null(r.get("inv_messrs")) and not _is_null(r.get("pl_messrs")):
            if norm(r.get("inv_messrs")) != norm(r.get("pl_messrs")):
                _append_err(r, "Invoice vs PL: inv_messrs != pl_messrs")

        # inv_messrs_address vs pl_messrs_address
        if not _is_null(r.get("inv_messrs_address")) and not _is_null(r.get("pl_messrs_address")):
            if norm(r.get("inv_messrs_address")) != norm(r.get("pl_messrs_address")):
                _append_err(r, "Invoice vs PL: inv_messrs_address != pl_messrs_address")

        # inv_gw vs coo_gw (hanya jika COO ada nilainya)
        inv_gw = _to_float(r.get("inv_gw"))
        coo_gw = _to_float(r.get("coo_gw"))
        if inv_gw is not None and coo_gw is not None:
            if abs(inv_gw - coo_gw) > 0.01:
                _append_err(r, f"Invoice vs COO: inv_gw != coo_gw (inv {inv_gw}, coo {coo_gw})")

        # inv_gw_unit vs coo_gw_unit (hanya jika COO ada nilainya)
        if not _is_null(r.get("inv_gw_unit")) and not _is_null(r.get("coo_gw_unit")):
            if norm(r.get("inv_gw_unit")) != norm(r.get("coo_gw_unit")):
                _append_err(r, "Invoice vs COO: inv_gw_unit != coo_gw_unit")

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
        return  # BL tidak tersedia -> skip semua validasi BL

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

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

        # 1) Seller fallback
        if _is_null(r.get("bl_seller_name")):
            if not _is_null(r.get("bl_shipper_name")):
                r["bl_seller_name"] = r.get("bl_shipper_name")
        if _is_null(r.get("bl_seller_address")):
            if not _is_null(r.get("bl_shipper_address")):
                r["bl_seller_address"] = r.get("bl_shipper_address")

        # 2) LC logic + consignee fallback
        # Rule prompt: jika consignee mengandung nama perusahaan Bank => LC.
        # Implementasi minimal: cek kata "BANK" pada consignee.
        is_lc = "BANK" in norm(r.get("bl_consignee_name"))

        if is_lc:
            # fallback consignee dari notify party (nama+alamat) jika tersedia
            if not _is_null(r.get("bl_notify_party")):
                if _is_null(r.get("bl_consignee_name")):
                    r["bl_consignee_name"] = r.get("bl_notify_party")
                if _is_null(r.get("bl_consignee_address")):
                    r["bl_consignee_address"] = r.get("bl_notify_party")

        # 3) Required fields jika BL ada
        for k in required:
            if _is_null(r.get(k)):
                _append_err(r, f"BL: missing {k}")

        # 4) Validasi kesesuaian dengan invoice: seller harus sama dengan vendor
        inv_vendor = r.get("inv_vendor_name")
        bl_seller = r.get("bl_seller_name")

        if not _is_null(inv_vendor) and not _is_null(bl_seller):
            if norm(inv_vendor) != norm(bl_seller):
                _append_err(r, "BL: bl_seller_name != inv_vendor_name")


def _validate_coo_rows(rows: list):
    """
    Implement rule dari prompt:
    - Required fields jika COO tersedia
    - Conditional required berdasarkan coo_criteria (RVC => amount required, PE => gw required)
    - Validasi terhadap invoice: qty, amount, unit, gw, gw_unit match (jika field ada)
    - Mapping: COO harus match invoice line (coo_invoice_no match inv_invoice_no).
      Similarity description tidak bisa 100% deterministik tanpa NLP berat,
      jadi implement minimal yang deterministic: invoice_no match + (optional) simple token overlap.
    """
    coo_keys_presence = ["coo_no", "coo_form_type", "coo_invoice_no", "coo_origin_country", "coo_hs_code"]
    if not _doc_present(rows, coo_keys_presence):
        return  # COO tidak tersedia -> skip semua validasi COO

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

        # 1) Required fields
        for k in required:
            if _is_null(r.get(k)):
                _append_err(r, f"COO: missing {k}")

        # 2) Conditional required by coo_criteria
        crit = norm(r.get("coo_criteria"))
        if crit == "RVC":
            if _is_null(r.get("coo_amount_unit")):
                _append_err(r, "COO: missing coo_amount_unit for RVC")
            if _is_null(r.get("coo_amount")):
                _append_err(r, "COO: missing coo_amount for RVC")
        elif crit == "PE":
            if _is_null(r.get("coo_gw_unit")):
                _append_err(r, "COO: missing coo_gw_unit for PE")
            if _is_null(r.get("coo_gw")):
                _append_err(r, "COO: missing coo_gw for PE")

        # 3) Validasi terhadap invoice (only if both sides exist)
        inv_qty = _to_float(r.get("inv_quantity"))
        coo_qty = _to_float(r.get("coo_quantity"))
        if inv_qty is not None and coo_qty is not None and abs(inv_qty - coo_qty) > 0.01:
            _append_err(r, f"COO: coo_quantity != inv_quantity (inv {inv_qty}, coo {coo_qty})")

        inv_amt = _to_float(r.get("inv_amount"))
        coo_amt = _to_float(r.get("coo_amount"))
        if inv_amt is not None and coo_amt is not None and abs(inv_amt - coo_amt) > 0.01:
            _append_err(r, f"COO: coo_amount != inv_amount (inv {inv_amt}, coo {coo_amt})")

        if not _is_null(r.get("inv_amount_unit")) and not _is_null(r.get("coo_amount_unit")):
            if norm(r.get("inv_amount_unit")) != norm(r.get("coo_amount_unit")):
                _append_err(r, "COO: coo_amount_unit != inv_amount_unit")

        # note: di schema invoice kamu tidak ada inv_gw/inv_gw_unit per line.
        # Yang ada total inv_total_gw. Jadi rule coo_gw==inv_gw tidak bisa diterapkan 1:1.
        # Implementasi aman: bandingkan coo_gw dengan inv_total_gw hanya jika masuk akal,
        # atau skip supaya tidak bikin false positive.
        # Saya SKIP validasi gw vs inv_* karena field inv_gw tidak tersedia.

        # 4) Mapping minimal deterministic:
        # coo_invoice_no harus sama dengan inv_invoice_no
        if not _is_null(r.get("coo_invoice_no")) and not _is_null(r.get("inv_invoice_no")):
            if str(r["coo_invoice_no"]).strip() != str(r["inv_invoice_no"]).strip():
                _append_err(r, "COO: coo_invoice_no != inv_invoice_no")

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


# ==============================
# (NEW) CONVERT TO CSV -> CUSTOM FOLDER/PATH
# ==============================
def _convert_to_csv_path(blob_path, rows):
    if rows is None:
        raise Exception("Tidak ada data untuk CSV")

    # normalize dict -> list
    if isinstance(rows, dict):
        rows = [rows]

    if not isinstance(rows, list) or not rows:
        raise Exception("Tidak ada data untuk CSV")

    # union keys biar kolom lengkap
    keys = []
    seen = set()
    for r in rows:
        if isinstance(r, dict):
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)

    priority = ["match_score", "match_description"]
    # ambil yang ada dulu
    front = [k for k in priority if k in keys]
    # sisanya
    rest = [k for k in keys if k not in priority]
    keys = front + rest

    if not keys:
        raise Exception("Row CSV tidak memiliki kolom")

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    with open(tmp_file.name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
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


# ==============================
# MAIN RUN OCR
# ==============================

def run_ocr(invoice_name, uploaded_pdf_paths, with_total_container):

    run_id = uuid.uuid4().hex  # atau [:8] kalau mau lebih pendek
    prefix = TMP_PREFIX.rstrip("/")
    run_prefix = f"{prefix}/{run_id}"

    _save_run_meta(run_prefix, invoice_name, with_total_container)

    bucket = storage_client.bucket(BUCKET_NAME)

    try:
        # DETAIL: invoice+packing saja (2 file pertama dari UI)
        merged_pdf_detail = _merge_pdfs(uploaded_pdf_paths[:2])
        merged_pdf_detail = _compress_pdf_if_needed(merged_pdf_detail)

        # FULL: semua dokumen yang diupload (untuk total/container)
        file_uri_detail = _upload_temp_pdf_to_gcs(merged_pdf_detail, run_prefix, name="detail")

        file_uri_full = None
        if with_total_container:
            merged_pdf_full = _merge_pdfs(uploaded_pdf_paths)
            merged_pdf_full = _compress_pdf_if_needed(merged_pdf_full)
            file_uri_full = _upload_temp_pdf_to_gcs(merged_pdf_full, run_prefix, name="full")

        detail_input_uri = file_uri_full if (with_total_container and file_uri_full) else file_uri_detail

        # GET TOTAL ROW FROM GEMINI
        data_row = _call_gemini_json_uri(file_uri_detail, ROW_SYSTEM_INSTRUCTION, expect_array=False, retries=3)

        if isinstance(data_row, dict) and "total_row" in data_row:
            total_row = int(data_row["total_row"])
        else:
            raise Exception(f"total_row tidak ditemukan di response: {data_row}")

        # BATCH DETAIL EXTRACTION
        jobs = []
        first_index = 1
        batch_no = 1

        while first_index <= total_row:
            last_index = min(first_index + BATCH_SIZE - 1, total_row)

            prompt = build_detail_prompt(
                total_row=total_row,
                first_index=first_index,
                last_index=last_index
            )

            jobs.append((batch_no, prompt))
            first_index = last_index + 1
            batch_no += 1

        # default 2 worker (aman untuk 2 CPU & mengurangi risiko 429)
        MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
        MAX_WORKERS = max(1, min(MAX_WORKERS, len(jobs)))

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [
                ex.submit(_run_one_detail_batch, detail_input_uri, run_prefix, bn, prm)
                for (bn, prm) in jobs
            ]
            for f in as_completed(futures):
                bn, arr = f.result()
                results[bn] = arr

        # gabungkan hasil batch sesuai urutan batch_no (tanpa download ulang dari GCS)
        all_rows = []
        for bn in sorted(results.keys()):
            all_rows.extend(results[bn])

        if not all_rows:
            raise Exception("Tidak ada data detail hasil Gemini")

        # 0) reset match fields (Gemini tidak validasi)
        _reset_match_fields(all_rows)

        # 1) apply rule invoice po forward-fill sebelum ambil po_numbers
        _fill_forward(all_rows, "inv_customer_po_no")

        # 2) ambil po_numbers setelah carry-forward
        po_numbers = {
            row.get("inv_customer_po_no")
            for row in all_rows
            if isinstance(row, dict)
            and row.get("inv_customer_po_no")
            and str(row.get("inv_customer_po_no")).strip().lower() != "null"
        }

        po_lines = _stream_filter_po_lines(po_numbers)
        print("PO NUMBERS:", po_numbers)
        print("PO LINES FOUND:", len(po_lines))

        # 3) recompute seq global
        _recompute_seq_by_key(all_rows, "inv_customer_po_no", "inv_seq")
        _recompute_seq_by_key(all_rows, "inv_customer_po_no", "coo_seq")

        # 4) MAP PO TO DETAIL (sekali saja)
        all_rows = _map_po_to_details(po_lines, all_rows)

        # =========================
        # OPTIONAL: total/container
        # =========================
        total_data = None
        container_data = None
        if with_total_container:
            total_data = _call_gemini_json_uri(file_uri_full, TOTAL_SYSTEM_INSTRUCTION, expect_array=True, retries=3)

            container_data = _call_gemini_json_uri(file_uri_full, CONTAINER_SYSTEM_INSTRUCTION, expect_array=True, retries=3)

        # =========================
        # VALIDASI (python-based)
        # =========================
        all_rows = _validate_po(all_rows)

        _validate_invoice_rows(all_rows)
        _validate_packing_rows(all_rows)
        _validate_invoice_vs_packing_extra(all_rows)

        if with_total_container:
            _validate_bl_rows(all_rows)
            _validate_coo_rows(all_rows)

        _finalize_match_fields(all_rows)
        _drop_columns(all_rows, ["inv_messrs", "inv_messrs_address", "inv_gw", "inv_gw_unit"])

        # ==============================
        # (NEW) MAP PO TO TOTAL (DETAIL tetap batch, TOTAL tidak batch)
        # ==============================
        if total_data is not None:
            total_data = _map_po_to_total(total_data, po_lines, po_numbers)

        # CONVERT TO CSV
        # ==============================
        # (NEW) OUTPUT PER FOLDER
        # ==============================
        detail_csv_uri = _convert_to_csv_path(
            f"output/detail/{invoice_name}_detail.csv", all_rows
        )

        total_csv_uri = None
        if total_data is not None:
            total_csv_uri = _convert_to_csv_path(
                f"output/total/{invoice_name}_total.csv", total_data
            )

        container_csv_uri = None
        if container_data is not None:
            container_csv_uri = _convert_to_csv_path(
                f"output/container/{invoice_name}_container.csv", container_data
            )


        # CLEAN TEMP FILES
        prefix = TMP_PREFIX.rstrip("/")
        for blob in bucket.list_blobs(prefix=f"{run_prefix}/"):
            blob.delete()

        return {
            "detail_csv": detail_csv_uri,
            "total_csv": total_csv_uri,
            "container_csv": container_csv_uri,
        }

    finally:
        for blob in bucket.list_blobs(prefix=f"{run_prefix}/"):
            blob.delete()