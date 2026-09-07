// charts.js — Chart.js helpers for query timing visualisations

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: {
        color: '#94a3b8',
        font: { family: 'Inter', size: 11 },
        boxWidth: 12,
      }
    },
    tooltip: {
      backgroundColor: '#111827',
      borderColor: 'rgba(99,102,241,0.3)',
      borderWidth: 1,
      titleColor: '#f1f5f9',
      bodyColor: '#94a3b8',
      callbacks: {
        label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} ms`
      }
    }
  },
  scales: {
    x: {
      ticks: { color: '#64748b', font: { family: 'Inter', size: 10 } },
      grid:  { color: 'rgba(255,255,255,0.05)' },
    },
    y: {
      ticks: {
        color: '#64748b',
        font: { family: 'Inter', size: 10 },
        callback: v => v.toFixed(1) + ' ms'
      },
      grid: { color: 'rgba(255,255,255,0.05)' },
      title: { display: true, text: 'Execution Time (ms)', color: '#64748b', font: { size: 10 } }
    }
  }
};

function renderTimingChart(canvasId, labels, p50, p95, p99) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'p50',
          data: p50,
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34,197,94,0.08)',
          fill: true,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 4,
          pointBackgroundColor: '#22c55e',
        },
        {
          label: 'p95',
          data: p95,
          borderColor: '#6366f1',
          backgroundColor: 'rgba(99,102,241,0.08)',
          fill: true,
          tension: 0.35,
          borderWidth: 2.5,
          pointRadius: 5,
          pointBackgroundColor: '#6366f1',
        },
        {
          label: 'p99',
          data: p99,
          borderColor: '#f97316',
          backgroundColor: 'rgba(249,115,22,0.05)',
          fill: false,
          tension: 0.35,
          borderWidth: 2,
          borderDash: [4, 4],
          pointRadius: 4,
          pointBackgroundColor: '#f97316',
        }
      ]
    },
    options: CHART_DEFAULTS
  });
}

function renderSeverityDoughnut(canvasId, counts) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const labels   = ['CRITICAL', 'HIGH', 'MEDIUM', 'OK'];
  const colors   = ['#ef4444', '#f97316', '#eab308', '#22c55e'];
  const borders  = ['rgba(239,68,68,0.5)', 'rgba(249,115,22,0.5)', 'rgba(234,179,8,0.5)', 'rgba(34,197,94,0.5)'];
  const data     = labels.map(l => counts[l] || 0);

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors.map(c => c + '33'),
        borderColor: borders,
        borderWidth: 2,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#94a3b8',
            font: { family: 'Inter', size: 11 },
            boxWidth: 10, padding: 12,
          }
        },
        tooltip: {
          backgroundColor: '#111827',
          borderColor: 'rgba(99,102,241,0.3)',
          borderWidth: 1,
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
        }
      }
    }
  });
}

// False positive / false negative marking
function markFP(regressionId, isFP) {
  const note = prompt('Analyst note (optional):') || '';
  fetch('/api/mark-fp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regression_id: regressionId, is_false_pos: isFP, note })
  })
  .then(r => r.json())
  .then(d => {
    if (d.status === 'ok') location.reload();
    else alert('Error: ' + (d.error || 'unknown'));
  });
}

function markFN(regressionId, isFN) {
  const note = prompt('Analyst note (optional):') || '';
  fetch('/api/mark-fn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regression_id: regressionId, is_false_neg: isFN, note })
  })
  .then(r => r.json())
  .then(d => {
    if (d.status === 'ok') location.reload();
    else alert('Error: ' + (d.error || 'unknown'));
  });
}
