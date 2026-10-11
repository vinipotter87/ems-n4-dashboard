// raiox_leitor.js — funções injetadas na aba do Power BI "Raio X" para ler as tabelas
// de Prescrição e de Demanda sem exportar arquivo. Usado pela task "atualizar-dados-mercado".
//
// Como usar: colar este arquivo inteiro num javascript_exec da aba do relatório (uma vez por
// carregamento da página; trocar de página pelo botão "home" do relatório mantém as funções).
// Depois: window.__run({...}) dispara a leitura em segundo plano e window.__st mostra o andamento.

(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  window.__sleep = sleep;

  // Texto atual de cada seletor suspenso da página, na ordem em que aparecem
  window.__sl = () => [...document.querySelectorAll('.slicer-dropdown-menu')].map((e) => e.innerText.trim());

  // Título da tabela: "... no período de [ago/26] vs [jul/26]"
  window.__titulo = () => {
    const e = [...document.querySelectorAll('div,span,p')].find((x) => x.children.length === 0 && /no período de/.test(x.textContent));
    return e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  };

  // A tabela principal é o único role=grid com cabeçalhos de coluna (os demais são filtros)
  window.__grid = () => [...document.querySelectorAll('[role=grid]')].find((g) => g.querySelector('[role=columnheader]'));
  const colunaUtil = (h) => h && h !== '|' && h !== 'Seleção de Linha' && h !== "'";

  window.__peek = () => {
    const g = window.__grid();
    if (!g) return { h: '', t: '', rc: null };
    const h = [...g.querySelectorAll('[role=columnheader]')].map((e) => e.innerText.trim()).filter(colunaUtil)[0] || '';
    const rows = [...g.querySelectorAll('[role=row]')];
    const last = rows[rows.length - 1];
    return { h, t: last ? last.innerText.replace(/\s+/g, ' ').trim() : '', rc: g.getAttribute('aria-rowcount') };
  };

  // Lê a tabela inteira rolando a área virtualizada e juntando as linhas por aria-rowindex
  window.__rt = async () => {
    const g = window.__grid();
    const total = parseInt(g.getAttribute('aria-rowcount'));
    const rows = new Map();
    const sc = g.querySelector('.mid-viewport');
    const hdr = [...g.querySelectorAll('[role=columnheader]')].map((e) => e.innerText.trim()).filter(colunaUtil);
    const grab = () => g.querySelectorAll('[role=row]').forEach((r) => {
      const i = parseInt(r.getAttribute('aria-rowindex'));
      const c = [...r.querySelectorAll('[role=rowheader],[role=gridcell]')]
        .map((e) => e.innerText.split('\n')[0].trim())
        .filter((v) => !(v === '' || v === 'Selecionar Linha'));
      if (c.length > 1) rows.set(i, c);
    });
    for (let pass = 0; pass < 5 && rows.size < total - 1; pass++) {
      const step = pass === 0 ? 260 : 110;
      for (let y = 0; y <= sc.scrollHeight; y += step) {
        sc.scrollTop = y;
        sc.dispatchEvent(new Event('scroll', { bubbles: true }));
        await sleep(650);
        grab();
        if (rows.size >= total - 1) break;
      }
    }
    sc.scrollTop = 0;
    sc.dispatchEvent(new Event('scroll', { bubbles: true }));
    return {
      hdr, expected: total - 1, slicers: window.__sl(), titulo: window.__titulo(),
      rows: [...rows.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]),
    };
  };

  // Item de um seletor suspenso pelo texto exato (precisa já ter sido renderizado)
  window.__item = (t) => [...document.querySelectorAll('.slicerItemContainer')].find((e) => e.innerText.trim() === t);

  // Clique sintético: funciona em Período, "Analisar por" e na folha da marca.
  // NÃO funciona nos botões do bloco FILTRO (Linha/UGN): esses precisam de clique real.
  window.__sclick = (el) => {
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + r.height / 2, view: window, button: 0 };
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, o));
    }
  };

  // Marcas-folha renderizadas agora na lista suspensa de marcas (a lista é virtualizada)
  window.__marcasRenderizadas = () =>
    [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].map((e) => e.innerText.trim());

  window.__setMarca = async (m) => {
    const el = [...document.querySelectorAll('.slicer-dropdown-popup .slicerItemContainer')].find((e) => e.innerText.trim() === m);
    if (!el) throw new Error('marca nao renderizada: ' + m);
    window.__sclick(el);
    await sleep(6000);
    return window.__sl()[0];
  };

  // Troca o filtro Período para um único mês ("2026-07"). Só funciona com o popup do Período
  // ABERTO por clique real, e exige marcar o mês novo ANTES de desmarcar o antigo.
  // window.__perSel deve refletir o que está marcado agora, ex.: new Set(['Último Mês']).
  window.__setPeriodo = async (idxMenu, m) => {
    if (!window.__perSel.has(m)) {
      const e = window.__item(m);
      if (!e) throw new Error('item de periodo ausente: ' + m);
      window.__sclick(e); window.__perSel.add(m); await sleep(5000);
    }
    for (const x of [...window.__perSel]) {
      if (x !== m) {
        const e = window.__item(x);
        if (!e) throw new Error('item de periodo ausente: ' + x);
        window.__sclick(e); window.__perSel.delete(x); await sleep(5000);
      }
    }
    for (let i = 0; i < 10 && window.__sl()[idxMenu] !== m; i++) await sleep(1000);
    return window.__sl()[idxMenu] === m;
  };

  // Espera a tabela refletir o "Analisar por" e o mês pedidos e, se algo mudou, a linha Total mudar
  window.__aguarda = async (hdr0, tok, antes) => {
    let ok = false;
    for (let i = 0; i < 120; i++) {
      const p = window.__peek();
      if (p.h === hdr0 && window.__titulo().includes(tok) && p.t && (antes === null || p.t !== antes)) { ok = true; break; }
      await sleep(1000);
    }
    if (!ok) {
      const p = window.__peek();
      if (!(p.h === hdr0 && window.__titulo().includes(tok))) throw new Error('tabela nao atualizou: ' + p.h + ' | ' + window.__titulo());
    }
    let prev = '';
    for (let i = 0; i < 20; i++) {
      const p = window.__peek();
      const t = p.t + p.rc;
      if (t === prev) break;
      prev = t;
      await sleep(2500);
    }
  };

  window.__res = window.__res || {};
  window.__saved = window.__saved || {};

  // Copia para a área de transferência as leituras ainda não salvas, com uma etiqueta de conferência
  window.__clipAll = async (tag) => {
    const items = Object.values(window.__res).filter((r) => !window.__saved[r.name]);
    try {
      await navigator.clipboard.writeText(JSON.stringify({ tag, items }));
      return 'ok ' + tag + ': ' + items.map((r) => r.name).join(', ');
    } catch (e) { return 'ERR ' + e; }
  };
  window.__markSaved = () => { Object.keys(window.__res).forEach((k) => (window.__saved[k] = 1)); return Object.keys(window.__saved).length; };

  // Job de leitura em segundo plano.
  //   tipo:      'RX' (Prescrição | Análise de Performance) ou 'DEM' (Demanda | Análise de Concorrentes)
  //   linha:     'NEXUS' | 'VITAL'     regional: 'SPI' | 'LESTE'
  //   marcas:    ['CONCARDIO', ...] — a primeira pode ser a já selecionada; as demais precisam estar renderizadas
  //   analises:  ['GDU | Setor', 'GDU | Distrital'] para RX; ['GDU | Setor'] para DEM
  //   periodos:  [{ sel: null, tok: '[ago/26]', suf: 'AGO' }] — sel null = não mexe no filtro Período
  //              (deixa "Último Mês"); sel '2026-07' troca o filtro (popup do Período aberto)
  //   idxPer:    posição do Período da tabela em __sl(): 5 na página de Prescrição, 4 na de Demanda
  window.__run = async ({ tipo, linha, regional, marcas, analises, periodos, idxPer }) => {
    window.__st = { running: true, log: [] };
    const L = (s) => window.__st.log.push(s);
    let lastTot = null;
    try {
      for (const m of marcas) {
        const alvo = 'MARCAS CHAVES ' + linha + ' (grupo) + ' + m + ' (mercado)';
        if (window.__sl()[0] !== alvo) await window.__setMarca(m);
        if (window.__sl()[0] !== alvo) { L('FALHA marca ' + m + ': ' + window.__sl()[0]); continue; }
        let mudou = true;
        for (const an of analises) {
          if (window.__sl()[1] !== an) {
            const it = window.__item(an);
            if (!it) { L('FALHA analisar ' + an); continue; }
            window.__sclick(it);
            await sleep(4000);
          }
          for (const { sel, tok, suf } of periodos) {
            const name = tipo + '_' + m.replace(/ /g, '_') + '_' + linha + '_' + regional + '_' + (an.endsWith('Setor') ? 'SETOR' : 'DISTRITAL') + '_' + suf;
            try {
              if (sel && window.__sl()[idxPer] !== sel) { await window.__setPeriodo(idxPer, sel); mudou = true; }
              if (sel && window.__sl()[idxPer] !== sel) throw new Error('periodo nao aplicou: ' + window.__sl()[idxPer]);
              await window.__aguarda(an, 'de ' + tok, mudou ? lastTot : null);
              const r = await window.__rt();
              r.name = name;
              if (r.rows.length !== r.expected) throw new Error('linhas ' + r.rows.length + '/' + r.expected);
              if (!r.titulo.includes('de ' + tok) || r.hdr[0] !== an || r.slicers[0] !== alvo) throw new Error('estado mudou durante a leitura');
              window.__res[name] = r;
              lastTot = window.__peek().t;
              mudou = false;
              L('ok ' + name + ' ' + r.rows.length);
            } catch (e) { L('ERRO ' + name + ': ' + e.message); mudou = true; }
          }
          mudou = true;
        }
      }
    } catch (e) { L('ABORTOU: ' + e.message); }
    window.__st.running = false;
  };

  return 'leitor instalado';
})();
