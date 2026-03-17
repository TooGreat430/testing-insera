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

if menu == "Upload":

    st.subheader("Upload Documents")

    invoice = st.file_uploader("Invoice*", type="pdf")
    packing = st.file_uploader("Packing List*", type="pdf")
    bl = st.file_uploader("Bill of Lading", type="pdf")
    coo = st.file_uploader("COO", type="pdf")

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

            for f in files_to_process:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tmp.write(f.read())
                tmp.close()
                pdf_paths.append(tmp.name)

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

                for p in pdf_paths:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass

                st.error(f"Gagal memulai OCR: {e}")

if menu == "Report":

    top_left, top_right = st.columns([8, 1.3])

    with top_left:
        st.subheader("Download OCR Result")

    with top_right:
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        if st.button("↻ Refresh", key="btn_refresh_report", use_container_width=True):
            st.rerun()

    report_type = st.selectbox(
        "Pilih Report",
        ["detail", "total", "container"]
    )

    # =========================
    # Filter UI (WIB)
    # =========================
    WIB = timezone(timedelta(hours=7))

    # ambil semua blob dulu (nanti baru difilter)
    result_prefix = f"output/{report_type}/"
    result_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=result_prefix))

    running_prefix = f"{TMP_PREFIX.rstrip('/')}/running/{report_type}/"
    running_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=running_prefix))

    # cari min/max updated untuk default filter
    done_updates = [b.updated for b in result_blobs if b.name and (not b.name.endswith("/"))]
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

    fcol1, fcol2, fcol3 = st.columns([2, 2, 2])
    with fcol1:
        start_date = st.date_input("FROM", value=default_start)
    with fcol2:
        end_date = st.date_input("TO", value=default_end)
    with fcol3:
        show_running = st.checkbox("Tampilkan RUNNING", value=True)

    if start_date > end_date:
        st.warning("Tanggal 'Dari' lebih besar dari 'Sampai'. Saya tukar otomatis.")
        start_date, end_date = end_date, start_date

    # convert range WIB -> UTC (blob.updated umumnya UTC)
    start_dt_wib = datetime.combine(start_date, datetime.min.time(), tzinfo=WIB)
    end_dt_wib_excl = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=WIB)
    start_dt_utc = start_dt_wib.astimezone(timezone.utc)
    end_dt_utc_excl = end_dt_wib_excl.astimezone(timezone.utc)

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

        lock_name = os.path.basename(blob.name)  # contoh: INV123_detail.lock
        expected_name = lock_name[:-5] + ".csv"  # -> INV123_detail.csv

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

        # kalau ada running lock yang lebih baru dari output, tampilkan RUNNING
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

        # DONE: filter by updated time
        dt = f.get("updated")
        if dt and (start_dt_utc <= dt < end_dt_utc_excl):
            filtered.append(f)

    if not filtered:
        st.warning("Belum ada file result untuk range waktu tersebut.")
    else:
        # DONE first (newest), RUNNING below
        rank = {"RUNNING": 2, "DONE": 1}
        filtered.sort(
            key=lambda x: (rank.get(x["status"], 0), x["updated"] or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True
        )

        # =========================
        # Pagination (10 items)
        # =========================
        PAGE_SIZE = 10
        total_items = len(filtered)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)

        # reset page kalau filter berubah / report_type berubah
        sig = (report_type, start_date, end_date, show_running)
        if st.session_state.get("report_sig") != sig:
            st.session_state["report_sig"] = sig
            st.session_state["report_page"] = 1

        # init & clamp page
        if "report_page" not in st.session_state:
            st.session_state["report_page"] = 1
        st.session_state["report_page"] = max(1, min(st.session_state["report_page"], total_pages))

        page = st.session_state["report_page"]
        start_idx = (page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_items = filtered[start_idx:end_idx]

        # =========================
        # Render table rows
        # =========================
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
                    file_bytes = blob.download_as_bytes()
                    st.download_button(
                        label="Download",
                        data=file_bytes,
                        file_name=f["invoice"],
                        mime="application/octet-stream",
                        key=f"dl_{report_type}_{f['invoice']}"  # ✅ unik
                    )

        # Pagination controls (BOTTOM + CENTER) => [Prev][Page][Next]
        # =========================
        def _prev_page():
            st.session_state["report_page"] = max(1, st.session_state["report_page"] - 1)

        def _next_page():
            st.session_state["report_page"] = min(total_pages, st.session_state["report_page"] + 1)

        # wrapper center
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
            st.markdown('</div>', unsafe_allow_html=True)

        with c3:
            st.button(
                "Next",
                on_click=_next_page,
                disabled=(st.session_state["report_page"] >= total_pages),
                key="btn_next",
                use_container_width=True
            )

        st.markdown("</div>", unsafe_allow_html=True)

        st.caption(f"Halaman {st.session_state['report_page']} / {total_pages} | Total {total_items} item | {PAGE_SIZE}/halaman")
