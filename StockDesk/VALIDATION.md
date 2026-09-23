# Validation record

Date: 21 September 2026. All records used in testing are synthetic.

- 27 backend checks passed: stock receipt, insufficient-stock rejection, atomic transfers, BOM consumption/wastage and shortage rollback, cycle rejection, tax splits/discounts, duplicate-line overselling, client validation, immutable invoice snapshots, unbilled conversion and reversal, payments, stale-screen rejection, financial-year sequence, ledger replay, master-history protection, formula escaping, signed gateway authentication, repeat-request idempotency and recovery after report-generation failure.
- 6 Python/UI checks passed: preview totals against the backend, short and multipage PDF generation, signed HTTP requests and backend errors, mocked PIN lookup/invalid input, unconfigured setup screen and authenticated navigation through all app pages with draft-invoice creation.
- Python source compiled successfully.
- Sample invoice rendered and inspected after font embedding. Long-table rendering inspected for page breaks and repeated headers.
- Tested dependencies are pinned in requirements.txt.

Not yet verified: a real Google Apps Script deployment and authorization, a live Google Sheets write/read cycle, the live external PIN service, hosted Streamlit access, representative production load, opening balances, supplied HSN/GST classifications, the existing invoice series and the user's actual invoice design. Complete these checks before production use.

The tests exercise the real business-rule and gateway code with mocked Google services. They do not claim that the user's accounts are already connected.

## Update 23 September 2026

Word template filled and rendered to one PDF page; page image inspected.
Repeated article row substitution, unresolved-placeholder check, saved totals,
unbilled notice and PDF-to-image preview checks passed. Reporting tests: 2 passed.
Python source compilation passed. Live Streamlit/LibreOffice installation and
Google Sheets integration still require deployment verification.
