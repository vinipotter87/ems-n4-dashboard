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
