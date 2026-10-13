import { initializeDatabase } from '../schema.js';

// One named SQLite-backed Durable Object owns the entire community database.
// Synchronous queries and transactions keep the Node and Workers business logic identical.
export function durableDatabase(storage){
  const db={
    exec(sql){storage.sql.exec(sql);},
    prepare(sql){return {
      get(...params){return storage.sql.exec(sql,...params).toArray()[0];},
      all(...params){return storage.sql.exec(sql,...params).toArray();},
      run(...params){storage.sql.exec(sql,...params).toArray();return {changes:storage.sql.exec('SELECT changes() AS n').one().n};}
    };},
    transactionSync(fn){return storage.transactionSync(fn);}
  };
  storage.transactionSync(()=>initializeDatabase(db));
  return db;
}
