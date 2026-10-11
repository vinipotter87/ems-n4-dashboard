// raiox_leitor_rxconc.js — leitura da página "Prescrição | Análise de Concorrentes" do Raio X
// (share de prescrição de cada marca do mercado: M. Share Anterior, M. Share Atual, Penetração).
// Colar inteiro num javascript_exec da aba. Depois window.__rc({...}) dispara o job e
// window.__rcst mostra o andamento. As leituras ficam em window.__res (mesmo formato do
// raiox_leitor.js) e saem pelo window.__clipAll(tag) + salvar_leitura_mercado.ps1.
//
// Esta página só tem a dimensão produto: o território vem do bloco FILTRO (Linha, UGN e
// Distrital), que só aceita clique REAL. Por isso o job roda um território por vez:
// marque Linha/UGN (e o distrito, se for o caso), abra o popup do Período e chame __rc.

(() => {
  // espera que não é estrangulada com a aba em segundo plano
  const w = new Worker(URL.createObjectURL(new Blob(['onmessage=e=>setTimeout(()=>postMessage(e.data[0]),e.data[1])'])));
  let seq = 0; const pend = {};
  w.onmessage = (e) => { const f = pend[e.data]; delete pend[e.data]; if (f) f(); };
  const sleep = (ms) => new Promise((r) => { const id = ++seq; pend[id] = r; w.postMessage([id, ms]); });
  window.__wsleep = sleep;

  const rest = () => [...document.querySelectorAll('.slicer-restatement')].map((e) => e.innerText.trim());
  const marcaAtual = () => rest().find((t) => /\(mercado\)/.test(t)) || '';
  const perAtual = () => rest().find((t) => /^(Último Mês|20\d\d-\d\d|Seleções múltiplas)$/.test(t)) || '';
  const titulo = () => {
    const e = [...document.querySelectorAll('div,span,p')].find((x) => x.children.length === 0 && /no período de/.test(x.textContent));
    return e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  };
  const grid = () => [...document.querySelectorAll('[role=grid]')].find((g) => [...g.querySelectorAll('[role=columnheader]')].some((h) => h.innerText.trim() === 'Mercado | Produto'));
  const linhas = (g) => {
    const out = new Map();
    g.querySelectorAll('[role=row]').forEach((r) => {
      const i = parseInt(r.getAttribute('aria-rowindex'));
      const c = [...r.querySelectorAll('[role=rowheader],[role=gridcell]')].map((e) => e.innerText.split('\n')[0].trim()).filter((v) => !(v === '' || v === 'Selecionar Linha' || v === '|'));
      if (c.length > 1) out.set(i, c);
    });
    return out;
  };
  const sig = () => { const g = grid(); return g ? g.getAttribute('aria-rowcount') + '#' + [...linhas(g).values()].map((c) => c.join('|')).join(';') : ''; };
  const ler = async () => {
    const g = grid(), total = parseInt(g.getAttribute('aria-rowcount')), sc = g.querySelector('.mid-viewport'), rows = new Map();
    for (let pass = 0; pass < 4 && rows.size < total - 1; pass++) {
      for (let y = 0; y <= sc.scrollHeight; y += 110) {
        sc.scrollTop = y; sc.dispatchEvent(new Event('scroll', { bubbles: true }));
        await sleep(600);
        linhas(g).forEach((v, k) => rows.set(k, v));
        if (rows.size >= total - 1) break;
      }
    }
    sc.scrollTop = 0; sc.dispatchEvent(new Event('scroll', { bubbles: true }));
    return { hdr: ['Mercado | Produto', 'M. Share Anterior', 'M. Share Atual', 'Penetração'], expected: total - 1, slicers: rest(), titulo: titulo(), rows: [...rows.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]) };
  };
  const item = (t) => [...document.querySelectorAll('.slicerItemContainer')].find((e) => e.innerText.trim() === t);
  const sclick = (el) => {
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + r.height / 2, view: window, button: 0 };
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) el.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, o));
  };
  window.__marcasRenderizadas = () => [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].map((e) => e.innerText.trim());
  window.__rcEstado = () => ({ marca: marcaAtual(), per: perAtual(), titulo: titulo(), painel: (document.body.innerText.match(/([\d.,]+(?: Mil)?)\s*\n?\s*Painel \(cad\.\)/) || [])[1], sig: sig().slice(0, 160) });

  // troca o Período guiando-se só pelo texto do seletor (as marcações do popup ficam defasadas)
  const setPeriodo = async (novo) => {
    const atual = perAtual();
    if (atual === novo) return;
    if (atual === 'Seleções múltiplas') throw new Error('periodo em selecao multipla');
    const a = item(novo), b = item(atual);
    if (!a || !b) throw new Error('item de periodo ausente (popup fechado?): ' + novo + ' / ' + atual);
    sclick(a);
    for (let i = 0; i < 40 && perAtual() === atual; i++) await sleep(500);
    if (perAtual() === atual) throw new Error('periodo nao marcou ' + novo);
    sclick(b);
    for (let i = 0; i < 40 && perAtual() !== novo; i++) await sleep(500);
    if (perAtual() !== novo) throw new Error('periodo nao aplicou: ' + perAtual());
  };

  window.__res = window.__res || {};
  window.__saved = window.__saved || {};
  window.__clipAll = async (tag) => {
    const items = Object.values(window.__res).filter((r) => !window.__saved[r.name]);
    try { await navigator.clipboard.writeText(JSON.stringify({ tag, items })); return 'ok ' + tag + ': ' + items.length + ' tabelas'; } catch (e) { return 'ERR ' + e; }
  };
  window.__markSaved = () => { Object.keys(window.__res).forEach((k) => (window.__saved[k] = 1)); return Object.keys(window.__saved).length; };

  // Job de um território.
  //   linha 'NEXUS'|'VITAL', regional 'SPI'|'LESTE', escopo 'REGIONAL' ou o código do distrito ('11030100')
  //   marcas ['CONCARDIO', ...] (renderizadas na lista de marcas), periodos [{sel:'2026-08',tok:'[ago/26]',suf:'AGO'}, ...]
  // Só grava uma leitura quando a tabela é DIFERENTE da última lida (troca de território, marca ou mês
  // sempre muda a tabela), o título mostra o mês pedido e o seletor mostra a marca pedida.
  window.__rcSig = sig;
  // Antes de mexer no bloco FILTRO (clique real), chame window.__rcMarcar(): guarda a tabela atual
  // para o job só aceitar a primeira leitura depois que ela mudar.
  window.__rcMarcar = () => { window.__rcAntes = sig(); return window.__rcAntes.slice(0, 80); };
  window.__rc = async ({ linha, regional, escopo, marcas, periodos }) => {
    window.__rcst = { running: true, log: [] };
    const L = (s) => window.__rcst.log.push(s);
    let ordem = periodos.slice(), antes = window.__rcAntes || null;
    window.__rcAntes = null;
    try {
      for (const m of marcas) {
        const alvo = 'MARCAS CHAVES ' + linha + ' (grupo) + ' + m + ' (mercado)';
        if (ordem.every((p) => window.__res['RXC_' + m.replace(/ /g, '_') + '_' + linha + '_' + regional + '_' + escopo + '_' + p.suf])) { L('ja ' + m); continue; }
        if (marcaAtual() !== alvo) {
          const el = [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].find((e) => e.innerText.trim() === m);
          if (!el) { L('FALHA marca nao renderizada ' + m); continue; }
          antes = sig();
          sclick(el);
          for (let i = 0; i < 60 && marcaAtual() !== alvo; i++) await sleep(500);
        }
        if (marcaAtual() !== alvo) { L('FALHA marca ' + m + ': ' + marcaAtual()); continue; }
        for (const { sel, tok, suf } of ordem) {
          const name = 'RXC_' + m.replace(/ /g, '_') + '_' + linha + '_' + regional + '_' + escopo + '_' + suf;
          if (window.__res[name]) { L('ja ' + name); continue; }
          if (perAtual() !== sel) { antes = sig(); await setPeriodo(sel); } // falha aqui aborta o job (não troca de marca com o período errado)
          try {
            let ok = false, prev = '', estavel = 0;
            for (let i = 0; i < 150; i++) {
              const s = sig();
              if (s && s !== antes && titulo().includes('de ' + tok + ' ') && grid() && linhas(grid()).size > 0) {
                if (s === prev) { if (++estavel >= 3) { ok = true; break; } } else { estavel = 0; prev = s; }
              } else { estavel = 0; prev = ''; }
              await sleep(1000);
            }
            if (!ok) throw new Error('tabela nao atualizou: ' + titulo());
            const r = await ler();
            if (r.rows.length !== r.expected) throw new Error('linhas ' + r.rows.length + '/' + r.expected);
            if (!r.titulo.includes('de ' + tok + ' ') || marcaAtual() !== alvo || perAtual() !== sel) throw new Error('estado mudou durante a leitura');
            if (sig() !== prev) throw new Error('tabela mudou durante a leitura');
            r.name = name; r.temMarca = r.rows.some((x) => x[0].replace(/\u00a0/g, ' ').toUpperCase() === m + ' (EMS)');
            window.__res[name] = r; antes = null;
            L('ok ' + name + ' ' + r.rows.length + (r.temMarca ? '' : ' SEM-MARCA'));
          } catch (e) { L('ERRO ' + name + ': ' + e.message); }
        }
        ordem.reverse(); // serpentina: a marca seguinte começa no mês em que a anterior terminou
      }
    } catch (e) { L('ABORTOU: ' + e.message); }
    window.__rcst.running = false;
  };

  return 'leitor rxconc instalado';
})();
