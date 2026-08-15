"""Standalone prediction dashboard. Existing trading code is intentionally untouched."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from prediction_system.snapshot import JsonForecastSnapshotRepository

HTML = r'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>توقع أسعار المعادن</title><style>*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#eef2ff;margin:0;padding:22px}.wrap{max-width:1180px;margin:auto}h1{font-size:clamp(30px,6vw,52px);margin:0}.sub{color:#a9b5d0;margin:10px 0 18px;line-height:1.7}.note,.source{background:#10182c;border:1px solid #273657;border-radius:14px;padding:12px 14px;color:#cbd5e8;margin-bottom:12px;line-height:1.7}.source{background:#0e1629}.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0 22px}button{background:#eef2ff;color:#10172a;border:0;border-radius:11px;padding:11px 16px;font-weight:800;cursor:pointer}.status{color:#9aa8c7}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:17px}.card{background:#131b31;border:1px solid #2b395c;border-radius:20px;padding:20px;box-shadow:0 18px 55px #0004}.metal{font-size:27px;font-weight:900}.code{font-size:12px;color:#8191b4}.current{margin:14px 0 18px;padding:14px;background:#0e1629;border-radius:13px}.current-label{font-size:13px;color:#9cacca}.current-price{font-size:28px;font-weight:900;font-variant-numeric:tabular-nums;direction:ltr;text-align:right}.forecast{padding:14px 0;border-top:1px solid #293755}.forecast-head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.horizon{font-size:16px;font-weight:800}.price{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;direction:ltr}.change{margin-top:6px;font-size:14px}.up{color:#63e6a6}.down{color:#ff8796}.flat{color:#c4cce0}.confidence{font-size:12px;color:#9aa8c7;margin-top:5px}details{margin-top:8px;color:#8f9dbb;font-size:12px}summary{cursor:pointer}.ltr{direction:ltr;display:inline-block}</style></head><body><main class="wrap"><h1>توقع أسعار المعادن الثمينة</h1><div class="sub">كل المبالغ المعروضة هي <b>دولار أمريكي لكل كيلوجرام</b>. السعر الحالي يأتي مباشرة من سوق BullionVault في لندن.</div><div class="source" id="source">المصدر الحي: BullionVault London · USD/kg · السعر المرجعي = متوسط أفضل عرض شراء وأفضل عرض بيع.</div><div class="note">بيانات التدريب التاريخية للنماذج الحالية ما زالت من بيانات المشروع السابقة. السعر الحالي المستخدم كنقطة انطلاق للتوقعات أصبح من BullionVault، ولن ننسب التدريب التاريخي إلى BullionVault إلا بعد إعادة بنائه من بيانات BullionVault فعلًا.</div><div class="actions"><button onclick="load()">تحديث التوقعات</button><span id="status" class="status">جاري تحميل آخر توقع محفوظ…</span></div><section id="grid" class="grid"></section></main><script>
const names={Gold:'الذهب',Silver:'الفضة',Platinum:'البلاتينيوم',Palladium:'البلاديوم'};
const horizons={'6h':'بعد 6 ساعات','12h':'بعد 12 ساعة','18h':'بعد 18 ساعة','24h':'بعد 24 ساعة','48h':'بعد 48 ساعة','1w':'بعد أسبوع','1m':'بعد شهر'};
const money=n=>'$'+Number(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
async function load(){const s=document.getElementById('status'),g=document.getElementById('grid');s.textContent='جاري تحميل آخر توقع محفوظ…';try{const r=await fetch('/api/predictions',{cache:'no-store'});const d=await r.json();if(r.status===503&&d.status==='warming'){s.textContent='يتم تجهيز أول مجموعة توقعات بعد النشر…';setTimeout(load,5000);return}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));g.innerHTML='';s.textContent='آخر تحديث: '+new Date(d.generated_at).toLocaleString('ar-SA');const source=document.getElementById('source');if(d.live_data_source){source.textContent='المصدر الحي: '+d.live_data_source+' · '+d.live_price_method+' · الوحدة: '+d.unit;}for(const m of d.metals){const c=document.createElement('article');c.className='card';const current=m.current_usd_per_kg ?? m.forecasts?.[0]?.current_usd_per_kg;c.innerHTML='<div class="metal">'+(names[m.metal]||m.metal)+'</div><div class="code"><span class="ltr">'+m.security_id+'</span> · '+(m.market||'BullionVault London')+' · USD/kg</div><div class="current"><div class="current-label">السعر الحالي من BullionVault لكل كيلوجرام</div><div class="current-price">'+money(current)+'</div></div>';for(const f of m.forecasts){const delta=Number(f.change_usd_per_kg ?? (f.predicted_usd_per_kg-current));const cls=delta>0?'up':delta<0?'down':'flat';const verb=delta>0?'ارتفاع متوقع':delta<0?'انخفاض متوقع':'دون تغير';const signPct=f.change_pct>0?'+':'';c.innerHTML+='<div class="forecast"><div class="forecast-head"><span class="horizon">'+(horizons[f.horizon]||f.horizon)+'</span><span class="price">'+money(f.predicted_usd_per_kg)+'</span></div><div class="change '+cls+'">'+verb+' بمقدار <b>'+money(Math.abs(delta))+'</b> لكل كجم (<span class="ltr">'+signPct+f.change_pct+'%</span>)</div><div class="confidence">ثقة النموذج: '+Math.round(f.confidence*100)+'%</div><details><summary>تفاصيل فنية</summary>Validation MAE(return): <span class="ltr">'+f.validation_mae_return+'</span></details></div>'}g.appendChild(c)}}catch(e){s.textContent='خطأ في تحميل التوقعات: '+e.message}}load();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    snapshots = JsonForecastSnapshotRepository()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "metal-prediction-dashboard", "forecast_ready": self.snapshots.exists()})
            return
        if self.path == "/api/predictions":
            if not self.snapshots.exists():
                self._json(503, {"status": "warming", "error": "Forecast snapshot is being prepared"})
                return
            try:
                self._json(200, self.snapshots.load())
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Prediction dashboard listening on 0.0.0.0:{port}")
    server.serve_forever()
