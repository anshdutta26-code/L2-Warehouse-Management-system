# Warehouse reference review — 22 September 2026

Reference: https://github.com/pantamit2003/L2-Warehouse-Management-system
Reviewed main snapshot: 53b4e9959335cd085896db1f5fd1a9493f0970b7.

This is a source review, not a live test of the reference system. Reviewed its
application router, authentication, dependencies and warehouse/report module
structure. Its Supabase database, policies and deployed behavior were not available.

## Useful approaches

| Reference approach | StockDesk treatment |
| --- | --- |
| Streamlit sidebar with operation pages | Retain the existing StockDesk navigation and add Movement reports. |
| SKU and location material checks | Add article/HSN search and a reorder-only filter to the warehouse stock table. |
| Filtered inventory transaction reports | Add date, warehouse and article filters with CSV export; dates use India time. |
| Purchase order, gate-in and gate-out stages | Candidate future extension; these stages are not newly implemented in StockDesk by this update. |
| Recent activity dashboard | Already represented by recent ledger movements in StockDesk. |

The added code was independently written. No source code, images, branding,
Supabase settings or email recipients were copied into the new firm's app.
The reference main tree has no LICENSE file. Preserve its upstream attribution
if forking it; do not assume a public repository grants an unrestricted reuse license.

## Findings that affect adoption

- The reference uses Supabase, whereas this app retains the requested Google Sheets backend.
- Its auth.py globally caches a mutable authenticated Supabase client and restores
  sessions from that client. This raises a possible cross-user session-isolation
  risk in Streamlit; do not transplant that pattern. This is a static finding,
  not a demonstrated exploit or a complete security audit.
- The reference contains L2/EMIZA identity defaults. These do not belong in the
  new firm's production app.
- Do not replace the existing revision checks, duplicate-request protection,
  immutable invoice snapshots or atomic ledger commits with UI-only stock checks.

## Invoice template requirement

Awaiting the user's Word (.docx) invoice template. Intended workflow:
entry -> populated template preview inside Streamlit -> user confirms ->
saved invoice -> later preview/download as DOCX and PDF.

Exact template rendering, DOCX output and the template-based in-app preview
have NOT been implemented yet. Inspect the actual template first, including its
tables, repeated line items, page breaks, logos and tax totals. A browser preview
should use a rendered representation; it should not require publishing client
invoices at a public URL for an external Word viewer.

## Verification and pending work

- Two focused reporting tests pass: combined search/reorder filtering and
  the India-time date boundary with warehouse/article filtering.
- app.py and reporting.py compile.
- The full UI/backend suite was not rerun in this update: the current Python
  environment does not have Streamlit installed. Earlier checks are documented
  separately in VALIDATION.md and are not claimed as fresh results.
- GitHub connector identity confirmed: anshdutta26-code. It exposes no fork or
  repository-creation operation. Browser GitHub is signed out, so no remote copy
  was made. Existing repositories were not altered.
- Streamlit production deployment and Google Sheets setup remain incomplete.
