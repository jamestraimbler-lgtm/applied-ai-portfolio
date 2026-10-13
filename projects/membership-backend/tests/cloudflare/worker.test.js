import test,{before} from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp,rm,readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { build } from 'esbuild';
import Stripe from 'stripe';
import { Miniflare,convertV4MiniflareOptions } from 'miniflare';
const password='a secure worker password';
const secret='whsec_local_fixture_only';
const stripe=new Stripe('sk_test_fixture');
before(async()=>{
  await build({entryPoints:['tests/cloudflare/harness.js'],outfile:'.worker/test-worker.js',bundle:true,format:'esm',platform:'node',target:'es2022',conditions:['workerd','worker','browser'],external:['node:*','cloudflare:*'],minify:true,legalComments:'none',banner:{js:"import { createRequire } from 'node:module';const require=createRequire('/worker.js');"},define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'test-legal-text',setup(build){
    build.onLoad({filter:/templates\.js$/},async args=>({contents:(await readFile(args.path,'utf8')).replace(/export const legal=.*;\n/, 'export const legal={terms:"Test terms",privacy:"Test privacy"};\n'),loader:'js'}));
  }}]});
});
async function fixture(t,{config={},production=false}={}){
  const directory=await mkdtemp(join(tmpdir(),'pop-worker-'));
  const mail=[],api=[],checkoutInputs=[];let subscriptions=[],checkouts=0,customers=0,failStripe=false,priceAmount=900;
  const options={name:'pop-tests',modules:true,scriptPath:production?'.worker/worker.js':'.worker/test-worker.js',compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],durableObjects:{SITE:{className:'POPSite',useSQLite:true}},durableObjectsPersist:join(directory,'db'),r2Buckets:['PRIVATE_FILES'],r2Persist:join(directory,'files'),bindings:{LOCAL_DEVELOPMENT:'true',BASE_URL:'http://localhost',BILLING_ENABLED:'false',RESEND_API_KEY:'test-email-secret',MAIL_FROM:'owner@example.test',...config},outboundService:async request=>{
    const url=new URL(request.url);api.push(url.pathname);
    if(url.origin==='https://api.resend.com'){mail.push(await request.json());return Response.json({id:'mail_test'});}
    if(url.origin!=='https://api.stripe.com')throw new Error('Unexpected outbound request');
    if(failStripe)return Response.json({error:{message:'Unavailable',type:'api_error'}},{status:503});
    const priceMatch=url.pathname.match(/^\/v1\/prices\/price_(explorer|practitioner|companion)_(month|year)$/);
    if(priceMatch){const [,tier,interval]=priceMatch;return Response.json({active:true,currency:'eur',unit_amount:{explorer:{month:900,year:9000},practitioner:{month:1800,year:18000},companion:{month:2700,year:27000}}[tier][interval],recurring:{interval,interval_count:1}});}
    if(url.pathname.startsWith('/v1/prices/'))return Response.json({id:'price_explorer',active:true,currency:'eur',unit_amount:priceAmount,recurring:{interval:'month',interval_count:1}});
    if(url.pathname==='/v1/customers')return Response.json({id:customers++?'cus_test_'+customers:'cus_test'});
    if(url.pathname==='/v1/subscriptions')return Response.json({object:'list',data:subscriptions,has_more:false});
    if(url.pathname==='/v1/checkout/sessions'){checkoutInputs.push(new URLSearchParams(await request.text()));return Response.json({id:'cs_'+(++checkouts),url:'https://checkout.stripe.com/test'});}
    if(url.pathname.startsWith('/v1/checkout/sessions/'))return Response.json({id:'cs_1',status:'open',url:'https://checkout.stripe.com/test'});
    if(url.pathname==='/v1/billing_portal/sessions')return Response.json({url:'https://billing.stripe.com/test'});
    throw new Error('Unhandled Stripe API path');
  }};
  let mf=new Miniflare({...convertV4MiniflareOptions(options),resourcePersistencePath:directory});
  t.after(async()=>{await mf.dispose();await rm(directory,{recursive:true,force:true});});
  async function request(path,init={}){
    const input=new Request((config.BASE_URL||'http://localhost')+path,init);
    const body=input.body?new Uint8Array(await input.arrayBuffer()):undefined;
    if(body)input.headers.set('content-length',String(body.byteLength));
    return mf.dispatchFetch(input.url,{method:input.method,headers:Object.fromEntries(input.headers),body,redirect:'manual'});
  }
  async function query(sql,params=[]){const r=await request('/__test/query',{method:'POST',body:JSON.stringify({sql,params})});assert.equal(r.status,200);return r.json();}
  function client(){
    let cookie='',csrf='';
    async function send(path,init={}){
      const r=await request(path,{...init,headers:{cookie,...init.headers}});
      if(r.headers.get('set-cookie'))cookie=r.headers.get('set-cookie').split(';')[0];
      const text=await r.text();csrf=text.match(/name="_csrf" value="([a-f0-9]+)"/)?.[1]||csrf;
      return {res:r,text};
    }
    return {get cookie(){return cookie;},get csrf(){return csrf;},get:path=>send(path),post:(path,body={},headers={})=>send(path,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded',...headers},body:new URLSearchParams({_csrf:csrf,...body})}),send};
  }
  async function register(email='reader@example.test'){
    const c=client();await c.get('/sign_up');const previous=c.cookie;
    const r=await c.post('/sign_up',{email,name:'Worker Reader',password});assert.equal(r.res.status,302,r.text);assert.notEqual(c.cookie,previous);await c.get('/account');return c;
  }
  async function verify(c,email='reader@example.test'){
    const link=new URL(mail.findLast(m=>m.to.includes(email)&&m.subject.startsWith('Confirm')).text.match(/http[^\s]+/)[0]);
    await c.get(link.pathname+link.search);assert.equal((await c.post('/verify',{token:link.searchParams.get('token')})).res.status,200);await c.get('/account');
  }
  async function webhook(id,type='customer.subscription.updated',signature=true){
    const body=JSON.stringify({id,type,data:{object:{customer:'cus_test'}}});
    return request('/webhooks/stripe',{method:'POST',headers:{'Content-Type':'application/json','stripe-signature':signature?stripe.webhooks.generateTestHeaderString({payload:body,secret}):'bad'},body});
  }
  return {mail,api,checkoutInputs,client,register,verify,query,request,webhook,get checkouts(){return checkouts;},async absolute(url,init={}){return mf.dispatchFetch(url,{...init,redirect:'manual'});},set subscriptions(value){subscriptions=value;},set failStripe(value){failStripe=value;},set priceAmount(value){priceAmount=value;},async restart(){await mf.dispose();mf=new Miniflare({...convertV4MiniflareOptions(options),resourcePersistencePath:directory});}};
}
const billing={BILLING_ENABLED:'true',STRIPE_SECRET_KEY:'sk_test_fixture',STRIPE_WEBHOOK_SECRET:secret,STRIPE_PRICE_EXPLORER_MONTH:'price_explorer'};
const subscription=status=>[{id:'sub_test',status,items:{data:[{price:{id:'price_explorer'},current_period_end:Math.floor(Date.now()/1000)+86400}]}}];

test('Worker renders all page types with precompiled templates and no runtime eval',async t=>{
  const f=await fixture(t),c=f.client();
  for(const path of ['/','/feed','/search?q=book','/login','/sign_up','/forgot','/reset','/verify','/events','/terms','/privacy','/checkout/explorer','/checkout/practitioner','/checkout/companion','/c/welcome','/c/welcome/download-the-introductory-edition-of-the-pop-book'])assert.equal((await c.get(path)).res.status,200,path);
  assert.equal((await c.get('/c/guided-practices')).res.status,403);
  assert.equal((await c.get('/not-a-route')).res.status,404);
  assert.doesNotMatch(await readFile('.worker/worker.js','utf8'),/__test\/query|testQuery/);
});

test('Worker passwords, confirmation emails, session rotation and CSRF work',async t=>{
  const f=await fixture(t),c=await f.register();
  const [user]=await f.query('SELECT * FROM users');assert.notEqual(user.password,password);assert.equal(user.verified,0);
  assert.equal((await c.post('/posts',{space:'questions',title:'Question',body:'My question'})).res.status,403);
  assert.equal((await c.post('/account',{name:'Forged'},{origin:'https://attacker.test'})).res.status,403);
  assert.equal((await c.post('/account',{name:'Forged',_csrf:'wrong'})).res.status,403);
  await f.verify(c);assert.equal((await f.query('SELECT verified FROM users'))[0].verified,1);
  await c.post('/logout');await c.get('/login');
  assert.equal((await c.post('/login',{email:user.email,password:'wrong'})).res.status,401);
  assert.equal((await c.post('/login',{email:user.email,password})).res.status,302);
  assert.equal((await c.get('/account')).res.status,200);
});

test('Worker posts, edits, comments, likes, search and moderation survive a runtime restart',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);
  const result=await c.post('/posts',{space:'questions',title:'A <script> question',body:'A perceptive observation'});assert.equal(result.res.status,302);
  const path=result.res.headers.get('location'),[post]=await f.query("SELECT * FROM posts WHERE space='questions'");
  await c.get(path);assert.equal((await c.post('/posts/'+post.id+'/comments',{body:'A reply'})).res.status,302);
  await c.post('/posts/'+post.id+'/like');assert.equal((await f.query('SELECT count(*) n FROM likes'))[0].n,1);
  assert.match((await c.get(path)).text,/&lt;script&gt;/);
  assert.match((await c.get('/search?q=observation')).text,/A &lt;script&gt; question/);
  assert.equal((await c.get('/posts/'+post.id+'/edit')).res.status,200);
  await c.post('/posts/'+post.id+'/edit',{title:'Edited title',body:'Updated content'});
  await f.restart();assert.match((await c.get(path)).text,/Edited title|A reply/);assert.equal((await c.get('/account')).res.status,200);
  const other=await f.register('other@example.test');await f.verify(other,'other@example.test');
  assert.equal((await other.post('/posts/'+post.id+'/delete')).res.status,403);
  await c.post('/posts/'+post.id+'/delete');assert.equal((await c.get(path)).res.status,404);
});

test('Worker password reset consumes a token atomically and revokes existing sessions',async t=>{
  const f=await fixture(t),c=await f.register();await f.verify(c);
  const reset=f.client();await reset.get('/forgot');await reset.post('/forgot',{email:'reader@example.test'});
  const token=new URL(f.mail.findLast(m=>m.subject.startsWith('Reset')).text.match(/http[^\s]+/)[0]).searchParams.get('token');
  await reset.get('/reset?token='+token);
  const results=await Promise.all([reset.post('/reset',{token,password:'another long password'}),reset.post('/reset',{token,password:'another long password'})]);
  assert.equal(results.filter(r=>r.res.status===200).length,1);assert.ok(results.some(r=>[400,403].includes(r.res.status)));
  await reset.get('/reset?token='+token);assert.equal((await reset.post('/reset',{token,password:'another long password'})).res.status,400);
  assert.equal((await c.get('/account')).res.status,302);
  const login=f.client();await login.get('/login');assert.equal((await login.post('/login',{email:'reader@example.test',password:'another long password'})).res.status,302);
});

test('Worker owner bootstrap requires verified email; R2 PDFs and event links stay protected',async t=>{
  const f=await fixture(t,{config:{OWNER_EMAIL:'owner@example.test'}}),owner=await f.register('owner@example.test');
  assert.equal((await owner.get('/admin')).res.status,403);await f.verify(owner,'owner@example.test');assert.equal((await owner.get('/admin')).res.status,200);
  const created=await owner.post('/posts',{space:'guided-practices',title:'Private practice',body:'Paid private content'});assert.equal(created.res.status,302);
  const [post]=await f.query("SELECT * FROM posts WHERE space='guided-practices'");
  await owner.get('/admin');
  const form=new FormData();form.set('post_id',post.id);form.set('file',new Blob(['%PDF-1.4\nTest private PDF'],{type:'application/pdf'}),'private.pdf');
  const upload=await owner.send('/admin/attachment',{method:'POST',headers:{'x-csrf-token':owner.csrf},body:form});assert.equal(upload.res.status,200,upload.text);
  const [saved]=await f.query('SELECT attachment FROM posts WHERE id=?',[post.id]);
  assert.match((await owner.get(saved.attachment)).text,/^%PDF-/);
  const reader=await f.register();await f.verify(reader);
  for(const path of ['/c/guided-practices',created.res.headers.get('location'),saved.attachment])assert.equal((await reader.get(path)).res.status,403,path);
  assert.doesNotMatch((await reader.get('/search?q=private')).text,/Paid private content/);
  await owner.get('/admin');assert.equal((await owner.post('/admin/events',{title:'A circle',description:'Practice together',starts:'2026-12-01T10:00',duration:60,level:2,join_url:'https://example.test/private-meeting',recording_url:'https://example.test/private-recording'})).res.status,302);
  const [event]=await f.query('SELECT * FROM events');assert.doesNotMatch((await reader.get('/events')).text,/private-meeting|private-recording/);
  assert.equal((await reader.get('/events/'+event.id+'/join')).res.status,403);
  assert.equal((await reader.get('/events/'+event.id+'/recording')).res.status,403);
  assert.equal((await reader.post('/events/'+event.id+'/rsvp')).res.status,403);
  assert.equal((await owner.get('/events/'+event.id+'/join')).res.headers.get('location'),event.join_url);
  await owner.post('/events/'+event.id+'/rsvp');assert.equal((await f.query('SELECT count(*) n FROM rsvps'))[0].n,1);
  await f.restart();assert.match((await owner.get(saved.attachment)).text,/^%PDF-/);
});

test('Worker Stripe SDK checkout, portal and signed subscription webhooks handle retries and cancellation',async t=>{
  const f=await fixture(t,{config:billing}),c=await f.register();await f.verify(c);
  const results=await Promise.all([c.post('/checkout/explorer',{interval:'month'}),c.post('/checkout/explorer',{interval:'month'})]);assert.ok(results.every(r=>r.res.status===303),results.map(r=>r.text).join('\n'));assert.equal(f.checkouts,1);
  assert.equal((await c.get('/c/guided-practices')).res.status,403);
  assert.equal((await f.webhook('evt_bad','customer.subscription.updated',false)).status,400);
  f.subscriptions=subscription('active');assert.equal((await f.webhook('evt_active')).status,200);assert.equal((await c.get('/c/guided-practices')).res.status,200);
  assert.equal((await c.post('/billing/portal')).res.status,303);
  const calls=f.api.length;assert.equal((await f.webhook('evt_active')).status,200);assert.equal(f.api.length,calls);
  f.subscriptions=subscription('canceled');assert.equal((await f.webhook('evt_cancel','customer.subscription.deleted')).status,200);assert.equal((await c.get('/c/guided-practices')).res.status,403);
  assert.equal((await f.webhook('evt_old_active')).status,200);assert.equal((await f.query('SELECT tier FROM users'))[0].tier,'reader');
  f.failStripe=true;assert.equal((await f.webhook('evt_retry')).status,503);assert.equal((await f.query("SELECT count(*) n FROM webhook_events WHERE id='evt_retry'"))[0].n,0);
  f.failStripe=false;f.subscriptions=subscription('trialing');assert.equal((await f.webhook('evt_retry')).status,200);assert.equal((await c.get('/c/guided-practices')).res.status,200);
});

test('Worker rejects wrong prices, expired entitlements and unavailable billing',async t=>{
  const f=await fixture(t,{config:billing}),c=await f.register();await f.verify(c);
  f.priceAmount=4200;assert.equal((await c.post('/checkout/explorer',{interval:'month'})).res.status,503);assert.equal(f.checkouts,0);
  await f.query("UPDATE users SET tier='companion',subscription_status='active',entitled_until=1,billing_checked=?",[Date.now()]);assert.equal((await c.get('/c/guided-practices')).res.status,403);
});

test('Worker auth rate limits survive restart and cannot be bypassed with forwarded headers',async t=>{
  const f=await fixture(t),c=f.client();await c.get('/forgot');
  for(let i=0;i<20;i++)assert.equal((await c.post('/forgot',{email:'absent@example.test'},{'x-forwarded-for':'10.0.0.'+i,'x-pop-client-ip':'fake-'+i})).res.status,200);
  await f.restart();const r=await c.post('/forgot',{email:'absent@example.test'});assert.equal(r.res.status,429);assert.ok(Number(r.res.headers.get('retry-after'))>0);
});

test('Production entrypoint fails closed without owner setup; local mode cannot be exposed publicly',async t=>{
  const f=await fixture(t,{production:true,config:{LOCAL_DEVELOPMENT:'false',BASE_URL:'https://thepopway.com'}});
  assert.equal((await f.request('/sign_up',{method:'POST'})).status,503);
  const mf=new Miniflare(convertV4MiniflareOptions({modules:true,scriptPath:'.worker/worker.js',compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],durableObjects:{SITE:{className:'POPSite',useSQLite:true}},r2Buckets:['PRIVATE_FILES'],bindings:{BASE_URL:'https://thepopway.com',BILLING_ENABLED:'false',LEGAL_APPROVED:'false'}}));
  try{const r=await mf.dispatchFetch('https://thepopway.com/sign_up');assert.equal(r.status,503);assert.doesNotMatch(await r.text(),/password|secret|token/i);}finally{await mf.dispose();}
  const local=new Miniflare(convertV4MiniflareOptions({modules:true,scriptPath:'.worker/worker.js',compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],durableObjects:{SITE:{className:'POPSite',useSQLite:true}},r2Buckets:['PRIVATE_FILES'],bindings:{LOCAL_DEVELOPMENT:'true',BASE_URL:'http://localhost'}}));
  try{assert.equal((await local.dispatchFetch('https://public.example/sign_up')).status,503);}finally{await local.dispose();}
});

test('Production-mode Worker uses secure cookies, blocks local mail and enforces its canonical origin',async t=>{
  const f=await fixture(t,{config:{LOCAL_DEVELOPMENT:'false',BASE_URL:'https://thepopway.com',LEGAL_APPROVED:'true'}}),c=f.client();
  const page=await c.get('/sign_up');assert.equal(page.res.status,200);assert.match(page.res.headers.get('set-cookie'),/HttpOnly/);assert.match(page.res.headers.get('set-cookie'),/Secure/);assert.match(page.res.headers.get('set-cookie'),/SameSite=Lax/);
  assert.equal((await c.get('/dev/mail')).res.status,404);
  const redirect=await f.absolute('https://alternate.test/feed?q=book');assert.equal(redirect.status,308);assert.equal(redirect.headers.get('location'),'https://thepopway.com/feed?q=book');
  assert.equal((await f.absolute('https://alternate.test/sign_up',{method:'POST'})).status,403);
  assert.equal((await c.post('/sign_up',{email:'prod@example.test',name:'Production Test',password},{origin:'https://thepopway.com'})).res.status,302);
  await c.get('/account');await f.verify(c,'prod@example.test');assert.equal((await c.get('/account')).res.status,200);
  assert.equal((await c.post('/account',{name:'Bad'},{origin:'https://alternate.test'})).res.status,403);
});

test('Worker accepts the promised 30 MB PDF limit and rejects oversized uploads',async t=>{
  const f=await fixture(t,{config:{OWNER_EMAIL:'owner@example.test'}}),c=await f.register('owner@example.test');await f.verify(c,'owner@example.test');
  await c.post('/posts',{space:'guided-practices',title:'Large PDF',body:'Private book attachment'});
  const [post]=await f.query("SELECT id FROM posts WHERE space='guided-practices'");await c.get('/admin');
  const bytes=new Uint8Array(30*1024*1024);bytes.set(new TextEncoder().encode('%PDF-1.4\n'));
  async function upload(parts){const data=new FormData();data.set('post_id',post.id);data.set('file',new Blob(parts,{type:'application/pdf'}),'book.pdf');return c.send('/admin/attachment',{method:'POST',headers:{'x-csrf-token':c.csrf},body:data});}
  const valid=await upload([bytes]);assert.equal(valid.res.status,200,valid.text);
  const [saved]=await f.query('SELECT attachment FROM posts WHERE id=?',[post.id]);const file=await c.get(saved.attachment);assert.equal(file.res.status,200);assert.equal(file.text.length,bytes.length);assert.match(file.text.slice(0,9),/^%PDF-1.4/);assert.match(file.res.headers.get('content-disposition'),/attachment/);
  const tooLarge=await upload([bytes,'x']);assert.equal(tooLarge.res.status,413);assert.equal((await f.query('SELECT attachment FROM posts WHERE id=?',[post.id]))[0].attachment,saved.attachment);
});

test('Worker checkout supports all six confirmed prices and only the agreed trial tiers',async t=>{
  const config={...billing};
  for(const tier of ['explorer','practitioner','companion'])for(const interval of ['month','year'])config[`STRIPE_PRICE_${tier.toUpperCase()}_${interval.toUpperCase()}`]=`price_${tier}_${interval}`;
  const f=await fixture(t,{config});
  for(const tier of ['explorer','practitioner','companion'])for(const interval of ['month','year']){
    const email=`${tier}-${interval}@example.test`,c=await f.register(email);await f.query('UPDATE users SET verified=1 WHERE email=?',[email]);await c.get('/account');
    const result=await c.post('/checkout/'+tier,{interval});assert.equal(result.res.status,303,result.text);
    const input=f.checkoutInputs.at(-1);assert.equal(input.get('line_items[0][price]'),`price_${tier}_${interval}`);assert.equal(input.get('subscription_data[trial_period_days]'),tier==='companion'?null:'7');
  }
  assert.equal(f.checkouts,6);
});
