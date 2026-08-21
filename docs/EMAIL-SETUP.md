# Envio automático por e-mail

O passo 5 do workflow envia o dashboard e o relatório executivo por e-mail
após cada atualização. Ele só roda se o secret `SMTP_HOST` estiver
configurado — sem isso, o passo é ignorado e a publicação segue normalmente.

## Configurar os secrets

No GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Obrigatório | Exemplo |
|---|---|---|
| `SMTP_HOST` | sim | `smtp.office365.com` |
| `SMTP_PORT` | não (padrão 587) | `587` |
| `SMTP_USER` | sim | `dashboard@sinobras.com.br` |
| `SMTP_PASS` | sim | senha de aplicativo |
| `MAIL_TO` | sim | `diretoria@sinobras.com.br, pcp@sinobras.com.br` |
| `MAIL_FROM` | não | usa `SMTP_USER` se vazio |
| `MAIL_CC` | não | `florestal@sinobras.com.br` |

Vários destinatários vão separados por vírgula, no mesmo secret.

## Servidores comuns

| Provedor | Host | Porta |
|---|---|---|
| Microsoft 365 / Outlook | `smtp.office365.com` | 587 |
| Google Workspace / Gmail | `smtp.gmail.com` | 587 |
| Servidor próprio (SSL) | — | 465 |

## Senha de aplicativo

Contas com autenticação em dois fatores **não aceitam a senha normal** em SMTP.
É preciso gerar uma senha de aplicativo:

- **Google:** Conta Google → Segurança → Verificação em duas etapas → Senhas de app
- **Microsoft 365:** pode exigir liberação do SMTP AUTH pelo administrador do
  tenant (`Set-CASMailbox -SmtpClientAuthenticationDisabled $false`)

Se o TI bloquear SMTP autenticado, a alternativa é usar um serviço
transacional (SendGrid, Amazon SES, Mailgun) — a configuração é a mesma,
mudando apenas host, usuário e senha.

## Anexo do dashboard

O `index.html` vai **compactado em .zip** por padrão, porque muitos filtros
corporativos bloqueiam ou removem anexos `.html`. Para anexar o HTML direto,
altere `ZIPAR_HTML` para `'false'` no workflow.

O corpo da mensagem também traz o link do GitHub Pages, que é a forma mais
confiável de acesso — não depende de anexo passar pelo filtro.

## Testar sem enviar

```bash
DRY_RUN=1 MAIL_TO="teste@exemplo.com" python scripts/enviar_email.py
```

Monta a mensagem, lista os anexos e o tamanho total, sem conectar ao servidor.

## Testar o envio real

Rode o workflow manualmente em **Actions → Run workflow** depois de cadastrar
os secrets. O log do passo mostra assunto, destinatários e anexos.
Falhas de envio não derrubam a execução: o dashboard já foi publicado antes
desse passo.
