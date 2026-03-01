import json

# =========================
# HEADER FIELDS (doc-level)
# =========================
HEADER_SCHEMA_TEXT = [
    "inv_invoice_no","inv_invoice_date","inv_messrs","inv_messrs_address","inv_vendor_name",
    "inv_vendor_address","inv_incoterms_terms","inv_terms","inv_coo_commodity_origin",
    "pl_invoice_no","pl_invoice_date","pl_messrs","pl_messrs_address",
    "bl_shipper_name","bl_shipper_address","bl_no","bl_date","bl_consignee_name","bl_consignee_address",
    "bl_consignee_tax_id","bl_seller_name","bl_seller_address","bl_lc_number","bl_notify_party","bl_vessel",
    "bl_voyage_no","bl_port_of_loading","bl_port_of_destination",
    "coo_no","coo_form_type","coo_invoice_no","coo_invoice_date","coo_shipper_name","coo_shipper_address",
    "coo_consignee_name","coo_consignee_address","coo_consignee_tax_id","coo_producer_name","coo_producer_address",
    "coo_departure_date","coo_vessel","coo_voyage_no","coo_port_of_discharge",
]

# =========================
# CONTENT FIELDS (line-level)
# =========================
DETAIL_LINE_SCHEMA_TEXT = """{
  "inv_customer_po_no": "string",
  "inv_seq": "number",
  "inv_spart_item_no": "string",
  "inv_description": "string",
  "inv_gw": "string",
  "inv_gw_unit": "string",
  "inv_quantity": "number",
  "inv_quantity_unit": "string",
  "inv_unit_price": "number",
  "inv_price_unit": "string",
  "inv_amount": "number",
  "inv_amount_unit": "string",
  "inv_total_quantity": "number",
  "inv_total_amount": "number",
  "inv_total_nw": "number",
  "inv_total_gw": "number",
  "inv_total_volume": "number",
  "inv_total_package": "number",

  "pl_item_no": "number",
  "pl_description": "string",
  "pl_quantity": "number",
  "pl_package_unit": "string",
  "pl_package_count": "number",
  "pl_weight_unit": "string",
  "pl_nw": "number",
  "pl_gw": "number",
  "pl_volume_unit": "string",
  "pl_volume": "number",
  "pl_total_quantity": "number",
  "pl_total_amount": "number",
  "pl_total_nw": "number",
  "pl_total_gw": "number",
  "pl_total_volume": "number",
  "pl_total_package": "number",

  "po_no": "string",
  "po_vendor_article_no": "string",
  "po_text": "string",
  "po_sap_article_no": "string",
  "po_line": "number",
  "po_quantity": "number",
  "po_unit": "string",
  "po_price": "number",
  "po_currency": "string",
  "po_info_record_price": "number",
  "po_info_record_currency": "string",

  "bl_description": "string",
  "bl_hs_code": "string",
  "bl_mark_number": "string",

  "coo_seq": "number",
  "coo_mark_number": "string",
  "coo_description": "string",
  "coo_hs_code": "string",
  "coo_quantity": "number",
  "coo_unit": "string",
  "coo_package_count": "number",
  "coo_package_unit": "string",
  "coo_gw_unit": "string",
  "coo_gw": "number",
  "coo_amount_unit": "string",
  "coo_amount": "number",
  "coo_criteria": "string",
  "coo_origin_country": "string",
  "coo_customer_po_no": "string"
}"""

# dipakai Python untuk "ensure semua kolom ada"
DETAIL_LINE_FIELDS = [
    "inv_customer_po_no","inv_seq","inv_spart_item_no","inv_description","inv_gw","inv_gw_unit",
    "inv_quantity","inv_quantity_unit","inv_unit_price","inv_price_unit","inv_amount","inv_amount_unit",
    "inv_total_quantity","inv_total_amount","inv_total_nw","inv_total_gw","inv_total_volume","inv_total_package",

    "pl_item_no","pl_description","pl_quantity","pl_package_unit","pl_package_count","pl_weight_unit","pl_nw","pl_gw",
    "pl_volume_unit","pl_volume","pl_total_quantity","pl_total_amount","pl_total_nw","pl_total_gw","pl_total_volume","pl_total_package",

    "po_no","po_vendor_article_no","po_text","po_sap_article_no","po_line","po_quantity","po_unit","po_price","po_currency",
    "po_info_record_price","po_info_record_currency",

    "bl_description","bl_hs_code","bl_mark_number",

    "coo_seq","coo_mark_number","coo_description","coo_hs_code","coo_quantity","coo_unit","coo_package_count","coo_package_unit",
    "coo_gw_unit","coo_gw","coo_amount_unit","coo_amount","coo_criteria","coo_origin_country","coo_customer_po_no",
]

DETAIL_LINE_NUM_FIELDS = {
    "inv_seq","inv_quantity","inv_unit_price","inv_amount",
    "inv_total_quantity","inv_total_amount","inv_total_nw","inv_total_gw","inv_total_volume","inv_total_package",

    "pl_item_no","pl_quantity","pl_package_count","pl_nw","pl_gw","pl_volume",
    "pl_total_quantity","pl_total_amount","pl_total_nw","pl_total_gw","pl_total_volume","pl_total_package",

    "po_line","po_quantity","po_price","po_info_record_price",

    "coo_seq","coo_quantity","coo_package_count","coo_gw","coo_amount",
}

def build_index_prompt(total_row: int) -> str:
    return f"""
ROLE:
Anda adalah AI IDP professional yang fokus membuat INDEX line items INVOICE.
Rule-based, deterministik, anti-halusinasi.

TUGAS:
Buat daftar INDEX untuk SEMUA line item di INVOICE SAJA.
INDEX ini akan dipakai sebagai "anchor" untuk ekstraksi detail batch berikutnya.

ATURAN:
1) Output HANYA JSON ARRAY, tanpa teks lain.
2) Panjang array harus = {total_row} (jika invoice memang memiliki {total_row} line item).
3) Setiap object mewakili 1 line item invoice berdasarkan urutan kemunculan di invoice.
4) DILARANG markdown / plan / penjelasan.
5) Jika suatu field tidak ada di dokumen → isi "null" (string) atau 0 (angka).

SCHEMA OUTPUT (INDEX):
[
  {{
    "idx": number,
    "inv_spart_item_no": "string",
    "inv_description": "string",
    "inv_quantity": number,
    "inv_quantity_unit": "string",
    "inv_unit_price": number,
    "inv_price_unit": "string",
    "inv_amount": number
  }}
]

CATATAN:
- Fokus INVOICE line item table.
- Jangan ikutkan packing list / BL / COO untuk index.
"""

def build_header_prompt() -> str:
    return """
ROLE:
Anda adalah AI IDP professional yang fokus mengambil HEADER dokumen (bukan line item).
Rule-based, deterministik, anti-halusinasi.

TUGAS:
Ekstrak HEADER (doc-level) dari dokumen yang tersedia:
1) Invoice (wajib)
2) Packing List (wajib)
3) Bill of Lading (opsional)
4) COO (opsional)

ATURAN:
1) Output HANYA 1 JSON OBJECT, tanpa teks lain.
2) DILARANG markdown / plan / penjelasan.
3) Tidak boleh JSON literal null → gunakan string "null".
4) Format tanggal: YYYY-MM-DD.
5) Jika dokumen tidak ada → semua field prefix dokumen tersebut = "null".

OUTPUT SCHEMA (HEADER ONLY):
{
  "inv_invoice_no": "string",
  "inv_invoice_date": "string",
  "inv_messrs": "string",
  "inv_messrs_address": "string",
  "inv_vendor_name": "string",
  "inv_vendor_address": "string",
  "inv_incoterms_terms": "string",
  "inv_terms": "string",
  "inv_coo_commodity_origin": "string",

  "pl_invoice_no": "string",
  "pl_invoice_date": "string",
  "pl_messrs": "string",
  "pl_messrs_address": "string",

  "bl_shipper_name": "string",
  "bl_shipper_address": "string",
  "bl_no": "string",
  "bl_date": "string",
  "bl_consignee_name": "string",
  "bl_consignee_address": "string",
  "bl_consignee_tax_id": "string",
  "bl_seller_name": "string",
  "bl_seller_address": "string",
  "bl_lc_number": "string",
  "bl_notify_party": "string",
  "bl_vessel": "string",
  "bl_voyage_no": "string",
  "bl_port_of_loading": "string",
  "bl_port_of_destination": "string",

  "coo_no": "string",
  "coo_form_type": "string",
  "coo_invoice_no": "string",
  "coo_invoice_date": "string",
  "coo_shipper_name": "string",
  "coo_shipper_address": "string",
  "coo_consignee_name": "string",
  "coo_consignee_address": "string",
  "coo_consignee_tax_id": "string",
  "coo_producer_name": "string",
  "coo_producer_address": "string",
  "coo_departure_date": "string",
  "coo_vessel": "string",
  "coo_voyage_no": "string",
  "coo_port_of_discharge": "string"
}
"""

def build_detail_prompt_from_index(total_row: int, index_slice: list, first_index: int, last_index: int) -> str:
    anchors_json = json.dumps(index_slice, ensure_ascii=False)
    return f"""
ROLE:
Anda adalah AI IDP professional yang fokus pada DATA DETAIL PER LINE ITEM.
Rule-based, deterministik, anti-halusinasi.

KONTEKS:
Total line item invoice = {total_row}.
Anda sekarang hanya mengerjakan item index {first_index}..{last_index}.

SANGAT PENTING (ANTI-SALAH INDEX):
Saya berikan "ANCHOR INDEX" untuk item yang harus Anda ekstrak.
Anda WAJIB mengembalikan output array dengan JUMLAH object = jumlah anchor,
dan URUTANNYA HARUS SAMA persis dengan urutan anchor.

ANCHOR INDEX (JSON):
{anchors_json}

ATURAN:
- Ekstrak hanya yang tertulis. Jangan mengarang.
- Tidak boleh JSON literal null → gunakan "null".
- Untuk FIELD BERTIPE NUMBER jika tidak ada → isi 0.
- Output HANYA JSON ARRAY, tanpa teks tambahan.
- Jika dokumen tidak tersedia → field prefix dokumen tsb WAJIB "null" / 0 sesuai tipe.
- Field po_* WAJIB "null"/0 (akan diisi Python dari master PO).

OUTPUT SCHEMA (CONTENT ONLY, TANPA HEADER):
{DETAIL_LINE_SCHEMA_TEXT}

OUTPUT RESTRICTION:
- Output HARUS dimulai '[' dan diakhiri ']'
- Tidak boleh markdown/plan/teks lain.
- Tidak boleh field tambahan.
- Jumlah object harus = {last_index - first_index + 1}
- Urutan object harus sama persis dengan ANCHOR INDEX.
"""


def build_detail_prompt(total_row, first_index, last_index):

    return f"""
ROLE:
Anda adalah AI IDP professional
yang fokus pada DATA DETAIL,
bersifat rule-based, deterministik, dan anti-halusinasi.

TUGAS UTAMA:
Melakukan OCR, ekstraksi dan mapping
untuk menghasilkan DETAIL OUTPUT
berdasarkan dokumen yang tersedia.
SEBELUM MELAKUKAN OCR, PAHAMI DULU DOKUMEN TERSEBUT AGAR MUDAH KETIKA MENGISI KOLOM-KOLOM TERSEBUT

DOKUMEN YANG MUNGKIN tersedia:
1. Invoice (WAJIB)
2. Packing List (WAJIB)
3. Bill of Lading (OPSIONAL)
4. Certificate of Origin (OPSIONAL)

ABAIKAN seluruh jenis dokumen lain sepenuhnya.

============================================
ATURAN UMUM EKSTRAKSI
============================================

1. Ekstrak HANYA data yang benar-benar tertulis di dokumen.
2. DILARANG mengarang.
3. Semua angka HARUS numeric murni.
4. DILARANG menggunakan JSON literal null.
5. Format tanggal: YYYY-MM-DD.
6. Boolean dan null HARUS STRING:
   "true" | "false" | "null"

7. Total line item pada dokumen adalah {total_row}.
8. Kerjakan HANYA line item dari index {first_index} sampai {last_index}.
9. Jika suatu dokumen TIDAK TERSEDIA:
- Seluruh field dengan prefix dokumen tersebut WAJIB diisi dengan string "null".
10. Jika pada dokumen terdapat value total seperti total net weight, gross weight, volume, amount, quantity, package yang berbentuk huruf:
- Ekstrak nilai numeriknya.

============================================
LOGIKA MAPPING
============================================

1. Invoice line item adalah BASELINE.
   Seluruh proses mapping dilakukan berdasarkan setiap baris di invoice
2. Setiap invoice line item dipetakan ke packing list line item.
3. BL dimapping ke invoice line berdasarkan:
   - bl_description
   - bl_hs_code
   (maksimal 5 item, hanya yang tertulis di BL)
4. COO dimapping ke invoice line berdasarkan:
   - coo_invoice_no
   - kemiripan antara coo_description dan inv_description (bukan similarity).

============================================
OUTPUT
============================================

- Output HANYA JSON ARRAY
- Maksimum object = ({last_index} - {first_index} + 1)
- DILARANG field tambahan
- DILARANG markdown
- DILARANG penjelasan tambahan

============================================
DETAIL OUTPUT SCHEMA
============================================

{{
  "inv_invoice_no": "string",
  "inv_invoice_date": "string",
  "inv_customer_po_no": "string",
  "inv_messrs": "string",
  "inv_messrs_address": "string",
  "inv_vendor_name": "string",
  "inv_vendor_address": "string",
  "inv_incoterms_terms": "string",
  "inv_terms": "string",
  "inv_coo_commodity_origin": "string",
  "inv_seq": "number",
  "inv_spart_item_no": "string",
  "inv_description": "string",
  "inv_gw": "string",
  "inv_gw_unit": "string",
  "inv_quantity": "number",
  "inv_quantity_unit": "string",
  "inv_unit_price": "number",
  "inv_price_unit": "string",
  "inv_amount": "number",
  "inv_amount_unit": "string",
  "inv_total_quantity": "number",
  "inv_total_amount": "number",
  "inv_total_nw": "number",
  "inv_total_gw": "number",
  "inv_total_volume": "number",
  "inv_total_package": "number",

  "pl_invoice_no": "string",
  "pl_invoice_date": "string",
  "pl_messrs": "string",
  "pl_messrs_address": "string",
  "pl_item_no": "number",
  "pl_description": "string",
  "pl_quantity": "number",
  "pl_package_unit": "string",
  "pl_package_count": "number",
  "pl_weight_unit": "string",
  "pl_nw": "number",
  "pl_gw": "number",
  "pl_volume_unit": "string",
  "pl_volume": "number",
  "pl_total_quantity": "number",
  "pl_total_amount": "number",
  "pl_total_nw": "number",
  "pl_total_gw": "number",
  "pl_total_volume": "number",
  "pl_total_package": "number",

  "po_no": "string",
  "po_vendor_article_no": "string",
  "po_text": "string",
  "po_sap_article_no": "string",
  "po_line": "number",
  "po_quantity": "number",
  "po_unit": "string",
  "po_price": "number",
  "po_currency": "string",
  "po_info_record_price": "number",
  "po_info_record_currency": "string",

  "bl_shipper_name": "string",
  "bl_shipper_address": "string",
  "bl_no": "string",
  "bl_date": "string",
  "bl_consignee_name": "string",
  "bl_consignee_address" : "string",
  "bl_consignee_tax_id": "string",
  "bl_seller_name": "string",
  "bl_seller_address" : "string",
  "bl_lc_number" : "string",
  "bl_notify_party": "string",
  "bl_vessel": "string",
  "bl_voyage_no": "string",
  "bl_port_of_loading": "string",
  "bl_port_of_destination": "string",
  "bl_description": "string",
  "bl_hs_code": "string",
  "bl_mark_number": "string",

  "coo_no": "string",
  "coo_form_type": "string",
  "coo_invoice_no": "string",
  "coo_invoice_date": "string",
  "coo_shipper_name": "string",
  "coo_shipper_address": "string",
  "coo_consignee_name": "string",
  "coo_consignee_address": "string",
  "coo_consignee_tax_id": "string",
  "coo_producer_name": "string",
  "coo_producer_address": "string",
  "coo_departure_date": "string",
  "coo_vessel": "string",
  "coo_voyage_no": "string",
  "coo_port_of_discharge": "string",
  "coo_seq": "number",
  "coo_mark_number": "string",
  "coo_description": "string",
  "coo_hs_code": "string",
  "coo_quantity": "number",
  "coo_unit": "string",
  "coo_package_count": "number",
  "coo_package_unit": "string",
  "coo_gw_unit": "string",
  "coo_gw": "number",
  "coo_amount_unit": "string",
  "coo_amount": "number",
  "coo_criteria": "string",
  "coo_origin_country": "string",
  "coo_customer_po_no": "string"
}}

===========================================
GENERAL KNOWLEDGE DETAIL
============================================

1. Output DETAIL merepresentasikan DATA PER LINE ITEM.

2. invoice_customer_po_no pada Invoice:
   - Jika invoice_customer_po_no bernilai "null", gunakan invoice_customer_po_no terakhir yang valid dari line item sebelumnya.

3. inv_vendor_name pada Invoice:
   - BUKAN berasal dari PT Insera Sena.
   - Jika terdapat PT Insera Sena dan pihak lain → pilih yang BUKAN PT Insera Sena.

4. inv_seq:
   - inv_seq wajib numeric murni dan tidak boleh "null".
   - inv_seq dihitung GLOBAL berdasarkan inv_customer_po_no yang sama untuk seluruh line item (index 1 sampai total_row), bukan dihitung ulang per batch.
   - Definisi inv_seq per baris: inv_seq = hitung berapa kali inv_customer_po_no yang sama sudah muncul dari index 1 sampai index baris ini (termasuk baris ini).
   Contoh: PO=112 muncul di index 2,5,6 → inv_seq untuk index 2=1, index 5=2, index 6=3.
   - Untuk baris yang kamu keluarkan (index {first_index}..{last_index}), inv_seq tetap harus mengikuti hitungan global dari index 1..total_row.

5. inv_spart_item_no:
   - Jika tidak eksplisit → cek kolom ke-2 tabel item.
   - Jika tetap tidak ada → "null".

6. pl_messrs pada Packing List (PL):
   - SELALU PT Insera Sena.
   - Jika terdapat beberapa nama → pilih PT Insera Sena.

7. Field po_* WAJIB diisi dengan STRING "null".

8. Package unit pada Packing List (PL):
   - Jika semua barang karton → CT
   - Jika semua barang pallet → PX
   - Jika barang campuran → PX
   - Jika barang Bal → BL
   - Selain itu → gunakan nilai asli.

9. LC Logic pada Bill of Lading (BL):
   - Jika bl_consignee_name mengandung nama perusahaan Bank → BL bertipe LC.
   - Jika tidak → BL bukan bertipe LC.

10. Jika pada dokumen Bill of Lading (BL) bertipe LC:
    - bl_consignee_name diambil dari notify party
    - bl_consignee_address diambil dari notify party

11. inv_coo_commodity_origin
   - SEBUTKAN NAMA NEGARANYA SAJA TIDAK PERLU TULISAN "Made In" yang penting nama negaranya dan tulisan dalam huruf besar semua.

12. coo_seq:
   - coo_seq adalah nomor urut line item PADA DOKUMEN CERTIFICATE OF ORIGIN (COO) SAJA.
   - Jika terdapat nomor urut eksplisit pada dokumen COO, WAJIB gunakan nomor tersebut.
   - JANGAN menghitung ulang berdasarkan jumlah item pada Invoice atau dokumen lain.
   - Jika tidak terdapat nomor urut eksplisit pada dokumen COO, hitung berdasarkan urutan kemunculan line item DI DALAM DOKUMEN COO SAJA (dimulai dari 1).
   - Jumlah coo_seq harus sama dengan jumlah line item pada dokumen COO.

============================================
OUTPUT RESTRICTION
============================================

- Output HARUS dimulai dengan '[' dan diakhiri dengan ']'.
- DILARANG ada teks lain sebelum/ sesudah JSON (termasuk "plan", "here's", dll).
- Jika melanggar, perbaiki dulu sebelum mengirim.
- OUTPUT HANYA JSON FORMAT. TIDAK ADA OUTPUT LAIN SELAIN JSON FORMAT!
- DILARANG:
  - Markdown
  - Penjelasan tambahan
  - Komentar
  - Field di luar skema
"""