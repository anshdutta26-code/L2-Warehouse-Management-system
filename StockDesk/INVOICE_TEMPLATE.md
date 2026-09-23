# Invoice template

The draft Word template is `templates/invoice.docx`. Replace this file to change
invoice styling. Keep the `{{field}}` placeholders and the one repeatable article
row containing `{{item}}`. Each placeholder should use consistent formatting.
Supported placeholders are listed in invoice_word.py. Top-level paragraphs,
tables, and header/footer paragraphs are supported; text boxes and nested tables
need additional mapping when the final design is supplied.

The app fills this Word template using the saved document snapshot, converts it
to PDF with LibreOffice, and displays every rendered page inside Streamlit.
Word and PDF downloads use that same content. A temporary private working folder
is removed after conversion. No external document viewer receives invoice data.

Install requirements.txt and the Linux packages in packages.txt. If conversion
is unavailable, the Word download remains available and the app shows a warning.
A sample invoice is synthetic and is not business data.

Drafts do not change stock. Stock changes only after checking the confirmation
box and selecting OK. Rendering a saved document does not change stock. Replacing
the template changes the presentation of regenerated copies; ledger values stay
as originally saved. Keep downloaded issued copies if the original appearance
must be retained.
