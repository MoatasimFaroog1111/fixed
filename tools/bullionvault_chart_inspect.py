from __future__ import annotations
import re
import requests

URL='https://www.bullionvault.com/chart/bullionvaultchart.js?v=1'
text=requests.get(URL,timeout=30,headers={'User-Agent':'Mozilla/5.0'}).text
print('STATUS_CHARS',len(text))
low=text.lower()
for token in ('pricescsvhost','/prices/csv/','updateinterval','timescale','timeframe'):
    print('\nTOKEN',token)
    start=0
    hits=0
    while hits<40:
        i=low.find(token.lower(),start)
        if i<0: break
        print(text[max(0,i-900):min(len(text),i+1600)].replace('\n',' '))
        print('\n---')
        start=i+len(token)
        hits+=1

print('\nOBJECT_LIKE_TIME_SCALES')
for m in re.finditer(r'updateInterval', text):
    snippet=text[max(0,m.start()-1200):min(len(text),m.start()+1200)]
    if any(tf in snippet for tf in ('10m','1h','6h','1d','1w','1m','1q','1y','5y','20y')):
        print(snippet)
        print('\n===')
