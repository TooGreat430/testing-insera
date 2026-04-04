import json
import os
import sys
import traceback

from function import run_ocr

if __name__ == "__main__":
    invoice_name = "unknown"
    pdf_paths = []

    try:
        if len(sys.argv) < 4:
            raise Exception("Argumen worker tidak lengkap")

        invoice_name = sys.argv[1]
        with_total_container = sys.argv[2].lower() == "true"
        pdf_paths = json.loads(sys.argv[3])
        invoice_doc_count = int(sys.argv[4]) if len(sys.argv) > 4 else 1

        run_ocr(
            invoice_name=invoice_name,
            uploaded_pdf_paths=pdf_paths,
            with_total_container=with_total_container,
            invoice_doc_count=invoice_doc_count,
        )

    except Exception as e:
        print(f"[OCR WORKER ERROR] invoice={invoice_name} err={e}")
        traceback.print_exc()

    finally:
        for p in pdf_paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass