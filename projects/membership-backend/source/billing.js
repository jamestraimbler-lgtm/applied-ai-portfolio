import Stripe from 'stripe';
import { randomUUID } from 'node:crypto';
import { tiers } from './content.js';
export const tierLevel=slug=>tiers.find(t=>t.slug===slug)?.level??0;
export function accessLevel(user,now=Date.now()){
  if(!user) return 0;
  if(user.admin) return 3;
  return ['active','trialing'].includes(user.subscription_status)&&user.entitled_until>now?tierLevel(user.tier):0;
}
export function createBilling(db,config,client){
  const stripe=client||(config.STRIPE_SECRET_KEY?new Stripe(config.STRIPE_SECRET_KEY,{httpClient:Stripe.createFetchHttpClient(),timeout:15000,maxNetworkRetries:1}):null);
  const enabled=config.BILLING_ENABLED==='true'&&!!stripe&&!!config.STRIPE_WEBHOOK_SECRET;
  const priceMap={};
  for(const tier of tiers.filter(t=>t.level)) for(const interval of ['month','year']){
    const price=config[`STRIPE_PRICE_${tier.slug.toUpperCase()}_${interval.toUpperCase()}`];
    if(price) priceMap[price]={...tier,interval};
  }
  const locks=new Map();
  async function exclusive(key,fn){
    const prior=locks.get(key)||Promise.resolve();
    const task=prior.catch(()=>{}).then(fn);locks.set(key,task);
    try{return await task;}finally{if(locks.get(key)===task)locks.delete(key);}
  }
  async function syncCustomer(customer){
    const user=db.prepare('SELECT * FROM users WHERE stripe_customer=?').get(customer);
    if(!user)return;
    // Read current Stripe state so old, retried or out-of-order events cannot restore stale access.
    const subscriptions=await stripe.subscriptions.list({customer,status:'all',limit:100});
    let best=null;
    for(const sub of subscriptions.data){
      if(!['active','trialing'].includes(sub.status))continue;
      for(const item of sub.items.data){
        const tier=priceMap[item.price.id];
        const until=(item.current_period_end||sub.current_period_end||sub.trial_end||0)*1000;
        if(tier&&until>Date.now()&&(!best||tier.level>best.level))best={tier:tier.slug,level:tier.level,status:sub.status,until};
      }
    }
    db.prepare('UPDATE users SET tier=?,subscription_status=?,entitled_until=?,billing_checked=?,trial_used=MAX(trial_used,?) WHERE id=?')
      .run(best?.tier||'reader',best?.status||'inactive',best?.until||0,Date.now(),subscriptions.data.length?1:0,user.id);
  }
  async function refresh(user){
    if(!user?.stripe_customer||user.admin)return user;
    if(!enabled) return {...user,tier:'reader',entitled_until:0};
    if(Date.now()-user.billing_checked>300000){
      try{await exclusive(user.stripe_customer,()=>syncCustomer(user.stripe_customer));}
      catch{const error=new Error('Membership verification is temporarily unavailable. Please try again shortly.');error.status=503;throw error;}
    }
    return db.prepare('SELECT * FROM users WHERE id=?').get(user.id);
  }
  async function checkout(user,tier,interval){
    if(!enabled) throw Object.assign(new Error('Membership payments are not connected yet.'),{status:503});
    const priceId=config[`STRIPE_PRICE_${tier.toUpperCase()}_${interval.toUpperCase()}`];
    if(!priceId||!priceMap[priceId])throw Object.assign(new Error('This membership price is not configured yet.'),{status:503});
    const expected=tiers.find(t=>t.slug===tier)[interval]*100;
    const price=await stripe.prices.retrieve(priceId);
    if(!price.active||price.currency!=='eur'||price.unit_amount!==expected||price.recurring?.interval!==interval||price.recurring.interval_count!==1)
      throw Object.assign(new Error('This price needs to be confirmed by the owner before checkout can open.'),{status:503});
    return exclusive(user.id,async()=>{
      user=db.prepare('SELECT * FROM users WHERE id=?').get(user.id);
      if(!user.stripe_customer){
        const customer=await stripe.customers.create({email:user.email,name:user.name,metadata:{pop_user_id:user.id}},{idempotencyKey:'pop-customer-'+user.id});
        db.prepare('UPDATE users SET stripe_customer=? WHERE id=?').run(customer.id,user.id);user.stripe_customer=customer.id;
      }
      await exclusive(user.stripe_customer,()=>syncCustomer(user.stripe_customer));
      user=db.prepare('SELECT * FROM users WHERE id=?').get(user.id);
      const existing=await stripe.subscriptions.list({customer:user.stripe_customer,status:'all',limit:100});
      if(existing.data.some(s=>['active','trialing','past_due','unpaid','incomplete','paused'].includes(s.status)))return portal(user);
      if(user.checkout_id){
        const pending=await stripe.checkout.sessions.retrieve(user.checkout_id);
        if(pending.status==='open')return pending.url;
        // A completed checkout may still be creating a subscription. Never create another immediately.
        if(pending.status==='complete'&&!existing.data.some(s=>s.id===pending.subscription&&['canceled','incomplete_expired'].includes(s.status)))throw Object.assign(new Error('Your previous checkout is being reconciled. Please contact us if it remains pending.'),{status:409});
        db.prepare('UPDATE users SET checkout_id=NULL,checkout_key=NULL WHERE id=?').run(user.id);
      }
      const fresh=db.prepare('SELECT * FROM users WHERE id=?').get(user.id);
      const checkoutKey=fresh.checkout_key||randomUUID();
      if(!fresh.checkout_key)db.prepare('UPDATE users SET checkout_key=? WHERE id=?').run(checkoutKey,user.id);
      const session=await stripe.checkout.sessions.create({
        mode:'subscription',customer:user.stripe_customer,client_reference_id:user.id,
        line_items:[{price:priceId,quantity:1}],
        success_url:config.BASE_URL+'/account?checkout=returned',cancel_url:config.BASE_URL+'/checkout/'+tier,
        subscription_data:{metadata:{pop_user_id:user.id},...(!fresh.trial_used&&tier!=='companion'?{trial_period_days:7}: {})}
      },{idempotencyKey:`pop-checkout-${user.id}-${checkoutKey}`});
      db.prepare('UPDATE users SET checkout_id=? WHERE id=?').run(session.id,user.id);
      return session.url;
    });
  }
  async function portal(user){
    if(!enabled||!user.stripe_customer)throw Object.assign(new Error('No connected billing account is available yet.'),{status:503});
    return (await stripe.billingPortal.sessions.create({customer:user.stripe_customer,return_url:config.BASE_URL+'/account'})).url;
  }
  async function webhook(req,res){
    if(!enabled)return res.status(503).json({error:'Billing is not enabled'});
    let event;
    try{event=stripe.webhooks.constructEventAsync?await stripe.webhooks.constructEventAsync(req.body,req.headers['stripe-signature'],config.STRIPE_WEBHOOK_SECRET):stripe.webhooks.constructEvent(req.body,req.headers['stripe-signature'],config.STRIPE_WEBHOOK_SECRET);}catch{return res.status(400).json({error:'Invalid signature'});}
    if(db.prepare('SELECT id FROM webhook_events WHERE id=?').get(event.id))return res.json({received:true});
    const allowed=['checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.async_payment_failed','customer.subscription.created','customer.subscription.updated','customer.subscription.deleted','invoice.paid','invoice.payment_failed'];
    try{
      if(allowed.includes(event.type)){
        const customer=event.data.object.customer;
        if(typeof customer==='string')await exclusive(customer,()=>syncCustomer(customer));
      }
      db.prepare('INSERT OR IGNORE INTO webhook_events VALUES (?,?)').run(event.id,Date.now());
      res.json({received:true});
    }catch{res.status(503).json({error:'Reconciliation failed; retry required'});}
  }
  return {enabled,refresh,checkout,portal,webhook,syncCustomer};
}
