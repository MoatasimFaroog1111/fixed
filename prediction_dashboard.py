"""Standalone prediction dashboard. Existing trading code is intentionally untouched."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from prediction_system import PredictionService

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Metal Forecast</title><style>body{font-family:system-ui;background:#0b1020;color:#eef2ff;margin:0;padding:28px}.wrap{max-width:1200px;margin:auto}h1{font-size:clamp(28px,5vw,54px);margin:0}.sub{color:#9aa8c7;margin:8px 0 28px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}.card{background:#131b31;border:1px solid #263252;border-radius:18px;padding:18px;box-shadow:0 18px 60px #0005}.metal{font-size:22px;font-weight:800}.unit{font-size:12px;color:#8ea0c6}.row{display:grid;grid-template-columns:52px 1fr auto;gap:8px;padding:10px 0;border-top:1px solid #25304d}.price{font-variant-numeric:tabular-nums}.up{color:#5ee7a0}.down{color:#ff8795}.conf{font-size:12px;color:#9aa8c7}.status{margin:18px 0;color:#9aa8c7}button{background:#eef2ff;color:#10172a;border:0;border-radius:10px;padding:10px 16px;font-weight:700;cursor:pointer}</style></head><body><main class="wrap"><h1>Precious Metal Forecast</h1><div class="sub">Persisted multi-horizon ensemble forecasts · USD/kg · leakage-safe walk-forward validation</div><button onclick="load()">Refresh forecasts</button><div id="status" class="status">Loading persisted models…</div><section id="grid" class="grid"></section></main><script>async function load(){const s=document.getElementById('status'),g=document.getElementById('grid');s.textContent='Loading persisted models and latest features…';g.innerHTML='';try{const r=await fetch('/api/predictions');const d=await r.json();if(!r.ok)throw new Error(d.error||('HTTP '+r.status));s.textContent='Generated '+new Date(d.generated_at).toLocaleString()+' · '+d.architecture;for(const m of d.metals){const c=document.createElement('article');c.className='card';c.innerHTML='<div class="metal">'+m.metal+'</div><div class="unit">'+m.security_id+' · '+d.unit+'</div>';for(const f of m.forecasts){if(f.status){c.innerHTML+='<div class="row"><b>'+f.horizon+'</b><span>'+f.status+'</span></div>';continue}const cls=f.direction==='UP'?'up':'down';c.innerHTML+='<div class="row"><b>'+f.horizon+'</b><span class="price">$'+Number(f.predicted_usd_per_kg).toLocaleString(undefined,{maximumFractionDigits:2})+'</span><span class="'+cls+'">'+(f.change_pct>0?'+':'')+f.change_pct+'%</span></div><div class="conf">Confidence '+Math.round(f.confidence*100)+'% · validation MAE(return) '+f.validation_mae_return+'</div>'}g.appendChild(c)}}catch(e){s.textContent='Forecast error: '+e.message}}load()</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    service = PredictionService()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "metal-prediction-dashboard"})
            return
        if self.path == "/api/predictions":
            try:
                self._json(200, self.service.predict_all())
            except FileNotFoundError as exc:
                self._json(503, {"error": str(exc), "status": "models_not_ready"})
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
