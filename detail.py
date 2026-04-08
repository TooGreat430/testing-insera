import json

# =========================
# HEADER FIELDS (doc-level)
# =========================



DETAIL_CSV_FIELD_ORDER_FULL = [
    "match_score",
    "match_description",

    "inv_invoice_no",
    "inv_invoice_date",
    "inv_customer_po_no",
    "inv_messrs",
    "inv_messrs_address",
    "inv_vendor_name",
    "inv_vendor_address",
    "inv_incoterms_terms",
    "inv_terms",
    "inv_coo_commodity_origin",
    "inv_seq",
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

    "po_no",
    "po_vendor_article_no",
    "po_text",
    "po_sap_article_no",
    "po_line",
    "po_quantity",
    "po_unit",
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
    "coo_customer_po_no",
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
    "pl_total_nw", "pl_total_gw", "pl_package_unit", "pl_weight_unit", "pl_total_volume", "pl_volume_unit", "pl_total_package",
    "bl_shipper_name","bl_shipper_address","bl_no","bl_date","bl_consignee_name","bl_consignee_address",
    "bl_consignee_tax_id","bl_seller_name","bl_seller_address","bl_lc_number","bl_notify_party","bl_vessel",
    "bl_voyage_no","bl_port_of_loading","bl_port_of_destination",
    "coo_no","coo_form_type","coo_invoice_no","coo_invoice_date","coo_shipper_name","coo_shipper_address",
    "coo_consignee_name","coo_consignee_address","coo_consignee_tax_id","coo_producer_name","coo_producer_address",
    "coo_departure_date","coo_vessel","coo_voyage_no","coo_port_of_discharge", "coo_package_unit", "coo_gw_unit", "coo_amount_unit", "coo_origin_country",
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

    "pl_customer_po_no", "pl_item_no","pl_description","pl_quantity","pl_package_count","pl_nw","pl_gw",
    "pl_volume","pl_total_quantity","pl_total_amount","pl_total_nw","pl_total_gw","pl_total_volume","pl_total_package",

    "po_no","po_vendor_article_no","po_text","po_sap_article_no","po_line","po_quantity","po_unit","po_price","po_currency",
    "po_info_record_price","po_info_record_currency",

    "bl_description","bl_hs_code","bl_mark_number",

    "coo_seq","coo_mark_number","coo_description","coo_hs_code","coo_quantity","coo_unit","coo_package_count",
    "coo_gw", "coo_amount","coo_criteria","coo_customer_po_no",
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

    "inv_page_no": number,
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

CATATAN:
- inv_* anchor diambil dari Invoice.
- pl_* anchor diambil dari Packing List.
- Jika pasangan row PL tidak ditemukan dengan yakin, isi field pl_* dengan "null"/0.
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
  "pl_package_unit": {"type": "string", "enum":  ["CT", "PX", "PK", "BL", "null"]},
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
  "coo_package_unit": {"type": "string", "enum": ["CT", "PX", "PK", "BL", "null"]},
  "coo_gw_unit": "string",
  "coo_amount_unit": "string",
  "coo_origin_country": "string",
}

GENERAL KNOWLEDGE:

1. inv_vendor_name pada Invoice:
   - BUKAN berasal dari PT Insera Sena.
   - Jika terdapat PT Insera Sena dan pihak lain → pilih yang BUKAN PT Insera Sena.

2. Messrs pada Packing List (PL) dan Invoice (INV):
   - SELALU PT Insera Sena.
   - Jika terdapat beberapa nama → pilih PT Insera Sena.
   - Jika ada variasi nama perusahaan PT Insera Sena seperti:
     "PT. INSERA SENA", "PERSEROAN TERBATAS INSERA SENA", "PT INSERASENA", atau bentuk lainnya yang merujuk pada PT Insera Sena,
     NORMALISASI menjadi: "PT Insera Sena"

3. Messrs address pada Packing List (PL) dan Invoice (INV):
   - Hanya ekstrak address dari perusahaannya tanpa kode posnya, contoh:
      JL VETERAN, LINGKAR TIMUR, KEL. WADUNGASIH, KEC. BUDURAN, KAB. SIDOARJO, PROV. JAWA TIMUR 61252
      Berarti yang diekstrak hanya: JL VETERAN, LINGKAR TIMUR, KEL. WADUNGASIH, KEC. BUDURAN, KAB. SIDOARJO, PROV. JAWA TIMUR
   - JANGAN SAMPAI SALAH EKSTRAK! PAHAMI KONTEKS. Jika messrs address maka yang ditanyakan adalah alamat jadi penulisan harus tepat
     contoh: Di dokumen seperti ini JI VETERAN maka perlu di convert menjadi "JL VETERAN" karena konteksnua adalah JALAN

4. inv_price_unit SAMA dengan inv_amount_unit:
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

5. pl_total_package dan pl_total_quantity:
   - Jika pada dokumen terdapat dua value dengan UNIT yang berbeda, maka sum kedua value tersebut
     contoh: pada dokumen terlampir total dari quantity seperti ini 2139PCE/150SET. Maka sum kedua value tersebut adalah 2289 (2139 + 150 = 2289)

5. pl_total_package:
   - Untuk total package yang digunakan, liat secara detail berapa package secara total. Jika secara eksplisit dikatakan totalnya, langsung ambil valuenya.
   - Jika tidak secara eksplisit, contoh:
     Total Number of Packages: 1,   Package Detail: 1 PLT(S)  Number of Carton: 9
     Maka pl_total_package adalah 9 karena secara detail, ada 9 total package.

6. LC Logic pada Bill of Lading (BL):
   - Jika bl_consignee_name mengandung nama perusahaan Bank → BL bertipe LC.
   - Jika tidak → BL bukan bertipe LC.

7. Jika pada dokumen Bill of Lading (BL) bertipe LC:
    - bl_consignee_name diambil dari notify party
    - bl_consignee_address diambil dari notify party

8. inv_coo_commodity_origin
   - SEBUTKAN NAMA NEGARANYA SAJA TIDAK PERLU TULISAN "Made In" yang penting nama negaranya dan tulisan dalam huruf besar semua.

9. pl_volume_unit
  - volume unit yang hanya ada dua value antara CUFT dan M3
  - Jika value pada dokumen seperti ini: MÂ³ --> maka value aslinya adalah "M3"
  - Jika value pada dokumen seperti ini: CU'FT --> maka value aslinya adalah "CUFT

10. coo_gw_unit:
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

11. Semua field [tipe_dokumen]_total (contoh: inv_total_quantity, pl_total_gw, inv_total_amount) itu boleh "null" JIKA PADA DOKUMEN EMANG TIDAK DISERTAKAN VALUE DARI TOTAL TERSEBUT

12. pl_package_unit:
    - pl_package_unit HANYA boleh diambil dari BUKTI PACKAGE, bukan dari quantity unit.
    - Sumber bukti yang VALID untuk pl_package_unit hanya:
      1) kolom/header package, packing, pkgs, cartons, ctn, pallet, plt, bale, package detail (Contoh: pada dokumen ada header bernama "Carton No.")
      2) unit yang menempel langsung pada package_count
      3) header rasio kemasan seperti PCS/CTN, SET/CTN, PCS/BOX, QTY/CARTON -> ambil unit kemasannya, BUKAN unit quantity

    - Sumber bukti yang TIDAK VALID untuk pl_package_unit:
      1) kolom quantity / qty / pcs / sets / units
      2) inv_quantity_unit
      3) unit penjualan barang
      4) unit yang hanya menjelaskan isi per kemasan

    - Jika satuan yang ditemukan berasal dari quantity column, quantity header, atau quantity-per-package header, MAKA JANGAN gunakan untuk pl_package_unit.

    - pl_package_unit harus final dalam canonical value berikut saja: ["CT", "PX", "PK", "BL", "null"]
      pl_package_unit TIDAK BISA DILUAR UNIT INI. JIKA DILUAR UNIT YANG DISEDIAKAN MAKA BUKAN UNIT DARI pl_package_unit.

    - Mapping canonical:
      CTN / CARTON / CARTONS -> CT
      PLT / PALLET / PALLETS -> PX
      BALE / BALES -> BL
      mixed standalone package types -> PK

    - Jika bukti package unit tidak ada atau yang ditemukan hanya quantity unit -> "null".

13. bl_shipper dan bl_seller
   - Penempatan bl_shipper selalu diatas dari bl_seller
   - Jika bingung, terdapat tulisan "O/B" Untuk memisahkan antara bl_shipper dan bl_seller
     contoh:
      SUZHOU GEYA TRADING CO.,LTD.
      NO.6 DONGYANLI RD., SUZHOU INDUSTRIAL 
      PARK 215125,SUZHOU CHINA 
      O/B BAFANG ELECTRIC MOTOR SCIENCE TECHNOLOGY B.V.
      KOVEL 11, 5431 ST CUIJK, THE NETHERLANDS 

   Maka value dari bl_shipper_name adalah SUZHOU GEYA TRADING CO.,LTD. dan bl_seller_name adalah BAFANG ELECTRIC MOTOR SCIENCE TECHNOLOGY B.V.

14. bl_voyage_no:
   - Penempatan dari bl_voyage_no selalu di sebelah bl_vessel
   - Format dari bl_voyage_no diawali dengan huruf terus konektor terus kode. Tugas anda ambil setelah V nya
     Contoh:
     V.S018
     Berarti value tersebut adalah S018
"""

def build_detail_prompt_from_index(total_row: int, index_slice: list, first_index: int, last_index: int) -> str:
    anchors_json = json.dumps(index_slice, ensure_ascii=False)
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
Anda WAJIB mengembalikan output array dengan JUMLAH object = jumlah anchor,
dan URUTANNYA HARUS SAMA persis dengan urutan anchor.

ANCHOR INDEX (JSON):
{anchors_json}

- Anchor terdiri dari dua sumber:
  1) Invoice anchor (utama)
  2) PL anchor (pendukung)

- Invoice anchor digunakan untuk menjaga identitas row:
  inv_invoice_no, inv_customer_po_no, inv_spart_item_no, inv_description, inv_quantity, inv_quantity_unit, inv_unit_price, inv_price_unit, inv_amount.

- Field inv_invoice_no WAJIB selalu ada di setiap row output dan nilainya HARUS sama persis dengan inv_invoice_no pada anchor row yang bersesuaian.
- PL anchor digunakan sebagai bukti pendukung agar model memilih pasangan row Packing List yang benar:
  pl_customer_po_no, pl_description, pl_quantity.

- inv_page_no dan pl_page_no adalah nomor halaman tempat anchor ditemukan pada masing-masing dokumen di file detail.

- PL anchor TIDAK BOLEH membuat object baru.
  Jumlah object output tetap harus mengikuti jumlah anchor invoice.

- Jika ada beberapa kandidat row PL, pilih yang paling konsisten dengan:
  1) pl_customer_po_no
  2) pl_description
  3) pl_quantity

- Jika bukti PL tidak cukup yakin, field pl_* boleh diisi "null"/0.
- DILARANG menggunakan row PL dari PO berbeda untuk mengisi line item invoice ini.

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
  pl_volume, pl_gw, pl_nw, pl_package_count, inv_gw, coo_gw, coo_amount, atau field numerik lain yang secara visual ditulis sebagai 1 merged cell untuk beberapa row.
- Contoh:
  Jika ada 3 row item dan kolom volume ditampilkan sebagai 1 merged cell bernilai 13.5 yang mencakup ketiga row tersebut seperti:

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
- Jika merged cell berada pada kolom non-numerik, hanya row paling atas yang boleh membawa value tersebut, sedangkan row lain di bawahnya isi "null".
- Jangan membuat row baru dan jangan menggeser urutan output hanya karena ada merged cell.
- TOLONG EKSTRAK SESUAI DENGAN KEBUTUHAN KOLOMNYA. Jika yang di ekstrak package count, package count pada dokumen lah yang akan di ekstrak. Jika itu quantity, maka ekstrak quantity dari dokumen jadi PAHAMI APA YANG AKAN DI EKSTRAK.
- Saat membaca OCR, bedakan angka "0" dan huruf kapital "O" berdasarkan konteks field.
- Untuk field code / part number / article number yang bersifat alfanumerik, tentukan "0" atau "O" berdasarkan pola code, posisi karakter, dan kemunculan berulang pada row lain.
- Untuk field pl_quantity dan pl_package_count, pahami makna header kolom terlebih dahulu sebelum mengekstrak value.
- Jangan menukar quantity dengan package_count.
- Jika tabel menggunakan format quantity-per-package dan package-count, maka pl_quantity dan pl_package_count harus dipetakan sesuai fungsi masing-masing, bukan sekadar berdasarkan posisi angka.

OUTPUT SCHEMA (CONTENT ONLY, TANPA HEADER):
{DETAIL_LINE_SCHEMA_TEXT}


GENERAL KNOWLEDGE DETAIL:

1. Output DETAIL merepresentasikan DATA PER LINE ITEM.

2. customer_po_no pada Invoice dan juga PL:
   - PO No. dapat terletak di atas Description Item atau memiliki kolom tersendiri jadi PAHAMI setiap line item itu PO No nya itu apa.
   - Jika invoice_customer_po_no bernilai "null", gunakan invoice_customer_po_no terakhir yang valid dari line item sebelumnya.
   - customer_po_no format numerik, biasanya berisi 8 digit (TANPA ALPHABET), Dan biasanya diawali dengan angka 4
      Contoh
      - 44200032
      - 49021348
      - 45295210
      - 45295893
      - 45297175
  - KHUSUS Vendor FOX, JIKA PO No pada Invoice tidak ada, maka boleh NULL NAMUN TETAP HARUS DIISI DARI "pl_customer_po_no"
  - INGAT BAHWA customer_po_no HARUS DIAWALI DENGAN ANGKA 4 jadi jika ada kasus:
    Po No:
    C25-1544U/45323564
    Maka value dari customer_po_no adalah "45323564". ABAIKAN Code depannya (C25-1544U) dan "/" juga
  - customer_po_no terkadang exist tidak sesuai dengan kolomnya nama kolom Item No. tapi valuenya PO No. JADI PAHAMI FORMAT DARI customer_po_no

3. inv_spart_item_no:
   - Field ini merepresentasikan PART NUMBER / SPARE PART NUMBER / ITEM PART CODE yang sesungguhnya, BUKAN nomor urut row, BUKAN index, dan BUKAN sequence number.
   - Berikut adalah list informasi yang bisa diekstrak sebagai inv_spart_item_no, berdasarkan prioritas dari yang paling tinggi ke paling rendah:
      1. Customer Article Number -> Biasanya terdapat pada header kolom tersebut.
      2. CODE -> Biasanya terdapat pada kolom deskripsi, ditandai dengan label CODE atau tertulis dalam kurung siku [CODE] - DESKRIPSI/NAMA ITEM (Prioritaskan yang memiliki label CODE)
      3. MATERIAL -> Biasanya terdapat pada header kolom tersebut.
      4. MODEL -> Biasanya terdapat pada header kolom tersebut.
      
   - Jika terdapat kolom khusus Item No dan juga terdapat CODE pada Description, maka inv_spart_item_no diambil dari CODE pada Description.
     Contoh:
        Item No: 
        CWSSXAF38D0002-165

        Description:
        SAMOX CHAINWHEEL MODEL: 
        AF38-D28NS-BG31, BLACK
        1 SP, (3/32" *28T* 165 MM), ALLOY CRANK, STEEL 28T BED,
        49MM 0T, W/CG, W/O SPIDER, SQUARE, C/CAPLESS BOLT
        W/O LOGO , W/BCD76, ALLOY CG
        ** CODE: CWSSXAF38D0002

        Maka inv_spart_item_no = CWSSXAF38D0002,
        BUKAN CWSSXAF38D0002-165 (karena ambil dari CODE di Description BUKAN dari kolom khusus Item No)

   - Jika di dalam 1 area / cell terdapat 2 baris atau lebih, lalu ada angka pendek pada satu baris dan code alfanumerik pada baris lain, maka:
     - angka pendek tersebut biasanya adalah index / item number / nomor urut
     - code alfanumerik adalah inv_spart_item_no yang benar
     
     - Contoh:
     1
     CWSFSSH12001-R
     Maka:
     - "1" adalah index / nomor urut
     - "CWSFSSH12001-R" adalah inv_spart_item_no

   - Jadi untuk inv_spart_item_no, prioritaskan token yang berbentuk code part number, bukan angka urut pendek.

   - Ciri umum inv_spart_item_no:
     - Biasanya berbentuk alfanumerik
     - Sering mengandung kombinasi huruf dan angka
     - Dapat mengandung dash / hyphen, slash, atau separator lain
     - Umumnya lebih panjang daripada index row
     - Biasanya terlihat seperti product code / part code

4. inv_quantity dan pl_quantity:
   - untuk membaca quantity harap pahami tipe dokumen yang akan di ekstrak.
   - jika inv_quantity, maka quantity pada dokumen invoice yang akan di ekstrak
   - jika pl_quantity, maka quantity pada dokumen Packing List yang akan di ekstrak.
   - JANGAN KEBALIK DAN AMBIL SESUAI DENGAN KEBUTUHAN KOLOM. 
  
5. quantity dan package_count:
   - quantity dan package_count adalah dua field yang berbeda dan tidak boleh saling menggantikan.
   - quantity adalah jumlah unit barang yang dikirim atau total item quantity.
   - package_count adalah jumlah kemasan fisik yang digunakan untuk mengirim barang, seperti carton, box, pallet, crate, package, dan jenis kemasan lainnya.

   - Header kolom harus dipahami berdasarkan maknanya:
     - Jika header menunjukkan "QTY", "QUANTITY", "PCS", "SETS", "UNITS", atau sejenisnya, maka itu mengarah ke quantity barang.
     - Jika header menunjukkan "PKGS", "PACKING", "CARTON", "CTNS", "BOX", "PALLET", atau sejenisnya, maka itu mengarah ke package_count.
     - Jika header menunjukkan format seperti "QTY/PKGS", "PCS/CTN", "SETS/BOX", "QTY/CARTON", atau pola "X per package", maka itu berarti quantity per package, BUKAN total quantity dan BUKAN package_count.

   - Contoh:
     Header:
     QTY/PKGS | PACKING PKGS

     Value:
     10       | 20

     Maka:
     - 10 adalah quantity per package
     - 20 adalah package count
     - pl_package_count = 20
     - pl_quantity = 10 × 20 = 200

   - Jika terdapat beberapa nilai dan jenis package count atau quantity pada satu line item seperti:
      ( 1 P/T & 65 C/T)
      Maka:
      Package count atau quantity line item tersebut = 1 + 65 = 66

6. pl_item_no
   - Setiap item memiliki item_no. Jadi coba telusuri item_no dari setiap item.
   - Terletak di atas deskripsi, ada di bagian customer_po_no, atau mungkin memiliki segmen nya sendiri.
   - Berikut adalah list informasi yang bisa diekstrak sebagai pl_item_no, berdasarkan prioritas dari yang paling tinggi ke paling rendah:
      1. Customer Article Number -> Biasanya terdapat pada header kolom tersebut.
      2. CODE -> Biasanya terdapat pada kolom deskripsi, ditandai dengan label CODE atau tertulis dalam kurung siku [CODE] - DESKRIPSI/NAMA ITEM (Prioritaskan yang memiliki label CODE)
      3. MATERIAL -> Biasanya terdapat pada header kolom tersebut.
      4. MODEL -> Biasanya terdapat pada header kolom tersebut.

    - Jika terdapat kolom Item No dan juga terdapat CODE pada description, maka pl_item_no diambil dari CODE pada kolom deskripsi.
      Contoh:
        Item No: 
        CWSSXAF38D0002-165
        Description:
        SAMOX CHAINWHEEL MODEL: 
        AF38-D28NS-BG31, BLACK
        1 SP, (3/32" *28T* 165 MM), ALLOY CRANK, STEEL 28T BED,
        49MM 0T, W/CG, W/O SPIDER, SQUARE, C/CAPLESS BOLT
        W/O LOGO , W/BCD76, ALLOY CG
        ** CODE: CWSSXAF38D0002
        Maka inv_spart_item_no = CWSSXAF38D0002 dan BUKAN CWSSXAF38D0002-165 (karena prioritas CODE lebih tinggi daripada Item No)
   
   - Jika tidak ditemukan kolom seperti CODE, MATERIAL, atau MODEL, maka telursuri bagian deskripsi itemnya, biasanya ada item_no yang menempel di deskripsi item tersebut seperti:
      [CWSFSSH12001-R] FRAME PART A-F3306-1 HS NUMBER: 8714.91
      Maka pl_item_no = CWSFSSH12001-R
   - Jika pada deskripsi item ditemukan lebih dari satu kandidat pl_item_no, maka pilih yang paling kanan, seperti:
      [ LD-STM28640T3501 ] - [ FFSLDCR2862702-R ] FORK STEM;ZZ;LD-STM28640T3501;STEEL;28.6X25.4X183 40T;CROWN DIAMETER:35MM, THREADED
      Maka pl_item_no = FFSLDCR2862702-R (karena lebih kanan daripada LD-STM28640T3501)   

7. pl_package_count:                                 
   - Field ini merepresentasikan jumlah package untuk setiap line item.
   - Hitung jumlah package berdasarkan jumlah Box# yang terkait dengan line item tersebut pada dokumen Packing List.
   - Jika satu item muncul pada beberapa Box#, maka jumlahkan semua Box# tersebut sebagai package count.
   - Jangan menggunakan nilai dari bagian summary seperti "Total # of Packages". 
   - Isi dengan jumlah package (angka).
   - Contoh:
     Jika item muncul pada:
     Box#1
     Box#2
     Box#4
     maka pl_package_count = 3.
   
8. pl_volume:
   - Field ini merepresentasikan total volume untuk setiap line item.
   - Ambil nilai volume yang tercantum pada dokumen Packing List.

   - Jika nilai volume pada dokumen merupakan volume per package, maka kalikan nilai tersebut dengan jumlah package pada line item (pl_package_count) untuk mendapatkan total volume line item.
   - Gunakan hasil perhitungan tersebut sebagai nilai pl_volume.
     Contoh:
     Jika pada dokumen tertulis:
     PACKAGES = 20
     VOL/PKGS = 0.05
     Maka:
     pl_volume = 0.05 × 20 = 1.0
   
      Contoh lain:
      PACKAGES = 155
      VOL/PKGS = 0.11
      Maka:
      pl_volume = 0.11 × 155 = 17.05

9. bl_description dan bl_hs_code:
   - bl_description dimapping dengan inv_description. Jika inv_description tidak exist pada dokumen BL, maka bl_description fill null aja
   - Value bl_hs_code diisi sesuai dengan bl_descriptionnya
     Contoh:
     FRAME PART A-F3306-1 HS NUMBER: 8714.91
     FRAME PART A-HG009 HS NUMBER: 8714.91
     FRAME PART A-HG011 HS NUMBER: 8714.91
     FRAME PART A-HG045 HS NUMBER: 8714.91
     FRAME TUBING HS NUMBER: 8714.91

     pada inv_description ada value FRAME PART AF-9F-0270 (which is tidak ada), maka bl_description isi null saja
     pada inv_description ada value FRAME PART A-HG009 (which is ada), maka bl_description isi FRAME PART A-HG009
     - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen yang lain

10. coo_description:
    - Jika description diawali dengan jumlah package dan jenis packagenya, maka exclude jumlah package dan jenis packagenya dan ambil hanya deskripsi itemnya saja.
      - Contoh:
        - ONE HUNDRED AND SIXTY THREE (163) CARTONS OF SAMOX CHAINWHEEL AND CRANK MODEL: ...
          - Maka coo_description: SAMOX CHAINWHEEL AND CRANK MODEL: ...
          - ONE HUNDRED AND SIXTY THREE (163) CARTONS OF DI EXCLUDE

11. coo_customer_po_no:
   - Field ini merepresentasikan Customer PO Number yang tercantum pada dokumen vendor Shimano.
   - Dokumen vendor Shimano dapat berupa Invoice, Packing List, COO, atau dokumen lain yang diterbitkan oleh perusahaan Shimano.
   - Vendor Shimano dapat dikenali dari nama perusahaan pada dokumen, seperti:
     - SHIMANO (SINGAPORE) PTE LTD
     - SHIMANO INC.
   - Jika dokumen berasal dari vendor Shimano → telusuri dan ekstrak Customer PO Number dari dokumen.
   - Customer PO Number biasanya berupa angka (numeric) yang merujuk pada pesanan customer.
   - Ambil nilai Customer PO Number persis seperti yang tertulis pada dokumen tanpa mengubah formatnya.
   - Jika dokumen BUKAN berasal dari vendor Shimano → isi coo_customer_po_no dengan "null".

OUTPUT RESTRICTION:
- Output HARUS dimulai '[' dan diakhiri ']'
- Tidak boleh markdown/plan/teks lain.
- Tidak boleh field tambahan.
- Jumlah object harus = {last_index - first_index + 1}
- Urutan object harus sama persis dengan ANCHOR INDEX.
"""