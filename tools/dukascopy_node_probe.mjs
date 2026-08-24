import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { getHistoricalRates } = require('dukascopy-node');

const targets = {
  gold: 'xauusd',
  silver: 'xagusd',
  platinum: 'xptcmdusd',
  palladium: 'xpdcmdusd',
};

const windows = {
  validation: { from: new Date('2022-01-03T00:00:00Z'), to: new Date('2022-01-10T00:00:00Z') },
  fiveYearBoundary: { from: new Date('2021-08-15T00:00:00Z'), to: new Date('2021-08-22T00:00:00Z') },
};

const monthlyChecks = [
  '2021-07-01', '2021-08-01', '2021-09-01', '2021-10-01',
  '2021-11-01', '2021-12-01', '2022-01-01'
];

function oneWeek(dateText) {
  const from = new Date(`${dateText}T00:00:00Z`);
  const to = new Date(from.getTime() + 7 * 24 * 60 * 60 * 1000);
  return { from, to };
}

async function fetchWindow(instrument, dates) {
  try {
    const data = await getHistoricalRates({ instrument, dates, timeframe: 'h1', format: 'json' });
    const rows = Array.isArray(data) ? data : [];
    const first = rows.length ? rows[0] : null;
    const last = rows.length ? rows[rows.length - 1] : null;
    return { ok: true, rows: rows.length, first, last };
  } catch (error) {
    return { ok: false, error: String(error?.message || error) };
  }
}

async function scanAvailability(instrument) {
  const checks = [];
  for (const dateText of monthlyChecks) {
    const result = await fetchWindow(instrument, oneWeek(dateText));
    checks.push({ date: dateText, rows: result.rows ?? 0, ok: result.ok, first: result.first ?? null });
  }
  return checks;
}

const report = { generated_at: new Date().toISOString(), source: 'Dukascopy via dukascopy-node', timeframe: 'h1', targets: {} };

for (const [metal, instrument] of Object.entries(targets)) {
  const result = {
    instrument,
    validation: await fetchWindow(instrument, windows.validation),
    five_year_boundary: await fetchWindow(instrument, windows.fiveYearBoundary),
  };
  if (metal !== 'gold') {
    result.availability_scan = await scanAvailability(instrument);
  }
  report.targets[metal] = result;
  console.log(JSON.stringify({ [metal]: result }));
}

fs.writeFileSync('dukascopy_node_probe_report.json', JSON.stringify(report, null, 2));
