/**
 * Gate de acesso aos dados restritos do dashboard (atas, planos, budget,
 * tendências) — substitui o antigo budget-webapp.gs.
 *
 * Por que isso existe: o dashboard é um site estático público (GitHub Pages).
 * Até out/2026 a senha das páginas de atas era só visual: a planilha inteira
 * era pública ("qualquer pessoa com o link") e qualquer um lia as abas direto
 * pela API do Sheets, sem passar pela senha. Agora as abas sensíveis ficam
 * numa planilha PRIVADA (só o Vinicius e a service account), e o navegador
 * só chega nelas por este script, que confere a senha ANTES de devolver ou
 * gravar qualquer linha. A senha nunca fica no código nem no repositório.
 *
 * O que o script faz (POST JSON, Content-Type text/plain pra não ter preflight):
 *   {acao:'login', senha}                → {ok, token}   sessão de 6 h
 *   {acao:'ler', token, aba}             → {ok, values}  linhas cruas da aba
 *   {acao:'add'|'edit'|'delete', token, ...campos}  (aba budget_lancamentos,
 *                                          mesmo contrato do web app antigo)
 *   {acao:'sair', token}                 → {ok}
 * Resposta {ok:false, erro:'sessao'} = token inválido/expirado → a página
 * pede a senha de novo.
 *
 * COMO IMPLANTAR (uma vez só) — na planilha PRIVADA, não na pública:
 * 1. Abra a planilha "EMS N4 — Dados restritos" no Google Sheets.
 * 2. Menu Extensões → Apps Script. Apague o Code.gs e cole este arquivo.
 * 3. Engrenagem "Configurações do projeto" → Propriedades do script →
 *    Adicionar propriedade: chave SENHA, valor = a senha (hoje um PIN de 4
 *    dígitos; ver SENHA_MIN abaixo). Salvar. Nunca coloque a senha no
 *    código nem no repositório.
 * 4. Implantar → Nova implantação → tipo "App da Web".
 *    - Executar como: Eu (sua conta)
 *    - Quem pode acessar: Qualquer pessoa
 * 5. Autorize quando o Google pedir (é a sua própria planilha).
 * 6. Copie a "URL do app da Web" e coloque em docs/config.json no campo
 *    "gate_url". Essa URL pode ser commitada: sem a senha ela não serve.
 * 7. Na planilha PÚBLICA antiga: Extensões → Apps Script → Implantar →
 *    Gerenciar implantações → arquivar a implantação do budget-webapp antigo
 *    (o token dele estava público no config.json e ainda gravaria lá).
 *
 * Sempre que editar este código: Implantar → Gerenciar implantações →
 * Editar → Nova versão (senão a URL continua rodando o código antigo).
 * Pra trocar a senha: só mudar a propriedade SENHA (as sessões abertas
 * continuam válidas por até 6 h).
 */

// ID da planilha PRIVADA. Se o projeto foi criado por Extensões → Apps Script
// dentro dela, getActiveSpreadsheet() já resolve; se foi criado avulso em
// script.google.com, abre por este ID (a service account e o dono têm acesso).
var PLANILHA_ID = '1ze0t-BoO9CDUjMQw6ucs5wthTVCoXbBR-9XrML2I8Mk';
var ABA_BUDGET = 'budget_lancamentos';
var HEADERS = ['id', 'gd', 'linha', 'produto', 'crm', 'medico', 'valor', 'acao', 'data', 'criadoEm', 'editado'];
var ABAS_PERMITIDAS = /^(budget_lancamentos|tendencias_[A-Z]{3})$/; // o que o navegador pode ler
var SESSAO_SEG = 6 * 60 * 60;        // 6 h (máximo do CacheService)
// Senha de 4 dígitos por decisão do Vinicius (16/10/2026): fácil pro time, mas são só
// 10 mil combinações. Pra compensar, o bloqueio é duro: 5 erros travam o login por
// 1 hora (pra todo mundo) e cada erro demora 1,5 s. Quem errar 5 vezes de propósito
// tranca o time por 1 hora — é o preço do PIN curto. Pra endurecer: SENHA_MIN = 12.
var MAX_FALHAS = 5, JANELA_SEG = 60 * 60; // 5 senhas erradas → bloqueia 1 h
var SENHA_MIN = 4;
var ATRASO_ERRO_MS = 1500;

function doGet() {
  return resposta({ ok: false, erro: 'use POST' });
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return resposta({ ok: false, erro: 'JSON inválido' });
  }
  var acao = body.acao;
  if (acao === 'login') return login(body);

  var sessao = sessaoValida(body.token);
  if (!sessao) return resposta({ ok: false, erro: 'sessao' });
  if (acao === 'sair') { cache().remove('tok:' + body.token); return resposta({ ok: true }); }
  if (acao === 'ler') return ler(body);
  if (acao === 'add' || acao === 'edit' || acao === 'delete') return gravar(body);
  return resposta({ ok: false, erro: 'ação desconhecida: ' + acao });
}

// ── Sessão ──────────────────────────────────────────────────────────────────

function cache() { return CacheService.getScriptCache(); }

function login(body) {
  var senhaCerta = PropertiesService.getScriptProperties().getProperty('SENHA') || '';
  if (senhaCerta.length < SENHA_MIN) {
    return resposta({ ok: false, erro: 'o gate ainda não tem senha configurada (propriedade SENHA, mínimo ' + SENHA_MIN + ' caracteres)' });
  }
  var falhas = Number(cache().get('falhas') || 0);
  if (falhas >= MAX_FALHAS) return resposta({ ok: false, erro: 'muitas tentativas — aguarde 1 hora' });

  var tentativa = String(body.senha || '');
  if (!iguais(tentativa, senhaCerta)) {
    cache().put('falhas', String(falhas + 1), JANELA_SEG);
    Utilities.sleep(ATRASO_ERRO_MS); // desacelera chute em série
    return resposta({ ok: false, erro: 'senha incorreta' });
  }
  cache().remove('falhas');
  var token = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  cache().put('tok:' + token, '1', SESSAO_SEG);
  return resposta({ ok: true, token: token, expiraEm: SESSAO_SEG });
}

function sessaoValida(token) {
  if (!token || typeof token !== 'string' || token.length < 32) return false;
  var ok = cache().get('tok:' + token);
  if (ok) cache().put('tok:' + token, '1', SESSAO_SEG); // renova a cada uso
  return !!ok;
}

// comparação sem sair cedo no primeiro caractere diferente
function iguais(a, b) {
  var dif = a.length ^ b.length, n = Math.max(a.length, b.length);
  for (var i = 0; i < n; i++) dif |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return dif === 0;
}

// ── Leitura ─────────────────────────────────────────────────────────────────

function ler(body) {
  var aba = String(body.aba || '');
  if (!ABAS_PERMITIDAS.test(aba)) return resposta({ ok: false, erro: 'aba não permitida: ' + aba });
  var sheet = planilha().getSheetByName(aba);
  if (!sheet) return resposta({ ok: true, values: [] }); // mesma semântica do 400 da API: aba inexistente = vazia
  var lastRow = sheet.getLastRow(), lastCol = sheet.getLastColumn();
  if (lastRow < 1 || lastCol < 1) return resposta({ ok: true, values: [] });
  var values = sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();
  return resposta({ ok: true, values: values });
}

// ── Gravação (budget_lancamentos) ───────────────────────────────────────────

function gravar(body) {
  // uma gravação por vez: sem isso, dois envios simultâneos do mesmo id passam
  // juntos pela checagem e ambos gravam
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
  } catch (err) {
    return resposta({ ok: false, erro: 'planilha ocupada, tente de novo' });
  }
  try {
    return executar(body);
  } finally {
    lock.releaseLock();
  }
}

function executar(body) {
  var sheet = pegarAba();
  var acao = body.acao;

  if (acao === 'add') {
    // idempotente: reenvio do mesmo lançamento (retry após timeout) não duplica
    if (encontrarLinha(sheet, body.id) >= 0) return resposta({ ok: true, jaExistia: true });
    sheet.appendRow([
      body.id, body.gd, body.linha, body.produto, body.crm,
      body.medico, body.valor, body.acao_lancamento, body.data, body.criadoEm, 'FALSE'
    ]);
    return resposta({ ok: true });
  }

  if (acao === 'edit') {
    var linha = encontrarLinha(sheet, body.id);
    if (linha < 0) return resposta({ ok: false, erro: 'lançamento não encontrado' });
    sheet.getRange(linha, 2, 1, 9).setValues([[
      body.gd, body.linha, body.produto, body.crm, body.medico,
      body.valor, body.acao_lancamento, body.data, body.criadoEm
    ]]);
    sheet.getRange(linha, 11).setValue('TRUE');
    return resposta({ ok: true });
  }

  if (acao === 'delete') {
    var linhaDel = encontrarLinha(sheet, body.id);
    if (linhaDel < 0) return resposta({ ok: false, erro: 'lançamento não encontrado' });
    sheet.deleteRow(linhaDel);
    return resposta({ ok: true });
  }

  return resposta({ ok: false, erro: 'ação desconhecida: ' + acao });
}

function planilha() {
  return SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(PLANILHA_ID);
}

function pegarAba() {
  var ss = planilha();
  var sheet = ss.getSheetByName(ABA_BUDGET);
  if (!sheet) {
    sheet = ss.insertSheet(ABA_BUDGET);
    sheet.appendRow(HEADERS);
  }
  return sheet;
}

function encontrarLinha(sheet, id) {
  if (sheet.getLastRow() < 2) return -1;
  var valores = sheet.getRange('A2:A' + sheet.getLastRow()).getValues();
  for (var i = 0; i < valores.length; i++) {
    if (String(valores[i][0]) === String(id)) return i + 2; // +2: pula header e é 1-indexado
  }
  return -1;
}

function resposta(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// Zera o contador de senhas erradas (o time ficou travado por 1 h sem querer).
// Rodar pelo editor: escolher "destravar" na lista de funções → Executar.
function destravar() {
  cache().remove('falhas');
  Logger.log('contador de falhas zerado');
}
