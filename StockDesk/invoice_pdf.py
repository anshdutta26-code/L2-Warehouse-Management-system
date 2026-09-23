"""PDFs are rebuilt from immutable invoice snapshots, not current master data."""
from io import BytesIO
from xml.sax.saxutils import escape
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

_ASSETS = Path(__file__).parent / 'assets'
if not (_ASSETS / 'DejaVuSans.ttf').exists():
    _ASSETS = Path('/usr/share/fonts/truetype/dejavu')
pdfmetrics.registerFont(TTFont('InvoiceSans', str(_ASSETS / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('InvoiceSans-Bold', str(_ASSETS / 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('InvoiceSans', normal='InvoiceSans', bold='InvoiceSans-Bold', italic='InvoiceSans', boldItalic='InvoiceSans-Bold')


def paise(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def calculate_preview(rows, products, local):
    lines = []
    for row in rows:
        p = products[row['article']]
        taxable = int((Decimal(str(row['quantity'])) * paise(row['rate']) *
                       (1 - Decimal(str(row.get('discount', 0))) / 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        def tax(divisor):
            return int((Decimal(taxable) * Decimal(str(p['gst'])) / divisor).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        cgst = sgst = tax(200) if local else 0
        igst = 0 if local else tax(100)
        lines.append({**row, 'name': p['name'], 'hsn': p['hsn'], 'unit': p['unit'],
                      'rate': paise(row['rate']), 'gst': p['gst'], 'taxable': taxable,
                      'cgst': cgst, 'sgst': sgst, 'igst': igst, 'total': taxable + cgst + sgst + igst})
    return lines, {k: sum(r[k] for r in lines) for k in ['taxable', 'cgst', 'sgst', 'igst', 'total']}


def make_pdf(d):
    out = BytesIO()
    styles = getSampleStyleSheet()
    for name in styles.byName:
        styles[name].fontName = 'InvoiceSans-Bold' if name.startswith('Heading') or name == 'Title' else 'InvoiceSans'
    styles.add(ParagraphStyle(name='SmallInvoice', fontName='InvoiceSans', fontSize=8, leading=11, textColor=colors.HexColor('#24364b')))
    styles.add(ParagraphStyle(name='Money', parent=styles['SmallInvoice'], alignment=TA_RIGHT))
    def p(text, style='SmallInvoice'):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])
    def amt(v):
        return f'{v / 100:,.2f}'
    supplier, buyer = d['supplier'], d['client']
    title = 'TAX INVOICE' if d['kind'] == 'invoice' else 'UNBILLED ENTRY - NOT A TAX INVOICE'
    flow = [p(supplier['name'], 'Title'), p(title, 'Heading2'),
            p(f"{d['number']}  |  Date: {d['date']}  |  Status: {d['status']}"), Spacer(1, 14)]
    boxes = Table([[p('SUPPLIER\n' + supplier['address'] + '\nGSTIN: ' + supplier.get('gstin', '') + '\nState code: ' + supplier['state'] + '\nPhone: ' + supplier.get('phone', '')),
                    p('BILL TO / SHIP TO\n' + buyer['name'] + '\n' + buyer['address'] + '\n' + buyer['city'] + ' - ' + buyer['pin'] + '\nState code: ' + buyer['state'] + '\nPhone: ' + buyer['phone'] + '\nGSTIN: ' + (buyer.get('gstin') or 'Unregistered'))]], colWidths=[257, 258])
    boxes.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f4f8')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    flow.extend([boxes, Spacer(1, 12), p(f"Place of supply (state code): {d['pos']}     Warehouse: {d['location']}     Reverse charge: No"), Spacer(1, 10)])
    rows = [[p(x) for x in ['Article / HSN', 'Qty / Unit', 'Rate INR', 'Disc %', 'GST %', 'Taxable INR', 'Total INR']]]
    for r in d['lines']:
        rows.append([p(r['name'] + '\nHSN ' + r['hsn']), p(f"{r['quantity']:g} {r['unit']}"), p(amt(r['rate']), 'Money'), p(r['discount'], 'Money'), p(r['gst'], 'Money'), p(amt(r['taxable']), 'Money'), p(amt(r['total']), 'Money')])
    table = Table(rows, colWidths=[150, 55, 65, 40, 40, 80, 85], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e9f2')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#183550')), ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#d5dce4'))]))
    flow.extend([table, Spacer(1, 14)])
    totals = [[p(label), p(amt(d['totals'][key]), 'Money')] for label, key in [('Taxable amount', 'taxable'), ('CGST', 'cgst'), ('SGST', 'sgst'), ('IGST', 'igst'), ('TOTAL INR', 'total')]]
    summary = Table(totals, colWidths=[170, 100], hAlign='RIGHT')
    summary.setStyle(TableStyle([('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e0e9f2')), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    flow.append(KeepTogether([summary, Spacer(1, 14)]))
    if d['kind'] == 'unbilled':
        flow.append(p('Stock has been issued. This record is pending invoicing. Tax amounts shown are estimates for the eventual invoice.'))
    for label, val in [('Notes', d.get('notes')), ('Bank details', supplier.get('bank')), ('Terms', supplier.get('terms')), ('Void reason', d.get('voidReason'))]:
        if val:
            flow.extend([p(label, 'Heading3'), p(val)])
    flow.extend([Spacer(1, 24), p('For ' + supplier['name']), Spacer(1, 24), p('Authorised signatory')])
    def footer(canvas, doc):
        canvas.setFont('InvoiceSans', 8)
        canvas.setFillColor(colors.HexColor('#63748a'))
        canvas.drawString(40, 25, d['number'])
        canvas.drawRightString(A4[0] - 40, 25, f'Page {doc.page}')
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=35, bottomMargin=45)
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
