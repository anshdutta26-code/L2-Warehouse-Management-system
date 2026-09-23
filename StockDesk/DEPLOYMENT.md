# StockDesk deployment

Streamlit Community Cloud settings:

- Repository: anshdutta26-code/L2-Warehouse-Management-system
- Branch: main
- Main file: StockDesk/app.py

Use StockDesk/requirements.txt. LibreOffice Writer and DejaVu fonts are listed
in packages.txt at the repository root for the Linux build.

Complete the Google Apps Script backend setup in START_HERE.md and put the
backend URL, secret and user password hashes into Streamlit's Secrets settings.
Never commit real credentials, client data or business invoices to this public repo.

The existing root app.py is the upstream warehouse reference. StockDesk/app.py
is the separate new-firm application. It uses Google Sheets and no upstream
firm branding or Supabase credentials. An empty installation stops at setup
instructions until the backend is configured.

Publication of source code is not deployment. Live hosting and Google Sheets
configuration still need to be completed and verified.
