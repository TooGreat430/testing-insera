import json

def _is_shimano_inc_vendor_id(vendor_id: str = "default") -> bool:
    return str(vendor_id or "default").strip().lower() == "shimano_inc"

def _is_kunshan_landon_vendor_id(vendor_id: str = "default") -> bool:
    return str(vendor_id or "default").strip().lower() == "kunshan_landon"

def _is_karet_deli_vendor_id(vendor_id: str = "default") -> bool:
    return str(vendor_id or "default").strip().lower() == "karet_deli"

def _is_fox_vendor_id(vendor_id: str = "default") -> bool:
    return str(vendor_id or "default").strip().lower() == "fox"

# =========================
# HEADER FIELDS (doc-level)
# =========================

UNNULLABLE_FIELD = """
{
  "inv_customer_po_no": "string",
  "inv_spart_item_no": "string",
  "inv_description": "string",
  "inv_quantity": "number",
  "inv_quantity_unit": "string",
  "inv_unit_price": "number",
  "inv_amount": "number",

  "pl_customer_po_no": "string",
  "pl_item_no": "string",
  "pl_description": "string",
  "pl_quantity": "number",
  "pl_package_unit": "string",
  "pl_package_count": "number",
  "pl_nw": "number",
  "pl_gw": "number",
  "pl_volume": "number",

  "bl_description": "string",
  "bl_hs_code": "string",

  "coo_description": "string",
  "coo_hs_code": "string",
  "coo_quantity": "number",
  "coo_amount": "number",
  "coo_criteria": "string",
}
"""


DETAIL_CSV_FIELD_ORDER_FULL = [
    "match_score",
    "match_description",
    "confidence_label",
    "inv_invoice_no",
    "inv_seq",
    "po_no",
    "po_line",
    "po_quantity",
    "po_unit",
    "inv_invoice_date",
    "inv_customer_po_no",
    "inv_messrs",
    "inv_messrs_address",
    "inv_vendor_name",
    "inv_vendor_address",
    "inv_incoterms_terms",
    "inv_terms",
    "inv_coo_commodity_origin",
    "inv_spart_item_no",
    "inv_description",
    "inv_gw",
    "inv_gw_unit",
    "inv_quantity",
    "inv_quantity_unit",
    "inv_unit_price",
    "inv_price_unit",
    "inv_amount",
    "inv_amount_unit",
    "inv_total_quantity",
    "inv_total_amount",
    "inv_total_nw",
    "inv_total_gw",
    "inv_total_volume",
    "inv_total_package",

    "pl_invoice_no",
    "pl_invoice_date",
    "pl_messrs",
    "pl_messrs_address",
    "pl_customer_po_no",
    "pl_item_no",
    "pl_description",
    "pl_quantity",
    "pl_package_unit",
    "pl_package_count",
    "pl_weight_unit",
    "pl_nw",
    "pl_gw",
    "pl_volume_unit",
    "pl_volume",
    "pl_total_quantity",
    "pl_total_amount",
    "pl_total_nw",
    "pl_total_gw",
    "pl_total_volume",
    "pl_total_package",

    "po_vendor_article_no",
    "po_text",
    "po_sap_article_no",
    "po_price",
    "po_currency",
    "po_info_record_price",
    "po_info_record_currency",

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
    "bl_description",
    "bl_hs_code",
    "bl_mark_number",

    "coo_no",
    "coo_form_type",
    "coo_invoice_no",
    "coo_invoice_date",
    "coo_shipper_name",
    "coo_shipper_address",
    "coo_consignee_name",
    "coo_consignee_address",
    "coo_consignee_tax_id",
    "coo_producer_name",
    "coo_producer_address",
    "coo_departure_date",
    "coo_vessel",
    "coo_voyage_no",
    "coo_port_of_discharge",
    "coo_seq",
    "coo_mark_number",
    "coo_description",
    "coo_hs_code",
    "coo_quantity",
    "coo_unit",
    "coo_package_count",
    "coo_package_unit",
    "coo_gw_unit",
    "coo_gw",
    "coo_amount_unit",
    "coo_amount",
    "coo_criteria",
    "coo_origin_country",
    "coo_customer_po_no"
]

# Versi FINAL: cocok kalau kamu tetap drop inv_messrs, inv_messrs_address, inv_gw, inv_gw_unit
DETAIL_CSV_FIELD_ORDER_FINAL = [
    (
        "inv_vendor_article_no" if k == "inv_spart_item_no"
        else "pl_vendor_article_no" if k == "pl_item_no"
        else k
    )
    for k in DETAIL_CSV_FIELD_ORDER_FULL
    if k not in {"inv_messrs", "inv_messrs_address", "inv_gw", "inv_gw_unit"}
]

HEADER_SCHEMA_TEXT = [
    "inv_invoice_no","inv_invoice_date","inv_messrs","inv_messrs_address","inv_vendor_name",
    "inv_vendor_address","inv_incoterms_terms","inv_terms","inv_coo_commodity_origin", "inv_price_unit", "inv_amount_unit", "inv_total_quantity",
    "inv_total_amount", "inv_total_nw", "inv_total_gw", "inv_total_volume", "inv_total_package",
    "pl_invoice_no","pl_invoice_date","pl_messrs","pl_messrs_address", "pl_total_quantity", "pl_total_amount",
    "pl_total_nw", "pl_total_gw", "pl_weight_unit", "pl_total_volume", "pl_volume_unit", "pl_total_package",
    "bl_shipper_name","bl_shipper_address","bl_no","bl_date","bl_consignee_name","bl_consignee_address",
    "bl_consignee_tax_id","bl_seller_name","bl_seller_address","bl_lc_number","bl_notify_party","bl_vessel",
    "bl_voyage_no","bl_port_of_loading","bl_port_of_destination", "bl_mark_number",
    "coo_no","coo_form_type","coo_invoice_no","coo_invoice_date","coo_shipper_name","coo_shipper_address",
    "coo_consignee_name","coo_consignee_address","coo_consignee_tax_id","coo_producer_name","coo_producer_address",
    "coo_departure_date","coo_vessel","coo_voyage_no","coo_port_of_discharge", "coo_gw_unit", "coo_amount_unit", "coo_origin_country",
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
  "inv_amount": "number",

  "pl_customer_po_no": "string",
  "pl_item_no": "string",
  "pl_description": "string",
  "pl_quantity": "number",
  "pl_package_unit": "string",
  "pl_package_count": "number",
  "pl_nw": "number",
  "pl_gw": "number",
  "pl_volume": "number",

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
  "coo_gw": "number",
  "coo_amount": "number",
  "coo_criteria": "string",
  "coo_customer_po_no": "string"
}"""

# dipakai Python untuk "ensure semua kolom ada"
DETAIL_LINE_FIELDS = [
    "inv_customer_po_no","inv_seq","inv_spart_item_no","inv_description","inv_gw","inv_gw_unit",
    "inv_quantity","inv_quantity_unit","inv_unit_price","inv_price_unit","inv_amount","inv_amount_unit",
    "inv_total_quantity","inv_total_amount","inv_total_nw","inv_total_gw","inv_total_volume","inv_total_package",

    "pl_customer_po_no", "pl_item_no","pl_description","pl_quantity","pl_package_unit", "pl_package_count","pl_nw","pl_gw",
    "pl_volume","pl_total_quantity","pl_total_amount","pl_total_nw","pl_total_gw","pl_total_volume","pl_total_package",

    "po_no","po_vendor_article_no","po_text","po_sap_article_no","po_line","po_quantity","po_unit","po_price","po_currency",
    "po_info_record_price","po_info_record_currency",

    "bl_description","bl_hs_code", "bl_mark_number",

    "coo_seq","coo_mark_number","coo_description","coo_hs_code","coo_quantity","coo_unit","coo_package_count", "coo_package_unit",
    "coo_gw", "coo_amount","coo_criteria","coo_customer_po_no"
]

DETAIL_LINE_NUM_FIELDS = {
    "inv_seq","inv_quantity","inv_unit_price","inv_amount",
    "inv_total_quantity","inv_total_amount","inv_total_nw","inv_total_gw","inv_total_volume","inv_total_package",

    "pl_quantity","pl_package_count","pl_nw","pl_gw","pl_volume",
    "pl_total_quantity","pl_total_amount","pl_total_nw","pl_total_gw","pl_total_volume","pl_total_package",

    "po_line","po_quantity","po_price","po_info_record_price",

    "coo_seq","coo_quantity","coo_package_count","coo_gw","coo_amount",
}

def build_index_prompt(total_row: int) -> str:
    return f"""
ROLE:
Anda adalah AI IDP professional yang fokus membuat INDEX line items berbasis DUA SUMBER:
1) Invoice
2) Packing List (PL)

Rule-based, deterministik, anti-halusinasi.

TUGAS:
Buat daftar INDEX untuk SEMUA line item dengan anchor utama dari Invoice dan anchor pendukung dari Packing List.
INDEX ini akan dipakai sebagai "anchor" untuk ekstraksi detail batch berikutnya.

ATURAN:
1) Output HANYA JSON ARRAY, tanpa teks lain.
2) Panjang array harus = {total_row} (jika invoice memang memiliki {total_row} line item).
3) Setiap object mewakili 1 line item berdasarkan urutan kemunculan di Invoice.
4) DILARANG markdown / plan / penjelasan.
5) Jika suatu field tidak ada di dokumen → isi "null" (string) atau 0 (angka).
6) Invoice adalah anchor utama untuk identitas row.
7) Packing List adalah anchor pendukung untuk membantu memilih pasangan row PL yang paling cocok.
8) PL TIDAK BOLEH membuat row baru.
9) Jangan ikutkan BL / COO ke index.

SCHEMA OUTPUT (INDEX):
[
  {{
    "idx": number,
    "page": number,
    "page_index": number,

    "inv_customer_po_no": "string",
    "inv_spart_item_no": "string",
    "inv_description": "string",
    "inv_quantity": number,
    "inv_quantity_unit": "string",
    "inv_unit_price": number,
    "inv_price_unit": "string",
    "inv_amount": number,

    "pl_page_no": number,
    "pl_customer_po_no": "string",
    "pl_description": "string",
    "pl_quantity": number
  }}
]

ANCHOR TRIO — WAJIB KONSISTEN UNTUK SETIAP OBJECT:
- "idx": nomor index ASLI global (running 1..N seluruh dokumen, tidak skip, tidak duplikat, TIDAK reset per halaman).
- "page": nomor halaman Invoice (1-based) tempat item itu muncul.
- "page_index": nomor urut item DI DALAM halaman tersebut (mulai 1 di setiap halaman baru, naik 1 per item dalam halaman yang sama).
- Ketiga field WAJIB self-consistent: saat "idx" naik 1, salah satu dari:
  (a) "page" tetap, "page_index" +1 (item berikutnya di halaman yang sama), atau
  (b) "page" +1, "page_index" reset ke 1 (item pertama di halaman berikutnya).
- "page" + "page_index" dipakai sebagai SELF-VERIFICATION sebelum commit "idx" supaya tidak terjadi lompat / geser / duplikat idx.
- Kalau ragu posisi suatu item, gunakan "page" dan "page_index" untuk grounding ke fisik dokumen sebelum mengisi "idx".

CONTOH ANCHOR TRIO (3 item pertama dari invoice 2-halaman):
[
  {{"idx": 1, "page": 1, "page_index": 1, ...}},
  {{"idx": 2, "page": 1, "page_index": 2, ...}},
  {{"idx": 3, "page": 2, "page_index": 1, ...}}
]

CATATAN:
- inv_* anchor diambil dari Invoice.
- pl_* anchor diambil dari Packing List.
- Jika pasangan row PL tidak ditemukan dengan yakin, isi field pl_* dengan "null"/0.
- Satu anchor invoice boleh memiliki lebih dari satu kandidat sub-row pada Packing List.
- Jika Packing List memecah 1 item menjadi beberapa sub-row, maka pl_quantity pada anchor
  HARUS merepresentasikan total agregat semua sub-row yang masih item yang sama,
  bukan hanya quantity dari sub-row pertama.
- Jangan menganggap perubahan CTN NO / carton range sebagai item baru
  jika description / item_no / PO masih konsisten.
- Row TOTAL/SUBTOTAL tidak boleh dijumlahkan bersama detail row yang sama karena akan menyebabkan double count.
"""

def build_header_prompt(vendor_id: str = "default") -> str:
    shimano_header_rule = ""
    if _is_shimano_inc_vendor_id(vendor_id):
        shimano_header_rule = """

ATURAN KHUSUS VENDOR shimano_inc:
- bl_mark_number TIDAK diekstrak pada header pass.
- Isi bl_mark_number dengan "null" pada output header.
- bl_mark_number untuk shimano_inc akan diekstrak pada content/detail pass dari dokumen Bill of Lading.
"""

    kunshan_landon_header_rule = ""
    if _is_kunshan_landon_vendor_id(vendor_id):
        kunshan_landon_header_rule = """

ATURAN KHUSUS VENDOR kunshan_landon:

CARA MEMBACA BARIS TOTAL (SANGAT PENTING):
- Pada dokumen Invoice (INV) dan Packing List (PL), baris total berada di paling bawah tabel dan diawali dengan penanda "C/NO." pada kolom Marks (kolom paling kiri).
- Urutan kolom pada baris total mengikuti urutan kolom tabel:
    INVOICE: [Marks="C/NO."] [PO Number] [Item] [Material] [Descriptions] [Quantity=<TOTAL QTY>] [Unit] [Unit price] [Amount=<TOTAL AMOUNT>]
    PACKING LIST: [Marks="C/NO."] [PO Number] [Item] [Material] [Descriptions] [QTY=<TOTAL QTY>] [UNIT] [Packing=<TOTAL PACKAGE>] [N.W=<TOTAL NW>] [G.W=<TOTAL GW>] [VOL=<TOTAL VOL>]

ATURAN inv_total_quantity dan pl_total_quantity:
- WAJIB diambil dari kolom "Quantity" / "QTY" pada baris total (baris "C/NO.") di paling bawah tabel.
- Nilai ini adalah penjumlahan seluruh quantity line item, sehingga biasanya berupa angka besar (5 digit atau lebih, contoh: 879946).
- DILARANG KERAS mengambil dari kolom Packing (yang berisi total CARTONS, contoh: 984).
- DILARANG KERAS mengambil dari kalimat naratif seperti "TOTAL: PACKED IN NINE HUNDRED EIGHTY FOUR ( 984 ) PKGS ONLY" atau "984 PKGS = 2 PALLET, 72 BAGS, 910 CARTONS". Kalimat tersebut HANYA menyebut total package, BUKAN total quantity.

ATURAN pl_total_package:
- Diambil dari kolom "Packing" pada baris total (contoh: 984), ATAU dari kalimat naratif "TOTAL: PACKED IN ... ( 984 ) PKGS ONLY".
- Nilai ini TIDAK BOLEH sama dengan pl_total_quantity. Jika hasil ekstraksi pl_total_quantity == pl_total_package, berarti pl_total_quantity SALAH dan harus diperbaiki dengan mengambil angka pada kolom Quantity/QTY (umumnya jauh lebih besar).

CONTOH KONKRET (format dokumen kunshan_landon):
- Baris total Invoice: "C/NO. 879946   US$ 85,731.38"
    → inv_total_quantity = 879946
    → inv_total_amount   = 85731.38
- Baris total Packing List: "879946  984  14036.01  14966.96  43.590"
    → pl_total_quantity = 879946
    → pl_total_package  = 984
    → pl_total_nw       = 14036.01
    → pl_total_gw       = 14966.96
    → pl_total_volume   = 43.590
"""

    karet_deli_header_rule = ""
    if _is_karet_deli_vendor_id(vendor_id):
        karet_deli_header_rule = """

ATURAN KHUSUS VENDOR karet_deli — MULTI-SECTION PACKING LIST:

Karet Deli kadang menempatkan beberapa Packing List di dalam SATU file PDF (multi-section). Pola yang harus dikenali pada body file Packing List:
    Header utama (atas dokumen):     "No. : INS-XXX/YY"           contoh: "INS-009/26"
    Sub-section header (di tengah):  "INS-XXX/YY/ZZZ"             contoh: "INS-009/26/K100"
                                                                  dimana ZZZ adalah kode tambahan (K100, WTB/HB, dst).
    Pemisah antar section biasanya berupa baris "TOTAL X.XX PCS / Y.YY SETS" dan kadang "CLAIM : CLMxxxxxx".

PRINSIP PENENTUAN pl_invoice_no — IKUTI INV_INVOICE_NO YANG SEDANG DIPROSES:
    1. Pertama, EKSTRAK inv_invoice_no dari file Invoice (mengikuti aturan invoice number umum).
    2. Lalu, CARI di body file Packing List apakah ada sub-section header yang EXACT MATCH dengan inv_invoice_no tersebut.
        - Jika ditemukan sub-section "INS-XXX/YY/ZZZ" yang sama persis dengan inv_invoice_no → SET pl_invoice_no = sub-section tersebut.
        - Jika tidak ada sub-section yang cocok, gunakan header utama file PL ("No. : ...") sebagai pl_invoice_no.

CONTOH KONKRET:
    Skenario A — Invoice file dengan inv_invoice_no = "INS-009/26", PL file punya header utama "INS-009/26" (di body-nya ada sub-section "INS-009/26/K100" tapi BUKAN milik invoice ini)
        → pl_invoice_no = "INS-009/26" (header utama, BUKAN sub-section K100).
    Skenario B — Invoice file dengan inv_invoice_no = "INS-009/26/K100", PL file yang sama (yang berisi sub-section "INS-009/26/K100" di body)
        → pl_invoice_no = "INS-009/26/K100" (dari sub-section di body, BUKAN header utama file).

DILARANG KERAS:
    - Memilih sub-section yang tidak cocok dengan inv_invoice_no.
    - Mengabaikan sub-section yang valid dan justru memaksa pakai header utama padahal inv_invoice_no menunjuk ke sub-section.
    - Memilih header utama saat inv_invoice_no jelas-jelas merujuk ke sub-section yang ada di body.

ATURAN KHUSUS INVOICE TOTAL AMOUNT:
- Ambil total amount dari value numerik "Brutto" yang biasanya terletak di bagian akhir/bawah dokumen Invoice.
  Contoh:
  Brutto Rp. 661,789,200.00
  Diskon Rp. 0.00
  Total tanpa PPN Rp. 661,789,200.00
  PPN Rp. 72,796,812.00
  Total dengan PPN Rp. 734,586,012.00
  maka inv_total_amount = 661,789,200.00 (Brutto), BUKAN 734,586,012.00 (total dengan PPN).

ATURAN KHUSUS PACKING LIST TOTAL QUANTITY:
- Ambil total quantity dari value numerik "Total" (Bukan dari "GRAND TOTAL") yang biasanya terletak tepat di bawah detail line item packing list.
- Jumlahkan semua value numerik "Total" jika ada lebih dari 1 jenis quantity unit (contoh: PCS, SETS) untuk mendapatkan pl_total_quantity.
- Dalam 1 packing list, dapat terdapat lebih dari 1 invoice number.  Ekstrak total quantity untuk masing-masing invoice number, untuk mengisi pl_total_quantity untuk masing-masing invoice number tersebut.
  Contoh:
  Dalam 1 file packing list terdapat 2 invoice number:
  - Invoice number: INS-009/26
      TOTAL 30,037.00 PCS
            400.00 SETS
  - Invoice number: INS-009/26/K100
      TOTAL 1.00 PCS
  
GRAND TOTAL 30,038.00 PCS
            400.00 SETS

Maka untuk invoice number INS-009/26, pl_total_quantity = 30437, BUKAN 30438.
Dan untuk invoice number INS-009/26/K100, pl_total_quantity = 1, BUKAN 30438.
"""

    fox_header_rule = ""
    if _is_fox_vendor_id(vendor_id):
        fox_header_rule = """
ATURAN KHUSUS VENDOR FOX:
Untuk dokumen Invoice ambil dari "Commercial Invoice #:" (Contoh: Commercial Invoice #: 91609521).
Untuk dokumen Packing List ambil dari "Delivery:" (Contoh: Delivery: 91609521).
maka inv_invoice_no = 91609521 dan pl_invoice_no = 91609521.
        """

    template = """
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
  "inv_price_unit": "string",
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
  "pl_total_quantity": "number", 
  "pl_total_amount": "number",
  "pl_total_nw": "number", 
  "pl_total_gw": "number",
  "pl_weight_unit": "string",
  "pl_total_volume": "number",
  "pl_volume_unit": "string",
  "pl_total_package": "number",

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
  "coo_gw_unit": "string",
  "coo_amount_unit": "string",
  "coo_origin_country": "string",
}

{shimano_header_rule}{kunshan_landon_header_rule}{karet_deli_header_rule}
GENERAL KNOWLEDGE:

INVOICE NUMBER EXTRACTION RULES (SANGAT PENTING):
1. inv_invoice_no:
   - Ambil NOMOR INVOICE DOKUMEN INVOICE pada level header dokumen, BUKAN dari line item.
   - Prioritaskan kandidat yang berada di area header / dekat judul dokumen / dekat data vendor / dekat tanggal.
   - Label yang valid bisa berupa:
     "INVOICE NO", "INV. NO.", "INVOICE:", "NO.:", "NO", "INVOICE NUMBER"
   - Pada beberapa vendor, invoice number dapat muncul hanya sebagai:
     - "NO.: 260116001"
     - "INVOICE:2026011601"
     - "Inv. No.: 80459929"
   - Jika ada beberapa angka di tabel line item seperti "PO NO", "PO/NO", "PO No.", maka JANGAN ambil angka tersebut sebagai inv_invoice_no.
   - Jangan ambil:
     PO number, item no, packing no, LC number, page number, date, quantity, amount.
   - Jika label invoice number dan nilainya berada pada baris berbeda, gabungkan nilainya menjadi satu value utuh.
   - Jika nomor invoice terputus karena line wrap, ambil seluruh bagiannya dan gabungkan tanpa spasi tambahan yang tidak perlu.

2. inv_invoice_date dan pl_invoice_date:
   - Ambil tanggal dari dokumen invoice dan packing list dengan format YYYY-MM-DD.
   - Biasanya memiliki label "DATE:", "DATED:", atau "DATES:".
     Contoh: 
     DATED: JAN. 07, 2026
     maka, inv_invoice_date = 2026-01-07
  - JANGAN AMBIL DARI "SAILING ON OR ABOUT:", "ETD:", atau "ETA:"

3. pl_invoice_no:
   - Ambil nomor invoice yang direferensikan oleh dokumen Packing List pada level header dokumen.
   - pl_invoice_no TIDAK HARUS selalu berlabel "INVOICE NO".
   - Label/konteks yang valid untuk pl_invoice_no bisa berupa:
     "NO.:", "INVOICE NO", "INV. NO.", "REF NO.", atau angka referensi header yang berdiri sendiri di dekat judul "PACKING LIST".
   - Contoh pola valid:
     - "NO.: 260116001"
     - "PACKING LIST" lalu di baris dekat header ada "2026011601"
     - "REF NO. 80459929"
   - Jika ada angka pada kolom "PO NO." atau "PO/NO" di tabel item, JANGAN ambil itu sebagai pl_invoice_no.
   - Prioritaskan kandidat yang muncul di area header atas, bukan di body table.
   - Jika ada beberapa kandidat, pilih yang paling dekat dengan judul dokumen / area header dan yang paling konsisten dengan invoice reference dokumen tersebut.

4. coo_invoice_no:
   - Ambil nomor invoice yang direferensikan oleh dokumen COO/RCEP.
   - coo_invoice_no BUKAN COO number / certificate number.
   - Untuk dokumen COO/RCEP, prioritas utama adalah membaca KOLOM / BOX 13 dengan label:
     "Invoice number(s) and date of invoice(s)".
   - Gunakan layout visual tabel dokumen, bukan urutan OCR linear.
   - Kolom ini biasanya berada di paling kanan tabel utama.
   - Ambil HANYA bagian invoice number.
   - Jika dalam 1 sel terdapat invoice number dan tanggal invoice:
     1) ambil semua fragmen invoice number,
     2) gabungkan tanpa spasi / line break,
     3) buang tanggal invoice sepenuhnya.
   - Contoh:
     SHXM22-2512000
     393
     DEC. 31, 2025
     Maka coo_invoice_no = SHXM22-2512000393
   - Jangan ambil:
     Certificate No., verification number, PO number, LC number, page number,
     HS code, quantity, gross weight, country of origin, vessel, voyage, port, date.
   - Jika continuation sheet tidak menampilkan ulang invoice number,
     tetap gunakan invoice number yang muncul pada page pertama dokumen yang sama.

5. inv_vendor_name pada Invoice:
   - BUKAN berasal dari PT Insera Sena.
   - Jika terdapat PT Insera Sena dan pihak lain → pilih yang BUKAN PT Insera Sena.

6. Messrs pada Packing List (PL) dan Invoice (INV):
   - SELALU PT Insera Sena.
   - Jika terdapat beberapa nama → pilih PT Insera Sena.
   - Jika ada variasi nama perusahaan PT Insera Sena seperti:
     "PT. INSERA SENA", "PERSEROAN TERBATAS INSERA SENA", "PT INSERASENA", atau bentuk lainnya yang merujuk pada PT Insera Sena,
     NORMALISASI menjadi: "PT Insera Sena"

7. Messrs address pada Packing List (PL) dan Invoice (INV):
   - Hanya ekstrak address dari perusahaannya tanpa kode posnya, contoh:
      JL VETERAN, LINGKAR TIMUR, KEL. WADUNGASIH, KEC. BUDURAN, KAB. SIDOARJO, PROV. JAWA TIMUR 61252
      Berarti yang diekstrak hanya: JL VETERAN, LINGKAR TIMUR, KEL. WADUNGASIH, KEC. BUDURAN, KAB. SIDOARJO, PROV. JAWA TIMUR
   - JANGAN SAMPAI SALAH EKSTRAK! PAHAMI KONTEKS. Jika messrs address maka yang ditanyakan adalah alamat jadi penulisan harus tepat
     contoh: Di dokumen seperti ini JI VETERAN maka perlu di convert menjadi "JL VETERAN" karena konteksnua adalah JALAN

8. inv_total_quantity:
   - Ambil nilai numerik dari total quantity invoice yang merepresentasikan jumlah quantity keseluruhan, bukan jumlah quantity line item. 
   - Dapat muncul dalam berbagai bentuk dan tidak selalu punya label eksplisit seperti "total quantity".
   - Biasanya muncul di bagian akhir dokumen atau bagian ringkasan, satu baris bersama total amount atau informasi ringkasan lainnya.
      Contoh: 7,290 PCS
      maka, inv_total_quantity = 7290
   - Jika tidak tersedia secara eksplisit dan jelas dari dokumen invoice, maka isi dengan "null".
   - JANGAN menghitung, menjumlahkan, mengarang, atau mengambil dari dokumen lain jika value total quantity tidak tersedia.

9. inv_price_unit SAMA dengan inv_amount_unit:
   - Kedua field ini mempresentasikan mata uang (currency).  
   - Telusuri currency yang digunakan, contoh valuenya: USD, CNY, YEN, EUR dan lain-lain.

   - Output harus menggunakan kode mata uang standar ISO 4217 (3 huruf).
   - Jangan menggunakan simbol mata uang seperti $, US$, ¥, €, Rp, dll.
     Contoh konversi:
     US$ atau $ → USD
     RMB atau ¥ → CNY
     ¥ → JPY (jika konteks Jepang)
     Rp → IDR
     € → EUR
     
   - Jika "null" gunakan currency dari dokumen tersebut, biasanya dapat ditemukan pada bagian Currency atau Currency Code.  
     Contoh:
     Currency Code : USD → maka inv_price_unit dan inv_amount_unit diisi dengan USD.

10. pl_total_package dan pl_total_quantity:
   - Jika pada dokumen terdapat dua value dengan UNIT yang berbeda, maka sum kedua value tersebut
     contoh: pada dokumen terlampir total dari quantity seperti ini 2139PCE/150SET. Maka sum kedua value tersebut adalah 2289 (2139 + 150 = 2289)

11. pl_total_package:
   - Ambil nilai numerik dari total kemasan fisik terluar (outermost packaging) yang dikirim.
   - ATURAN TANDA KURUNG (SANGAT PENTING): Jika ada angka di dalam tanda kurung ( ) atau kurung siku < >, ABAIKAN ANGKA TERSEBUT SEPENUHNYA. Angka di dalam kurung hanya menjelaskan isi dari kemasan luar, bukan total kemasan fisik.
   - Aturan Hierarki: Jika terdapat gabungan unit besar (contoh: Pallet/PLT/PT/Skid) dan unit kecil yang lepas/loose (contoh: Carton/CTN/CT), JUMLAHKAN HANYA UNIT TERBESAR DENGAN UNIT KECIL YANG LEPAS.
   
   CONTOH KASUS PENJUMLAHAN:
   - "TOTAL PACKAGES : 1 PLT (16 CTN) & 55 CTN"
     Maka pl_total_package = 56.
     (Cara hitung: 1 PLT + 55 CTN. Angka 16 CTN di dalam kurung DIABAIKAN).
   - "2P/T  < 32C/T > &   83C/T"
     Maka pl_total_package = 85.
     (Cara hitung: 2 P/T + 83 C/T. Angka 32 C/T di dalam tanda < > DIABAIKAN).
   - "Total Packages: 4 PLT (108 CTN) & 95 CTN"
     Maka pl_total_package = 99.
     (Cara hitung: 4 PLT + 95 CTN. Angka 108 CTN DIABAIKAN).
   
   - Jika dokumen secara eksplisit menyebutkan 1 total detail tanpa hirarki campuran, ambil angkanya langsung. 
     Contoh: "Total Number of Packages: 91 CTNS" -> pl_total_package = 91.
     
12. 11. pl_total_volume:
   - Ambil nilai numerik dari total volume packing list yang merepresentasikan jumlah volume keseluruhan, bukan jumlah volume line item.
   - Dapat muncul dalam berbagai bentuk dan tidak selalu punya label eksplisit seperti "total volume".
   - Biasanya muncul di bagian akhir dokumen atau bagian ringkasan total, satu baris bersama total nw, total gw, total package atau informasi ringkasan lainnya.
      Contoh: 13.500
      maka, inv_total_quantity = 13.5
   - Jika tidak tersedia secara eksplisit dan jelas dari dokumen packing list, maka isi dengan "null".
   - JANGAN menghitung, menjumlahkan, mengarang, atau mengambil dari dokumen lain jika value total volume tidak tersedia.

13. LC Logic pada Bill of Lading (BL):
   - Jika bl_consignee_name mengandung nama perusahaan Bank → BL bertipe LC.
   - Jika tidak → BL bukan bertipe LC.

14. Jika pada dokumen Bill of Lading (BL) bertipe LC:
    - bl_consignee_name diambil dari notify party
    - bl_consignee_address diambil dari notify party

15. inv_coo_commodity_origin
   - SEBUTKAN NAMA NEGARANYA SAJA TIDAK PERLU TULISAN "Made In" yang penting nama negaranya dan tulisan dalam huruf besar semua.

16. pl_volume_unit
  - volume unit yang hanya ada dua value antara CUFT dan M3
  - Jika value pada dokumen seperti ini: MÂ³ --> maka value aslinya adalah "M3"
  - Jika value pada dokumen seperti ini: CU'FT --> maka value aslinya adalah "CUFT
  - JIKA PADA DOKUMEN TIDAK TERTERA VOLUME UNIT DARI Packing List Volume Unit, maka biarkan "null".

17. coo_gw_unit:
    - Field ini merepresentasikan satuan dari gross weight pada dokumen Certificate of Origin (COO).
    - Pada dokumen COO, nilai weight dapat ditulis dalam format seperti: "80KG G.W.", "160KG G.W.", atau "240KG G.W.".
    - Dalam format tersebut:
      KG = satuan berat (unit)
      G.W. = label yang berarti Gross Weight.

    - Ambil satuan berat yang terletak setelah angka weight, yaitu KG.
    - Jangan mengambil "G.W." sebagai unit karena itu hanya penanda Gross Weight.
      Contoh:
      80KG G.W. → coo_gw_unit = KG
      160KG G.W. → coo_gw_unit = KG
      240KG G.W. → coo_gw_unit = KG 
    
    - Jika coo_gw_unit tidak tersedia maka isi dengan "null"

18. Semua field [tipe_dokumen]_total (contoh: inv_total_quantity, pl_total_gw, inv_total_amount) itu boleh "null" JIKA PADA DOKUMEN EMANG TIDAK DISERTAKAN VALUE DARI TOTAL TERSEBUT

19. bl_shipper dan bl_seller
   - Penempatan bl_shipper selalu diatas dari bl_seller
   - Jika bingung, terdapat tulisan "O/B" Untuk memisahkan antara bl_shipper dan bl_seller
     contoh:
      SUZHOU GEYA TRADING CO.,LTD.
      NO.6 DONGYANLI RD., SUZHOU INDUSTRIAL 
      PARK 215125,SUZHOU CHINA 
      O/B BAFANG ELECTRIC MOTOR SCIENCE TECHNOLOGY B.V.
      KOVEL 11, 5431 ST CUIJK, THE NETHERLANDS 

     Maka value dari bl_shipper_name adalah SUZHOU GEYA TRADING CO.,LTD. dan bl_seller_name adalah BAFANG ELECTRIC MOTOR SCIENCE TECHNOLOGY B.V.
   - bl_seller_name HARUS selain "PT INSERA SENA", TIDAK BOLEH diisi dengan "PT INSERA SENA".

20. bl_voyage_no:
   - Penempatan dari bl_voyage_no selalu di sebelah bl_vessel
   - Format dari bl_voyage_no diawali dengan huruf terus konektor terus kode. Tugas anda ambil setelah V nya
     Contoh:
     V.S018
     Berarti value tersebut adalah S018

21. inv_invoice_no, pl_invoice_no & coo_invoice_no:
    - PADA SETIAP DOKUMEN INVOICE, PACKING LIST DAN COO, PASTI ADA INVOICE NO JADI TOLONG CARI DENGAN TELITI.
    - inv_invoice_no, pl_invoice_no & coo_invoice_no TIDAK BERSIFAT NULLABLE, JADI TOLONG PERHATIKAN DENGAN TELITI

22. coo_invoice_no:
    - Merepresentasikan invoice number yang direferensikan pada dokumen COO.
    - Biasanya memiliki kolom sendiri
    - Biasanya kolom ditaruh di paling kanan dari dokumen.
    - coo_invoice_no lengthnya panjang.
    - coo_invoice_no tidak mungkin ditaruh barengan dengan item_description.
    - Ambil seluruh nilai invoice number secara lengkap, termasuk jika invoice number terpisah ke baris berikutnya.
    - Jika nomor invoice terpotong ke baris berikutnya, semua bagian nomor tetap diambil dan digabungkan menjadi 1 nilai.
      - Contoh:
        Invoice Number:
        SHXM22-2512000
        393

        Maka, coo_invoice_no: SHXM22-2512000393

23. bl_mark_number:
    - Ekstrak dari kolom "Marks and Numbers" pada dokumen BL.
    - Ekstrak secara kesuluruhan apabila ada "PT. IS" pada kolom tersebut.
      Contoh:
      Marks and Numbers
      PT.IS
      PO#
      P/I NO.:
      C/NO.:A
      MADE IN CHINA
      maka, bl_mark_number: "PT.IS  PO#  P/I NO.:  C/NO.:A  MADE IN CHINA"
    - Khusus vendor shimano_inc, abaikan rule ini pada header pass dan isi bl_mark_number dengan "null".

24. coo_no
    - coo_no merupakan nomor certificate dari dokumen
    - Biasanya di labelkan dengan "Certificate No:..."

25. coo_form_type:
   - Ekstrak jenis form Certificate of Origin (COO) dari dokumen.
   - Prioritaskan mapping ke salah satu dari pilihan berikut:
     - RCEP / Regional Comprehensive Economic Partnership Agreement → "RCEP"
     - "ATIGA" / "FORM D"
     - "AWSC"
     - "FORM AJ"
     - "JIEPA"
  - Jika ditemukan jenis form COO yang jelas dan eksplisit tetapi TIDAK termasuk dalam daftar di atas:
     → isi dengan nilai asli tersebut (tanpa mengubah makna).
  - Jika tidak ditemukan indikasi jenis COO secara eksplisit atau tidak cukup jelas:
     → isi dengan "null".
  - Jangan mengarang atau menebak.
"""
    return (
        template
        .replace("{shimano_header_rule}", shimano_header_rule)
        .replace("{kunshan_landon_header_rule}", kunshan_landon_header_rule)
        .replace("{karet_deli_header_rule}", karet_deli_header_rule)
    )

def build_detail_prompt_from_index(
    total_row: int,
    index_slice: list,
    first_index: int,
    last_index: int,
    vendor_id: str = "default",
    vendor_prompt_text: str = ""
) -> str:
    anchors_json = json.dumps(index_slice, ensure_ascii=False)

    vendor_section = ""
    if vendor_prompt_text and str(vendor_prompt_text).strip():
        vendor_section = f"""

VENDOR KHUSUS YANG TERDETEKSI:
- vendor_id: {vendor_id}

ATURAN KHUSUS VENDOR:
{vendor_prompt_text}
"""

    bl_mark_number_detail_rule = """

ATURAN bl_mark_number:
- Untuk vendor selain shimano_inc, bl_mark_number diekstrak pada header pass.
- Pada content/detail pass vendor selain shimano_inc, isi bl_mark_number dengan "null".
"""
    if _is_shimano_inc_vendor_id(vendor_id):
        bl_mark_number_detail_rule = """

ATURAN KHUSUS SHIMANO_INC UNTUK bl_mark_number:
- bl_mark_number WAJIB diekstrak pada content/detail pass, BUKAN pada header pass.
- Gunakan dokumen Bill of Lading saja.
- Ambil dari kolom/area "Marks and Numbers".
- Karena output detail berbasis line item, isikan bl_mark_number pada row yang paling relevan dengan mark/PO/item tersebut.
- Jika mark berlaku global untuk seluruh BL dan tidak bisa dipetakan ke item tertentu, isi nilai yang sama pada semua row output batch yang relevan.
- Jika tidak ditemukan pada BL, isi "null".
"""

    return f"""
ROLE:
Anda adalah AI IDP professional yang fokus pada DATA DETAIL PER LINE ITEM.
Rule-based, deterministik, anti-halusinasi.
Tugas kamu adalah mengekstrak dokumen dan melakukan mappingan data berdasarkan line item daripada dokumen.
Mappingan harus masuk akal sesuai dengan yang di ekstrak

KONTEKS:
Total line item invoice = {total_row}.
Anda sekarang hanya mengerjakan item index {first_index}..{last_index}.

SANGAT PENTING (ANTI-SALAH INDEX):
Saya berikan "ANCHOR INDEX" untuk item yang harus Anda ekstrak.
Anda WAJIB mengembalikan output HANYA untuk index berikut:
{anchors_json}

- Anchor terdiri dari dua sumber:
 1) Invoice anchor (utama)
 2) PL anchor (pendukung)

- Invoice anchor digunakan untuk menjaga identitas row:
 inv_invoice_no, inv_customer_po_no, inv_spart_item_no, inv_description, inv_quantity, inv_quantity_unit, inv_unit_price, inv_price_unit, inv_amount.

- Field inv_invoice_no WAJIB selalu ada di setiap row output dan nilainya HARUS sama persis dengan inv_invoice_no pada anchor row yang bersesuaian.
- PL anchor digunakan sebagai bukti pendukung agar model memilih pasangan row Packing List yang benar:
 pl_customer_po_no, pl_description, pl_quantity.

ATURAN:
- EKSTRAK HANYA YANG TERTULIS. JANGAN MENGARANG.
- PAHAMI DOKUMEN DAN EKSTRAK SESUAI DENGAN KEBUTUHAN KOLOMNYA
- Jika suatu field tidak ada di dokumen → isi "null" (string) atau 0 (angka).
- Tidak boleh JSON literal null → gunakan "null".
- Untuk FIELD BERTIPE NUMBER jika tidak ada → isi 0.
- Output HANYA JSON ARRAY, tanpa teks tambahan.
- Field hanya boleh diisi dari dokumen sesuai prefix-nya, TIDAK BOLEH dari dokumen lain:
  inv_* → Invoice, tidak boleh dari dokumen lain
  pl_* → Packing List, tidak boleh dari dokumen lain
  bl_* → Bill of Lading, tidak boleh dari dokumen lain
  coo_* → Certificate of Origin, tidak boleh dari dokumen lain
- Jika dokumen tidak tersedia → semua field dengan prefix dokumen tersebut (contoh: inv_*, pl_*, bl_*, coo_*) WAJIB diisi dengan "null" / 0 sesuai tipe.
- Jika terdapat merged cell vertikal yang mencakup beberapa line item / beberapa row, maka nilai pada merged cell tersebut HANYA boleh diassign ke line item paling atas dalam merge group.
- Semua line item lain yang berada di bawah merged cell yang sama WAJIB diisi 0 untuk field numerik yang berasal dari merged cell tersebut.
- Jangan melakukan pembagian proporsional, jangan melakukan averaging, dan jangan menduplikasi nilai merged cell ke semua row.
- Merge group harus ditentukan berdasarkan cakupan visual merge vertikal pada tabel.
- "Top row" adalah row pertama / paling atas yang secara visual bersinggungan dengan merged cell tersebut.
- Rule ini berlaku untuk field numerik yang berasal dari merged cell, termasuk namun tidak terbatas pada:

  ----------------------
  |ITEM NAME | VOLUME  |
  |--------------------|
  |row 1     |         |
  |----------|         |
  |row 2     |   13.5  |
  |----------|         |
  |row 3     |         |
  ----------------------
  
  Maka:
  - row paling atas: pl_volume = 13.5
  - row ke-2: pl_volume = 0
  - row ke-3: pl_volume = 0

- Apabila pada package count terdapat dua atau lebih value yang berbeda, tambahkan values tersebut dengan package unit terbesar
  Contoh:
  ( 2 P/T     &     83 C/T)
  < 32 C/T>
  Artinya: Total package count terdapat 2 palet yang berisi 32 carton dan 80 carton.
  Maka: pl_total_package = 2 P/T + 83 C/T = 82
  Karena: satuan P/T > C/T, sehingga yang ditambahkan adalah 2 P/T dan bukan 32 P/T.


- Apabila ditemukan dokumen dengan format seperti berikut:
  [2006722]               Battery; BT-DN300;        Part# KBTDN3003
  PT. IS                  Spec: Bulk                PRODUCT CD 27HK000A066
  P/O No. 43018041                                  S.PART# KBTDN3003

  C/T NO: 1-4         400 PCS           32 Kg       42.4 Kg     0.236M3
  (4 C/T)
                ------------------------------------------------------------
                Total 400 PCS           

  PLT NO: 5-6           85 PCS            6.8 Kg       9.4 Kg     0.058M3
  (2 P/T... 32 C/T)
                ------------------------------------------------------------
                Total 85 PCS

  PENTING: PERHATIKAN POSISI GARIS PEMISAH (separator) YANG MEMISAH ANTARA SUB-ROW DENGAN TOTAL/SUBTOTAL!
  Line yang terpisah dengan separator (garis panjang pemisah) namun tidak memiliki informasi P/O No. atau S.PART yang jelas, JANGAN LANGSUNG DIABAIKAN! Line tersebut dapat diasumsikan tergabung dengan line item di atasnya.
  JANGAN BUAT LINE BARU! CUKUP TAMBAHKAN NILAI NUMERIKNYA SAJA KE LINE ITEM DI ATASNYA! (BUKAN DI BAWAHNYA!)
  Sebagai contoh pada format tersebut, berarti tergabung menjadi 1 line item dengan:
  - pl_quantity = 400 + 85 = 485 PCS
  - pl_package_count = 4 C/T + 2 P/T = 6 (karena 1 P/T bisa berisi beberapa C/T, sedangkan C/T tidak bisa berisi P/T, maka yang dijumlahkan adalah value dari package count dengan hierarki terbesar yaitu P/T)
  - pl_nw = 32 + 6.8 = 38.8 Kg 
  - pl_gw = 42.4 + 9.4 = 51.8 Kg
  - pl_volume = 0.236 + 0.058 = 0.294 M3          
  - po_no = 43018041
  - pl_item_no = KBTDN3003
  - pl_description = Battery; BT-DN300; Spec: Bulk;

- Jika merged cell berada pada kolom non-numerik, hanya row paling atas yang boleh membawa value tersebut, sedangkan row lain di bawahnya isi "null".
- Jangan membuat row baru dan jangan menggeser urutan output hanya karena ada merged cell.
- TOLONG EKSTRAK SESUAI DENGAN KEBUTUHAN KOLOMNYA. Jika yang di ekstrak package count, package count pada dokumen lah yang akan di ekstrak. Jika itu quantity, maka ekstrak quantity dari dokumen jadi PAHAMI APA YANG AKAN DI EKSTRAK.
- Untuk field pl_quantity dan pl_package_count, pahami makna header kolom terlebih dahulu sebelum mengekstrak value.
- Jangan menukar quantity dengan package_count.
- Jika tabel menggunakan format quantity-per-package dan package-count, maka pl_quantity dan pl_package_count harus dipetakan sesuai fungsi masing-masing, bukan sekadar berdasarkan posisi angka.
  pl_volume, pl_gw, pl_nw, pl_package_count, inv_gw, coo_gw, coo_amount, atau field numerik lain yang secara visual ditulis sebagai 1 merged cell untuk beberapa row.
- Contoh:
  Jika ada 3 row item dan kolom volume ditampilkan sebagai 1 merged cell bernilai 13.5 yang mencakup ketiga row tersebut seperti:
- Jika 1 item invoice cocok dengan beberapa sub-row PL yang masih item yang sama
  (PO sama/konsisten, description sama/konsisten, part/item code sama/konsisten, beda hanya CTN NO/range carton),
  maka gabungkan semua sub-row tersebut ke 1 output row.

- Dalam kasus ini:
  pl_quantity = jumlah semua quantity sub-row valid
  pl_package_count = jumlah semua package_count sub-row valid
  pl_nw = jumlah semua nw sub-row valid
  pl_gw = jumlah semua gw sub-row valid
  pl_volume = jumlah semua volume sub-row valid

- Jangan hanya ambil sub-row pertama jika masih ada sub-row lain yang jelas merupakan pecahan item yang sama.
- Row TOTAL/SUBTOTAL hanya untuk validasi, jangan dijumlahkan lagi jika detail sub-row sudah ada.

{bl_mark_number_detail_rule}
OUTPUT SCHEMA (CONTENT ONLY, TANPA HEADER):
{DETAIL_LINE_SCHEMA_TEXT}

FIELD YANG TIDAK BOLEH NULL:
{UNNULLABLE_FIELD}

GENERAL KNOWLEDGE:
{vendor_section}

OUTPUT RESTRICTION:
- Output HARUS dimulai '[' dan diakhiri ']'
- Tidak boleh markdown/plan/teks lain.
- Tidak boleh field tambahan.
- Jumlah object harus = {last_index - first_index + 1}
- Urutan object harus sama persis dengan ANCHOR INDEX.
"""