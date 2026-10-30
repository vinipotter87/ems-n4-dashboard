/* rps-regras.js — a regra única de "desvio que exige plano" do Copiloto de RPS.
 *
 * Usada pelo Copiloto (rps.html: deck individual, Histórico do time) e pela
 * página Planos RPS (planos-rps.html: card "Desvios × planos"). Só funções
 * puras sobre as linhas das abas do Sheets e dos snapshots, sem estado: quem
 * chama escolhe o mês de cada fonte (o Copiloto usa ST.d.ref; a Planos RPS,
 * o último mês com dado até o mês fechado). Mudou a meta ou a lista de
 * marcas-chave? Muda aqui, e as duas páginas seguem iguais.
 *
 *   RpsRegras.MARCAS_CHAVE               marcas-chave por linha e a partir de que mês
 *   RpsRegras.marcas(linha, mes)         marcas-chave vigentes no mês
 *   RpsRegras.chaveMarca(mk)             'marca-<MARCA>' (chave do plano no crm)
 *   RpsRegras.fundamentos(r, f, s, px, simulado)
 *       r  = linha de reps_<mês> do setor (prod, q1..q4, cob_painel, q1_q3)
 *       f  = RpsRegras.q13(FAROL_Q13[mês].setores[setor]) ou null
 *       s  = RpsRegras.sobrep(linha de SOBREP_REPS_RAW[mês] do setor) ou null
 *       px = linha de pex_<mês> do setor ou null; simulado = PEX do mês é simulado
 *       → [{nome, valor, meta, desvio, sem, n, fonte, quad?, info?}] (um por indicador de execução;
 *         info = só informativo, nunca é desvio — hoje, a Cobertura Q4)
 *   RpsRegras.cobertura(rows, marcasCh)  rows = produtos_rep_<LINHA>_<mês>
 *       → {marcas, reps:[{setor, nome, m:{MARCA:{cob,cota,real}}, cota, real, cob, gap, abaixo:[{m,cob,falta}]}]}
 *   RpsRegras.exigidos(inds, eu)         planos exigidos de um rep: [['fund','Fundamentos'], ['marca-X','X'], …]
 */
var RpsRegras = (function () {
  var MESES = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ'];
  var MARCAS_CHAVE = {
    NEXUS: [{desde:'JAN', m:['BRAMICAR','BRAMICAR HCT','OLIRE','LYBERDIA']}, {desde:'JUL', m:['CONCARDIO','LYBERDIA','OZIVY']}],
    VITAL: [{desde:'JAN', m:['BRASART HCT','BRASART BCC','LINADIB','LINADIB DUO','BUPIUM XL']}, {desde:'JUL', m:['OZIVY','LINADIB','LINADIB DUO','BUPIUM XL']}]
  };
  function num(v) { var n = parseFloat(String(v).replace(',', '.')); return isNaN(n) ? null : n; }
  function p1(v) { return v === null ? '—' : v.toFixed(1).replace('.', ',') + '%'; }
  function norm(s) { return String(s || '').toUpperCase().trim().replace(/\s+/g, ' '); }

  function marcas(linha, mes) { var out = []; (MARCAS_CHAVE[linha] || []).forEach(function (x) { if (MESES.indexOf(x.desde) <= MESES.indexOf(mes)) out = x.m; }); return out; }
  function chaveMarca(mk) { return 'marca-' + mk.replace(/[^A-Z0-9]+/g, '_'); }

  // Frequência Q1–Q3 (PEX, meta 90%) do Farol da Frequência: por setor e ciclo
  // [médicos Q1–Q3, com frequência, Freq 0, 20, 40, 60, 80, 100, n Q1, cf Q1, n Q2, cf Q2, n Q3, cf Q3]
  function q13(x) {
    if (!x) return null;
    function q(i) { return { n: x[i], cf: x[i + 1], cob: x[i] ? x[i + 1] / x[i] * 100 : null }; }
    return { n: x[0], cf: x[1], painel: x[0], f: x.slice(2, 8), cob: x[0] ? x[1] / x[0] * 100 : null, q: { Q1: q(8), Q2: q(10), Q3: q(12) } };
  }
  // Sobreposição do setor: linha "setor|nome|linha|gd|painel|todas|nv" do snapshot SOBREP_REPS_RAW
  function sobrep(l) {
    if (!l) return null; var x = String(l).split('|');
    return { painel: +x[4], todas: +x[5], nv: +x[6], pNv: +x[4] ? +x[6] / +x[4] * 100 : null, pTd: +x[4] ? +x[5] / +x[4] * 100 : null };
  }

  // Indicadores de execução do representante e se cada um está em desvio
  function fundamentos(r, f, s, px, sim) {
    var out = []; r = r || {};
    function add(nome, v, meta, desvio, fonte) { out.push({ nome: nome, valor: v === null ? '—' : p1(v), meta: meta, desvio: v !== null && desvio, sem: v === null, n: v, fonte: fonte || 'reps' }); }
    var p = num(r.prod); add('Produtividade (MDV)', p, '≥ 100%', p < 100);
    [['q1_q3','Cobertura Q1-Q3 (PEX)'],['q1','Cobertura Q1'],['q2','Cobertura Q2'],['q3','Cobertura Q3'],['cob_painel','Cobertura de painel']].forEach(function (q) { var v = num(r[q[0]]); add(q[1], v, '≥ 90%', v < 90); });
    // Cobertura Q4 é só informativa (decisão do Vinicius, 22/10/2026): aparece no card, mas nunca
    // conta como desvio nem exige plano de Fundamentos — Q4 não é prioridade e não pontua no PEX.
    var q4 = num(r.q4); out.push({ nome: 'Cobertura Q4', valor: q4 === null ? '—' : p1(q4), meta: 'informativo', desvio: false, info: true, sem: q4 === null, n: q4, fonte: 'reps' });
    add('Frequência Q1–Q3 (PEX)', f ? f.cob : null, '≥ 90%', f && f.cob < 90, 'freq');
    add('Sobreposição Clínica × Saúde', s ? s.pNv : null, '≤ 10%', s && s.pNv > 10, 'sob');
    // PEX aparece sempre, com a pontuação e o quadrante (medalha); só conta como desvio em atenção ou crítico
    if (px) out.push({ nome: 'PEX' + (sim ? ' (simulado)' : ''), valor: num(px.pts).toFixed(1).replace('.', ',') + ' pts', meta: 'bronze ou acima', desvio: /ATEN|CR[IÍ]T/i.test(px.medalha), sem: false, quad: px.medalha, n: num(px.pts), fonte: 'pex' });
    else out.push({ nome: 'PEX', valor: '—', meta: 'bronze ou acima', desvio: false, sem: true, n: null, fonte: 'pex' });
    return out;
  }

  // Por rep: cobertura em cada marca-chave e gap em R$ das que estão abaixo de 100%
  function cobertura(rows, ch) {
    var reps = {};
    (rows || []).forEach(function (r) {
      var mk = norm(r.produto); if (ch.indexOf(mk) < 0) return;
      var c = num(r.cota), re = num(r.realizado), o = (reps[r.setor_id] = reps[r.setor_id] || { setor: r.setor_id, nome: r.nome, m: {}, cota: 0, real: 0, gap: 0, abaixo: [] });
      var cob = c ? re / c * 100 : null;
      o.m[mk] = { cob: cob, cota: c, real: re };
      o.cota += c || 0; o.real += re || 0;
      if (cob !== null && cob < 100) { o.gap += c - re; o.abaixo.push({ m: mk, cob: cob, falta: c - re }); }
    });
    return { marcas: ch, reps: Object.keys(reps).map(function (k) { var o = reps[k]; o.cob = o.cota ? o.real / o.cota * 100 : null; return o; }) };
  }

  // Planos que o desvio exige de um rep: um de Fundamentos (qualquer indicador em desvio) e um por marca-chave abaixo de 100%
  function exigidos(inds, eu) {
    var ex = [];
    if ((inds || []).some(function (i) { return i.desvio; })) ex.push(['fund', 'Fundamentos']);
    ((eu && eu.abaixo) || []).forEach(function (d) { ex.push([chaveMarca(d.m), d.m]); });
    return ex;
  }

  return { MESES: MESES, MARCAS_CHAVE: MARCAS_CHAVE, marcas: marcas, chaveMarca: chaveMarca, q13: q13, sobrep: sobrep, fundamentos: fundamentos, cobertura: cobertura, exigidos: exigidos, num: num, p1: p1, norm: norm };
})();
