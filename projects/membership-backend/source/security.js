import { randomBytes,createHash,scrypt,timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
const derive=promisify(scrypt);
export const randomToken=()=>randomBytes(32).toString('hex');
export const hashToken=value=>createHash('sha256').update(value).digest('hex');
export async function hashPassword(password){
  const salt=randomBytes(16).toString('hex');
  const key=await derive(password,salt,64);
  return salt+':'+key.toString('hex');
}
export async function checkPassword(password,stored){
  const [salt,key]=stored.split(':');
  const candidate=await derive(password,salt,64);
  return timingSafeEqual(candidate,Buffer.from(key,'hex'));
}
export function sameToken(a,b){
  return typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
}
export function sessionMiddleware(db,production){
  let lastPrune=0;
  return (req,res,next)=>{
    const now=Date.now();
    if(now-lastPrune>3600000){db.prepare('DELETE FROM sessions WHERE expires<?').run(now);db.prepare('DELETE FROM tokens WHERE expires<?').run(now);db.prepare('DELETE FROM mail_preview WHERE created<?').run(now-86400000);db.prepare('DELETE FROM request_limits WHERE expires<?').run(now);lastPrune=now;}
    const raw=req.headers.cookie?.split(';').map(x=>x.trim()).find(x=>x.startsWith('pop_session='))?.slice(12);
    let session=raw&&/^[a-f0-9]{64}$/.test(raw)?db.prepare('SELECT * FROM sessions WHERE hash=? AND expires>?').get(hashToken(raw),now):null;
    req.newSession=(userId=null)=>{
      if(session) db.prepare('DELETE FROM sessions WHERE hash=?').run(session.hash);
      const token=randomToken();
      session={hash:hashToken(token),csrf:randomToken(),user_id:userId,expires:now+7*86400000};
      db.prepare('INSERT INTO sessions VALUES (?,?,?,?)').run(session.hash,session.user_id,session.csrf,session.expires);
      res.cookie('pop_session',token,{httpOnly:true,secure:production,sameSite:'lax',maxAge:7*86400000,path:'/'});
      req.session=session;return session;
    };
    if(!session) req.newSession();
    req.session=session;
    req.user=session.user_id?db.prepare('SELECT * FROM users WHERE id=?').get(session.user_id):null;
    res.locals.user=req.user;
    res.locals.csrf=session.csrf;
    next();
  };
}
// Persistent counters survive instance eviction; no interval keeps a Worker awake.
export function persistentRateLimit(db,scope,windowMs,limit,address=req=>req.ip){
  return (req,res,next)=>{
    const now=Date.now(),expires=(Math.floor(now/windowMs)+1)*windowMs;
    const key=hashToken(scope+':'+address(req)+':'+expires);
    const row=db.prepare('INSERT INTO request_limits(key,count,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1 RETURNING count').get(key,expires);
    if(row.count>limit){res.setHeader('Retry-After',Math.ceil((expires-now)/1000));return res.status(429).send('Too many attempts. Please try again later.');}
    next();
  };
}
export function csrfProtection(baseUrl){
  const origin=new URL(baseUrl).origin;
  return (req,res,next)=>{
    if(['GET','HEAD','OPTIONS'].includes(req.method)) return next();
    if((req.headers.origin&&req.headers.origin!==origin)||!sameToken(req.body?._csrf,req.session.csrf)){
      return res.status(403).render('message',{title:'Please try again',message:'This form has expired or came from another site. Reload the page and try again.'});
    }
    next();
  };
}
