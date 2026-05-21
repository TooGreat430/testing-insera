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