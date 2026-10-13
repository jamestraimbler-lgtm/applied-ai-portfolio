import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openDatabase } from '../src/db.js';
import { createApp } from '../src/server.js';
import { accessLevel,createBilling } from '../src/billing.js';

async function fixture(t,extra={}){
  const db=openDatabase(':memory:'),mail=[];
  const uploads=mkdtempSync(join(tmpdir(),'pop-test-'));
  const {app,billing}=createApp({db,config:{NODE_ENV:'test',BASE_URL:'http://127.0.0.1:4317',BILLING_ENABLED:'false',PRIVATE_FILES_PATH:uploads,...extra.config},mail:async(to,subject,body)=>mail.push({to,subject,body}),stripe:extra.stripe});
  const server=app.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(async()=>{await new Promise(r=>server.close(r));db.close();rmSync(uploads,{recursive:true,force:true});});
  const base='http://127.0.0.1:'+server.address().port;
  function client(){
    let cookie='',csrf='';
    return {get cookie(){return cookie;},get csrf(){return csrf;},
      async get(path){const res=await fetch(base+path,{headers:{cookie},redirect:'manual'});if(res.headers.get('set-cookie'))cookie=res.headers.get('set-cookie').split(';')[0];const text=await res.text();csrf=text.match(/name="_csrf" value="([a-f0-9]+)"/)?.[1]||csrf;return {res,text};},
      async post(path,body={},headers={}){const res=await fetch(base+path,{method:'POST',headers:{cookie,'content-type':'application/x-www-form-urlencoded',...headers},body:new URLSearchParams({_csrf:csrf,...body}),redirect:'manual'});if(res.headers.get('set-cookie'))cookie=res.headers.get('set-cookie').split(';')[0];const text=await res.text();csrf=text.match(/name="_csrf" value="([a-f0-9]+)"/)?.[1]||csrf;return {res,text};}
    };
  }
  async function register(email='reader@example.test',name='Test Reader'){
    const c=client();await c.get('/sign_up');const oldCookie=c.cookie;
    const result=await c.post('/sign_up',{email,name,password:'a secure test password'});assert.equal(result.res.status,302);assert.notEqual(c.cookie,oldCookie);
    await c.get('/account');return c;
  }
  async function verify(c,email='reader@example.test'){
    const link=mail.findLast(m=>m.to===email&&m.subject.startsWith('Confirm')).body.match(/http[^\s]+/)[0];
    const url=new URL(link);await c.get(url.pathname+url.search);assert.equal((await c.post('/verify',{token:url.searchParams.get('token')})).res.status,200);await c.get('/account');
  }
  return {db,base,mail,client,register,verify,billing};
}

test('public pages render, assets are local, all confirmed prices agree, PDF is real',async t=>{
  const f=await fixture(t),c=f.client();
  for(const path of ['/','/feed','/search','/search?q=perception','/sign_up','/login','/forgot','/checkout/explorer','/checkout/practitioner','/checkout/companion','/events','/c/welcome','/c/welcome/download-the-introductory-edition-of-the-pop-book','/terms','/privacy'])assert.equal((await c.get(path)).res.status,200,path);
  const {text}=await c.get('/');assert.match(text,/Explorer — €9\/month/);assert.match(text,/Practitioner — €18\/month/);assert.match(text,/Companion — €27\/month/);assert.doesNotMatch(text,/assets-v2.circle|app.circle|€42\/month|€115\/month/);
  assert.equal((await c.get('/')).res.headers.get('referrer-policy'),'strict-origin-when-cross-origin');
  const pdf=await fetch(f.base+'/assets/introductory-edition.pdf');assert.equal(pdf.status,200);assert.equal(Buffer.from(await pdf.arrayBuffer()).subarray(0,5).toString(),'%PDF-');
  const css=await c.get('/style.css');assert.equal(css.res.status,200);
});

test('signup persists a hashed password, rotates sessions, verifies email, and protects mutations',async t=>{
  const f=await fixture(t),c=await f.register();
  const user=f.db.prepare('SELECT * FROM users').get();assert.notEqual(user.password,'a secure test password');assert.equal(user.verified,0);
  assert.equal((await c.post('/posts',{space:'recognitions',title:'A recognition',body:'Something noticed.'})).res.status,403);
  assert.equal((await c.post('/account',{name:'Forged'}, {origin:'https://attacker.example'})).res.status,403);
  assert.equal((await c.post('/account',{name:'Forged',_csrf:'é'.repeat(64)})).res.status,403);
  await f.verify(c);assert.equal(f.db.prepare('SELECT verified FROM users').get().verified,1);
  assert.equal((await c.get('/dev/mail')).res.status,200);
  const result=await c.post('/posts',{space:'recognitions',title:'Noticing <script>alert(1)</script>',body:'A real observation <script>alert(1)</script>'});assert.equal(result.res.status,302);
  const page=await c.get(result.res.headers.get('location'));assert.match(page.text,/&lt;script&gt;/);assert.doesNotMatch(page.text,/<script>alert/);
});

test('posting, comments, likes and search work; another member cannot archive a post',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);
  let result=await c.post('/posts',{space:'questions',title:'A question about perception',body:'How does recognition change what is available?'});
  const path=result.res.headers.get('location');await c.get(path);
  const post=f.db.prepare('SELECT * FROM posts WHERE space=?').get('questions');
  assert.equal((await c.post('/posts/'+post.id+'/comments',{body:'My first response'})).res.status,302);
  assert.equal((await c.post('/posts/'+post.id+'/like')).res.status,302);assert.equal(f.db.prepare('SELECT count(*) AS n FROM likes').get().n,1);
  await c.post('/posts/'+post.id+'/like');assert.equal(f.db.prepare('SELECT count(*) AS n FROM likes').get().n,0);
  assert.match((await c.get(path)).text,/My first response/);
  assert.match((await c.get('/search?q=recognition')).text,/A question about perception/);
  const other=await f.register('other@example.test','Other Member');await f.verify(other,'other@example.test');
  assert.equal((await other.post('/posts/'+post.id+'/edit',{title:'Hijacked',body:'Bad change'})).res.status,403);
  assert.equal((await c.post('/posts/'+post.id+'/edit',{title:'Updated question',body:'A corrected observation.'})).res.status,302);
  assert.match((await c.get(path)).text,/A corrected observation/);
  assert.equal((await other.post('/posts/'+post.id+'/delete')).res.status,403);
  assert.equal((await c.post('/posts/'+post.id+'/delete')).res.status,302);
  assert.equal((await c.get(path)).res.status,404);
});

test('paid content is denied through spaces, direct URLs, search, downloads and event join links',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);
  f.db.prepare('INSERT INTO posts (id,slug,space,title,body,author,created,attachment) VALUES (?,?,?,?,?,?,?,?)').run('paid','private-practice','guided-practices','Secret paid title','PRIVATE BODY','PK',Date.now(),'/downloads/11111111-1111-1111-1111-111111111111.pdf');
  for(const path of ['/c/guided-practices','/c/guided-practices/private-practice','/downloads/11111111-1111-1111-1111-111111111111.pdf']){const page=await c.get(path);assert.equal(page.res.status,403);assert.doesNotMatch(page.text,/PRIVATE BODY/);}
  assert.doesNotMatch((await c.get('/search?q=Secret')).text,/Secret paid title/);
  f.db.prepare('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)').run('circle','A live circle','Explore together','2026-12-01T10:00:00Z',75,2,'https://example.test/private-meeting','https://example.test/private-recording',Date.now());
  assert.doesNotMatch((await c.get('/events')).text,/private-meeting|private-recording/);
  assert.equal((await c.get('/events/circle/join')).res.status,403);
  assert.equal((await c.get('/events/circle/recording')).res.status,403);
  assert.equal((await c.post('/events/circle/rsvp')).res.status,403);
  const billing=await c.post('/checkout/explorer',{interval:'month'});assert.equal(billing.res.status,503);
  assert.equal((await c.get('/admin')).res.status,403);
});

test('reset tokens expire, are single-use, and reset revokes all previous sessions',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);
  const other=f.client();await other.get('/login');await other.post('/login',{email:'reader@example.test',password:'a secure test password'});await other.get('/account');
  const reset=f.client();await reset.get('/forgot');await reset.post('/forgot',{email:'reader@example.test'});
  const link=new URL(f.mail.findLast(m=>m.subject.startsWith('Reset')).body.match(/http[^\s]+/)[0]);
  await reset.get(link.pathname+link.search);
  assert.equal((await reset.post('/reset',{token:link.searchParams.get('token'),password:'the new secure password'})).res.status,200);
  assert.equal((await c.get('/account')).res.status,302);assert.equal((await other.get('/account')).res.status,302);
  await reset.get('/reset'+link.search);assert.equal((await reset.post('/reset',{token:link.searchParams.get('token'),password:'another secure password'})).res.status,400);
  await reset.get('/login');assert.equal((await reset.post('/login',{email:'reader@example.test',password:'a secure test password'})).res.status,401);
  assert.equal((await reset.post('/login',{email:'reader@example.test',password:'the new secure password'})).res.status,302);
});

test('owner can publish protected content and manage events; free accounts cannot upload',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);const user=f.db.prepare('SELECT id FROM users').get();
  const forged=await fetch(f.base+'/admin/attachment',{method:'POST',headers:{cookie:c.cookie,'x-csrf-token':c.csrf}});assert.equal(forged.status,403);
  f.db.prepare('UPDATE users SET admin=1 WHERE id=?').run(user.id);assert.equal((await c.get('/admin')).res.status,200);
  assert.equal((await c.post('/posts',{space:'guided-practices',title:'A private practice',body:'A guided Field Check.'})).res.status,302);
  await c.get('/admin');const bad=await c.post('/admin/events',{title:'Circle',description:'Together',starts:'2026-12-01T10:00',duration:'75',level:'2',join_url:'javascript:alert(1)'});assert.equal(bad.res.status,400);
  assert.equal((await c.post('/admin/events',{title:'Circle',description:'Together',starts:'2026-12-01T10:00',duration:'75',level:'2',join_url:'https://example.test/meeting'})).res.status,302);
  const event=f.db.prepare('SELECT * FROM events').get();assert.equal(event.starts,'2026-12-01T10:00:00.000Z');assert.equal((await c.post('/events/'+event.id+'/rsvp')).res.status,302);
  assert.equal((await c.get('/events/'+event.id+'/join')).res.headers.get('location'),'https://example.test/meeting');
});

test('entitlement expiry and subscription states fail closed',()=>{
  const now=Date.now();
  for(const status of ['past_due','unpaid','canceled','incomplete','paused'])assert.equal(accessLevel({tier:'companion',subscription_status:status,entitled_until:now+99999}),0);
  assert.equal(accessLevel({tier:'companion',subscription_status:'active',entitled_until:now-1}),0);
  assert.equal(accessLevel({tier:'practitioner',subscription_status:'trialing',entitled_until:now+99999}),2);
});

test('Stripe webhook signature, replay, current-state reconciliation and retry behavior',async t=>{
  let state='active',fail=false;
  const stripe={webhooks:{constructEvent(body,signature){if(signature!=='test-valid')throw new Error('bad signature');return JSON.parse(body);}},subscriptions:{async list(){if(fail)throw new Error('network');return {data:[{status:state,items:{data:[{price:{id:'price_explorer'},current_period_end:Math.floor(Date.now()/1000)+3600}]}}]};}}};
  const f=await fixture(t,{stripe,config:{BILLING_ENABLED:'true',STRIPE_WEBHOOK_SECRET:'test-secret',STRIPE_PRICE_EXPLORER_MONTH:'price_explorer'}});
  f.db.prepare('INSERT INTO users (id,email,name,password,created,stripe_customer) VALUES (?,?,?,?,?,?)').run('u','u@example.test','Member','unused',Date.now(),'cus_test');
  const event=id=>JSON.stringify({id,type:'customer.subscription.updated',data:{object:{customer:'cus_test',status:'active'}}});
  const webhook=(id,sig='test-valid')=>fetch(f.base+'/webhooks/stripe',{method:'POST',headers:{'content-type':'application/json','stripe-signature':sig},body:event(id)});
  assert.equal((await webhook('evt_1','invalid')).status,400);assert.equal((await webhook('evt_1')).status,200);
  assert.equal(f.db.prepare('SELECT tier FROM users WHERE id=?').get('u').tier,'explorer');
  state='canceled';assert.equal((await webhook('evt_old')).status,200);assert.equal(f.db.prepare('SELECT tier FROM users WHERE id=?').get('u').tier,'reader');
  assert.equal((await webhook('evt_1')).status,200);assert.equal(f.db.prepare('SELECT tier FROM users WHERE id=?').get('u').tier,'reader');
  fail=true;assert.equal((await webhook('evt_retry')).status,503);assert.equal(f.db.prepare('SELECT id FROM webhook_events WHERE id=?').get('evt_retry'),undefined);
  fail=false;state='trialing';assert.equal((await webhook('evt_retry')).status,200);assert.equal(f.db.prepare('SELECT tier FROM users WHERE id=?').get('u').tier,'explorer');
});

test('checkout validates actual Stripe price and never grants access on return',async t=>{
  let amount=1800,calls=0;
  const stripe={prices:{async retrieve(){return {active:true,currency:'eur',unit_amount:amount,recurring:{interval:'month',interval_count:1}};}},customers:{async create(){return {id:'cus_checkout'};}},subscriptions:{async list(){return {data:[]};}},checkout:{sessions:{async create(){calls++;return {id:'cs_test',url:'https://checkout.stripe.com/test'};},async retrieve(){return {status:'open',url:'https://checkout.stripe.com/test'};}}}};
  const f=await fixture(t,{stripe,config:{BILLING_ENABLED:'true',STRIPE_WEBHOOK_SECRET:'test-secret',STRIPE_PRICE_EXPLORER_MONTH:'price_explorer'}}),c=await f.register();await f.verify(c);
  assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.status,503);
  amount=900;assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.headers.get('location'),'https://checkout.stripe.com/test');
  assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.status,303);assert.equal(calls,1);
  await c.get('/account?checkout=returned');assert.equal(f.db.prepare('SELECT tier FROM users').get().tier,'reader');
  assert.equal((await c.get('/c/guided-practices')).res.status,403);
});

test('real PDF uploads stay private and reject other file types',async t=>{
  const f=await fixture(t),owner=await f.register('owner@example.test','Owner');await f.verify(owner,'owner@example.test');
  f.db.prepare('UPDATE users SET admin=1 WHERE email=?').run('owner@example.test');await owner.get('/admin');
  await owner.post('/posts',{space:'digital-library',title:'The complete book',body:'Download your full book.'});
  const post=f.db.prepare('SELECT * FROM posts WHERE space=?').get('digital-library');
  async function upload(bytes){const form=new FormData();form.set('post_id',post.id);form.set('file',new Blob([bytes],{type:'application/pdf'}),'book.pdf');return fetch(f.base+'/admin/attachment',{method:'POST',headers:{cookie:owner.cookie,'x-csrf-token':owner.csrf},body:form});}
  assert.equal((await upload('<html>not a PDF</html>')).status,400);
  assert.equal((await upload('%PDF-1.4\nlocal test document')).status,200);
  const path=f.db.prepare('SELECT attachment FROM posts WHERE id=?').get(post.id).attachment;
  assert.equal((await owner.get(path)).res.status,200);
  const reader=await f.register('reader2@example.test','Reader Two');await f.verify(reader,'reader2@example.test');
  assert.equal((await reader.get(path)).res.status,403);assert.equal((await fetch(f.base+path)).status,403);
  await owner.get('/admin');await owner.post('/posts/'+post.id+'/delete');assert.equal((await owner.get(path)).res.status,403);
});

test('expired verification links cannot verify an account; one user cannot read another local mailbox',async t=>{
  const f=await fixture(t),first=await f.register();
  const link=new URL(f.mail[0].body.match(/http[^\s]+/)[0]);
  f.db.prepare('UPDATE tokens SET expires=?').run(Date.now()-1);
  await first.get('/verify'+link.search);assert.equal((await first.post('/verify',{token:link.searchParams.get('token')})).res.status,400);
  assert.equal(f.db.prepare('SELECT verified FROM users').get().verified,0);
  const second=await f.register('second@example.test','Second Reader');
  f.db.prepare('INSERT INTO mail_preview VALUES (?,?,?,?,?)').run(randomUUID(),'reader@example.test','Private first mailbox','DO NOT LEAK',Date.now());
  assert.doesNotMatch((await second.get('/dev/mail')).text,/DO NOT LEAK/);
});

test('checkout can renew after cancellation and reuses pending sessions during concurrent requests',async t=>{
  let calls=0,existing=[];
  const stripe={prices:{async retrieve(){return {active:true,currency:'eur',unit_amount:900,recurring:{interval:'month',interval_count:1}};}},customers:{async create(){return {id:'cus_renew'};}},subscriptions:{async list(){return {data:existing};}},checkout:{sessions:{async create(input){calls++;return {id:'cs_'+calls,url:'https://checkout.stripe.com/new',input};},async retrieve(id){return id==='cs_old'?{status:'complete',subscription:'sub_old'}:{status:'open',url:'https://checkout.stripe.com/new'};}}}};
  const f=await fixture(t,{stripe,config:{BILLING_ENABLED:'true',STRIPE_WEBHOOK_SECRET:'test-secret',STRIPE_PRICE_EXPLORER_MONTH:'price_explorer'}}),c=await f.register();await f.verify(c);
  const results=await Promise.all([c.post('/checkout/explorer',{interval:'month'}),c.post('/checkout/explorer',{interval:'month'})]);assert.ok(results.every(r=>r.res.status===303));assert.equal(calls,1);
  existing=[{id:'sub_old',status:'canceled',items:{data:[]}}];f.db.prepare('UPDATE users SET checkout_id=?,trial_used=1').run('cs_old');
  assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.status,303);assert.equal(calls,2);
  assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.status,303);assert.equal(calls,2);
});
