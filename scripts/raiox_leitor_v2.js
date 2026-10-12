// raiox_leitor_v2.js — leitor das páginas "Prescrição | Análise de Performance" e "Demanda | Análise de
// Concorrentes" do Raio X, na versão que aguenta a aba em segundo plano e a troca de Período (meses antigos).
// Mesmo formato de saída do raiox_leitor.js (window.__res → __clipAll → salvar_leitura_mercado.ps1).
//
// Uso: colar inteiro num javascript_exec. Antes de cada job: Linha/UGN por clique real, lista de marcas
// renderizada, popup "Analisar por" aberto uma vez e popup do Período ABERTO (clique real).
//   window.__marcar()                       // antes de mexer no FILTRO: guarda a tabela atual
//   window.__job({ tipo:'RX'|'DEM', linha, regional, marcas:[...], analises:['GDU | Setor','GDU | Distrital'],
//                  periodos:[{sel:'2026-05',tok:'[mai/26]',suf:'MAI'}, ...] })
//   window.__js  → { running, log }
// Na prática (leitura de ABR/MAI em out/2026): o clique sintético NÃO desmarca o mês antigo do Período.
// Trocar o mês por clique real (marcar o novo, forçar um quadro com zoom, desmarcar o antigo) e passar
// UM mês por job em `periodos`. Marca e "Analisar por" trocam bem por clique sintético, mas com a aba em
// segundo plano a tabela congela: intercalar um zoom/screenshot a cada ~20 s enquanto o job roda.
// OZIVY antes de jun/26 não tem linha "(EMS)" na Demanda: usar tipo 'DEMX' (pula essa checagem) e
// renomear os arquivos DEMX_* para DEM_* antes de ingerir.
// Só grava uma leitura se a tabela MUDOU em relação à de antes da última troca (marca, analisar ou mês),
// o cabeçalho bate com o "Analisar por", o título mostra o mês e a marca do seletor é a pedida.

(() => {
  const w = new Worker(URL.createObjectURL(new Blob(['onmessage=e=>setTimeout(()=>postMessage(e.data[0]),e.data[1])'])));
  let seq = 0; const pend = {};
  w.onmessage = (e) => { const f = pend[e.data]; delete pend[e.data]; if (f) f(); };
  const sleep = (ms) => new Promise((r) => { const id = ++seq; pend[id] = r; w.postMessage([id, ms]); });
  window.__wsleep = sleep;

  const rest = () => [...document.querySelectorAll('.slicer-restatement')].map((e) => e.innerText.trim());
  const marcaAtual = () => rest().find((t) => /\(mercado\)/.test(t)) || '';
  const perAtual = () => rest().find((t) => /^(Último Mês|20\d\d-\d\d|Seleções múltiplas)$/.test(t)) || '';
  const anAtual = () => rest().find((t) => /^GDU \|/.test(t)) || '';
  const titulo = () => {
    const e = [...document.querySelectorAll('div,span,p')].find((x) => x.children.length === 0 && /no período de/.test(x.textContent));
    return e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  };
  const util = (h) => h && h !== '|' && h !== 'Seleção de Linha' && h !== "'";
  const grid = () => [...document.querySelectorAll('[role=grid]')].find((g) => [...g.querySelectorAll('[role=columnheader]')].some((h) => h.innerText.trim() === 'Penetração'));
  const hdr = (g) => [...g.querySelectorAll('[role=columnheader]')].map((e) => e.innerText.trim()).filter(util);
  const linhas = (g) => {
    const out = new Map();
    g.querySelectorAll('[role=row]').forEach((r) => {
      const i = parseInt(r.getAttribute('aria-rowindex'));
      const c = [...r.querySelectorAll('[role=rowheader],[role=gridcell]')].map((e) => e.innerText.split('\n')[0].trim()).filter((v) => !(v === '' || v === 'Selecionar Linha'));
      if (c.length > 1) out.set(i, c);
    });
    return out;
  };
  // assinatura: nº de linhas + cabeçalho + as linhas visíveis (inclui a de Total, que fica fixa no rodapé)
  const sig = () => { const g = grid(); return g ? g.getAttribute('aria-rowcount') + '#' + hdr(g)[0] + '#' + [...linhas(g).values()].map((c) => c.join('|')).join(';') : ''; };
  const ler = async () => {
    const g = grid(), total = parseInt(g.getAttribute('aria-rowcount')), sc = g.querySelector('.mid-viewport'), rows = new Map();
    for (let pass = 0; pass < 5 && rows.size < total - 1; pass++) {
      const step = pass === 0 ? 240 : 110;
      for (let y = 0; y <= sc.scrollHeight; y += step) {
        sc.scrollTop = y; sc.dispatchEvent(new Event('scroll', { bubbles: true }));
        await sleep(600);
        linhas(g).forEach((v, k) => rows.set(k, v));
        if (rows.size >= total - 1) break;
      }
    }
    sc.scrollTop = 0; sc.dispatchEvent(new Event('scroll', { bubbles: true }));
    await sleep(400);
    return { hdr: hdr(g), expected: total - 1, slicers: rest(), titulo: titulo(), rows: [...rows.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]) };
  };
  const item = (t) => [...document.querySelectorAll('.slicerItemContainer')].find((e) => e.innerText.trim() === t);
  const sclick = (el) => {
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + r.height / 2, view: window, button: 0 };
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) el.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, o));
  };
  window.__marcasRenderizadas = () => [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].map((e) => e.innerText.trim());
  window.__estado = () => ({ marca: marcaAtual(), an: anAtual(), per: perAtual(), titulo: titulo(), sig: sig().slice(0, 150) });
  window.__sig = sig;
  window.__marcar = () => { window.__antes = sig(); return window.__antes.slice(0, 80); };

  const setPeriodo = async (novo) => {
    const atual = perAtual();
    if (atual === novo) return false;
    if (atual === 'Seleções múltiplas') throw new Error('periodo em selecao multipla');
    if (!item(novo) || !item(atual)) throw new Error('item de periodo ausente (popup fechado?): ' + novo + ' / ' + atual);
    sclick(item(novo));
    for (let i = 0; i < 240 && perAtual() === atual; i++) await sleep(500);
    if (perAtual() === atual) throw new Error('periodo nao marcou ' + novo);
    // UM clique só para desmarcar o antigo. Com a aba em segundo plano o texto do seletor só muda quando
    // o Chrome desenha um quadro (um zoom/screenshot de fora força isso): clicar de novo "para garantir"
    // marcaria o mês outra vez. Por isso a espera é longa e quem acompanha o job deve intercalar zooms.
    sclick(item(atual));
    for (let i = 0; i < 240 && perAtual() !== novo; i++) await sleep(500);
    if (perAtual() !== novo) throw new Error('periodo nao aplicou: ' + perAtual());
    return true;
  };

  window.__res = window.__res || {};
  window.__saved = window.__saved || {};
  window.__clipAll = async (tag) => {
    const items = Object.values(window.__res).filter((r) => !window.__saved[r.name]);
    try { await navigator.clipboard.writeText(JSON.stringify({ tag, items })); return 'ok ' + tag + ': ' + items.length + ' tabelas'; } catch (e) { return 'ERR ' + e; }
  };
  window.__markSaved = () => { Object.keys(window.__res).forEach((k) => (window.__saved[k] = 1)); return Object.keys(window.__saved).length; };

  window.__job = async ({ tipo, linha, regional, marcas, analises, periodos }) => {
    window.__js = { running: true, log: [] };
    const L = (s) => window.__js.log.push(s);
    let antes = window.__antes || null, ordem = periodos.slice();
    window.__antes = null;
    const nomeDe = (m, an, suf) => tipo + '_' + m.replace(/ /g, '_') + '_' + linha + '_' + regional + '_' + (an.endsWith('Setor') ? 'SETOR' : 'DISTRITAL') + '_' + suf;
    try {
      for (const m of marcas) {
        const alvo = 'MARCAS CHAVES ' + linha + ' (grupo) + ' + m + ' (mercado)';
        if (analises.every((an) => ordem.every((p) => window.__res[nomeDe(m, an, p.suf)]))) { L('ja ' + m); continue; }
        if (marcaAtual() !== alvo) {
          const el = [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].find((e) => e.innerText.trim() === m);
          if (!el) { L('FALHA marca nao renderizada ' + m); continue; }
          antes = sig();
          sclick(el);
          for (let i = 0; i < 90 && marcaAtual() !== alvo; i++) await sleep(500);
        }
        if (marcaAtual() !== alvo) { L('FALHA marca ' + m + ': ' + marcaAtual()); continue; }
        for (const an of analises) {
          if (ordem.every((p) => window.__res[nomeDe(m, an, p.suf)])) continue;
          if (anAtual() !== an) {
            const it = item(an);
            if (!it) { L('FALHA analisar nao renderizado ' + an); continue; }
            antes = sig();
            sclick(it);
            for (let i = 0; i < 90 && anAtual() !== an; i++) await sleep(500);
            if (anAtual() !== an) { L('FALHA analisar ' + an + ': ' + anAtual()); continue; }
          }
          for (const { sel, tok, suf } of ordem) {
            const name = nomeDe(m, an, suf);
            if (window.__res[name]) continue;
            const a0 = sig();
            if (await setPeriodo(sel)) antes = a0; // falha aqui aborta o job: não seguir com o mês errado
            try {
              let ok = false, prev = '', estavel = 0;
              for (let i = 0; i < 180; i++) {
                const s = sig(), g = grid();
                if (s && s !== antes && g && hdr(g)[0] === an && titulo().includes('de ' + tok + ' ') && linhas(g).size > 0) {
                  if (s === prev) { if (++estavel >= 3) { ok = true; break; } } else { estavel = 0; prev = s; }
                } else { estavel = 0; prev = ''; }
                await sleep(1000);
              }
              if (!ok) throw new Error('tabela nao atualizou: ' + (grid() ? hdr(grid())[0] : '?') + ' | ' + titulo());
              const r = await ler();
              if (r.rows.length !== r.expected) throw new Error('linhas ' + r.rows.length + '/' + r.expected);
              if (!r.titulo.includes('de ' + tok + ' ') || r.hdr[0] !== an || marcaAtual() !== alvo || perAtual() !== sel) throw new Error('estado mudou durante a leitura');
              if (sig() !== prev) throw new Error('tabela mudou durante a leitura');
              if (tipo === 'DEM' && !r.rows.some((x) => (x[1] || '').replace(/ /g, ' ').toUpperCase() === m + ' (EMS)')) throw new Error('produto da marca nao aparece (tabela de outra marca?)');
              r.name = name; r.slicers[0] = alvo;
              window.__res[name] = r; antes = null;
              L('ok ' + name + ' ' + r.rows.length);
            } catch (e) { L('ERRO ' + name + ': ' + e.message); antes = sig(); }
          }
          ordem.reverse(); // serpentina: evita uma troca de mês a cada troca de "Analisar por"/marca
        }
      }
    } catch (e) { L('ABORTOU: ' + e.message); }
    window.__js.running = false;
  };

  return 'leitor v2 instalado';
})();
