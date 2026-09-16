import requests, json
from collections import Counter
r = requests.get('https://external-api.kalshi.com/trade-api/v2/markets',
                 params={'limit':50,'status':'open'}, timeout=20)
mkts = r.json().get('markets', [])
print('got', len(mkts), 'markets')
m = mkts[0]
print('price fields on market 0:')
for k in ['yes_bid','yes_ask','last_price','no_bid','no_ask','volume','title','subtitle','category']:
    print('  ', k, '=', m.get(k))
print()
cats = Counter(m.get('category','?') for m in mkts)
print('categories seen:', dict(cats))
print()
print('sample titles:')
for m in mkts[:12]:
    print('  [', m.get('category','?'), '] yes_bid=', m.get('yes_bid'), '|', (m.get('title') or '')[:60])
