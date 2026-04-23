import json
import os
import sys
import traceback

from function import run_ocr, run_grouped_ocr


def _collect_paths(obj):
    paths = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "forced_vendor_id":
                continue
            paths.extend(_collect_paths(value))
    elif isinstance(obj, list):
        for item in obj:
            paths.extend(_collect_paths(item))
    elif isinstance(obj, str):
        paths.append(obj)

    return paths


if __name__ == "__main__":
    invoice_name = sys.argv[1]
    with_total_container = sys.argv[2].lower() == "true"
    payload = json.loads(sys.argv[3])

    try:
        if isinstance(payload, list):
            run_ocr(
                invoice_name=invoice_name,
                uploaded_pdf_paths=payload,
                with_total_container=with_total_container
            )
        else:
            forced_vendor_id = payload.get("forced_vendor_id")
            run_grouped_ocr(
                invoice_name=invoice_name,
                uploaded_docs=payload,
                with_total_container=with_total_container,
                forced_vendor_id=forced_vendor_id,
            )

    except Exception as e:
        print(f"[OCR WORKER ERROR] invoice={invoice_name} err={e}")
        traceback.print_exc()

    finally:
        for p in set(_collect_paths(payload)):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass