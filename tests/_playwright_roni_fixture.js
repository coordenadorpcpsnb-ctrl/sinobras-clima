#!/usr/bin/env node
/*
 * tests/_playwright_roni_fixture.js — Fase ENSO-RONI 4B.1: carrega uma
 * cópia de docs/index.html com `const RONI = {...}` substituído por
 * uma fixture sintética (mesma técnica de regex que
 * tests/_playwright_cmp_fixture.js já usa para SARIMAX_DATA/CPC_IRI —
 * nunca uma reimplementação separada da página), abre no Chromium
 * headless pré-instalado deste ambiente (sem rede, só file://) e
 * devolve, como JSON em stdout, o texto/HTML renderizado dos
 * elementos relevantes:
 *   - kRoniHTML / dRoniText: card "Situação ENSO oficial" (RONI)
 *   - semaforoHeadText: cabeçalho do painel de gatilho legado (deve
 *     dizer "legado"/"provisório", nunca apresentar RONI como se
 *     fosse o índice do gatilho)
 *   - plansHTML: painel de Planos SECA/EXCESSO (deve continuar
 *     refletindo só o ONI-aprox, nunca a fixture de RONI)
 *   - consoleErrors / pageErrors: nenhum erro JS, mesmo com RONI
 *     ausente/inválido na fixture
 *
 * Uso: node _playwright_roni_fixture.js <fixture.json>
 * fixture.json: {"roni": "{ seas: 'ASO', ano: 2026, valor: 1.97,
 *   atualizado: '23/11/2026' }"}  — já como literal JS (string), para
 * poder expressar `valor: null` sem ambiguidade de JSON puro, e para
 * testar o objeto totalmente ausente com {"roni": null}.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const fixturePath = process.argv[2];
  if (!fixturePath) {
    console.error('uso: node _playwright_roni_fixture.js <fixture.json>');
    process.exit(2);
  }
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const dashboardPath = path.join(__dirname, '..', 'docs', 'index.html');
  let html = fs.readFileSync(dashboardPath, 'utf8');

  html = html.replace(/<script src="https:\/\/cdnjs\.cloudflare\.com[^"]*"><\/script>\n?/g, '');

  if (fixture.roni === null) {
    // Remove a linha inteira de `const RONI = ...;` para simular o
    // objeto totalmente ausente (nunca `undefined` sutil — ausência
    // real do identificador, testando o `typeof RONI !== 'undefined'`).
    html = html.replace(/const RONI = \{[^}]*\};\n?/, '');
  } else {
    html = html.replace(/const RONI = \{[^}]*\};/, `const RONI = ${fixture.roni};`);
  }

  const tmpFile = path.join(os.tmpdir(), `roni-fixture-${process.pid}-${Date.now()}.html`);
  fs.writeFileSync(tmpFile, html, 'utf8');

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
    await page.waitForTimeout(150); // buildMonitor() roda em DOMContentLoaded, já disparado no load

    const kRoniHTML = await page.$eval('#k-roni', el => el.innerHTML).catch(() => null);
    const dRoniText = await page.$eval('#d-roni', el => el.textContent).catch(() => null);
    const semaforoHeadText = await page.$eval('.semaforo-head h2', el => el.textContent).catch(() => null);
    const plansHTML = await page.$eval('#plans', el => el.innerHTML).catch(() => null);
    const verdictText = await page.$eval('#verdict', el => el.textContent).catch(() => null);

    console.log(JSON.stringify({ consoleErrors, pageErrors, kRoniHTML, dRoniText, semaforoHeadText, plansHTML, verdictText }));
  } finally {
    await browser.close();
    fs.unlinkSync(tmpFile);
  }
}

main().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
