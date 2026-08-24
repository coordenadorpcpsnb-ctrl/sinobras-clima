#!/usr/bin/env python3
"""
enviar_email.py — Envia o dashboard e o relatório executivo por e-mail
Sinobras Florestal · executado pelo GitHub Actions após gerar_relatorio.py

Credenciais vêm de variáveis de ambiente (GitHub Secrets) — nunca do código:
  SMTP_HOST   servidor SMTP            ex.: smtp.office365.com
  SMTP_PORT   porta                    ex.: 587 (STARTTLS) ou 465 (SSL)
  SMTP_USER   usuário de autenticação  ex.: dashboard@empresa.com.br
  SMTP_PASS   senha ou app password
  MAIL_FROM   remetente exibido        (opcional; usa SMTP_USER)
  MAIL_TO     destinatários            separados por vírgula
  MAIL_CC     cópia                    (opcional)

Opcionais:
  ZIPAR_HTML  'true' (padrão) compacta o dashboard antes de anexar — muitos
              servidores corporativos bloqueiam anexos .html
  PAGES_URL   link do GitHub Pages incluído no corpo da mensagem
  DRY_RUN     '1' monta a mensagem e imprime um resumo, sem enviar
"""

import os, sys, smtplib, ssl, zipfile, mimetypes
from pathlib import Path
from datetime import date
from email.message import EmailMessage

sys.path.insert(0, str(Path(__file__).parent))
from gerar_relatorio import carregar, cenario_central, NOME_PT, num, ARM_CRITICO

ROOT      = Path(__file__).parent.parent
DOCS      = ROOT / 'docs'
DASHBOARD = DOCS / 'index.html'
RELATORIO = DOCS / 'relatorio-executivo.docx'

MESES = ['janeiro','fevereiro','março','abril','maio','junho',
         'julho','agosto','setembro','outubro','novembro','dezembro']

VERDE = '#1F4D2E'
SECA  = '#A8322C'


def env(nome, padrao=None, obrigatorio=False):
    v = os.environ.get(nome, padrao)
    if obrigatorio and not v:
        raise RuntimeError(f'variável de ambiente ausente: {nome}')
    return v


# ══════════════════════════════════════════════════════════════════════════
# Corpo da mensagem
# ══════════════════════════════════════════════════════════════════════════
def montar_corpo(d, pages_url):
    HOJE    = date.today()
    central = cenario_central(d['iri_pico'])
    linha   = d['scen'][d['scen']['cenario'] == central].iloc[0]
    meta    = d['meta']
    bh      = d['bh']

    arm      = bh['cenarios'][central]['arm']
    n_crit   = sum(1 for v in arm if v < ARM_CRITICO)
    n_clim   = sum(1 for v in bh['clim']['arm'] if v < ARM_CRITICO)
    def_c    = bh['cenarios'][central]['def_total']
    def_clim = bh['clim']['def_total']
    media    = d['anual'].mean()

    labels = d['fc'][list(d['fc'].keys())[0]]['labels']
    horiz  = (f"{MESES[int(labels[0][:2])-1]}/20{labels[0][3:]} a "
              f"{MESES[int(labels[-1][:2])-1]}/20{labels[-1][3:]}")

    seco  = linha['anom_pct'] < 0
    cor   = SECA if seco else VERDE
    sinal = 'abaixo' if seco else 'acima'

    assunto = (f"Clima Operacional Norte do Tocantins — {NOME_PT[central]} · "
               f"{num(linha['total12m'])} mm ({'+' if not seco else '−'}"
               f"{num(abs(linha['anom_pct']),1)}%)")

    # ── versão texto puro (fallback) ────────────────────────────────────
    texto = f"""Atualização do dashboard climático — {HOJE.strftime('%d/%m/%Y')}

CENÁRIO CENTRAL: {NOME_PT[central]}
Horizonte: {horiz}

  Precipitação projetada .... {num(linha['total12m'])} mm ({sinal} da média de {num(media)} mm)
  Anomalia .................. {'+' if not seco else '−'}{num(abs(linha['anom_pct']),1)}%
  Probabilidade de ano seco . {num(linha['p_seca'],1)}%
  Déficit hídrico ........... {def_c} mm (climatologia: {def_clim} mm)
  Meses com solo esgotado ... {n_crit} (climatologia: {n_clim})

MONITORAMENTO ENSO
  Niño 3.4 semanal .......... {meta.get('nino34_semana','n/d')}
  ONI ....................... {meta.get('oni_mensal','n/d')}
  CPC ....................... {meta.get('cpc_status','n/d')} (emissão {meta.get('cpc_emissao','n/d')})

Em anexo: relatório executivo (2 páginas) e o dashboard interativo.
{f'Dashboard online: {pages_url}' if pages_url else ''}

Próxima atualização automática: {meta.get('dash_proxima','dia 21 do mês seguinte')}
--
Mensagem gerada automaticamente pelo pipeline de clima operacional.
"""

    # ── versão HTML ─────────────────────────────────────────────────────
    def kpi(rot, val, destaque=False):
        return (f'<tr>'
                f'<td style="padding:7px 14px 7px 0;color:#555;font-size:13px;'
                f'border-bottom:1px solid #eee">{rot}</td>'
                f'<td style="padding:7px 0;font-size:13px;font-weight:600;'
                f'color:{cor if destaque else "#222"};border-bottom:1px solid #eee;'
                f'text-align:right">{val}</td></tr>')

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f6f7f6">
<div style="max-width:620px;margin:0 auto;padding:26px 22px;background:#fff;
            font-family:Segoe UI,Calibri,Arial,sans-serif;color:#222">

  <div style="border-bottom:3px solid {VERDE};padding-bottom:12px;margin-bottom:20px">
    <div style="font-size:11px;letter-spacing:1.6px;color:#3E7D52;font-weight:700">
      SINOBRAS FLORESTAL · PLANEJAMENTO E OPERAÇÕES</div>
    <div style="font-size:20px;font-weight:700;color:{VERDE};margin-top:4px">
      Clima Operacional — Norte do Tocantins</div>
    <div style="font-size:12px;color:#666;margin-top:3px">
      Horizonte {horiz} · Emissão {HOJE.strftime('%d/%m/%Y')}</div>
  </div>

  <div style="background:#F2F6F3;border-left:4px solid {cor};padding:13px 16px;
              margin-bottom:20px">
    <div style="font-size:12px;color:#555">Cenário central</div>
    <div style="font-size:17px;font-weight:700;color:{cor};margin-top:2px">
      {NOME_PT[central]}</div>
    <div style="font-size:13px;color:#444;margin-top:6px">
      {num(linha['total12m'])} mm projetados —
      <strong>{num(abs(linha['anom_pct']),1)}% {sinal}</strong> da média histórica
      de {num(media)} mm.</div>
  </div>

  <table style="width:100%;border-collapse:collapse;margin-bottom:22px">
    {kpi('Probabilidade de ano seco', f"{num(linha['p_seca'],1)}%", seco)}
    {kpi('Déficit hídrico anual', f"{def_c} mm <span style='color:#888;font-weight:400'>(clim. {def_clim} mm)</span>")}
    {kpi('Meses com solo esgotado', f"{n_crit} <span style='color:#888;font-weight:400'>(clim. {n_clim})</span>")}
    {kpi('Niño 3.4 semanal', meta.get('nino34_semana','n/d'))}
    {kpi('ONI', meta.get('oni_mensal','n/d'))}
    {kpi('Status CPC', meta.get('cpc_status','n/d'))}
  </table>

  <div style="font-size:13px;color:#444;line-height:1.6;margin-bottom:20px">
    Seguem em anexo o <strong>relatório executivo</strong> (2 páginas) e o
    <strong>dashboard interativo</strong>.
    {f'<br>Versão online sempre atualizada: <a href="{pages_url}" style="color:{VERDE}">{pages_url}</a>' if pages_url else ''}
  </div>

  <div style="border-top:1px solid #e3e3e3;padding-top:12px;font-size:11px;
              color:#888;line-height:1.5">
    Próxima atualização automática: {meta.get('dash_proxima','dia 21 do mês seguinte')}.<br>
    Mensagem gerada automaticamente pelo pipeline de clima operacional.
    Cenário central classificado pelo pico projetado do Niño 3.4
    ({num(d['iri_pico'],2).replace('.',',')} °C).
  </div>
</div></body></html>"""

    return assunto, texto, html


# ══════════════════════════════════════════════════════════════════════════
# Anexos
# ══════════════════════════════════════════════════════════════════════════
def anexar(msg, caminho: Path, nome=None):
    tipo, _ = mimetypes.guess_type(caminho.name)
    maintype, subtype = (tipo or 'application/octet-stream').split('/', 1)
    msg.add_attachment(caminho.read_bytes(), maintype=maintype,
                       subtype=subtype, filename=nome or caminho.name)


def preparar_anexos(msg, zipar_html: bool):
    anexos = []

    if RELATORIO.exists():
        nome = f'Relatorio-Executivo-Clima-{date.today():%Y-%m}.docx'
        anexar(msg, RELATORIO, nome)
        anexos.append((nome, RELATORIO.stat().st_size))
    else:
        print('  ⚠ relatório não encontrado — seguindo sem ele')

    if DASHBOARD.exists():
        if zipar_html:
            # .html costuma ser bloqueado por filtro de e-mail corporativo
            destino = ROOT / 'dashboard.zip'
            with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(DASHBOARD, f'dashboard-clima-{date.today():%Y-%m}.html')
            nome = f'Dashboard-Clima-{date.today():%Y-%m}.zip'
            anexar(msg, destino, nome)
            anexos.append((nome, destino.stat().st_size))
            destino.unlink()
        else:
            nome = f'dashboard-clima-{date.today():%Y-%m}.html'
            anexar(msg, DASHBOARD, nome)
            anexos.append((nome, DASHBOARD.stat().st_size))
    else:
        print('  ⚠ dashboard não encontrado — seguindo sem ele')

    return anexos


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════
def main():
    HOJE = date.today()
    print(f"\n{'='*55}")
    print(f"  ENVIO POR E-MAIL — {HOJE.strftime('%d/%m/%Y')}")
    print(f"{'='*55}")

    dry = env('DRY_RUN', '') in ('1', 'true', 'True')

    destinatarios = [e.strip() for e in (env('MAIL_TO', '') or '').split(',') if e.strip()]
    copias        = [e.strip() for e in (env('MAIL_CC', '') or '').split(',') if e.strip()]

    if not destinatarios and not dry:
        print('  ⚠ MAIL_TO não definido — envio ignorado')
        return 0

    try:
        d = carregar()
    except FileNotFoundError as e:
        print(f'  ❌ dados ausentes: {e}')
        return 1

    pages_url = env('PAGES_URL', '')
    assunto, texto, html = montar_corpo(d, pages_url)

    remetente = env('MAIL_FROM') or env('SMTP_USER', '')
    msg = EmailMessage()
    msg['Subject'] = assunto
    msg['From']    = remetente
    msg['To']      = ', '.join(destinatarios) or remetente
    if copias:
        msg['Cc'] = ', '.join(copias)
    msg.set_content(texto)
    msg.add_alternative(html, subtype='html')

    zipar = env('ZIPAR_HTML', 'true').lower() in ('1', 'true', 'sim')
    anexos = preparar_anexos(msg, zipar)

    total_kb = sum(t for _, t in anexos) / 1024
    print(f'\n  Assunto : {assunto}')
    print(f'  Para    : {", ".join(destinatarios) or "(nenhum)"}')
    if copias:
        print(f'  Cópia   : {", ".join(copias)}')
    print(f'  Anexos  :')
    for nome, tam in anexos:
        print(f'            {nome} ({tam/1024:.0f} KB)')
    print(f'  Total   : {total_kb:.0f} KB')

    if dry:
        print('\n  🧪 DRY_RUN ativo — mensagem montada, nada foi enviado')
        print(f"{'='*55}\n")
        return 0

    host = env('SMTP_HOST', obrigatorio=True)
    port = int(env('SMTP_PORT', '587'))
    user = env('SMTP_USER', obrigatorio=True)
    senha = env('SMTP_PASS', obrigatorio=True)

    print(f'\n  Conectando em {host}:{port}…')
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
                s.login(user, senha)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                s.ehlo(); s.starttls(context=ctx); s.ehlo()
                s.login(user, senha)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        print('  ❌ falha de autenticação — verifique SMTP_USER/SMTP_PASS.')
        print('     Em contas com 2FA é necessário usar uma senha de aplicativo.')
        return 1
    except Exception as e:
        print(f'  ❌ falha no envio: {type(e).__name__}: {e}')
        return 1

    print(f'  ✅ enviado para {len(destinatarios) + len(copias)} destinatário(s)')
    print(f"{'='*55}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
