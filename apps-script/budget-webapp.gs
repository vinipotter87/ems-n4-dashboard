/**
 * Web App de gravação da aba "budget_lancamentos" (página Budget do dashboard).
 *
 * Por que isso existe: o dashboard inteiro só LÊ do Google Sheets via API key
 * (chave pública, somente leitura). Não dá pra escrever com só a API key, e
 * não dá pra usar o service account (credentials.json) direto do navegador —
 * a chave privada dele vazaria pra qualquer visitante do GitHub Pages.
 * Este Apps Script roda DENTRO da conta Google do Vinicius (sem expor nenhuma
 * chave privada) e expõe um endpoint HTTP que o budget.html chama por fetch()
 * pra gravar/editar/excluir lançamentos direto na planilha.
 *
 * COMO IMPLANTAR (uma vez só):
 * 1. Abra a planilha do ems-n4-dashboard no Google Sheets.
 * 2. Menu Extensões → Apps Script.
 * 3. Apague o conteúdo de Code.gs e cole este arquivo inteiro.
 * 4. IMPORTANTE — troque TOKEN abaixo por um valor secreto só seu (uma
 *    string aleatória qualquer). NÃO deixe o texto de exemplo: esse valor
 *    não deve nunca ser commitado neste repositório (ele é público), então
 *    troque aqui, dentro do editor do Apps Script, e guarde só com você.
 * 5. Implantar → Nova implantação → tipo "App da Web".
 *    - Executar como: Eu (sua conta)
 *    - Quem pode acessar: Qualquer pessoa
 * 6. Autorize o acesso quando o Google pedir (é a sua própria planilha).
 * 7. Copie a "URL do app da Web" gerada. Depois, edite o arquivo
 *    docs/config.json do dashboard *localmente* (não peça pra IA fazer
 *    isso — commitar um token novo é bloqueado por segurança) e adicione:
 *      "budget_webapp_url": "<a URL que você copiou>",
 *      "budget_token": "<o mesmo valor que você colocou no TOKEN acima>"
 *    Depois é só commitar e dar push você mesmo (ou pedir pra IA só
 *    revisar o restante do código, sem tocar no valor do token).
 *
 * Sempre que editar este código, use "Gerenciar implantações → Editar →
 * Nova versão" pra publicar a mudança (senão a URL antiga continua rodando
 * o código antigo).
 */

var SHEET_NAME = 'budget_lancamentos';
var TOKEN = 'TROQUE_ESTE_VALOR_POR_UM_SEGREDO_SEU'; // NUNCA commite o valor real deste token
var HEADERS = ['id', 'gd', 'linha', 'produto', 'crm', 'medico', 'valor', 'acao', 'data', 'criadoEm', 'editado'];

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return resposta({ ok: false, erro: 'JSON inválido' });
  }

  if (body.token !== TOKEN) {
    return resposta({ ok: false, erro: 'não autorizado' });
  }

  var sheet = pegarAba();
  var acao = body.acao;

  if (acao === 'add') {
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

function pegarAba() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADERS);
  }
  return sheet;
}

function encontrarLinha(sheet, id) {
  var valores = sheet.getRange('A2:A' + sheet.getLastRow()).getValues();
  for (var i = 0; i < valores.length; i++) {
    if (String(valores[i][0]) === String(id)) return i + 2; // +2: pula header e é 1-indexado
  }
  return -1;
}

function resposta(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
