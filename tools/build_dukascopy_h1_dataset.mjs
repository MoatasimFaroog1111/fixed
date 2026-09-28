import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { getHistoricalRates } = require('dukascopy-node');

const OZ_PER_KG = 32.1507466;
const START = new Date('2021-08-15T00:00:00Z');
const END = new Date('2026-08-15T23:59:59Z');
const OUT_DIR = 'dukascopy_h1_candidate';
const TARGETS = {
  gold: 'xauusd',
  silver: 'xagusd',
  platinum: 'xptcmdusd',
  palladium: 'xpdcmdusd',
};

function addMonths(date, months) {
  const d = new Date(date);
  d.setUTCMonth(d.getUTCMonth() + months);
  return d;
}

function iso(ts) { return new Date(ts).toISOString(); }

async function fetchChunk(instrument, from, to) {
  const data = await getHistoricalRates({
    instrument,
    dates: { from, to },
    timeframe: 'h1',
    format: 'json',
  });
  return Array.isArray(data) ? data : [];
}

function csvEscape(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

function buildExpectedTradingHours(rows) {
  if (!rows.length) return [];
  const start = new Date(rows[0].timestamp);
  const end = new Date(rows[rows.length - 1].timestamp);
  const expected = [];
  for (let t = start.getTime(); t <= end.getTime(); t += 3600000) {
    const d = new Date(t);
    const day = d.getUTCDay();
    if (day === 0 || day === 6) continue;
    expected.push(t);
  }
  return expected;
}

function summarize(metal, instrument, rows, chunkStats) {
  const timestamps = new Set(rows.map(r => r.timestamp));
  const expected = buildExpectedTradingHours(rows);
  const missing = expected.filter(t => !timestamps.has(t));
  let invalidOhlc = 0;
  for (const r of rows) {
    if (![r.open, r.high, r.low, r.close].every(Number.isFinite)) invalidOhlc++;
    if (Number.isFinite(r.high) && Number.isFinite(r.low) && r.high < r.low) invalidOhlc++;
  }
  const first = rows[0] ?? null;
  const last = rows[rows.length - 1] ?? null;
  return {
    metal,
    instrument,
    source: 'Dukascopy',
    timeframe: 'H1',
    source_unit: 'USD/troy_oz',
    output_unit: 'USD/kg',
    rows: rows.length,
    first_timestamp: first ? iso(first.timestamp) : null,
    last_timestamp: last ? iso(last.timestamp) : null,
    span_days: first && last ? (last.timestamp - first.timestamp) / 86400000 : 0,
    duplicate_timestamps: rows.length - timestamps.size,
    missing_weekday_hours: missing.length,
    missing_weekday_hours_sample: missing.slice(0, 50).map(iso),
    invalid_ohlc_rows: invalidOhlc,
    chunks: chunkStats,
  };
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const report = {
    generated_at: new Date().toISOString(),
    requested_start: START.toISOString(),
    requested_end: END.toISOString(),
    conversion: { oz_per_kg: OZ_PER_KG, formula: 'USD/kg = USD/troy_oz * 32.1507466' },
    metals: {},
  };

  for (const [metal, instrument] of Object.entries(TARGETS)) {
    const all = [];
    const chunkStats = [];
    let cursor = new Date(START);
    while (cursor < END) {
      const next = addMonths(cursor, 1);
      const chunkEnd = next < END ? next : END;
      try {
        const chunk = await fetchChunk(instrument, cursor, chunkEnd);
        chunkStats.push({ from: cursor.toISOString(), to: chunkEnd.toISOString(), rows: chunk.length, ok: true });
        for (const r of chunk) {
          if (r.timestamp < START.getTime() || r.timestamp > END.getTime()) continue;
          all.push({
            timestamp: r.timestamp,
            datetime: iso(r.timestamp),
            open_oz: Number(r.open),
            high_oz: Number(r.high),
            low_oz: Number(r.low),
            close_oz: Number(r.close),
            volume: Number(r.volume ?? 0),
            open: Number(r.open) * OZ_PER_KG,
            high: Number(r.high) * OZ_PER_KG,
            low: Number(r.low) * OZ_PER_KG,
            close: Number(r.close) * OZ_PER_KG,
          });
        }
      } catch (error) {
        chunkStats.push({ from: cursor.toISOString(), to: chunkEnd.toISOString(), rows: 0, ok: false, error: String(error?.message || error) });
      }
      cursor = next;
    }

    const byTs = new Map();
    for (const r of all) byTs.set(r.timestamp, r);
    const rows = [...byTs.values()].sort((a, b) => a.timestamp - b.timestamp);

    const headers = ['timestamp','datetime','open','high','low','close','volume','open_oz','high_oz','low_oz','close_oz'];
    const csv = [headers.join(',')];
    for (const r of rows) csv.push(headers.map(h => csvEscape(r[h])).join(','));
    fs.writeFileSync(path.join(OUT_DIR, `${metal}_h1_usdkg.csv`), csv.join('\n'));

    const summary = summarize(metal, instrument, rows, chunkStats);
    report.metals[metal] = summary;
    console.log(JSON.stringify(summary));
  }

  fs.writeFileSync(path.join(OUT_DIR, 'quality_report.json'), JSON.stringify(report, null, 2));
}

main().catch(err => { console.error(err); process.exit(1); });
