/* gate.js — acesso às abas restritas (atas, planos, budget, tendências).
 *
 * Essas abas ficam numa planilha PRIVADA; o navegador não lê nem grava nelas
 * direto. Tudo passa pelo Apps Script de apps-script/gate-webapp.gs (URL em
 * config.json → "gate_url"), que confere a senha no servidor e devolve só o
 * que foi pedido. A senha nunca fica no HTML. A sessão (token) fica em
 * localStorage e vale em todas as abas do navegador por até 6 h (o servidor
 * também expira). Páginas em subpasta definem window.GATE_BASE = '../' antes
 * de carregar este arquivo, pra achar o config.json.
 *
 * Uso nas páginas:
 *   await GATE.garantir('Atas de N4');  // mostra a tela de senha se preciso
 *   var linhas = await GATE.ler('budget_lancamentos'); // [{id, gd, ...}]
 *   await GATE.gravar({acao:'add'|'edit'|'delete', id, gd, ...});
 *   GATE.liberado()  → true quando há sessão nesta aba
 *   GATE.pronto()    → true quando o gate_url está configurado
 */
var GATE = (function () {
  var URL = null, TOKEN = null, CFG = null;
  var CHAVE = 'ems_gate_token';
  function lerGuardado() {
    try { sessionStorage.removeItem(CHAVE); } catch (e) {} // versão anterior guardava por aba
    try {
      var raw = localStorage.getItem(CHAVE); if (!raw) return null;
      var o = JSON.parse(raw);
      if (!o || !o.t || (o.exp && Date.now() > o.exp)) { localStorage.removeItem(CHAVE); return null; }
      return o.t;
    } catch (e) { return null; }
  }
  TOKEN = lerGuardado();

  function guardar(t, seg) {
    TOKEN = t;
    try { if (t) localStorage.setItem(CHAVE, JSON.stringify({ t: t, exp: Date.now() + (seg || 6 * 3600) * 1000 })); else localStorage.removeItem(CHAVE); } catch (e) {}
  }

  // lê config.json uma vez (mesma pasta das páginas) só pra pegar gate_url
  function config() {
    if (CFG) return CFG;
    CFG = fetch((window.GATE_BASE || '') + 'config.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('config.json não encontrado.'); return r.json(); })
      .then(function (c) { URL = c.gate_url || null; return c; })
      .catch(function (e) { CFG = null; throw e; });
    return CFG;
  }

  async function chamar(body, tent) {
    await config();
    if (!URL) throw new Error('Acesso restrito não configurado (gate_url ausente em config.json).');
    tent = tent || 0;
    var r, texto;
    try {
      r = await fetch(URL, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify(body) });
      texto = await r.text();
    } catch (e) {
      if (tent < 2) { await new Promise(function (ok) { setTimeout(ok, 900 * (tent + 1)); }); return chamar(body, tent + 1); }
      throw new Error('Sem resposta do servidor de dados restritos.');
    }
    var resp;
    try { resp = JSON.parse(texto); } catch (e) {
      if (tent < 3) { await new Promise(function (ok) { setTimeout(ok, 900 * (tent + 1)); }); return chamar(body, tent + 1); }
      throw new Error('Resposta inválida do servidor de dados restritos.');
    }
    // De vez em quando o redirecionamento do Apps Script entrega à página a resposta
    // de um GET ("use POST") em vez da do POST que ela fez. É transitório: refaz o POST.
    if (!resp.ok && resp.erro === 'use POST') {
      if (tent < 3) { await new Promise(function (ok) { setTimeout(ok, 900 * (tent + 1)); }); return chamar(body, tent + 1); }
      throw new Error('O servidor de dados restritos não respondeu direito. Clique em Atualizar para tentar de novo.');
    }
    if (!resp.ok && resp.erro === 'sessao') { guardar(null); var err = new Error('Sessão expirada — digite a senha de novo.'); err.sessao = true; throw err; }
    return resp;
  }

  async function entrar(senha) {
    var r = await chamar({ acao: 'login', senha: String(senha || '') });
    if (!r.ok) throw new Error(r.erro || 'senha incorreta');
    guardar(r.token, r.expiraEm);
    return true;
  }

  async function sair() {
    var t = TOKEN; guardar(null);
    if (t) try { await chamar({ acao: 'sair', token: t }); } catch (e) {}
  }

  function paraObjetos(rows) {
    rows = rows || [];
    if (rows.length < 2) return [];
    var h = rows[0];
    return rows.slice(1).map(function (row) { var o = {}; h.forEach(function (k, i) { o[k] = row[i] !== undefined ? row[i] : ''; }); return o; });
  }

  // linhas da aba como objetos {coluna: valor}, igual ao fetchAba das páginas
  async function ler(aba) {
    if (!TOKEN) { var e = new Error('Digite a senha para abrir os dados restritos.'); e.sessao = true; throw e; }
    var r = await chamar({ acao: 'ler', token: TOKEN, aba: aba });
    if (!r.ok) throw new Error(r.erro || 'falha ao ler ' + aba);
    return paraObjetos(r.values);
  }

  // leitura SEM senha: só os combinados das atas de RPS (produto RPS_ATA), pro Copiloto
  async function lerAberto() {
    var r = await chamar({ acao: 'ler_aberto' });
    if (!r.ok) throw new Error(r.erro || 'falha ao ler os combinados');
    return paraObjetos(r.values);
  }

  // payload no contrato do web app: {acao:'add'|'edit'|'delete', id, gd, linha, produto, crm, medico, valor, acao_lancamento, data, criadoEm}
  async function gravar(payload) {
    if (!TOKEN) { var e = new Error('Digite a senha para gravar.'); e.sessao = true; throw e; }
    var env = {}; for (var k in payload) if (k !== 'token') env[k] = payload[k];
    env.token = TOKEN;
    var r = await chamar(env);
    if (!r.ok) throw new Error(r.erro || 'falha desconhecida');
    return r;
  }

  // igual a gravar(), mas devolve a resposta {ok, erro} sem lançar erro em ok:false
  // (páginas que tratam o erro elas mesmas)
  async function enviar(payload) {
    if (!TOKEN) { var e = new Error('Digite a senha para gravar.'); e.sessao = true; throw e; }
    var env = {}; for (var k in payload) if (k !== 'token') env[k] = payload[k];
    env.token = TOKEN;
    return chamar(env);
  }

  // ── Tela de senha ─────────────────────────────────────────────────────────
  var CSS = '.gate-trava{position:fixed;inset:0;z-index:5000;background:rgba(15,23,42,.55);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;padding:16px;font-family:inherit}' +
    '.gate-trava.cheia{background:#ECEDF0;backdrop-filter:none}' +
    '.gate-trava form{background:#fff;border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,.18);padding:28px 30px;width:100%;max-width:360px;text-align:center}' +
    '.gate-trava h2{font-size:17px;font-weight:800;color:var(--brand-d,#0b2a5b);margin:0 0 6px}' +
    '.gate-trava p{font-size:12.5px;color:var(--gray,#6b7280);margin:0 0 16px;line-height:1.5}' +
    '.gate-trava input{width:100%;box-sizing:border-box;border:1.5px solid var(--border,#e5e7eb);border-radius:8px;padding:10px 12px;font-size:15px;text-align:center}' +
    '.gate-trava input:focus{outline:none;border-color:var(--brand,#1d4ed8)}' +
    '.gate-trava button{width:100%;margin-top:12px;background:var(--brand,#1d4ed8);color:#fff;border:none;border-radius:8px;padding:10px;font-size:13px;font-weight:800;cursor:pointer}' +
    '.gate-trava button[disabled]{opacity:.6;cursor:default}' +
    '.gate-trava button.volta{background:transparent;color:var(--gray,#6b7280);margin-top:6px;font-weight:700}' +
    '.gate-trava .err{color:var(--red,#c8102e);font-size:12px;font-weight:700;margin-top:10px;min-height:16px}' +
    '.gate-btn{background:var(--brand,#1d4ed8);color:#fff;border:none;border-radius:8px;padding:7px 12px;font-size:11.5px;font-weight:800;cursor:pointer;white-space:nowrap}';
  var cssOk = false;
  function css() { if (cssOk) return; cssOk = true; var s = document.createElement('style'); s.textContent = CSS; document.head.appendChild(s); }

  var pendente = null;
  // Promessa que resolve true quando a senha é aceita; false se o usuário cancelar
  // (só há "Cancelar" quando opts.cancelavel). opts.cheia = tela inteira opaca
  // (páginas que são 100% restritas); senão é um modal sobre a página.
  function pedirSenha(titulo, opts) {
    opts = opts || {};
    if (pendente) return pendente;
    css();
    pendente = new Promise(function (resolve) {
      var box = document.createElement('div');
      box.className = 'gate-trava' + (opts.cheia ? ' cheia' : '');
      box.innerHTML = '<form autocomplete="off"><h2>🔒 ' + (titulo || 'Acesso restrito') + '</h2>' +
        '<p>' + (opts.texto || 'Digite a senha para abrir.') + '</p>' +
        '<input type="password" autocomplete="current-password" placeholder="senha" autofocus>' +
        '<button type="submit">Entrar</button>' +
        (opts.cancelavel ? '<button type="button" class="volta">' + (opts.rotuloCancelar || 'Agora não') + '</button>' : '') +
        '<div class="err"></div></form>';
      var form = box.querySelector('form'), inp = box.querySelector('input'), bt = box.querySelector('button[type=submit]'), err = box.querySelector('.err');
      function fechar(v) { box.remove(); pendente = null; resolve(v); }
      form.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        var s = inp.value; if (!s) { inp.focus(); return; }
        bt.disabled = true; err.textContent = 'Conferindo…';
        try { await entrar(s); fechar(true); }
        catch (e) { err.textContent = e.message || 'Senha incorreta.'; inp.value = ''; inp.focus(); bt.disabled = false; }
      });
      var volta = box.querySelector('.volta'); if (volta) volta.addEventListener('click', function () { fechar(false); });
      document.body.appendChild(box);
      setTimeout(function () { inp.focus(); }, 30);
    });
    return pendente;
  }

  // tela cheia opaca imediata (sem esperar rede), usada enquanto a sessão guardada é conferida
  function cobrir(titulo) {
    css();
    var box = document.createElement('div');
    box.className = 'gate-trava cheia';
    box.innerHTML = '<form><h2>🔒 ' + (titulo || 'Acesso restrito') + '</h2><p>Conferindo acesso…</p></form>';
    document.body.appendChild(box);
    return box;
  }

  // confere no servidor se o token guardado ainda vale (aba inexistente permitida: resposta vazia e rápida)
  async function validar() {
    if (!TOKEN) return false;
    try { var r = await chamar({ acao: 'ler', token: TOKEN, aba: 'tendencias_ZZZ' }); return !!r.ok; }
    catch (e) { return e.sessao ? false : !!TOKEN; } // falha de rede não derruba a sessão
  }

  async function garantir(titulo, opts) {
    opts = opts || {};
    if (opts.cheia) { // página inteira restrita: cobre já, antes de qualquer carregamento
      if (TOKEN) { var tela = cobrir(titulo); var ok = await validar(); tela.remove(); if (ok) return true; }
      var p = pedirSenha(titulo, opts); config().catch(function () {}); return p;
    }
    try { await config(); } catch (e) {}
    if (!URL) { if (opts.silencioso) return false; throw new Error('Acesso restrito não configurado (gate_url ausente em config.json).'); }
    if (TOKEN) return true;
    return pedirSenha(titulo, opts);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', css); else css();
  return {
    garantir: garantir, pedirSenha: pedirSenha, entrar: entrar, sair: sair, ler: ler, lerAberto: lerAberto, gravar: gravar, enviar: enviar,
    liberado: function () { return !!TOKEN; },
    validar: validar,
    pronto: function () { return !!URL; },
    config: config,
    esqueceu: function () { guardar(null); }
  };
})();
