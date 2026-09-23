/* StockDesk: paste this entire file into Google Apps Script. V8 runtime. */
function blankState() {
  return {revision:0, settings:{name:'',address:'',gstin:'',state:'',phone:'',bank:'',terms:'',locations:['Main']}, products:{},clients:{},boms:{},stock:{},docs:{},payments:{},moves:[],audit:[]};
}
function requireThat(ok,msg){if(!ok)throw new Error(msg);}
function clone(x){return JSON.parse(JSON.stringify(x));}
function textField(x,label,max){x=String(x||'').trim();requireThat(x.length>0&&x.length<=(max||200),label+' is required / too long');return x;}
function keyField(x){x=textField(x,'ID',40);requireThat(/^[A-Za-z0-9_-]+$/.test(x),'ID: letters, numbers, underscore or hyphen only');return x;}
function num(x,label,min,max){x=Number(x);requireThat(Number.isFinite(x)&&x>=min&&x<=max,label+' is outside allowed range');return x;}
function qty(x){x=num(x,'Quantity',0.001,1000000);requireThat(Math.abs(x*1000-Math.round(x*1000))<0.00001,'Quantity: maximum 3 decimals');return x;}
function money(x){return Math.round((num(x,'Amount',0,100000000)+Number.EPSILON)*100);}
function gstin(x){x=String(x||'').trim().toUpperCase();requireThat(!x||/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(x),'GSTIN format invalid');return x;}
function stateCode(x){x=String(x||'');requireThat(/^(0[1-9]|[12][0-9]|3[0-8]|97)$/.test(x),'Select a valid state code');return x;}
function stockKey(p,l){return p+'@'+l;}
function applyEvent(s,e){
  Object.keys(e.patch).forEach(k=>{if(k==='settings')s.settings=e.patch[k];else Object.assign(s[k],e.patch[k]);});
  s.moves=s.moves.concat(e.moves||[]);s.revision=e.revision;
  s.audit.push({id:e.id,at:e.at,actor:e.actor,action:e.action,reference:e.reference});return s;
}
function prepareEvent(s,c,at){
  requireThat(c.id&&/^[a-f0-9-]{16,64}$/.test(c.id),'Missing request ID');
  requireThat(Number(c.revision)===s.revision,'Data changed. Refresh and review before submitting again.');
  var p=c.data||{},patch={},moves=[],reference='',actor=textField(c.actor,'Operator',100);
  function set(k,id,v){if(!patch[k])patch[k]={};patch[k][id]=v;}
  function product(id){requireThat(!!s.products[id],'Unknown article '+id);return s.products[id];}
  function location(l){requireThat(s.settings.locations.indexOf(l)>=0,'Unknown warehouse');return l;}
  function move(id,l,delta,reason){
    product(id);location(l);var k=stockKey(id,l),previous=(patch.stock&&patch.stock[k]!==undefined)?patch.stock[k]:(s.stock[k]||0);
    var next=Math.round((previous+delta)*1000)/1000;requireThat(next>=0,'Insufficient stock: '+id+' at '+l+' (available '+previous+')');
    set('stock',k,next);moves.push({id:c.id,at:at,article:id,location:l,quantity:delta,balance:next,reason:reason,actor:actor});
  }
  function lines(input,pos){
    requireThat(Array.isArray(input)&&input.length>0&&input.length<=100,'Add 1 to 100 article lines');
    return input.map(r=>{var a=product(r.article),q=qty(r.quantity),rate=money(r.rate),discount=num(r.discount||0,'Discount',0,100);
      requireThat(q*rate<9000000000000,'Line value exceeds supported range');
      var taxable=Math.round(q*rate*(1-discount/100)+1e-7),tax=Math.round(taxable*a.gst/100+1e-7);
      var local=pos===s.settings.state,cgst=local?Math.round(taxable*a.gst/200):0,sgst=cgst,igst=local?0:tax;
      return {article:a.id,name:a.name,hsn:a.hsn,unit:a.unit,quantity:q,rate:rate,discount:discount,gst:a.gst,taxable:taxable,cgst:cgst,sgst:sgst,igst:igst,total:taxable+cgst+sgst+igst};});
  }
  function nextNumber(kind){var date=at.slice(0,10),y=Number(date.slice(0,4))-(Number(date.slice(5,7))<4?1:0),fy=String(y).slice(2)+String(y+1).slice(2),prefix=(kind==='invoice'?'INV':'UB')+'/'+fy+'/',n=1;
    Object.values(s.docs).forEach(d=>{if(d.number.indexOf(prefix)===0)n=Math.max(n,Number(d.number.split('/')[2])+1);});
    requireThat(n<=999999,'Invoice sequence exhausted');return prefix+String(n).padStart(6,'0');}
  if(c.action==='settings'){
    var locations=(p.locations||[]).map(x=>textField(x,'Warehouse',40));requireThat(locations.length>0&&locations.length<=15&&new Set(locations).size===locations.length,'Use 1 to 15 unique warehouses');
    requireThat(locations.every(x=>!/[\/@]/.test(x)),'Warehouse name cannot contain / or @');
    s.settings.locations.forEach(l=>requireThat(locations.includes(l)||!s.moves.some(m=>m.location===l),'Cannot remove a warehouse with stock history'));
    patch.settings={name:textField(p.name,'Business name'),address:textField(p.address,'Business address',1000),gstin:gstin(p.gstin),state:stateCode(p.state),phone:String(p.phone||''),bank:String(p.bank||'').slice(0,1000),terms:String(p.terms||'').slice(0,2000),locations:locations};
    requireThat(!patch.settings.gstin||patch.settings.gstin.slice(0,2)===patch.settings.state,'Supplier GSTIN and state mismatch');
    requireThat(!Object.keys(s.docs).length||patch.settings.state===s.settings.state,'Cannot change supplier state after documents exist');
    requireThat(!Object.values(s.docs).some(d=>d.kind==='invoice')||patch.settings.gstin===s.settings.gstin,'Cannot change supplier GSTIN after invoicing begins');
  }else if(c.action==='product'){
    var id=keyField(p.id),hsn=String(p.hsn||'');requireThat(/^\d{4,8}$/.test(hsn),'HSN: enter 4 to 8 digits from your approved article master');
    requireThat(!s.products[id]||!s.moves.some(m=>m.article===id)||p.unit===s.products[id].unit,'Cannot change unit after stock movements exist');
    set('products',id,{id:id,name:textField(p.name,'Article name'),hsn:hsn,gst:num(p.gst,'GST rate',0,100),unit:textField(p.unit,'Unit',12),rate:money(p.rate),reorder:num(p.reorder||0,'Reorder level',0,1000000)});reference=id;
  }else if(c.action==='client'){
    var id=keyField(p.id),pin=String(p.pin||'');requireThat(/^[1-9][0-9]{5}$/.test(pin),'PIN code must be 6 digits');
    var g=gstin(p.gstin),st=stateCode(p.state);requireThat(!g||g.slice(0,2)===st,'Client GSTIN and state mismatch');
    requireThat(/^\+?[0-9 ()-]{10,18}$/.test(String(p.phone||'')),'Enter client phone number');
    set('clients',id,{id:id,name:textField(p.name,'Client name'),address:textField(p.address,'Address',1000),pin:pin,city:textField(p.city,'City'),state:st,phone:String(p.phone),gstin:g});reference=id;
  }else if(c.action==='bom'){
    product(p.article);requireThat(Array.isArray(p.components)&&p.components.length>0&&p.components.length<=100,'Add BOM components');var seen={};
    var components=p.components.map(r=>{product(r.article);requireThat(r.article!==p.article&&!seen[r.article],'Duplicate/self component');seen[r.article]=true;return {article:r.article,quantity:qty(r.quantity),waste:num(r.waste||0,'Wastage %',0,100)};});
    var all=clone(s.boms);all[p.article]={components:components};
    function visit(id,path){requireThat(!path.includes(id),'BOM cycle detected');if(all[id])all[id].components.forEach(r=>visit(r.article,path.concat([id])));}
    visit(p.article,[]);set('boms',p.article,{article:p.article,version:((s.boms[p.article]||{}).version||0)+1,components:components});reference=p.article;
  }else if(c.action==='stock'){
    var amount=qty(Math.abs(Number(p.quantity))),sign=Number(p.quantity)<0?-1:1;
    requireThat(['Opening','Receipt','Adjustment','Return'].includes(p.kind),'Invalid movement type');
    requireThat(sign>0||p.kind==='Adjustment','Negative quantities require Adjustment');reference=textField(p.reference,'Stock reference / reason',300);move(p.article,p.location,sign*amount,p.kind+': '+reference);
  }else if(c.action==='transfer'){
    requireThat(p.from!==p.to,'Choose different warehouses');var q=qty(p.quantity);reference=textField(p.reference,'Transfer reference');move(p.article,p.from,-q,'Transfer out: '+reference);move(p.article,p.to,q,'Transfer in: '+reference);
  }else if(c.action==='produce'){
    var b=s.boms[p.article];requireThat(!!b,'Create a BOM first');var q=qty(p.quantity);reference=textField(p.reference,'Production batch');
    b.components.forEach(r=>move(r.article,p.location,-Math.ceil(r.quantity*q*(1+r.waste/100)*1000-1e-8)/1000,'BOM v'+b.version+' batch '+reference));move(p.article,p.location,q,'Finished production: '+reference);
  }else if(c.action==='invoice'||c.action==='unbilled'||c.action==='convert'){
    var source=c.action==='convert'?s.docs[p.source]:null;
    if(c.action==='convert')requireThat(source&&source.kind==='unbilled'&&source.status==='OPEN','Select an open unbilled entry');
    var client=source?source.client:s.clients[p.client];requireThat(!!client,'Select a client');
    var kind=c.action==='unbilled'?'unbilled':'invoice',pos=source?source.pos:stateCode(p.pos),loc=source?source.location:location(p.location);
    requireThat(s.settings.name&&s.settings.address&&s.settings.state,'Complete Business setup first');
    if(kind==='invoice')requireThat(!!s.settings.gstin,'Supplier GSTIN is required for Tax Invoice');
    var ll=source?clone(source.lines):lines(p.lines,pos),number=nextNumber(kind);
    if(!source)ll.forEach(r=>move(r.article,loc,-r.quantity,number));
    var totals={taxable:0,cgst:0,sgst:0,igst:0,total:0};ll.forEach(r=>Object.keys(totals).forEach(k=>totals[k]+=r[k]));
    var d={id:c.id,number:number,kind:kind,status:'OPEN',date:at.slice(0,10),created:at,client:clone(client),supplier:clone(s.settings),pos:pos,location:loc,lines:ll,totals:totals,notes:String(source?source.notes:p.notes||'').slice(0,2000),source:source?source.id:'',actor:actor};
    set('docs',d.id,d);reference=number;
    if(source){var old=clone(source);old.status='CONVERTED';old.invoice=d.id;set('docs',old.id,old);}
  }else if(c.action==='void'){
    var d=clone(s.docs[p.id]);requireThat(d&&d.status==='OPEN','Only open records can be voided');
    requireThat(!Object.values(s.payments).some(x=>x.document===d.id),'Recorded payments exist; reconcile with administrator first');
    var reason=textField(p.reason,'Void reason',500);d.status='VOID';d.voidReason=reason;d.voided=at;set('docs',d.id,d);
    if(d.source){var src=clone(s.docs[d.source]);src.status='OPEN';src.invoice='';set('docs',src.id,src);}else d.lines.forEach(r=>move(r.article,d.location,r.quantity,'Void '+d.number+': '+reason));reference=d.number;
  }else if(c.action==='payment'){
    var d=s.docs[p.document];requireThat(d&&d.status==='OPEN'&&d.kind==='invoice','Choose an open invoice');
    var paid=Object.values(s.payments).filter(x=>x.document===d.id).reduce((a,x)=>a+x.amount,0),amount=money(p.amount);
    requireThat(amount>0&&amount+paid<=d.totals.total,'Payment exceeds outstanding balance / is zero');
    set('payments',c.id,{id:c.id,document:d.id,number:d.number,date:at.slice(0,10),amount:amount,method:textField(p.method,'Method'),reference:textField(p.reference,'Payment reference'),actor:actor});reference=d.number;
  }else throw new Error('Unknown action');
  var e={id:c.id,at:at,actor:actor,action:c.action,reference:reference,revision:s.revision+1,patch:patch,moves:moves};
  requireThat(JSON.stringify(e).length<45000,'Transaction too large. Split it into smaller entries.');return e;
}

/* Google Sheets gateway. Events is the authoritative append-only ledger.
   Every accepted operation is committed in ONE cell under ScriptLock.
   Human-readable tabs are recoverable projections, never read as source. */
function setup(){
  var props=PropertiesService.getScriptProperties();var id=props.getProperty('SPREADSHEET_ID');
  var book=id?SpreadsheetApp.openById(id):SpreadsheetApp.create('StockDesk - Stock, BOM and Invoices');
  props.setProperty('SPREADSHEET_ID',book.getId());
  if(!props.getProperty('API_SECRET'))props.setProperty('API_SECRET',Utilities.getUuid()+Utilities.getUuid());
  var events=book.getSheetByName('Events')||book.insertSheet('Events');events.getRange(1,1).setValue('Committed event JSON - DO NOT EDIT');
  events.setFrozenRows(1);project(book,loadState(book).state);
  console.log('Spreadsheet: '+book.getUrl());console.log('API_SECRET is in Project Settings > Script properties. Keep it private.');
}
function loadState(book){
  var sh=book.getSheetByName('Events');requireThat(!!sh,'Run setup() first');var s=blankState(),ids={};
  if(sh.getLastRow()>1)sh.getRange(2,1,sh.getLastRow()-1,1).getValues().forEach(r=>{if(r[0]){var e=JSON.parse(r[0]);requireThat(e.revision===s.revision+1,'Ledger revision mismatch; restore backup before writing');applyEvent(s,e);ids[e.id]=e.reference;}});
  return {state:s,ids:ids};
}
function doPost(e){
  var lock=LockService.getScriptLock();
  try{
    var envelope=JSON.parse(e.postData.contents),payload=String(envelope.payload||''),props=PropertiesService.getScriptProperties(),secret=props.getProperty('API_SECRET');
    requireThat(secret&&secret.length>=32,'Backend not configured');
    var expected=Utilities.computeHmacSha256Signature(payload,secret).map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
    var supplied=String(envelope.signature||''),diff=expected.length^supplied.length;for(var i=0;i<expected.length;i++)diff|=expected.charCodeAt(i)^(supplied.charCodeAt(i)||0);
    requireThat(diff===0,'Authentication failed');var c=JSON.parse(payload);requireThat(Math.abs(Date.now()/1000-Number(c.timestamp))<300,'Request expired');
    lock.waitLock(25000);var book=SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID')),loaded=loadState(book),s=loaded.state;
    if(c.action==='snapshot')return json({ok:true,state:s,url:book.getUrl()});
    if(c.action==='rebuild'){project(book,s);return json({ok:true,state:s,url:book.getUrl()});}
    if(loaded.ids[c.id]!==undefined)return json({ok:true,duplicate:true,reference:loaded.ids[c.id],state:s,url:book.getUrl()});
    var at=Utilities.formatDate(new Date(),'Asia/Kolkata',"yyyy-MM-dd'T'HH:mm:ssXXX"),event=prepareEvent(s,c,at);
    book.getSheetByName('Events').appendRow([JSON.stringify(event)]);SpreadsheetApp.flush();applyEvent(s,event);
    var warning='';try{project(book,s);}catch(ex){warning='Saved to ledger; report tabs need refresh: '+ex.message;}
    return json({ok:true,state:s,reference:event.reference,warning:warning,url:book.getUrl()});
  }catch(ex){return json({ok:false,error:String(ex.message||ex)});}finally{if(lock.hasLock())lock.releaseLock();}
}
function json(x){return ContentService.createTextOutput(JSON.stringify(x)).setMimeType(ContentService.MimeType.JSON);}
function safeCell(x){return typeof x==='string'&&/^[=+\-@]/.test(x)?"'"+x:x;}
function writeTab(book,name,rows){
  var sh=book.getSheetByName(name)||book.insertSheet(name),w=rows[0].length,h=rows.length;
  if(sh.getMaxRows()<h)sh.insertRowsAfter(sh.getMaxRows(),h-sh.getMaxRows());if(sh.getMaxColumns()<w)sh.insertColumnsAfter(sh.getMaxColumns(),w-sh.getMaxColumns());
  sh.clearContents();sh.getRange(1,1,h,w).setValues(rows.map(r=>r.map(safeCell)));sh.setFrozenRows(1);
  sh.getRange(1,1,1,w).setBackground('#10243A').setFontColor('#FFFFFF').setFontWeight('bold');sh.autoResizeColumns(1,w);
}
function project(book,s){
  var locations=s.settings.locations,ps=Object.values(s.products),cs=Object.values(s.clients),ds=Object.values(s.docs);
  writeTab(book,'Stock',[['Article ID','Article','HSN','Unit'].concat(locations).concat(['Total','Reorder level','Alert','Ledger revision'])].concat(ps.map(p=>{var qq=locations.map(l=>s.stock[stockKey(p.id,l)]||0),sum=qq.reduce((a,b)=>a+b,0);return [p.id,p.name,p.hsn,p.unit].concat(qq).concat([sum,p.reorder,sum<=p.reorder?'REORDER':'OK',s.revision]);})));
  writeTab(book,'Articles',[['ID','Article','HSN','GST %','Unit','Default rate INR','Reorder level']].concat(ps.map(p=>[p.id,p.name,p.hsn,p.gst,p.unit,p.rate/100,p.reorder])));
  writeTab(book,'Clients',[['ID','Name','Address','PIN','City','State code','Phone','GSTIN']].concat(cs.map(c=>[c.id,c.name,c.address,c.pin,c.city,c.state,c.phone,c.gstin])));
  var header=['Number','Date','Status','Client ID','Client','Address','PIN','City','State code','GSTIN','Phone','Warehouse','Place of supply','Taxable INR','CGST INR','SGST INR','IGST INR','Total INR','Paid INR','Outstanding INR','Source ID','Document ID'];
  function docRow(d){var paid=Object.values(s.payments).filter(p=>p.document===d.id).reduce((a,p)=>a+p.amount,0);return [d.number,d.date,d.status,d.client.id,d.client.name,d.client.address,d.client.pin,d.client.city,d.client.state,d.client.gstin,d.client.phone,d.location,d.pos,d.totals.taxable/100,d.totals.cgst/100,d.totals.sgst/100,d.totals.igst/100,d.totals.total/100,paid/100,d.status==='OPEN'?(d.totals.total-paid)/100:0,d.source,d.id];}
  writeTab(book,'Invoices',[header].concat(ds.filter(d=>d.kind==='invoice').map(docRow)));
  writeTab(book,'Without_Bill',[header].concat(ds.filter(d=>d.kind==='unbilled').map(docRow)));
  writeTab(book,'Invoice_Lines',[['Document','Status','Article','Name','HSN','Unit','Quantity','Rate INR','Discount %','GST %','Taxable INR','CGST INR','SGST INR','IGST INR','Total INR']].concat(ds.flatMap(d=>d.lines.map(r=>[d.number,d.status,r.article,r.name,r.hsn,r.unit,r.quantity,r.rate/100,r.discount,r.gst,r.taxable/100,r.cgst/100,r.sgst/100,r.igst/100,r.total/100]))));
  writeTab(book,'BOM',[['Finished article','Version','Component','Quantity per unit','Wastage %']].concat(Object.values(s.boms).flatMap(b=>b.components.map(r=>[b.article,b.version,r.article,r.quantity,r.waste]))));
  writeTab(book,'Movements',[['Date/time','Article','Warehouse','Quantity change','Balance after','Reason','Operator','Event ID']].concat(s.moves.map(m=>[m.at,m.article,m.location,m.quantity,m.balance,m.reason,m.actor,m.id])));
  writeTab(book,'Payments',[['Date','Invoice','Amount INR','Method','Reference','Operator','ID']].concat(Object.values(s.payments).map(p=>[p.date,p.number,p.amount/100,p.method,p.reference,p.actor,p.id])));
  writeTab(book,'Audit',[['Revision','Date/time','Operator','Action','Reference','Event ID']].concat(s.audit.map((e,i)=>[i+1,e.at,e.actor,e.action,e.reference,e.id])));
  writeTab(book,'Read_Me',[['Setting','Value'],['Business',s.settings.name],['Ledger revision',s.revision],['Entry rule','Use Streamlit for every entry. These tabs are reports; direct edits are overwritten.'],['Events','Authoritative ledger. Do not edit or delete. Restrict spreadsheet edit access to administrator.'],['Unbilled','Tracked stock issue pending invoice; included in stock, never a hidden ledger.'],['Stock layout','Warehouse balances are side by side.'],['Backup','Make a dated Google Drive copy daily and before maintenance.']]);
}
