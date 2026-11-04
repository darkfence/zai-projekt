// Strona startowa etapu E1: lista serii z liczbą wyników (dane z publicznego API).
(function () {
  'use strict';
  const status = document.getElementById('status');
  const table = document.getElementById('series-table');
  const tbody = table.querySelector('tbody');

  const fmt = new Intl.DateTimeFormat('pl-PL', { dateStyle: 'short', timeStyle: 'short' });

  async function getJson(url) {
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function cell(text) {
    const td = document.createElement('td');
    td.textContent = text;
    return td;
  }

  async function load() {
    try {
      const series = await getJson('/api/series');
      if (!series.length) {
        status.textContent = 'Brak serii.';
        return;
      }
      for (const s of series) {
        const items = await getJson(`/api/measurements?series=${encodeURIComponent(s.id)}&limit=10000`);
        const tr = document.createElement('tr');
        const name = document.createElement('th');
        name.scope = 'row';
        const swatch = document.createElement('span');
        swatch.className = 'swatch';
        swatch.setAttribute('aria-hidden', 'true');
        swatch.style.backgroundColor = s.color;
        name.append(swatch, s.name);
        tr.append(name, cell(s.unit || '–'), cell(`${s.minValue} … ${s.maxValue}`));
        const count = cell(String(items.length));
        count.className = 'text-end';
        tr.append(count);
        const last = items.length ? items[items.length - 1] : null;
        tr.append(cell(last ? `${last.value} ${s.unit || ''} (${fmt.format(new Date(last.timestamp))})` : '–'));
        tbody.append(tr);
      }
      table.hidden = false;
      status.textContent = `Liczba serii: ${series.length}.`;
    } catch (err) {
      status.textContent = `Nie udało się pobrać danych z serwera (${err.message}).`;
      status.classList.add('text-danger');
    }
  }

  load();
})();
