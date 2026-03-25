import streamlit as st
import tempfile
import subprocess
import sys
from function import create_running_markers, delete_running_markers
from google.cloud import storage
from config import BUCKET_NAME, TMP_PREFIX, PO_PREFIX
import os
import re
from datetime import datetime, timezone, timedelta
import json
import shutil
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment
import csv
from PyPDF2 import PdfReader

st.set_page_config(layout="wide")

st.markdown("""
<style>
    section[data-testid="stSidebar"] * {
        font-size: 18px !important;
    }

    .main-title {
        font-size: 42px;
        font-weight: 700;
        margin-bottom: 10px;
    }

    .pager-wrap {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
      margin-top: 12px;
    }

    div[data-testid="stButton"] button[kind="secondary"] {
      height: 42px !important;
      padding: 0 18px !important;
      border-radius: 10px !important;
      font-size: 16px !important;
      white-space: nowrap !important;
    }

    div.pager-select div[data-baseweb="select"] > div {
      min-height: 42px !important;
      border-radius: 10px !important;
      font-size: 16px !important;
    }

    div.pager-select {
      min-width: 110px;
    }
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo-polygon-insera-sena.jpg", width=120) 

with col2:
    st.markdown('<div class="main-title">OCR Gemini</div>', unsafe_allow_html=True)

menu = st.sidebar.radio("Menu", ["Upload", "Report"])

storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

def _launch_ocr_process(invoice_name, pdf_paths, with_total_container):
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_worker.py")

    cmd = [
        sys.executable,
        worker_path,
        invoice_name,
        "true" if with_total_container else "false",
        json.dumps(pdf_paths),
    ]

    return subprocess.Popen(
        cmd,
        start_new_session=True
    )

def _get_uploaded_extension(uploaded_file):
    name = (uploaded_file.name or "").lower()
    return os.path.splitext(name)[1]

def _save_uploaded_file_to_temp(uploaded_file):
    ext = _get_uploaded_extension(uploaded_file)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext if ext else ".tmp")
    tmp.write(uploaded_file.read())
    tmp.close()
    return tmp.name

def _count_pdf_pages(pdf_path: str) -> int:
    try:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except Exception as e:
        raise Exception(f"Gagal membaca jumlah halaman PDF hasil convert: {e}")


def _get_soffice_path() -> str:
    soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_path:
        raise Exception(
            "LibreOffice headless tidak ditemukan di server. "
            "Install libreoffice/soffice agar file xls/xlsx/csv bisa dikonversi ke PDF."
        )
    return soffice_path


def _run_soffice_convert(local_input_path: str, out_dir: str, convert_to: str):
    soffice_path = _get_soffice_path()

    # profile sementara supaya hasil convert lebih konsisten
    profile_dir = tempfile.mkdtemp(prefix="lo-profile-")
    profile_uri = Path(profile_dir).as_uri()

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
    out_dir = tempfile.mkdtemp()
    _run_soffice_convert(local_xls_path, out_dir, "xlsx")
    return _find_first_output_file(out_dir, ".xlsx")


def _validate_spreadsheet_pdf_result(pdf_path: str, source_name: str):
    total_pages = _count_pdf_pages(pdf_path)

    if total_pages == 0:
        raise Exception(f"Hasil convert PDF untuk '{source_name}' kosong.")

    # warning saja, jangan hard fail
    if total_pages > 100:
        print(f"[WARNING] {source_name} menghasilkan {total_pages} halaman")


def _convert_file_to_pdf(local_input_path):
    """
    Convert xls/xlsx/csv -> pdf
    Prinsip:
    - xlsx: convert langsung, jangan rewrite workbook
    - xls : convert ke xlsx via soffice, lalu convert langsung ke pdf
    - csv : buat xlsx sederhana dulu, lalu convert ke pdf
    """
    ext = os.path.splitext(local_input_path)[1].lower()

    if ext == ".pdf":
        return local_input_path

    if ext not in [".xls", ".xlsx", ".csv"]:
        raise Exception(f"Format file tidak didukung untuk conversion ke PDF: {ext}")

    source_for_pdf = local_input_path

    if ext == ".csv":
        source_for_pdf = _csv_to_xlsx(local_input_path)

    elif ext == ".xls":
        source_for_pdf = _xls_to_xlsx(local_input_path)

    out_dir = tempfile.mkdtemp()

    _run_soffice_convert(
        source_for_pdf,
        out_dir,
        "pdf:calc_pdf_Export"
    )

    pdf_path = _find_first_output_file(out_dir, ".pdf")
    _validate_spreadsheet_pdf_result(pdf_path, os.path.basename(local_input_path))

    return pdf_path

def _prepare_uploaded_file_as_pdf(uploaded_file):
    """
    Simpan upload ke temp file sesuai extension asli.
    Jika bukan PDF, convert ke PDF.
    Return final PDF path dan list temp files yang perlu dibersihkan.
    """
    temp_paths = []

    local_input_path = _save_uploaded_file_to_temp(uploaded_file)
    temp_paths.append(local_input_path)

    ext = os.path.splitext(local_input_path)[1].lower()

    if ext == ".pdf":
        return local_input_path, temp_paths

    pdf_path = _convert_file_to_pdf(local_input_path)
    temp_paths.append(pdf_path)

    return pdf_path, temp_paths

if menu == "Upload":

    st.subheader("Upload Documents")

    invoice = st.file_uploader("Invoice*", type=["pdf", "xlsx", "xls", "csv"])
    packing = st.file_uploader("Packing List*", type=["pdf", "xlsx", "xls", "csv"])
    bl = st.file_uploader("Bill of Lading", type=["pdf", "xlsx", "xls", "csv"])
    coo = st.file_uploader("COO", type=["pdf", "xlsx", "xls", "csv"])

    output_name = st.text_input("Output file name (default invoice name)")

    if st.button("Extract"):

        if not invoice or not packing:
            st.warning("Invoice dan Packing List wajib diupload")

        else:
            has_bl = bool(bl)
            has_coo = bool(coo)
            with_total_container = has_bl

            if has_coo and not has_bl:
                st.error("COO hanya bisa diproses jika Bill of Lading juga diupload.")
                st.stop()

            files_to_process = [invoice, packing]

            if bl:
                files_to_process.append(bl)
            if coo:
                files_to_process.append(coo)

            if not has_bl and not has_coo:
                st.info("Hanya Invoice dan Packing List yang diupload. Sistem akan menghasilkan DETAIL saja.")
            elif has_bl and not has_coo:
                st.info("Bill of Lading terdeteksi tanpa COO. Sistem akan tetap menghasilkan DETAIL, TOTAL, dan CONTAINER.")
            elif has_bl and has_coo:
                st.info("Dokumen lengkap terdeteksi. Sistem akan menghasilkan DETAIL, TOTAL, dan CONTAINER.")

            pdf_paths = []
            temp_cleanup_paths = []

            for f in files_to_process:
                final_pdf_path, created_paths = _prepare_uploaded_file_as_pdf(f)
                pdf_paths.append(final_pdf_path)
                temp_cleanup_paths.extend(created_paths)

            #butuh diubah menjadi base_name = os.path.splitext(invoice.name)[0]
            #final_invoice_name = (output_name or base_name).strip()
            final_invoice_name = (output_name or invoice.name.replace(".pdf", "")).strip()

            try:
                # bikin marker RUNNING lebih dulu supaya Report langsung bisa baca status
                create_running_markers(final_invoice_name, with_total_container)

                # jalankan OCR di process terpisah
                _launch_ocr_process(
                    invoice_name=final_invoice_name,
                    pdf_paths=pdf_paths,
                    with_total_container=with_total_container
                )

                st.success("OCR sedang diproses. Silakan cek menu Report untuk status RUNNING / DONE.")

            except Exception as e:
                try:
                    delete_running_markers(final_invoice_name, with_total_container)
                except Exception:
                    pass

                for p in temp_cleanup_paths:
                    try:
                        if os.path.isfile(p) and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass

                st.error(f"Gagal memulai OCR: {e}")

if menu == "Report":

    WIB = timezone(timedelta(hours=7))

    # =========================
    # Init session state
    # =========================
    if "report_type" not in st.session_state:
        st.session_state["report_type"] = "detail"
    if "show_running" not in st.session_state:
        st.session_state["show_running"] = True
    if "report_page" not in st.session_state:
        st.session_state["report_page"] = 1
    if "refresh_counter" not in st.session_state:
        st.session_state["refresh_counter"] = 0

    def _refresh_report():
        st.session_state["refresh_counter"] += 1

    top_left, top_right = st.columns([8, 1.3])

    with top_left:
        st.subheader("Download OCR Result")

    with top_right:
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        st.button(
            "↻ Refresh",
            key="btn_refresh_report",
            use_container_width=True,
            on_click=_refresh_report
        )

    # =========================
    # Report selector
    # =========================
    report_type = st.selectbox(
        "Pilih Report",
        ["detail", "total", "container"],
        key="report_type"
    )

    # =========================
    # Load blobs sesuai report_type aktif
    # =========================
    result_prefix = f"output/{report_type}/"
    result_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=result_prefix))

    running_prefix = f"{TMP_PREFIX.rstrip('/')}/running/{report_type}/"
    running_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=running_prefix))

    # =========================
    # Default date range
    # =========================
    done_updates = [b.updated for b in result_blobs if b.name and not b.name.endswith("/")]
    now_wib_date = datetime.now(WIB).date()

    if done_updates:
        max_dt = max(done_updates).astimezone(WIB)
        default_end = max_dt.date()
        default_start = (max_dt - timedelta(days=30)).date()
        if default_start > default_end:
            default_start = default_end
    else:
        default_start = now_wib_date
        default_end = now_wib_date

    if "start_date" not in st.session_state:
        st.session_state["start_date"] = default_start
    if "end_date" not in st.session_state:
        st.session_state["end_date"] = default_end

    # =========================
    # Filter UI
    # =========================
    fcol1, fcol2, fcol3 = st.columns([2, 2, 2])
    with fcol1:
        start_date = st.date_input("FROM", key="start_date")
    with fcol2:
        end_date = st.date_input("TO", key="end_date")
    with fcol3:
        show_running = st.checkbox("Tampilkan RUNNING", key="show_running")

    if start_date > end_date:
        st.warning("Tanggal 'Dari' lebih besar dari 'Sampai'. Saya tukar otomatis.")
        start_date, end_date = end_date, start_date
        st.session_state["start_date"] = start_date
        st.session_state["end_date"] = end_date

    # convert range WIB -> UTC
    start_dt_wib = datetime.combine(start_date, datetime.min.time(), tzinfo=WIB)
    end_dt_wib_excl = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=WIB)
    start_dt_utc = start_dt_wib.astimezone(timezone.utc)
    end_dt_utc_excl = end_dt_wib_excl.astimezone(timezone.utc)

    # =========================
    # Reset page hanya jika filter/report berubah
    # Refresh TIDAK reset report_type
    # =========================
    sig = (report_type, start_date, end_date, show_running)
    if st.session_state.get("report_sig") != sig:
        st.session_state["report_sig"] = sig
        st.session_state["report_page"] = 1

    # =========================
    # Build files_data
    # =========================
    files_data = []

    done_files = {}
    for blob in result_blobs:
        if blob.name.endswith("/"):
            continue

        fname = os.path.basename(blob.name)
        done_files[fname] = {
            "invoice": fname,
            "status": "DONE",
            "updated": blob.updated,
            "path": blob.name
        }

    running_files = {}
    for blob in running_blobs:
        if blob.name.endswith("/") or not blob.name.endswith(".lock"):
            continue

        lock_name = os.path.basename(blob.name)
        expected_name = lock_name[:-5] + ".csv"

        running_files[expected_name] = {
            "invoice": expected_name,
            "status": "RUNNING",
            "updated": blob.updated,
            "path": None
        }

    all_names = set(done_files.keys())
    if show_running:
        all_names |= set(running_files.keys())

    for name in all_names:
        done_item = done_files.get(name)
        running_item = running_files.get(name) if show_running else None

        if running_item and (
            done_item is None
            or (
                running_item["updated"] is not None
                and done_item["updated"] is not None
                and running_item["updated"] > done_item["updated"]
            )
        ):
            files_data.append(running_item)
        elif done_item:
            files_data.append(done_item)

    # =========================
    # Apply time filter (DONE only)
    # =========================
    filtered = []
    for f in files_data:
        if f["status"] == "RUNNING":
            filtered.append(f)
            continue

        dt = f.get("updated")
        if dt and (start_dt_utc <= dt < end_dt_utc_excl):
            filtered.append(f)

    if not filtered:
        st.warning("Belum ada file result untuk range waktu tersebut.")
    else:
        rank = {"RUNNING": 2, "DONE": 1}
        filtered.sort(
            key=lambda x: (
                rank.get(x["status"], 0),
                x["updated"] or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True
        )

        # =========================
        # Pagination
        # =========================
        PAGE_SIZE = 10
        total_items = len(filtered)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)

        st.session_state["report_page"] = max(
            1, min(st.session_state["report_page"], total_pages)
        )

        page = st.session_state["report_page"]
        start_idx = (page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_items = filtered[start_idx:end_idx]

        for f in page_items:
            col1, col2, col3, col4 = st.columns([3, 2, 3, 2])

            with col1:
                st.write(f["invoice"])

            with col2:
                if f["status"] == "DONE":
                    st.success("DONE")
                else:
                    st.warning("RUNNING")

            with col3:
                if f["updated"]:
                    wib_time = f["updated"].astimezone(WIB)
                    st.write(wib_time.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    st.write("-")

            with col4:
                if f["status"] == "DONE":
                    blob = bucket.blob(f["path"])

                    file_name = f["invoice"]
                    if not file_name.lower().endswith(".csv"):
                        file_name = f"{file_name}.csv"

                    file_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{f['path']}"

                    st.link_button(
                        "Download",
                        file_url,
                        use_container_width=True
                    )

        def _prev_page():
            st.session_state["report_page"] = max(1, st.session_state["report_page"] - 1)

        def _next_page():
            st.session_state["report_page"] = min(total_pages, st.session_state["report_page"] + 1)

        st.markdown('<div class="pager-wrap">', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([2, 1, 2])

        with c1:
            st.button(
                "Prev",
                on_click=_prev_page,
                disabled=(st.session_state["report_page"] <= 1),
                key="btn_prev",
                use_container_width=True
            )

        with c2:
            st.markdown('<div class="pager-select">', unsafe_allow_html=True)
            st.selectbox(
                label="",
                options=list(range(1, total_pages + 1)),
                key="report_page",
                label_visibility="collapsed"
            )
            st.markdown("</div>", unsafe_allow_html=True)

        with c3:
            st.button(
                "Next",
                on_click=_next_page,
                disabled=(st.session_state["report_page"] >= total_pages),
                key="btn_next",
                use_container_width=True
            )

        st.markdown("</div>", unsafe_allow_html=True)

        st.caption(
            f"Halaman {st.session_state['report_page']} / {total_pages} | "
            f"Total {total_items} item | {PAGE_SIZE}/halaman"
        )