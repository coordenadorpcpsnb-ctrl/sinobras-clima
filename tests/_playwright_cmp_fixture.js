#!/usr/bin/env node
/*
 * tests/_playwright_cmp_fixture.js — ENSO-DADOS Fase C: carrega uma
 * cópia de docs/index.html com SARIMAX_DATA/CPC_IRI substituídos por
 * fixtures sintéticas (mesma técnica de regex que
 * scripts/update_dashboard.py e scripts/update_indices.py já usam em
 * produção — nunca uma reimplementação da página), abre no Chromium
 * headless pré-instalado deste ambiente (sem rede, sem navegar para
 * URL nenhuma, só file://), clica na aba "Comparativo" (onde
 * buildComparativo()/rebuildCmpTri()/buildCmpTable() são
 * efetivamente chamadas) e devolve, como JSON em stdout:
 *   - consoleErrors / pageErrors: para o critério "sem erro JS"
 *   - tbodyHTML: innerHTML de #t-cmp-full, para inspecionar texto
 *     renderizado (nunca "null mm", "NaN", "undefined", "mm" duplicado)
 *   - emptyStateVisible / canvasVisible: estado do gráfico trimestral
 *
 * Uso: node _playwright_cmp_fixture.js <fixture.json>
 * fixture.json: {"sarimax": {...}, "cpc_iri": {...}}  (objetos JS
 * completos — serão serializados com JSON.stringify, válidos como
 * literal JS já que não têm comentários).
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const fixturePath = process.argv[2];
  if (!fixturePath) {
    console.error('uso: node _playwright_cmp_fixture.js <fixture.json>');
    process.exit(2);
  }
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const dashboardPath = path.join(__dirname, '..', 'docs', 'index.html');
  let html = fs.readFileSync(dashboardPath, 'utf8');

  /* Este ambiente de teste não tem acesso de rede ao CDN do Chart.js —
     e isso não importa para o que este teste verifica (disponibilidade
     regional e texto renderizado na tabela, não o desenho do gráfico em
     si). Remove os <script src="https://..."> externos e injeta um
     stub mínimo de `Chart` via addInitScript, ANTES de qualquer script
     da página rodar, para que new Chart(...)/.destroy() nunca lancem. */
  html = html.replace(/<script src="https:\/\/cdnjs\.cloudflare\.com[^"]*"><\/script>\n?/g, '');

  html = html.replace(
    /const SARIMAX_DATA = \{.*?\};/s,
    `const SARIMAX_DATA = ${JSON.stringify(fixture.sarimax)};`
  );
  html = html.replace(
    /const CPC_IRI = \{.*?\n\};/s,
    `const CPC_IRI = ${JSON.stringify(fixture.cpc_iri)};`
  );

  const tmpFile = path.join(os.tmpdir(), `cmp-fixture-${process.pid}-${Date.now()}.html`);
  fs.writeFileSync(tmpFile, html, 'utf8');

  /* Sem caminho fixo de binário: por padrão, deixa o próprio Playwright
     resolver o Chromium que ele já gerencia (o que `npx playwright
     install chromium` prepara na CI, e o que já vem pronto neste
     ambiente de desenvolvimento). Só usa um caminho explícito quando
     PLAYWRIGHT_CHROMIUM_PATH é definido — único jeito de amarrar isto a
     um ambiente específico sem deixar de funcionar nos outros. */
  const launchOpts = { headless: true };
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH) {
    launchOpts.executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH;
  }
  const browser = await chromium.launch(launchOpts);
  const page = await browser.newPage();
  await page.addInitScript(() => {
    window.Chart = class {
      constructor() {}
      destroy() {}
    };
  });
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', err => { pageErrors.push(String(err)); });

  try {
    await page.goto('file://' + tmpFile, { waitUntil: 'load', timeout: 15000 });
    await page.click('[data-tab=comparativo]');
    await page.waitForTimeout(150); // Chart.js/DOM assíncronos terminarem

    const tbodyHTML = await page.$eval('#t-cmp-full', el => el.innerHTML).catch(() => null);
    const emptyStateVisible = await page.$eval('#cmp-tri-empty',
      el => getComputedStyle(el).display !== 'none').catch(() => null);
    const canvasVisible = await page.$eval('#c-cmp-tri',
      el => getComputedStyle(el).display !== 'none').catch(() => null);

    console.log(JSON.stringify({ consoleErrors, pageErrors, tbodyHTML, emptyStateVisible, canvasVisible }));
  } finally {
    await browser.close();
    fs.unlinkSync(tmpFile);
  }
}

main().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
