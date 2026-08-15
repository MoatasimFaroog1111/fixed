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
  platinumStartCheck: { from: new Date('2021-11-01T00:00:00Z'), to: new Date('2021-11-08T00:00:00Z') },
};

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

const report = { generated_at: new Date().toISOString(), source: 'Dukascopy via dukascopy-node', timeframe: 'h1', targets: {} };

for (const [metal, instrument] of Object.entries(targets)) {
  const result = { instrument, validation: await fetchWindow(instrument, windows.validation) };
  if (metal === 'platinum') {
    result.five_year_boundary = await fetchWindow(instrument, windows.fiveYearBoundary);
    result.platinum_start_check = await fetchWindow(instrument, windows.platinumStartCheck);
  } else {
    result.five_year_boundary = await fetchWindow(instrument, windows.fiveYearBoundary);
  }
  report.targets[metal] = result;
  console.log(JSON.stringify({ [metal]: result }));
}

fs.writeFileSync('dukascopy_node_probe_report.json', JSON.stringify(report, null, 2));
