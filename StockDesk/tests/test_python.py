import json
import hashlib
import hmac
import sys
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import Backend, pin_lookup
from invoice_pdf import calculate_preview, make_pdf


def test_preview_matches_saved_invoice():
    sample = json.loads((Path(__file__).parent/'sample_invoice.json').read_text())
    products = {r['article']:{**r} for r in sample['lines']}
    rows = [{**r, 'rate':r['rate']/100} for r in sample['lines']]
    _, totals = calculate_preview(rows, products, True)
    assert totals == sample['totals']


def test_pdf_and_long_invoice():
    sample = json.loads((Path(__file__).parent/'sample_invoice.json').read_text())
    pdf = make_pdf(sample)
    assert pdf.startswith(b'%PDF')
    sample['lines'] *= 30
    assert len(make_pdf(sample)) > len(pdf)


def test_signed_request_and_server_error():
    api = Backend('https://script.google.com/macros/s/TEST/exec','private-secret')
    reply=Mock()
    reply.json.return_value={'ok':True,'state':{}}
    with patch('client.requests.post',return_value=reply) as post:
        api.call('snapshot')
        data=post.call_args.kwargs['json']
        expected=hmac.new(b'private-secret',data['payload'].encode(),hashlib.sha256).hexdigest()
        assert data['signature']==expected
    reply.json.return_value={'ok':False,'error':'Insufficient stock'}
    with patch('client.requests.post',return_value=reply):
        import pytest
        with pytest.raises(ValueError,match='Insufficient stock'):
            api.call('invoice')


def test_pin_lookup_and_failure():
    reply=Mock()
    reply.json.return_value=[{'Status':'Success','PostOffice':[{'District':'New Delhi','State':'Delhi','Name':'Demo'}]}]
    with patch('client.requests.get',return_value=reply):
        assert pin_lookup('110001')[0]['State']=='Delhi'
    import pytest
    with pytest.raises(ValueError):
        pin_lookup('invalid')


def test_app_setup_screen():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=20)
    assert not app.exception
    assert 'Connect your Google Sheets' in app.info[0].value


def test_authenticated_pages_and_bill_review():
    from streamlit.testing.v1 import AppTest
    sample=json.loads((Path(__file__).parent/'sample_state.json').read_text())
    response={'ok':True,'state':sample,'url':'https://docs.google.com/spreadsheets/d/test'}
    with patch('client.Backend') as backend:
        backend.return_value.call.return_value=response
        app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'))
        app.secrets={'backend_url':'https://script.google.com/macros/s/TEST/exec','api_secret':'test',
                     'users':{'admin':{'role':'admin','password_hash':'unused'}}}
        app.session_state['user']='admin'
        app.run(timeout=20)
        assert not app.exception
        for page in ['Business setup','Articles','Clients','Stock entries','BOM & production','Documents & payments','Import & backup','New bill / entry']:
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception, (page,app.exception)
        next(x for x in app.button if x.label=='Add article').click().run()
        assert not app.exception
        next(x for x in app.button if x.label=='Review document').click().run()
        assert not app.exception
        assert 'review' in app.session_state
