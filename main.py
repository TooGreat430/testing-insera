import streamlit as st
import tempfile
from function import run_ocr
from google.cloud import storage
from config import BUCKET_NAME, TMP_PREFIX
import os
import re
from datetime import timezone, timedelta
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

col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo-polygon-insera-sena.jpg", width=120) 

with col2:
    st.markdown('<div class="main-title">OCR Gemini</div>', unsafe_allow_html=True)

menu = st.sidebar.radio("Menu", ["Upload", "Report"])

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

    # ... di menu Report ...

    result_prefix = f"output/{report_type}/"

    result_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=result_prefix))
    tmp_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=f"{TMP_PREFIX.rstrip('/')}/"))

    files_data = []  # <-- WAJIB ADA

    # DONE list dari output CSV
    for blob in result_blobs:
        if blob.name.endswith("/"):
            continue

        files_data.append({
            "invoice": os.path.basename(blob.name),
            "status": "DONE",
            "updated": blob.updated,
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

    for inv in running_invoices:
        already_done = any(f["invoice"] == f"{inv}_{report_type}.csv" for f in files_data)
        if not already_done:
            files_data.append({
                "invoice": f"{inv}_{report_type}.csv",
                "status": "RUNNING",
                "updated": None,
                "path": None
            })

    # setelah ini baru aman:
    if not files_data:
        st.warning("Belum ada file result.")
    else:
        # Sort by updated time (DONE first newest)
        files_data = sorted(
            files_data,
            key=lambda x: (x["status"], x["updated"] or 0),
            reverse=True
        )

        for f in files_data:

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
                    wib_time = f["updated"].astimezone(timezone(timedelta(hours=7)))
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
                        mime="application/octet-stream"
                    )

