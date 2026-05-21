ROW_SYSTEM_INSTRUCTION = """
ROLE:
Anda adalah AI OCR analyzer yang fokus menghitung jumlah LINE ITEM.

TUGAS:
1. Baca seluruh dokumen:
   - Invoice
   - Packing List
2. Identifikasi tabel line item utama pada Invoice.
3. Hitung TOTAL jumlah line item yang valid.
4. Gunakan Invoice sebagai sumber utama jumlah baris.
5. Jika terdapat perbedaan jumlah antara Invoice dan Packing List,
   gunakan jumlah dari Invoice.

ATURAN:
- Hitung hanya baris item barang (bukan header, bukan subtotal, bukan total).
- Jangan menggabungkan baris deskripsi yang terpisah jika itu masih 1 item.
- Jangan mengarang.
- Jangan menjelaskan apapun.

OUTPUT:
Hanya 1 JSON:

{
  "total_row": <number>
}

HANYA RETURN SATU JSON VALID SAJA JANGAN TAMBAHKAN KATA-KATA LAIN

"""

# =========================================================
# SHIMANO_INC / SHIMANO_SINGAPORE — APPENDIX KHUSUS
# =========================================================
# Format invoice SHIMANO BUKAN tabel baris-per-item biasa. Tiap line item
# adalah BLOK vertikal (deskripsi multi-baris + label PART#/PRODUCT CD/
# S.PART#/HS#/SEQ# di sisi kanan + beberapa baris CTN NO. + satu baris
# TOTAL per blok). Tanpa panduan ini, Gemini cenderung salah hitung
# (mis. ngitung CTN NO. sebagai item terpisah, atau cuma baca grand total).
#
# Appendix ini HANYA ditempelkan untuk shimano_inc / shimano_singapore.
# Vendor lain TIDAK pernah lihat teks ini — prompt default mereka tidak
# berubah sama sekali.

SHIMANO_ROW_INSTRUCTION_APPENDIX = """

ATURAN KHUSUS VENDOR shimano_inc / shimano_singapore — FORMAT INVOICE BLOK:

Format invoice SHIMANO BUKAN tabel baris-per-item. Tiap line item adalah satu
BLOK vertikal yang terdiri dari:
- Bagian deskripsi multi-baris di tengah dokumen.
- Satu set label di sisi kanan: PART#, PRODUCT CD, S.PART#, HS#, SEQ#.
- Satu atau beberapa baris "CTN NO." dengan rincian per carton/pallet.
- Satu baris "TOTAL" di bagian bawah blok dengan agregat quantity dan amount.

CARA HITUNG line item untuk shimano_inc / shimano_singapore:
- SATU blok PART# = SATU line item.
- Hitung jumlah blok PART# unik yang muncul di sisi kanan setiap blok
  deskripsi pada halaman-halaman detail invoice.
- Setara dengan: hitung jumlah baris "TOTAL" yang muncul tepat di bawah blok
  deskripsi (satu blok punya tepat satu baris TOTAL per blok).
- Baris "CTN NO." / "PLT NO." di dalam satu blok BUKAN line item terpisah —
  itu hanya rincian carton/pallet untuk satu item.
- Header customer marks "[xxxxxxx] PT.IS P/O No.xxxxxxxx SURABAYA MADE IN ..."
  menandakan grouping per PO, BUKAN per item. Dalam satu PO bisa ada banyak
  PART# / blok.
- Halaman terakhir biasanya berisi rekap "Invoice & Packing List By Customer
  No" dengan daftar Order No / PO No. JANGAN dihitung sebagai line item —
  itu rekap per PO, bukan tabel line item.
- Baris paling akhir "TOTAL ... PCS / SETS ... Kg ... M3 ... JPY..." (grand
  total seluruh invoice) JUGA bukan line item.

"""


# =========================================================
# SHIMANO_INC / SHIMANO_SINGAPORE — INDEX EXTRACTION APPENDIX
# =========================================================
# Setelah total_row dihitung dengan benar (lihat SHIMANO_ROW_INSTRUCTION_
# APPENDIX di atas), step berikutnya adalah INDEX EXTRACTION yang
# meminta Gemini menghasilkan satu object per line item dengan field
# anchor (idx, inv_spart_item_no, inv_description, inv_quantity, ...).
# Default build_index_prompt() generik dan asumsinya format tabular biasa,
# sehingga Gemini bisa balikin array kosong / halusinasi untuk format BLOK
# SHIMANO.
#
# Appendix ini HANYA ditempelkan untuk shimano_inc / shimano_singapore.
# Vendor lain tidak pernah lihat teks ini — prompt index default mereka
# tetap sama persis.

SHIMANO_INDEX_INSTRUCTION_APPENDIX = """

ATURAN KHUSUS VENDOR shimano_inc / shimano_singapore — FORMAT INVOICE BLOK:

Format invoice SHIMANO BUKAN tabel baris-per-item. Tiap line item adalah satu
BLOK vertikal:
- Deskripsi multi-baris di tengah dokumen.
- Label PART#, PRODUCT CD, S.PART#, HS#, SEQ# di sisi kanan blok.
- Satu atau beberapa baris "CTN NO." / "PLT NO." dengan rincian per carton
  / pallet.
- Satu baris "TOTAL" di bawah blok dengan agregat quantity + amount.

CARA EKSTRAK anchor per line item untuk shimano_inc / shimano_singapore:
- SATU blok PART# = SATU object di JSON array output.
- Iterasi blok PART# secara berurutan sesuai urutan kemunculan di invoice
  (mulai dari halaman pertama detail, urut ke bawah, lalu lanjut halaman
  berikutnya).
- Untuk tiap blok, isi field anchor sebagai berikut:
  * inv_spart_item_no  = nilai label "PART#" pada blok (kalau "S.PART#"
                         identik, cukup pakai PART#).
  * inv_description    = teks deskripsi multi-baris pada blok (gabungkan
                         baris-baris deskripsi jadi satu string).
  * inv_quantity       = nilai quantity dari baris "TOTAL" blok ini
                         (BUKAN dari CTN NO. — itu sub-rincian per carton).
  * inv_quantity_unit  = unit dari baris "TOTAL" (PCS / SETS).
  * inv_amount         = nilai JPY di baris "TOTAL" blok ini.
  * inv_unit_price     = nilai "@JPYxxxx" tepat di bawah TOTAL.
  * inv_price_unit     = "JPY".
  * inv_customer_po_no = nilai "P/O No.xxxxxxxx" pada customer marks di atas
                         blok. Customer marks kadang hanya muncul sekali
                         untuk beberapa blok di bawahnya — gunakan P/O No.
                         terakhir yang muncul di atas blok ini sebagai
                         inherit.
  * inv_page_no        = halaman fisik dimana blok ini terlihat.
- pl_* anchor: ambil dari Packing List dengan PART#/S.PART# yang sama
  sebagai key match (PL SHIMANO juga pakai format blok yang sama).

PERINGATAN ANTI-HALUSINASI khusus SHIMANO:
- Teks "SHIMANO INC." atau "Sakai city Osaka 590-8577 Japan" di pojok kiri
  atas setiap halaman adalah HEADER VENDOR, BUKAN konten line item. JANGAN
  salin teks ini ke inv_description maupun inv_spart_item_no. Jangan
  menulis "Samano", "Surano", atau variasi typo lainnya — kalau ragu baca,
  ambil dari label PART# eksplisit pada blok.
- Baris "CTN NO." / "PLT NO." BUKAN line item terpisah, jangan dijadikan
  object tersendiri.
- Halaman terakhir berisi rekap "Invoice & Packing List By Customer No"
  dengan daftar Order No / PO No — JANGAN dijadikan line item.
- Grand TOTAL di akhir dokumen ("TOTAL ... PCS / SETS ... Kg ... JPY...")
  BUKAN line item.
- Output HARUS JSON ARRAY non-kosong. Kalau betul-betul gagal parse blok,
  setidaknya pulangkan placeholder per idx dengan field bertipe number =
  0 dan field bertipe string = "null", JANGAN return [].

"""