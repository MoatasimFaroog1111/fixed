from __future__ import annotations
import re
import requests

URL='https://www.bullionvault.com/chart/bullionvaultchart.js?v=1'
text=requests.get(URL,timeout=30,headers={'User-Agent':'Mozilla/5.0'}).text
print('STATUS_CHARS',len(text))
low=text.lower()
for token in ('csv','export','download','getchart','chartdata','data.do','.do'):
    print('\nTOKEN',token)
    start=0
    hits=0
    while hits<20:
        i=low.find(token,start)
        if i<0: break
        print(text[max(0,i-500):min(len(text),i+800)].replace('\n',' '))
        print('\n---')
        start=i+len(token)
        hits+=1

print('\nURL_STRINGS')
for s in re.findall(r"['\"]([^'\"]{3,250})['\"]",text):
    l=s.lower()
    if any(k in l for k in ('csv','export','download','.do','chartdata','getchart')):
        print(s)
