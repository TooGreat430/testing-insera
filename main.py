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

    # ambil dulu berdasarkan report_type yang sedang aktif di session
    current_report_type = st.session_state["report_type"]

    result_prefix = f"output/{current_report_type}/"
    result_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=result_prefix))

    running_prefix = f"{TMP_PREFIX.rstrip('/')}/running/{current_report_type}/"
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

    if "start_date" not in st.session_state:
        st.session_state["start_date"] = default_start
    if "end_date" not in st.session_state:
        st.session_state["end_date"] = default_end

    top_left, top_right = st.columns([8, 1.3])

    with top_left:
        st.subheader("Download OCR Result")

    with top_right:
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        if st.button("↻ Refresh", key="btn_refresh_report", use_container_width=True):
            # klik button Streamlit sendiri sudah trigger rerun,
            # ini hanya untuk memastikan UI rerender dengan state saat ini
            st.rerun()

    report_type = st.selectbox(
        "Pilih Report",
        ["detail", "total", "container"],
        key="report_type"
    )

    # kalau report_type berubah, reload blob list sesuai pilihan baru
    result_prefix = f"output/{report_type}/"
    result_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=result_prefix))

    running_prefix = f"{TMP_PREFIX.rstrip('/')}/running/{report_type}/"
    running_blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=running_prefix))

    # =========================
    # Filter UI (WIB)
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

    # reset page kalau filter/report berubah
    sig = (report_type, start_date, end_date, show_running)
    if st.session_state.get("report_sig") != sig:
        st.session_state["report_sig"] = sig
        st.session_state["report_page"] = 1

    if not filtered:
        st.warning("Belum ada file result untuk range waktu tersebut.")
    else:
        rank = {"RUNNING": 2, "DONE": 1}
        filtered.sort(
            key=lambda x: (rank.get(x["status"], 0), x["updated"] or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True
        )

        # =========================
        # Pagination
        # =========================
        PAGE_SIZE = 10
        total_items = len(filtered)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)

        st.session_state["report_page"] = max(1, min(st.session_state["report_page"], total_pages))

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
                    file_bytes = blob.download_as_bytes()
                    st.download_button(
                        label="Download",
                        data=file_bytes,
                        file_name=f["invoice"],
                        mime="application/octet-stream",
                        key=f"dl_{report_type}_{f['invoice']}"
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