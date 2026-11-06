#!/usr/bin/env node
/*
 * tests/_playwright_ui_smoke.js — ENSO-UI: smoke test de inicialização
 * geral do dashboard (docs/index.html REAL, sem fixtures — este teste é
 * sobre comportamento de carregamento/navegação, não sobre dados
 * CPC_IRI/SARIMAX). Confirma, numa única carga de página:
 *
 *   - ausência de qualquer erro JS não tratado durante o carregamento;
 *   - initPersistence() de fato executou (window._sinobrasBundle
 *     definido) e o indicador de storage saiu do estado padrão estático;
 *   - comportamento controlado quando window.storage não existe (este
 *     ambiente headless não define window.storage — é o cenário real
 *     de "storage indisponível", não simulado);
 *   - rótulos [data-periodo] refletem D.fc_labels, não o texto estático
 *     original do HTML;
 *   - as seis abas (monitor/previsao/comparativo/clima/balanco/plano)
 *     trocam de painel sem lançar nenhum erro JS novo;
 *   - a aba Comparativo continua renderizando a tabela de
 *     disponibilidade regional (correção da PR #65) ao ser aberta.
 *
 * Uso: node _playwright_ui_smoke.js <caminho para docs/index.html>
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const TABS = ['monitor', 'previsao', 'comparativo', 'clima', 'balanco', 'plano'];

async function main() {
  const dashboardPath = process.argv[2];
  if (!dashboardPath) {
    console.error('uso: node _playwright_ui_smoke.js <docs/index.html>');
    process.exit(2);
  }
  let html = fs.readFileSync(dashboardPath, 'utf8');
  // mesma técnica das outras suítes desta fase: sem rede ao CDN do Chart.js
  html = html.replace(/<script src="https:\/\/cdnjs\.cloudflare\.com[^"]*"><\/script>\n?/g, '');

  const tmpFile = path.join(os.tmpdir(), `ui-smoke-${process.pid}-${Date.now()}.html`);
  fs.writeFileSync(tmpFile, html, 'utf8');

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.addInitScript(() => {
    window.Chart = class { constructor() {} destroy() {} };
  });
  const pageErrors = [];
  const consoleErrors = [];
  page.on('pageerror', err => pageErrors.push(String(err)));
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });

  try {
    await page.goto('file://' + tmpFile, { waitUntil: 'load', timeout: 15000 });
    await page.waitForTimeout(250);

    const estadoInicial = await page.evaluate(() => ({
      embeddedBundleDefined: typeof window._sinobrasBundle !== 'undefined',
      sinobrasSource: window._sinobrasSource,
      persistStatusHTML: document.getElementById('persist-status')
        ? document.getElementById('persist-status').innerHTML.trim() : null,
      periodoEls: Array.from(document.querySelectorAll('[data-periodo]')).map(el => el.textContent),
      fcLabelsRange: (typeof D !== 'undefined')
        ? D.fc_labels[0] + '–' + D.fc_labels[D.fc_labels.length - 1] : null,
      windowStorageExiste: typeof window.storage !== 'undefined',
    }));

    const tabResults = [];
    for (const tab of TABS) {
      const antesDoClique = pageErrors.length;
      await page.click(`.nav-btn[data-tab="${tab}"]`);
      await page.waitForTimeout(200);
      const paneVisivel = await page.evaluate(t => {
        const pane = document.getElementById('pane-' + t);
        return !!pane && pane.classList.contains('on');
      }, tab);
      tabResults.push({
        tab,
        paneVisivel,
        novosErrosAposClique: pageErrors.slice(antesDoClique),
      });
    }

    const comparativoHTML = await page.$eval('#t-cmp-full', el => el.innerHTML).catch(() => null);

    console.log(JSON.stringify({
      pageErrors, consoleErrors, estadoInicial, tabResults, comparativoHTML,
    }));
  } finally {
    await browser.close();
    fs.unlinkSync(tmpFile);
  }
}

main().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
