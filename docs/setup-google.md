# Guia de Setup Google — Service Account + API Key

Faça isso uma vez. Depois é só rodar `pipeline.py` todo mês.

---

## PARTE 1 — Criar o Projeto Google Cloud

1. Acesse: https://console.cloud.google.com
2. Clique em **"Select a project"** → **"New Project"**
3. Nome: `ems-n4-dashboard` → **Create**
4. Certifique-se de que o projeto novo está selecionado no topo

---

## PARTE 2 — Habilitar as APIs

No menu lateral: **APIs & Services → Library**

Buscar e habilitar:
- ✅ **Google Sheets API**
- ✅ **Google Drive API**

---

## PARTE 3 — Criar a Service Account (para o squad escrever nas Sheets)

1. **APIs & Services → Credentials → Create Credentials → Service Account**
2. Nome: `ems-dashboard-sa`
3. Clicar em **"Create and Continue"** (não precisa de papel/role especial)
4. Clicar em **"Done"**
5. Na lista de Service Accounts, clicar na que acabou de criar
6. Aba **"Keys" → Add Key → Create New Key → JSON**
7. Salvar o arquivo `.json` em: `config/service_account.json`

> ⚠️ NUNCA commitar este arquivo. Ele já está no `.gitignore`.

---

## PARTE 4 — Criar a API Key (para o dashboard HTML ler as Sheets)

1. **APIs & Services → Credentials → Create Credentials → API Key**
2. Uma key é gerada automaticamente
3. Clicar em **"Edit API key"** para restringi-la:
   - **Application restrictions**: HTTP referrers
   - Adicionar: `https://SEU_USUARIO.github.io/*`
   - **API restrictions**: Restrict to → Google Sheets API
4. Copiar a key (formato: `AIzaSy...`)
5. Adicionar ao `.env` como `SHEETS_API_KEY=AIzaSy...`

---

## PARTE 5 — Dar acesso à Service Account na sua planilha

Após rodar `python scripts/setup.py` e criar a planilha:

1. Abra a planilha criada no Google Sheets
2. Clique em **"Share"**
3. Adicionar o email da Service Account (formato: `ems-dashboard-sa@ems-n4-dashboard.iam.gserviceaccount.com`)
4. Permissão: **Editor**
5. Clique em **"Share"**

> O email exato da Service Account está no arquivo `config/service_account.json`, campo `client_email`.

---

## PARTE 6 — GitHub Token (para publicar o dashboard)

1. GitHub.com → Settings → Developer settings → Personal Access Tokens → Tokens (classic)
2. **Generate new token (classic)**
3. Nome: `ems-dashboard-deploy`
4. Expiração: 1 ano
5. Selecionar: ✅ `repo` (acesso completo)
6. **Generate token** → copiar o token (começa com `ghp_...`)
7. Adicionar ao `.env` como `GITHUB_TOKEN=ghp_...`

---

## PARTE 7 — Criar o repositório no GitHub

1. github.com → New repository
2. Nome: `ems-n4-dashboard`
3. Visibilidade: **Public** (necessário para GitHub Pages gratuito)
4. Não inicializar com README
5. Criar
6. Adicionar ao `.env`: `GITHUB_REPO=SEU_USUARIO/ems-n4-dashboard`

---

## PARTE 8 — Configurar GitHub Pages

Após o primeiro push (via `python scripts/publish.py`):

1. GitHub → Seu repositório → **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / Folder: `/dashboard`
4. **Save**

URL do dashboard: `https://SEU_USUARIO.github.io/ems-n4-dashboard`

---

## Checklist Final

```
[ ] config/service_account.json salvo
[ ] .env preenchido com todos os campos de .env.example
[ ] python scripts/setup.py rodou sem erros
[ ] SPREADSHEET_ID adicionado ao .env
[ ] SHEETS_API_KEY adicionado ao .env
[ ] Service Account adicionada como Editor na planilha
[ ] GitHub Pages configurado
[ ] python scripts/pipeline.py --mes JAN rodou com sucesso
```

Após o checklist: repita `pipeline.py --mes {MES}` para FEV, MAR e ABR.
A partir do próximo mês, rode apenas uma vez por mês quando os dados chegarem.

---

## PARTE 7 — Área restrita (atas, planos, budget, tendências)

Desde out/2026 as abas sensíveis **não ficam na planilha pública** do dashboard:

| Onde | O quê | Quem lê |
|---|---|---|
| Planilha pública (`SPREADSHEET_ID`) | KPIs, produtos, visitas, CRM, mercado… | qualquer página, via API key (leitura pública) |
| Planilha privada (`SPREADSHEET_ID_RESTRITO`) | `budget_lancamentos` (atas N4/RPS, planos, budget, classificações) e `tendencias_*` | só o Apps Script `apps-script/gate-webapp.gs`, depois de conferir a senha |

A senha antiga das páginas de atas era só visual (hash no HTML e planilha pública):
qualquer um lia as abas direto pela API. Agora o navegador chama o gate
(`config.json` → `gate_url`), que valida a senha **no servidor** e devolve só a aba
pedida; a sessão vale 6 h na aba do navegador (`sessionStorage`). O módulo
compartilhado pelas páginas é `docs/assets/gate.js`.

Deploy do gate: seguir o cabeçalho de `apps-script/gate-webapp.gs` (planilha
**privada** → Extensões → Apps Script → propriedade `SENHA` → implantar como App da
Web → colar a URL em `gate_url`). Senhas por papel, todas em Propriedades do script:
`SENHA` (SPI, abre tudo), `SENHA_LESTE` (só `leste.html` e registros da Leste),
`SENHA_GLEMPA` (só `budget-glempa.html` e os lançamentos GLEMPA / GLEMPA_CLASSIF) e
`SENHA_GRD` (senha pessoal do GRD: a única que abre a página de atas de N4,
`docs/atas-grd-*.html`, que não tem link no dashboard; a senha SPI não abre essa página).
Toda mudança no `.gs` exige publicar uma **nova versão** da implantação (Implantar →
Gerenciar implantações → editar → Nova versão), senão a URL continua rodando o código antigo. Depois, arquivar a implantação antiga do
`budget-webapp` na planilha pública. Nunca voltar `budget_token`/`budget_webapp_url`
para o `config.json`.

Scripts Python que escrevem nessas abas usam `ingest.conectar_sheets_restrito()`
(`subir_atas_n4_notion.py` aqui e `publicar_tendencias.py` no SQUAD N4), que lê
`SPREADSHEET_ID_RESTRITO` do `.env`. A service account precisa ser Editor também
na planilha privada.
