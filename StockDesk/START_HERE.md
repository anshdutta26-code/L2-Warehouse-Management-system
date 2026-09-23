# StockDesk — first working version

A Streamlit app with Google Sheets as its persistent ledger. Supports stock across warehouses, client records, invoices, unbilled stock issues, BOM production and received payments. No live account is connected in this download. Your invoice sample has not yet been supplied; the included layout is a standard starting layout.

## What to send for your actual setup

1. One invoice sample, preferably PDF, with the layout you want.
2. Legal business name, address, GSTIN, phone, bank details and invoice terms.
3. Article master: article ID/name, HSN, GST rate, unit and selling rate.
4. Opening stock: article, warehouse and quantity, with an opening date/reference.
5. BOM: finished article, component article, quantity per finished unit and wastage %.
6. Client details, if already maintained. Confirm whether “without bill” means a stock issue awaiting invoice or another workflow.
7. Existing invoice number sequence. This build starts a new `INV/2627/000001` series for FY 2026–27; check the series is unused before your first real invoice.

## 1. Create the Google Sheets backend

1. Open https://script.google.com and select **New project**. Name it `StockDesk Backend`.
2. Replace `Code.gs` with the entire contents of `backend/Code.gs` from this package.
3. Save. Select the `setup` function and click **Run**. Authorize it using the business Google account that should own the workbook.
4. The execution log shows the newly created spreadsheet link. Open it. You will see Stock, Articles, Clients, Invoices, Without_Bill, BOM, Invoice_Lines, Movements, Payments, Audit, Read_Me and Events.
5. In **Project Settings → Script properties**, copy the `API_SECRET` privately. The `SPREADSHEET_ID` property identifies the workbook.
6. Choose **Deploy → New deployment → Web app**. Execute as **Me**. Access **Anyone**. Deploy, then copy the `/exec` URL. The endpoint requires signed requests using your private secret; a public URL alone cannot read or write records.
7. If your Workspace administrator disallows “Anyone” web apps, this gateway cannot be used unchanged. Ask for an approved deployment route; do not make the spreadsheet publicly editable.

To use an existing EMPTY spreadsheet instead, set its ID as `SPREADSHEET_ID` in Script properties before running `setup`. Never point this at an operational workbook with same-named tabs: generated report tabs are replaced.

## 2. Run Streamlit on your computer

Install Python 3.11 or 3.12, extract this folder, then open a terminal inside it.

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
python make_password.py
```

Copy `secrets.example.toml` to `.streamlit/secrets.toml`. Fill the backend URL, API secret and the password hash printed by the password tool. Keep the `[users.ansh]` section or change it to your preferred username.

```bash
streamlit run app.py
```

Open the local address shown by Streamlit and sign in. A local app runs while the terminal/computer is on; the records remain in Google Sheets after it closes.

## 3. Make it an online web app

Upload the source folder to a private GitHub repository, excluding `.streamlit/secrets.toml`. On https://share.streamlit.io create an app pointing to `app.py`. Paste the actual secrets into the deployment’s Secrets settings. Use Streamlit’s private sharing/access controls if available for your account, in addition to the app login. Add separate user hashes for staff.

The persistent data is in Google Sheets, not the hosting machine. This avoids depending on temporary Streamlit-hosted local files. No hosting deployment has been performed as part of this package.

## 4. Prepare for your first working day

1. **Business setup:** enter company details and real warehouse names.
2. **Articles:** add all finished goods and raw materials. HSN/GST must be verified; the app looks them up from your master and does not guess them from a product name.
3. **Import & backup:** use the empty CSV templates to import articles, clients and opening stock, or enter records manually. Opening stock ADDS quantity; do it only once. Stable IDs stop the exact same CSV file from being imported twice, but a changed file has a new identity.
4. **Clients:** enter the PIN and click Fetch. The lookup returns postal district/state and post offices; confirm the actual city/locality. All address fields remain editable if the service is unavailable.
5. **BOM & production:** save component quantities. Receive raw material first. Production then consumes components plus wastage and adds finished units. Produce stocked subassemblies separately before making their parent item.
6. Test in a separate Google Apps Script project/workbook with two articles, one client and a small test invoice. Verify stock, GST, PDF and workbook tabs before entering live stock in the production workbook.

## Daily workflow

- Receive goods through **Stock entries** with a supplier bill/reference. Purchase invoice attachment storage is not included; the reference is recorded with the receipt.
- Choose **New bill / entry**, client, warehouse and place of supply. Add items. Default rates, HSN and GST come from the article master. Edit quantities/rates/discounts in the cart. Review the draft, confirm the checkbox and press **OK - create document**.
- Open **Documents & payments** to download the final PDF. Attach it to WhatsApp/email yourself when required.
- For **Without bill / pending invoice**, stock is deducted and the client/amount remain recorded in the same ledger. Later, **Convert to tax invoice** creates an invoice without a second stock deduction. Unbilled records are not treated as tax-exempt sales or hidden records.
- Record receipts against invoices through **Documents & payments**.
- Move stock using **Warehouse transfer**. Every transfer writes matching out/in movements.
- Use **BOM & production** for production batches. If any material is short, the whole batch is rejected.
- At close of day, reconcile physical stock, invoices and payments. Make a dated Drive copy of the entire workbook including Events. Download PDFs that you need to share or archive.

## How Google Sheets stays consistent

`Events` is the authoritative ledger. Each accepted transaction is appended as one event cell while a server lock is held. Invoice numbering, stock validation and saving happen under that lock. Every request has a unique ID: retrying after an uncertain response returns the original result. A stale screen is rejected before stock changes.

The other tabs are generated views. Warehouse quantities sit side by side in **Stock**. Keep spreadsheet edit rights limited to the administrator; give staff view access and make entries in Streamlit. Editing the generated tabs does not change app balances and the next refresh overwrites those edits. Never edit/delete Events manually.

If an event saved but report refresh failed, the app reports this. Use **Rebuild Google Sheets report tabs**. The app itself reads the event ledger, so reports cannot silently override balances. For restore, make a copy of a known-good full workbook backup, point `SPREADSHEET_ID` at the copy, then run `setup`. Do not merge two ledgers or restore the JSON snapshot as an event sheet.

## Defined limits of this first version

- Intended for a small internal team and modest transaction volumes. Reads replay the event history and rebuild report tabs; Google Apps Script quotas and execution limits apply. Load-test your real data before large imports. This is not an ERP-scale database.
- One business/GST registration; up to 15 warehouses; up to 100 lines per transaction (also bounded by a 45,000-character event limit); quantities to three decimals; INR amounts rounded to paise per line.
- GST invoice mode assumes regular domestic goods, tax-exclusive rates, no reverse charge, no cess and bill-to equals ship-to. CGST/SGST or IGST uses supplier state and the explicitly confirmed place of supply. Non-GST businesses/bill-of-supply, export/SEZ transactions and separate ship-to addresses need an extension before use.
- GSTIN validation checks format/state prefix, not government registration validity. HSN/GST rates are user-maintained. PIN lookup uses a third-party service and can return district rather than city.
- GST e-invoice IRN/QR registration, e-way bills, credit/debit notes, GST return filing, batch/serial/expiry tracking, purchase PDF attachment storage, valuation/COGS and automated sharing are not implemented.
- Do not treat a locally generated PDF as an e-invoice registration. Have your accountant confirm invoice applicability/fields and your numbering series before your first live invoice.
- Voiding retains records and restores stock for erroneous original entries. Voiding a converted invoice reopens its unbilled entry without changing stock. Paid invoices cannot be voided. Tax corrections to issued invoices need a proper credit-note workflow outside this version.
- Existing invoice import is not included; this build creates and maintains new invoices. Historical invoices can be added through a later dedicated import after their format and opening balances are provided.
- Password hashing and signed backend requests are included. Staff roles limit the app interface; this first version does not provide enterprise SSO, per-warehouse authorization or a compliance-certified audit archive. Anyone with spreadsheet owner access can alter the underlying ledger.

## Validation included

Run `node tests/backend.test.cjs` for business-rule checks. Run `python -m pytest tests/test_python.py` for signing, PDF and preview checks. Tests use synthetic records, never your business data. Live Google deployment, network PIN lookup and your exact invoice layout require final verification after connecting your account and receiving your sample.

## References used for implementation

- Streamlit secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Streamlit deployment: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Google Apps Script locks: https://developers.google.com/apps-script/reference/lock/lock
- Google Apps Script quotas: https://developers.google.com/apps-script/guides/services/quotas
- PIN lookup API: https://www.postalpincode.in/Api-Details
- GST invoice particulars: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter6/rule46_v1.00.html
