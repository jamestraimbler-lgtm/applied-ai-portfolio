import { bookSlug, bookText } from './content.js';
export function initializeDatabase(db){
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,password TEXT NOT NULL,
      verified INTEGER NOT NULL DEFAULT 0,admin INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,
      stripe_customer TEXT UNIQUE,tier TEXT NOT NULL DEFAULT 'reader',subscription_status TEXT,
      entitled_until INTEGER NOT NULL DEFAULT 0,billing_checked INTEGER NOT NULL DEFAULT 0,
      checkout_id TEXT,checkout_key TEXT,trial_used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sessions (
      hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
      csrf TEXT NOT NULL,expires INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tokens (
      hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      purpose TEXT NOT NULL,expires INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS posts (
      id TEXT PRIMARY KEY,slug TEXT UNIQUE NOT NULL,space TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,
      user_id TEXT REFERENCES users(id),author TEXT NOT NULL,created INTEGER NOT NULL,
      published INTEGER NOT NULL DEFAULT 1,attachment TEXT
    );
    CREATE TABLE IF NOT EXISTS comments (
      id TEXT PRIMARY KEY,post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id),body TEXT NOT NULL,created INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS likes (
      post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id),PRIMARY KEY(post_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,starts TEXT NOT NULL,
      duration INTEGER NOT NULL,level INTEGER NOT NULL DEFAULT 2,join_url TEXT NOT NULL,
      recording_url TEXT,created INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rsvps (
      event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id),PRIMARY KEY(event_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS webhook_events(id TEXT PRIMARY KEY,created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS mail_preview(id TEXT PRIMARY KEY,recipient TEXT,subject TEXT,body TEXT,created INTEGER);

CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS tokens_expiry ON tokens(expires);
CREATE INDEX IF NOT EXISTS tokens_user_purpose ON tokens(user_id,purpose);
CREATE INDEX IF NOT EXISTS posts_space_created ON posts(space,published,created);
CREATE INDEX IF NOT EXISTS posts_attachment ON posts(attachment);
CREATE INDEX IF NOT EXISTS comments_post ON comments(post_id,created);
CREATE TABLE IF NOT EXISTS request_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS request_limits_expiry ON request_limits(expires);
  `);
  if(!db.prepare('PRAGMA table_info(users)').all().some(c=>c.name==='checkout_key'))db.exec('ALTER TABLE users ADD COLUMN checkout_key TEXT');
  db.prepare('INSERT OR IGNORE INTO posts (id,slug,space,title,body,author,created,attachment) VALUES (?,?,?,?,?,?,?,?)')
    .run('introductory-edition',bookSlug,'welcome','Download the Introductory Edition of the PoP Book',bookText,'The Power of Perception',Date.parse('2026-03-23T12:00:00Z'),'/assets/introductory-edition.pdf');
}
