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
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import * 
from total import TOTAL_SYSTEM_INSTRUCTION 
from container import CONTAINER_SYSTEM_INSTRUCTION
from pathlib import Path
from email import policy
from email.parser import BytesParser
from weasyprint import HTML
import shutil
from detail import (
    build_index_prompt,
    build_header_prompt,
    build_detail_prompt_from_index,
    HEADER_SCHEMA_TEXT as HEADER_FIELDS,      # header keys
    DETAIL_LINE_FIELDS,
    DETAIL_LINE_NUM_FIELDS,
    DETAIL_CSV_FIELD_ORDER_FINAL
)
from row import ROW_SYSTEM_INSTRUCTION 
import uuid

BATCH_SIZE = 30
storage_client = storage.Client() 
genai_client = genai.Client( vertexai=True, project=PROJECT_ID, location=LOCATION, )

# ==============================
# SANITIZER: pl_package_unit
# ==============================

PL_PACKAGE_UNIT_MAP = {
    "ctn": "CT",
    "ctns": "CT",
    "carton": "CT",
    "cartons": "CT",

    "plt": "PX",
    "plts": "PX",
    "pallet": "PX",
    "pallets": "PX",

    "bal": "BL",
    "bale": "BL",
    "bales": "BL",
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

def _sum_numeric(rows: list, key: str) -> float:
    total = 0.0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        v = _to_float(r.get(key))
        if v is not None:
            total += v
    return total

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

    total_obj = {
        # =========================
        # DETAIL
        # =========================
        "match_score": "true",
        "match_description": "null",
        
        "inv_quantity": _sum_numeric(detail_rows, "inv_quantity"),
        "inv_amount": _sum_numeric(detail_rows, "inv_amount"),
        "inv_total_quantity": _first_number(detail_rows, "inv_total_quantity", default=0),
        "inv_total_amount": _first_number(detail_rows, "inv_total_amount", default=0),
        "inv_total_nw": _first_number(detail_rows, "inv_total_nw", default=0),
        "inv_total_gw": _first_number(detail_rows, "inv_total_gw", default=0),
        "inv_total_volume": _first_number(detail_rows, "inv_total_volume", default=0),
        "inv_total_package": _first_number(detail_rows, "inv_total_package", default=0),

        "pl_package_unit": _first_text(detail_rows, "pl_package_unit"),
        "pl_package_count": _sum_numeric(detail_rows, "pl_package_count"),
        "pl_nw": _sum_numeric(detail_rows, "pl_nw"),
        "pl_gw": _sum_numeric(detail_rows, "pl_gw"),
        "pl_volume": _sum_numeric(detail_rows, "pl_volume"),
        "pl_total_quantity": _first_number(detail_rows, "pl_total_quantity", default=0),
        "pl_total_amount": _first_number(detail_rows, "pl_total_amount", default=0),
        "pl_total_nw": _first_number(detail_rows, "pl_total_nw", default=0),
        "pl_total_gw": _first_number(detail_rows, "pl_total_gw", default=0),
        "pl_total_volume": _first_number(detail_rows, "pl_total_volume", default=0),
        "pl_total_package": _first_number(detail_rows, "pl_total_package", default=0),

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
        "bl_gw_unit": _first_text(container_rows, "bl_gw_unit"),
        "bl_gw": _sum_numeric(container_rows, "bl_gw"),
        "bl_volume_unit": _first_text(container_rows, "bl_volume_unit"),
        "bl_volume": _sum_numeric(container_rows, "bl_volume"),
        "bl_package_count": _sum_numeric(container_rows, "bl_package_count"),
        "bl_package_unit": _first_text(container_rows, "bl_package_unit"),
    }

    _ensure_total_keys(total_obj)

    # WAJIB 1 line saja
    return [total_obj]

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

    def _cmp_text(left_label: str, left_val, right_label: str, right_val):
        if _is_null(left_val) or _is_null(right_val):
            return
        if _normalize_compare_text(left_val) != _normalize_compare_text(right_val):
            _append_total_error(
                total_obj,
                f"Total: {left_label} != {right_label} ({left_val} vs {right_val})"
            )

    # 1) cek total bl_package_count vs total pl_package_count
    _cmp_num("bl_package_count", "pl_package_count")

    # 2) cek bl_package_unit vs pl_package_unit
    _cmp_text(
        "bl_package_unit",
        total_obj.get("bl_package_unit"),
        "pl_package_unit",
        total_obj.get("pl_package_unit")
    )

    # 3) cek total bl_gw vs total pl_gw
    _cmp_num("bl_gw", "pl_gw")

    # 4) cek bl_gw_unit vs pl_gw_unit
    # NOTE:
    # di output total yang Anda minta tidak ada field pl_gw_unit,
    # jadi validasi diambil dari source detail: pl_weight_unit
    _cmp_text(
        "bl_gw_unit",
        total_obj.get("bl_gw_unit"),
        "pl_weight_unit",
        _first_non_null(detail_rows, "pl_weight_unit")
    )

    # 5) cek total bl_volume vs total pl_volume
    _cmp_num("bl_volume", "pl_volume")

    # 6) cek bl_volume_unit vs pl_volume_unit
    _cmp_text(
        "bl_volume_unit",
        total_obj.get("bl_volume_unit"),
        "pl_volume_unit",
        _first_non_null(detail_rows, "pl_volume_unit")
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

def _postprocess_pl_package_unit(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue

        row["pl_package_unit"] = _sanitize_pl_package_unit(
            row.get("pl_package_unit")
        )

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

HTML_LIKE_MARKERS = (
    b"content-type: multipart/",
    b"content-type: text/html",
    b"<!doctype html",
    b"<html",
    b"quoted-printable",
)

def _read_head(path, n=8192):
    with open(path, "rb") as f:
        return f.read(n)

def _looks_like_xlsx(head: bytes) -> bool:
    return head.startswith(b"PK\x03\x04")

def _looks_like_ole_xls(head: bytes) -> bool:
    return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

def _looks_like_html_wrapped_xls(head: bytes) -> bool:
    low = head.lower()
    return any(marker in low for marker in HTML_LIKE_MARKERS)

def _extract_html_from_wrapped_xls(src_path, workdir):
    raw = Path(src_path).read_bytes()
    html_path = Path(workdir) / f"{Path(src_path).stem}_extracted.html"

    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue
                if part.get_content_type() == "text/html":
                    html = part.get_content()
                    html_path.write_text(html, encoding="utf-8")
                    return str(html_path)
    except Exception:
        pass

    text = raw.decode("utf-8", errors="replace")
    m = re.search(r"(?is)(<!DOCTYPE html.*|<html.*)</html>", text)
    if m:
        html_path.write_text(m.group(0), encoding="utf-8")
        return str(html_path)

    raise Exception("HTML part tidak ditemukan dari file .xls")

def _inject_print_css(html: str) -> str:
    extra_css = """
    <style>
    @page { size: Letter landscape; margin: 0.18in; }
    html, body {
        print-color-adjust: exact;
        -webkit-print-color-adjust: exact;
    }
    table, tr, td, th { page-break-inside: avoid; }
    img { max-width: 100%; }
    </style>
    """

    if "</head>" in html:
        return html.replace("</head>", extra_css + "\n</head>", 1)
    return extra_css + "\n" + html

def _render_html_to_pdf(html_path, output_pdf):
    html = Path(html_path).read_text(encoding="utf-8", errors="replace")
    html = _inject_print_css(html)
    HTML(string=html, base_url=str(Path(html_path).parent)).write_pdf(output_pdf)

def _convert_with_libreoffice(src_path, output_pdf):
    outdir = str(Path(output_pdf).parent)

    subprocess.run([
        "soffice",
        "--headless",
        "--convert-to", "pdf",
        "--outdir", outdir,
        src_path,
    ], check=True)

    produced = str(Path(outdir) / f"{Path(src_path).stem}.pdf")
    if os.path.abspath(produced) != os.path.abspath(output_pdf):
        shutil.move(produced, output_pdf)

def _pdf_contains_raw_markup(pdf_path) -> bool:
    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages[:2]).lower()

    markers = [
        "content-type:",
        "multipart/mixed",
        "quoted-printable",
        "<html",
        "<!doctype",
        "style type=",
        ".c0 {",
    ]
    return any(m in text for m in markers)

def _ensure_input_is_pdf(src_path: str) -> str:
    ext = Path(src_path).suffix.lower()

    if ext == ".pdf":
        return src_path

    tmp_pdf_path = None

    try:
        tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_pdf.close()
        tmp_pdf_path = tmp_pdf.name

        head = _read_head(src_path)

        if _looks_like_html_wrapped_xls(head):
            workdir = tempfile.mkdtemp()
            try:
                html_path = _extract_html_from_wrapped_xls(src_path, workdir)
                _render_html_to_pdf(html_path, tmp_pdf_path)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
            return tmp_pdf_path

        if ext in (".xls", ".xlsx") or _looks_like_xlsx(head) or _looks_like_ole_xls(head):
            _convert_with_libreoffice(src_path, tmp_pdf_path)

            if _pdf_contains_raw_markup(tmp_pdf_path):
                try:
                    workdir = tempfile.mkdtemp()
                    try:
                        html_path = _extract_html_from_wrapped_xls(src_path, workdir)
                        _render_html_to_pdf(html_path, tmp_pdf_path)
                    finally:
                        shutil.rmtree(workdir, ignore_errors=True)
                except Exception:
                    pass

            return tmp_pdf_path

        raise Exception(f"Format file tidak didukung: {src_path}")

    except Exception:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            try:
                os.remove(tmp_pdf_path)
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
            top_p=0,
            seed=42,
            candidate_count = 1,
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

def _map_po_to_details(po_lines, detail_rows):
    """
    Join key priority:
    1. inv_customer_po_no <-> po_no
       + inv_spart_item_no <-> vendor_article_no OR sap_article_no
    2. fallback:
       inv_customer_po_no <-> po_no
       + inv_description <-> po_text

    Normalisasi hanya untuk matching.
    Data output tetap pakai value asli dari po_line.
    """

    # index article: (po_no_norm, article_norm) -> list[(idx, po_line)]
    po_article_index = {}

    # index description: (po_no_norm, desc_norm) -> list[(idx, po_line)]
    po_desc_index = {}

    for idx, line in enumerate(po_lines):
        po_no_norm = _norm_po_number(line.get("po_no"))
        if not po_no_norm:
            continue

        v_norm = _norm_key(line.get("vendor_article_no") or line.get("po_vendor_article_no"))
        s_norm = _norm_key(line.get("sap_article_no") or line.get("po_sap_article_no"))
        d_norm = _norm_desc(line.get("po_text"))

        if v_norm:
            po_article_index.setdefault((po_no_norm, v_norm), []).append((idx, line))

        if s_norm:
            po_article_index.setdefault((po_no_norm, s_norm), []).append((idx, line))

        if d_norm:
            po_desc_index.setdefault((po_no_norm, d_norm), []).append((idx, line))

    used = set()  # (po_no_norm, idx_in_po_lines)

    for row in detail_rows:
        if not isinstance(row, dict):
            continue

        inv_po_norm = _norm_po_number(row.get("inv_customer_po_no"))
        inv_article_norm = _norm_key(row.get("inv_spart_item_no"))
        inv_desc_norm = _norm_desc(row.get("inv_description"))

        if not inv_po_norm:
            row["_po_mapped"] = False
            continue

        chosen = None
        chosen_key = None

        # =========================
        # PRIORITAS 1: match by article
        # =========================
        candidates = []
        if inv_article_norm:
            candidates = po_article_index.get((inv_po_norm, inv_article_norm), [])

        for idx, po_line in candidates:
            key = (inv_po_norm, idx)
            if key in used:
                continue
            chosen = po_line
            chosen_key = key
            row["_po_match_source"] = "article"
            break

        # =========================
        # PRIORITAS 2: fallback by description
        # =========================
        if chosen is None and inv_desc_norm:
            candidates = po_desc_index.get((inv_po_norm, inv_desc_norm), [])

            for idx, po_line in candidates:
                key = (inv_po_norm, idx)
                if key in used:
                    continue
                chosen = po_line
                chosen_key = key
                row["_po_match_source"] = "description"
                break

        if chosen:
            used.add(chosen_key)
            row["_po_mapped"] = True
            row["_po_data"] = chosen
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

        if norm(r.get("pl_messrs")) and "PT INSERA SENA" not in norm(r.get("pl_messrs")):
            _append_err(r, "PackingList: pl_messrs bukan PT Insera Sena")

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
    - inv_messrs == pl_messrs (compare 20 huruf pertama setelah normalisasi)
    - inv_messrs_address == pl_messrs_address
    - inv_gw == coo_gw
    - inv_gw_unit == coo_gw_unit
    """

    def norm_prefix_20(s):
        return _normalize_compare_prefix(s, 20)

    def norm(s):
        if _is_null(s):
            return ""
        return re.sub(r"\s+", " ", str(s).strip().upper())

    for r in rows:
        if not isinstance(r, dict):
            continue

        # inv_messrs vs pl_messrs -> compare 20 huruf pertama setelah normalisasi
        if not _is_null(r.get("inv_messrs")) and not _is_null(r.get("pl_messrs")):
            if norm_prefix_20(r.get("inv_messrs")) != norm_prefix_20(r.get("pl_messrs")):
                _append_err(r, "Invoice vs PL: inv_messrs != pl_messrs")

        # inv_messrs_address vs pl_messrs_address
        inv_messrs_address = r.get("inv_messrs_address")
        pl_messrs_address = r.get("pl_messrs_address")
        if not _is_null(inv_messrs_address) and not _is_null(pl_messrs_address):
            if norm_prefix_20(inv_messrs_address) != norm_prefix_20(pl_messrs_address):
                _append_err(
                    r,
                    f"Invoice vs PL: inv_messrs_address != pl_messrs_address "
                    f"(inv {inv_messrs_address}, pl {pl_messrs_address})"
                )

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
        inv_vendor = r.get("inv_vendor_name")
        bl_seller = r.get("bl_seller_name")

        if not _is_null(inv_vendor) and not _is_null(bl_seller):
            if norm_prefix_20(inv_vendor) != norm_prefix_20(bl_seller):
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


def _normalize_inv_spart_item_no(value):
    """
    Gabungkan whitespace di item code OCR.
    Contoh:
    - 'BAXVLPLG38802 OR' -> 'BAXVLPLG38802OR'
    - ' BAXV LP LG38802   OR ' -> 'BAXVLPLG38802OR'
    """
    if value is None:
        return "null"

    s = str(value).strip()

    if s == "" or s.lower() == "null":
        return "null"

    # hapus semua whitespace: spasi, tab, newline, non-breaking space, dll
    s = re.sub(r"[\s\u00A0]+", "", s)

    return s


def _postprocess_inv_spart_item_no(rows: list):
    for row in rows:
        if not isinstance(row, dict):
            continue
        row["inv_spart_item_no"] = _normalize_inv_spart_item_no(
            row.get("inv_spart_item_no")
        )


# ==============================
# MAIN RUN OCR
# ==============================

def run_ocr(invoice_name, uploaded_pdf_paths, with_total_container):

    # Guard backend supaya COO tidak pernah diproses tanpa Bill of Lading.
    # Kontrak dari UI: jika ada 3 file tetapi with_total_container=False,
    # maka file ke-3 adalah COO tanpa BL dan harus ditolak.
    if len(uploaded_pdf_paths) == 3 and not with_total_container:
        raise Exception("COO hanya bisa diproses jika Bill of Lading juga diupload.")

    normalized_pdf_paths = []
    temp_local_paths = []

    run_id = uuid.uuid4().hex
    prefix = TMP_PREFIX.rstrip("/")
    run_prefix = f"{prefix}/{run_id}"

    create_running_markers(invoice_name, with_total_container)

    bucket = storage_client.bucket(BUCKET_NAME)

    try:
        for p in uploaded_pdf_paths:
            normalized = _ensure_input_is_pdf(p)
            normalized_pdf_paths.append(normalized)

            if os.path.abspath(str(normalized)) != os.path.abspath(str(p)):
                temp_local_paths.append(normalized)

        # DETAIL: invoice+packing saja (2 file pertama dari UI)
        merged_pdf_detail = _merge_pdfs(normalized_pdf_paths[:2])
        merged_pdf_detail = _compress_pdf_if_needed(merged_pdf_detail)

        # FULL: semua dokumen yang diupload (untuk total/container)
        file_uri_detail = _upload_temp_pdf_to_gcs(merged_pdf_detail, run_prefix, name="detail")

        file_uri_full = None

        has_extra_docs = len(normalized_pdf_paths) > 2
        if has_extra_docs:
            merged_pdf_full = _merge_pdfs(normalized_pdf_paths)
            merged_pdf_full = _compress_pdf_if_needed(merged_pdf_full)
            file_uri_full = _upload_temp_pdf_to_gcs(merged_pdf_full, run_prefix, name="full")

        detail_input_uri = file_uri_full if file_uri_full else file_uri_detail

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

        # BATCH DETAIL EXTRACTION
        jobs = []
        first_index = 1
        batch_no = 1

        while first_index <= total_row:
            last_index = min(first_index + BATCH_SIZE - 1, total_row)

            index_slice = index_items[first_index-1:last_index]  # 1-based -> 0-based

            prompt = build_detail_prompt_from_index(
                total_row=total_row,
                index_slice=index_slice,
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

        _ensure_all_detail_keys(all_rows)

        _apply_header_to_rows(all_rows, header_obj)

        _postprocess_inv_spart_item_no(all_rows)
        _postprocess_pl_package_unit(all_rows)

        # 0) reset match fields (Gemini tidak validasi)
        _reset_match_fields(all_rows)

        # 1) apply rule invoice po forward-fill sebelum ambil po_numbers
        _fill_forward(all_rows, "inv_customer_po_no")

        #  FIX: kalau inv_price_unit null, samakan dengan inv_amount_unit
        _fill_inv_price_unit_from_amount_unit(all_rows)

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
        _recompute_seq_by_key(all_rows, "inv_invoice_no", "inv_seq")
        _recompute_seq_by_key(all_rows, "coo_no", "coo_seq")

        # 4) MAP PO TO DETAIL (sekali saja)
        all_rows = _map_po_to_details(po_lines, all_rows)

        # =========================
        # OPTIONAL: total/container
        # =========================
        # Total dan container dibuat setiap Bill of Lading tersedia.
        total_data = None
        container_data = None
        if with_total_container:
            container_data = _call_gemini_json_uri(
                file_uri_full,
                CONTAINER_SYSTEM_INSTRUCTION,
                expect_array=True,
                retries=3
            )

        # =========================
        # VALIDASI (python-based)
        # =========================
        all_rows = _validate_po(all_rows)

        _validate_invoice_rows(all_rows)
        _validate_packing_rows(all_rows)
        _validate_invoice_vs_packing_extra(all_rows)

        _validate_bl_rows(all_rows)
        _validate_coo_rows(all_rows)

        _finalize_match_fields(all_rows)
        _drop_columns(all_rows, ["inv_messrs", "inv_messrs_address", "inv_gw", "inv_gw_unit"])

        if with_total_container:
            total_data = _build_total_from_detail_and_container(all_rows, container_data)
            total_data = _validate_total_rows(total_data, all_rows)

        # ==============================
        # (NEW) MAP PO TO TOTAL (DETAIL tetap batch, TOTAL tidak batch)
        # ==============================
        # if total_data is not None:
        #     total_data = _map_po_to_total(total_data, po_lines, po_numbers)

        _rename_final_fields(all_rows)
        # CONVERT TO CSV
        # ==============================
        # (NEW) OUTPUT PER FOLDER
        # ==============================
        detail_csv_uri = _convert_to_csv_path(
            f"output/detail/{invoice_name}_detail.csv",
            all_rows,
            field_order=DETAIL_CSV_FIELD_ORDER_FINAL
        )

        total_csv_uri = None
        if total_data is not None:
            total_csv_uri = _convert_to_csv_path(
                f"output/total/{invoice_name}_total.csv",
                total_data,
                field_order=TOTAL_CSV_FIELD_ORDER_FINAL
            )

        container_csv_uri = None
        if container_data is not None:
            container_csv_uri = _convert_to_csv_path(
                f"output/container/{invoice_name}_container.csv", container_data
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

        for blob in bucket.list_blobs(prefix=f"{run_prefix}/"):
            blob.delete()

        for p in temp_local_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass