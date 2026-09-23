import hashlib
import hmac
import json
import uuid
import subprocess
from datetime import datetime
from decimal import InvalidOperation
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from client import Backend, pin_lookup
from invoice_pdf import make_pdf, calculate_preview
from states import STATES
from reporting import filter_stock, filter_movements
from invoice_word import make_word, word_to_pdf, preview_pages


def show_invoice(document, key):
    word = make_word(document)
    st.download_button('Download Word invoice', word, document['number'].replace('/', '-') + '.docx',
                       'application/vnd.openxmlformats-officedocument.wordprocessingml.document', key=key+'-word')
    try:
        pdf = word_to_pdf(word)
        st.download_button('Download PDF invoice', pdf, document['number'].replace('/', '-') + '.pdf',
                           'application/pdf', key=key+'-pdf')
        for index, image in enumerate(preview_pages(pdf), 1):
            st.image(image, caption=f'Page {index}', width='stretch')
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        st.warning(f'Word download is available, but the preview could not be generated. {exc}')

st.set_page_config(page_title='StockDesk', page_icon='📦', layout='wide')
st.markdown('''<style>.block-container{padding-top:2rem;max-width:1450px}
[data-testid="stMetric"]{background:#edf3fa;padding:18px;border-radius:12px}
h1,h2,h3{color:#142c46}</style>''', unsafe_allow_html=True)
st.title('StockDesk')
st.caption('Stock, clients, bills and production in one place.')

try:
    cfg = dict(st.secrets)
except FileNotFoundError:
    cfg = {}
if not all(cfg.get(k) for k in ['backend_url', 'api_secret', 'users']):
    st.info('Connect your Google Sheets backend to start. No business data has been loaded.')
    st.markdown('''1. Follow **START_HERE.md** in the downloaded package.
2. Run `setup()` in Google Apps Script to create the stock workbook.
3. Deploy the backend and add its URL, secret and your user account to Streamlit secrets.
4. Restart this app, sign in, then complete Business setup.''')
    st.stop()

if 'user' not in st.session_state:
    with st.form('login'):
        user = st.text_input('Username')
        password = st.text_input('Password', type='password')
        submit = st.form_submit_button('Sign in')
    if submit:
        record = cfg['users'].get(user, {})
        encoded = record.get('password_hash', '')
        try:
            salt, digest = encoded.split('$', 1)
            check = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
            valid = hmac.compare_digest(check, digest)
        except (ValueError, TypeError):
            valid = False
        if valid:
            st.session_state.user = user
            st.rerun()
        else:
            st.error('Username or password incorrect.')
    st.stop()

user = st.session_state.user
role = cfg['users'].get(user, {}).get('role', 'operator')
if user not in cfg['users']:
    st.session_state.clear()
    st.rerun()
api = Backend(cfg['backend_url'], cfg['api_secret'])


def refresh():
    response = api.call('snapshot')
    st.session_state.snapshot = response


if 'snapshot' not in st.session_state:
    try:
        refresh()
    except Exception as exc:
        st.error(str(exc))
        st.stop()

with st.sidebar:
    st.subheader('Workspace')
    st.caption(f'{user} · {role}')
    if st.button('Refresh data'):
        try:
            refresh()
        except Exception as exc:
            st.error(str(exc))
    pages = ['Overview', 'New bill / entry', 'Documents & payments', 'Clients', 'Articles', 'Stock entries', 'BOM & production', 'Movement reports']
    if role == 'admin':
        pages += ['Business setup', 'Import & backup']
    page = st.radio('Go to', pages)
    st.link_button('Open Google Sheets', st.session_state.snapshot['url'])
    if st.button('Sign out'):
        st.session_state.clear()
        st.rerun()

s = st.session_state.snapshot['state']
products, clients, docs = s['products'], s['clients'], s['docs']
st.caption(f"{s['settings']['name'] or 'Business setup required'} · Ledger revision {s['revision']}")
if st.session_state.get('notice'):
    st.success(st.session_state.pop('notice'))
if st.session_state.get('warning'):
    st.warning(st.session_state.pop('warning'))


def mutate(action, data, key=None):
    # The same unresolved operation keeps its ID after a timeout and on retry.
    signature = json.dumps([action, data], sort_keys=True)
    pending = st.session_state.get('pending')
    if pending and pending['signature'] != signature:
        st.error('A previous request has an unknown outcome. Resolve it below before entering another transaction.')
        return False
    if not pending:
        pending = {'signature': signature, 'id': key or str(uuid.uuid4()), 'revision': s['revision'], 'action': action, 'data': data}
        st.session_state.pending = pending
    try:
        result = api.call(action, data, pending['revision'], pending['id'], user)
        st.session_state.snapshot = result
        st.session_state.pop('pending', None)
        st.session_state.notice = f"Saved {result.get('reference') or action}."
        if result.get('warning'):
            st.session_state.warning = result['warning']
        st.session_state.pop('review', None)
        if action in ('invoice', 'unbilled'):
            st.session_state.cart = []
            st.session_state.pop('cart_editor', None)
        st.rerun()
    except ValueError as exc:
        st.session_state.pop('pending', None)
        st.error(str(exc))
    except Exception as exc:
        st.error(f'Could not confirm the response. Keep this page open and retry the same request. {exc}')
    return False


if st.session_state.get('pending'):
    pending = st.session_state.pending
    st.warning('An earlier submission needs confirmation. Retrying uses the same transaction ID to prevent duplicate stock deductions.')
    if st.button('Resolve previous submission'):
        mutate(pending['action'], pending['data'])


def state_select(label, value='07', key=None):
    codes = list(STATES)
    return st.selectbox(label, codes, index=codes.index(value) if value in codes else 0,
                        format_func=lambda x: f'{x} - {STATES[x]}', key=key)


def article_select(label='Article', key=None):
    return st.selectbox(label, list(products), format_func=lambda x: f"{x} · {products[x]['name']}", key=key)


def require_articles():
    if not products:
        st.info('Add your articles first.')
        st.stop()


def stock_table():
    records = []
    for a in products.values():
        row = {'Article ID': a['id'], 'Article': a['name'], 'HSN': a['hsn'], 'Unit': a['unit']}
        for loc in s['settings']['locations']:
            row[loc] = s['stock'].get(a['id'] + '@' + loc, 0)
        row['Total'] = sum(row[loc] for loc in s['settings']['locations'])
        row['Reorder level'] = a['reorder']
        row['Status'] = 'REORDER' if row['Total'] <= a['reorder'] else 'OK'
        records.append(row)
    return pd.DataFrame(records)


if page == 'Overview':
    invoices = [d for d in docs.values() if d['kind'] == 'invoice' and d['status'] == 'OPEN']
    unbilled = [d for d in docs.values() if d['kind'] == 'unbilled' and d['status'] == 'OPEN']
    billed = sum(d['totals']['total'] for d in invoices)
    paid = sum(p['amount'] for p in s['payments'].values())
    cols = st.columns(4)
    for col, title, value in zip(cols, ['Articles', 'Invoiced INR', 'Outstanding INR', 'Pending unbilled entries'], [len(products), f'{billed/100:,.2f}', f'{(billed-paid)/100:,.2f}', len(unbilled)]):
        col.metric(title, value)
    st.subheader('Stock by warehouse')
    df = stock_table()
    stock_query = st.text_input('Find article, article ID or HSN')
    reorder_only = st.checkbox('Show only articles at or below reorder level')
    df = pd.DataFrame(filter_stock(df.to_dict('records'), stock_query, reorder_only), columns=df.columns)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button('Download stock CSV', df.to_csv(index=False), 'stock.csv', 'text/csv')
    st.subheader('Recent movements')
    st.dataframe(pd.DataFrame(s['moves'][-30:][::-1]), hide_index=True, use_container_width=True)

elif page == 'Movement reports':
    st.subheader('Movement reports')
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    c1, c2 = st.columns(2)
    start = c1.date_input('From date', today.replace(day=1))
    end = c2.date_input('To date', today)
    location = st.selectbox('Warehouse', [None] + s['settings']['locations'], format_func=lambda x: x or 'All warehouses')
    article = st.selectbox('Article filter', [None] + list(products), format_func=lambda x: f"{x} · {products[x]['name']}" if x else 'All articles')
    if start > end:
        st.warning('From date must be on or before To date.')
    else:
        movements = filter_movements(s['moves'], start, end, location, article)
        st.caption('Dates use India time. Quantities in different units are shown separately and are not added together.')
        frame = pd.DataFrame(movements)
        st.dataframe(frame, hide_index=True, use_container_width=True)
        st.download_button('Download movement report CSV', frame.to_csv(index=False), 'movement-report.csv', 'text/csv')
        if not movements:
            st.info('No movements match these filters.')

elif page == 'Business setup':
    st.subheader('Business details')
    current = s['settings']
    with st.form('settings'):
        name = st.text_input('Legal business name', current['name'])
        address = st.text_area('Business address', current['address'])
        gst = st.text_input('Supplier GSTIN', current['gstin'])
        state = state_select('Supplier state', current.get('state', '07'))
        phone = st.text_input('Business phone', current['phone'])
        locations = st.text_input('Warehouse names, comma separated', ', '.join(current['locations']))
        bank = st.text_area('Bank details printed on invoice', current['bank'])
        terms = st.text_area('Invoice terms', current['terms'])
        if st.form_submit_button('Save business details'):
            mutate('settings', dict(name=name,address=address,gstin=gst,state=state,phone=phone,locations=[x.strip() for x in locations.split(',') if x.strip()],bank=bank,terms=terms))

elif page == 'Articles':
    st.subheader('Article master')
    st.caption('HSN and GST are fetched from this master on every new bill. Use verified classifications.')
    options = ['New article'] + list(products)
    selected = st.selectbox('Create or edit', options)
    p = products.get(selected, {})
    with st.form('article-' + selected):
        aid = st.text_input('Article ID', p.get('id', ''), disabled=bool(p))
        name = st.text_input('Article name', p.get('name', ''))
        a,b,c = st.columns(3)
        hsn = a.text_input('HSN', p.get('hsn', ''))
        gst = b.number_input('GST %', min_value=0.0,max_value=100.0,value=float(p.get('gst', 0)))
        unit = c.text_input('Unit', p.get('unit', 'PCS'))
        rate = st.number_input('Default selling rate before GST (INR)', min_value=0.0,value=p.get('rate',0)/100,step=1.0)
        reorder = st.number_input('Reorder alert level', min_value=0.0,value=float(p.get('reorder',0)))
        if st.form_submit_button('Save article'):
            mutate('product',dict(id=aid,name=name,hsn=hsn,gst=gst,unit=unit,rate=rate,reorder=reorder))
    st.dataframe(pd.DataFrame(products.values()), hide_index=True)

elif page == 'Clients':
    st.subheader('Client master')
    chosen = st.selectbox('Create or edit client', ['New client'] + list(clients))
    c = clients.get(chosen, {})
    # Selection-specific keys keep unsaved details isolated between clients.
    prefix = 'client_' + chosen
    pin = st.text_input('PIN code', c.get('pin',''), key=prefix+'_pin')
    if st.button('Fetch city and state from PIN'):
        try:
            offices = pin_lookup(pin)
            st.session_state[prefix+'_offices'] = offices
            first = offices[0]
            st.session_state[prefix+'_city'] = first.get('District', '')
            found = next((k for k,v in STATES.items() if v.lower() == first['State'].lower()), None)
            if found:
                st.session_state[prefix+'_state'] = found
            st.success('Postal district and state fetched. Confirm the actual city/locality below.')
        except Exception as exc:
            st.warning(f'Lookup unavailable: {exc}. You can fill the address manually.')
    offices = st.session_state.get(prefix+'_offices', [])
    if offices:
        st.caption('Post offices for this PIN: ' + ', '.join(sorted(set(x['Name'] for x in offices))))
    with st.form(prefix):
        cid = st.text_input('Client ID', c.get('id',''), disabled=bool(c))
        name = st.text_input('Client name', c.get('name',''))
        address = st.text_area('Address', c.get('address',''))
        city = st.text_input('City / locality', c.get('city',''), key=prefix+'_city')
        state = state_select('Client state', c.get('state','07'), key=prefix+'_state')
        phone = st.text_input('Phone number', c.get('phone',''))
        gst = st.text_input('Client GSTIN (blank for unregistered client)', c.get('gstin',''))
        if st.form_submit_button('Save client'):
            mutate('client',dict(id=cid,name=name,address=address,pin=pin,city=city,state=state,phone=phone,gstin=gst))
    st.dataframe(pd.DataFrame(clients.values()), hide_index=True, use_container_width=True)

elif page == 'New bill / entry':
    st.subheader('Create a bill or an unbilled entry')
    require_articles()
    if not clients:
        st.info('Save your client in Clients first, including their address and PIN code.')
        st.stop()
    kind = st.radio('Document type', ['Tax invoice', 'Without bill / pending invoice'], horizontal=True)
    client_id = st.selectbox('Client', list(clients), format_func=lambda x: clients[x]['name']+' · '+x)
    customer = clients[client_id]
    st.info(f"{customer['name']} | {customer['address']} | {customer['city']} {customer['pin']} | {STATES.get(customer['state'],customer['state'])} | {customer['phone']} | GSTIN: {customer['gstin'] or 'Unregistered'}")
    loc = st.selectbox('Issue stock from', s['settings']['locations'])
    pos = state_select('Place of supply (confirm for this sale)', customer['state'], key='pos_'+client_id)
    if 'cart' not in st.session_state:
        st.session_state.cart = []
    with st.form('add-line'):
        aid = article_select()
        quantity = st.number_input('Quantity', min_value=0.001,value=1.0,step=1.0,format='%.3f')
        st.caption('The article master supplies HSN, GST and the default rate. Edit rates in the cart below.')
        if st.form_submit_button('Add article'):
            # Preserve existing grid edits before the add-line form triggers a rerun.
            previous = list(st.session_state.cart)
            grid = st.session_state.get('cart_editor', {})
            for index, changes in grid.get('edited_rows', {}).items():
                previous[int(index)] = {**previous[int(index)], **changes}
            for index in sorted(grid.get('deleted_rows', []), reverse=True):
                previous.pop(int(index))
            previous.extend(grid.get('added_rows', []))
            st.session_state.cart = previous
            st.session_state.pop('cart_editor', None)
            st.session_state.cart.append({'article':aid,'quantity':quantity,'rate':products[aid]['rate']/100,'discount':0.0})
            st.session_state.pop('review',None)
            st.rerun()
    if st.session_state.cart:
        edited = st.data_editor(pd.DataFrame(st.session_state.cart),num_rows='dynamic',hide_index=True,
            column_config={'article':st.column_config.SelectboxColumn('Article',options=list(products),required=True),
                           'quantity':st.column_config.NumberColumn('Quantity',min_value=.001,required=True),
                           'rate':st.column_config.NumberColumn('Rate before GST',min_value=0.0,required=True),
                           'discount':st.column_config.NumberColumn('Discount %',min_value=0.0,max_value=100.0,required=True)},key='cart_editor')
        rows = edited.to_dict('records')
        notes = st.text_area('Notes / order reference')
        data = dict(client=client_id,location=loc,pos=pos,lines=rows,notes=notes)
        action = 'invoice' if kind == 'Tax invoice' else 'unbilled'
        fingerprint = json.dumps([action,data],sort_keys=True)
        try:
            lines, totals = calculate_preview(rows, products, pos == s['settings']['state'])
            st.dataframe(pd.DataFrame(lines)[['name','hsn','quantity','gst']],hide_index=True)
            st.metric('Total including GST (INR)',f"{totals['total']/100:,.2f}")
            if st.button('Review document'):
                d = dict(number='DRAFT',date=datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat(),kind=action,status='DRAFT',supplier=s['settings'],client=customer,pos=pos,location=loc,lines=lines,totals=totals,notes=notes)
                st.session_state.review = {'fingerprint':fingerprint,'revision':s['revision'],'pdf':make_pdf(d),'document':d}
            review = st.session_state.get('review')
            if review and review['fingerprint']==fingerprint and review['revision']==s['revision']:
                show_invoice(review['document'], 'draft')
                okay = st.checkbox('Details checked. Commit this document and deduct stock.')
                if st.button('OK - create document',disabled=not okay,type='primary'):
                    mutate(action,data)
            if st.button('Clear cart'):
                st.session_state.cart=[]
                st.session_state.pop('cart_editor',None)
                st.session_state.pop('review',None)
                st.rerun()
        except (ValueError,KeyError,TypeError,InvalidOperation) as exc:
            st.warning(f'Complete valid article, quantity and rate values before reviewing. {exc}')
    else:
        st.caption('Add articles to start. Saved documents appear in Documents & payments.')

elif page == 'Documents & payments':
    st.subheader('Documents & payments')
    query = st.text_input('Search invoice number or client name').lower()
    filtered = {k:d for k,d in docs.items() if query in (d['number']+' '+d['client']['name']).lower()}
    st.dataframe(pd.DataFrame([{'Number':d['number'],'Date':d['date'],'Client':d['client']['name'],'Type':d['kind'],'Status':d['status'],'Total INR':d['totals']['total']/100} for d in filtered.values()]),hide_index=True,use_container_width=True)
    if filtered:
        did = st.selectbox('Open document',list(filtered)[::-1],format_func=lambda k:filtered[k]['number']+' · '+filtered[k]['client']['name'])
        d=docs[did]
        show_invoice(d, 'saved-'+did)
        st.caption('Download and attach the PDF to WhatsApp or email. No message is sent automatically.')
        if d['kind']=='unbilled' and d['status']=='OPEN':
            st.info('Conversion uses the saved client, prices and quantities. It does not deduct stock again.')
            if st.button('Convert to tax invoice'):
                mutate('convert',{'source':did})
        if d['kind']=='invoice' and d['status']=='OPEN':
            paid=sum(p['amount'] for p in s['payments'].values() if p['document']==did)
            st.metric('Outstanding INR',f"{(d['totals']['total']-paid)/100:,.2f}")
            with st.form('payment-'+did):
                amount=st.number_input('Payment received INR',min_value=0.0,step=1.0)
                method=st.selectbox('Payment mode',['UPI','Bank transfer','Cash','Cheque','Card'])
                reference=st.text_input('Payment reference')
                if st.form_submit_button('Record payment'):
                    mutate('payment',dict(document=did,amount=amount,method=method,reference=reference))
        if role=='admin' and d['status']=='OPEN':
            with st.expander('Void an incorrect entry'):
                st.caption('For erroneous entries only. Issued invoices needing tax corrections require your accountant’s credit-note process. Records and numbering are retained.')
                reason=st.text_input('Void reason',key='void_reason')
                confirmed=st.checkbox('I have checked stock and accounting treatment.')
                if st.button('Void document',disabled=not confirmed):
                    mutate('void',{'id':did,'reason':reason})

elif page == 'Stock entries':
    st.subheader('Stock entries')
    require_articles()
    st.dataframe(stock_table(),hide_index=True,use_container_width=True)
    mode=st.radio('Movement',['Opening / receipt / adjustment','Warehouse transfer'],horizontal=True)
    with st.form('stock-'+mode):
        aid=article_select()
        if mode.startswith('Opening'):
            location=st.selectbox('Warehouse',s['settings']['locations'])
            kind=st.selectbox('Entry type',['Opening','Receipt','Adjustment','Return'])
            quantity=st.number_input('Quantity change (negative only for adjustment)',value=0.0,step=1.0,format='%.3f')
            reference=st.text_input('Supplier bill / opening reference / reason')
            if st.form_submit_button('Save stock movement'):
                mutate('stock',dict(article=aid,location=location,kind=kind,quantity=quantity,reference=reference))
        else:
            source=st.selectbox('From warehouse',s['settings']['locations'])
            target=st.selectbox('To warehouse',s['settings']['locations'])
            quantity=st.number_input('Transfer quantity',min_value=.001,value=1.0,format='%.3f')
            reference=st.text_input('Transfer reference')
            if st.form_submit_button('Transfer stock'):
                mutate('transfer',{'article':aid,'from':source,'to':target,'quantity':quantity,'reference':reference})

elif page == 'BOM & production':
    st.subheader('BOM & production')
    require_articles()
    finished=article_select('Finished article',key='finished')
    components=s['boms'].get(finished,{}).get('components',[])
    frame=pd.DataFrame(components,columns=['article','quantity','waste'])
    st.caption('Component quantities are per one finished unit. Production consumes stocked components, including wastage, and adds finished stock.')
    edited=st.data_editor(frame,num_rows='dynamic',hide_index=True,key='bom-'+finished,column_config={
        'article':st.column_config.SelectboxColumn('Component article',options=list(products),required=True),
        'quantity':st.column_config.NumberColumn('Qty per finished unit',min_value=.001,required=True),
        'waste':st.column_config.NumberColumn('Wastage %',min_value=0.0,max_value=100.0,default=0.0)})
    if st.button('Save BOM'):
        mutate('bom',dict(article=finished,components=edited.fillna({'waste':0}).to_dict('records')))
    with st.form('production'):
        location=st.selectbox('Production warehouse',s['settings']['locations'])
        quantity=st.number_input('Finished units to produce',min_value=.001,value=1.0,format='%.3f')
        reference=st.text_input('Batch / production reference')
        if st.form_submit_button('Produce and update stock'):
            mutate('produce',dict(article=finished,location=location,quantity=quantity,reference=reference))
    if components:
        st.caption('Subassemblies must be produced first; production consumes the listed immediate components only.')

elif page == 'Import & backup':
    st.subheader('Import & backup')
    st.download_button('Download full ledger snapshot',json.dumps(s,indent=2),'StockDesk-snapshot.json','application/json')
    st.caption('For a recoverable backup, also make a dated Drive copy of the whole workbook, including Events. Snapshot JSON is a portable report, not an automatic restore file.')
    if st.button('Rebuild Google Sheets report tabs'):
        try:
            st.session_state.snapshot=api.call('rebuild',actor=user)
            st.success('Report tabs rebuilt from the event ledger.')
        except Exception as exc:
            st.error(str(exc))
    st.subheader('Import CSV')
    kind=st.selectbox('Import type',['Articles','Clients','Opening stock'])
    required={'Articles':['id','name','hsn','gst','unit','rate','reorder'],
              'Clients':['id','name','address','pin','city','state','phone','gstin'],
              'Opening stock':['article','location','quantity','reference']}[kind]
    st.download_button('Download empty CSV template',','.join(required)+'\n',kind.lower().replace(' ','_')+'.csv','text/csv')
    upload=st.file_uploader('Upload completed CSV',type='csv')
    if upload:
        try:
            frame=pd.read_csv(upload,dtype=str,keep_default_na=False)
            if not set(required).issubset(frame.columns):
                raise ValueError('Required columns: '+', '.join(required))
            st.dataframe(frame,hide_index=True)
            st.caption('Each row is committed separately. Existing article/client IDs are updated. Opening stock rows ADD stock. A repeated identical file/row is skipped using a stable request ID.')
            if st.button('Import displayed rows',disabled=bool(st.session_state.get('pending'))):
                revision=s['revision']
                for idx,row in enumerate(frame.to_dict('records')):
                    action={'Articles':'product','Clients':'client','Opening stock':'stock'}[kind]
                    if kind=='Opening stock':
                        row['kind']='Opening'
                    rid=hashlib.sha256((kind+upload.getvalue().hex()+str(idx)).encode()).hexdigest()
                    try:
                        result=api.call(action,row,revision,rid,user)
                        revision=result['state']['revision']
                        st.session_state.snapshot=result
                    except Exception as exc:
                        st.error(f'Stopped at CSV data row {idx+1}: {exc}. Earlier rows were saved. Retry the same file to skip committed rows; resolve an uncertain timeout before editing the file.')
                        break
                else:
                    st.success(f'Processed {len(frame)} rows. Refresh data to continue.')
        except Exception as exc:
            st.error(str(exc))
