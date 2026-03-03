import streamlit as st
import tempfile
from function import run_ocr
from google.cloud import storage
from config import BUCKET_NAME, TMP_PREFIX
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
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* wrapper pagination */
.pager-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

/* Target tombol Prev/Next dengan key: btn_prev / btn_next */
div[data-testid="stButton"] button[kind="secondary"] {
  height: 42px !important;
  padding: 0 18px !important;
  border-radius: 10px !important;
  font-size: 16px !important;
  white-space: nowrap !important;
}

/* selectbox lebar & tinggi konsisten */
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

menu = st.sidebar.radio("Menu", ["Upload", "Report", "Sync PO"])

storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

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
            # optional hanya dipakai kalau lengkap
            with_total_container = bool(bl and coo)

            # file wajib
            files_to_process = [invoice, packing]

            # file optional hanya kalau lengkap
            if bl:
                files_to_process.append(bl)
            if coo:
                files_to_process.append(coo)
            if (bl or coo) and not with_total_container:
                st.info("BL/COO tidak lengkap, sistem tetap menghasilkan DETAIL (Invoice+PL+dokumen yang ada). Total/Container tidak dibuat.")

            pdf_paths = []

            for f in files_to_process:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tmp.write(f.read())
                tmp.close()
                pdf_paths.append(tmp.name)

            run_ocr(
                invoice_name=output_name or invoice.name.replace('.pdf',''),
                uploaded_pdf_paths=pdf_paths,
                with_total_container=with_total_container
            )

            st.success("OCR selesai diproses")

if menu == "Report":

    st.subheader("Download OCR Result")

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
    tmp_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=f"{TMP_PREFIX.rstrip('/')}/"))

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

    # DONE list dari output CSV
    done_filenames = set()
    for blob in result_blobs:
        if blob.name.endswith("/"):
            continue
        fname = os.path.basename(blob.name)
        done_filenames.add(fname)

        files_data.append({
            "invoice": fname,
            "status": "DONE",
            "updated": blob.updated,   # tz-aware datetime
            "path": blob.name
        })

    # RUNNING list dari meta.json
    meta_blobs = [b for b in tmp_blobs if b.name.endswith("/meta.json")]
    running_invoices = set()

    for mb in meta_blobs:
        meta = json.loads(mb.download_as_text())
        inv = meta.get("invoice_name")
        wtc = bool(meta.get("with_total_container"))

        # kalau user pilih total/container tapi run tsb tidak generate itu -> skip
        if report_type in ("total", "container") and not wtc:
            continue

        if inv:
            running_invoices.add(inv)

    if show_running:
        for inv in running_invoices:
            expected_name = f"{inv}_{report_type}.csv"
            # penting: cek DONE berdasarkan semua output, bukan berdasarkan filter
            if expected_name not in done_filenames:
                files_data.append({
                    "invoice": expected_name,
                    "status": "RUNNING",
                    "updated": None,
                    "path": None
                })

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
        rank = {"DONE": 2, "RUNNING": 1}
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

if menu == "Sync PO":
    st.subheader("Sync Purchase Order (SAP → GCS)")

    st.info(
        f"Fungsi ini akan:\n"
        f"1) Menghapus semua file di gs://{BUCKET_NAME}/{PO_PREFIX}/\n"
        f"2) Mengambil PO terbaru dari SAP\n"
        f"3) Upload 1 file JSON ke gs://{BUCKET_NAME}/{PO_PREFIX}/po_master.json"
    )

    # tampilkan kondisi folder po/
    po_blobs = [b for b in storage_client.list_blobs(BUCKET_NAME, prefix=f"{PO_PREFIX.rstrip('/')}/")
                if not b.name.endswith("/")]

    if po_blobs:
        latest = max(po_blobs, key=lambda b: b.updated or datetime.min.replace(tzinfo=timezone.utc))
        st.write(f"File PO saat ini: **{os.path.basename(latest.name)}**")
        st.write(f"Last updated (UTC): {latest.updated}")
        st.caption(f"Total file di {PO_PREFIX}/: {len(po_blobs)}")
    else:
        st.warning("Folder po/ masih kosong.")

    st.divider()

    # (opsional) tampilkan config sumber SAP dari env
    sap_url = os.getenv("SAP_ODATA_URL", "")
    st.caption("Config (env): SAP_ODATA_URL harus diset di environment / secrets.")

    if st.button("Pull PO dari SAP", type="primary"):
        with st.spinner("Menarik data PO dari SAP dan upload ke GCS..."):
            # uri, n = sync_po_from_sap_to_gcs(
            #     bucket_name=BUCKET_NAME,
            #     po_prefix=PO_PREFIX
            # )
            pass
        st.success(f"Berhasil upload {n} baris PO ke: {uri}")
