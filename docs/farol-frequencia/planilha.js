// Farol da Frequência — download da estratégia em .xlsx (GD e rep).
// Usa as funções e os dados da página (index.html); o ExcelJS é carregado sob demanda de assets/.

const XL = {
  navy: 'FF1F2D44', gelo: 'FFDFF1FB', linha: 'FFD6E6F0', zebra: 'FFF7FBFE', preencher: 'FFFFF9DB', branco: 'FFFFFFFF',
  grupos: {
    proteger: ['FFFDF3D7', 'FF9A6B00'], conquistar: ['FFFDE9DA', 'FFB5530C'], possivel: ['FFFFF1E6', 'FFB5530C'],
    reconstruir: ['FFFBE3E3', 'FFD23F3F'], garantido: ['FFE3F5EC', 'FF1E9E62'],
  },
  acoes: { manter: ['FFE3F5EC', 'FF1E9E62'], cobrar: ['FFFDF3D7', 'FF9A6B00'], campo: ['FFFDE9DA', 'FFB5530C'], vago: ['FFFBE3E3', 'FFD23F3F'] },
  farol: p => p >= FAROL.verde ? ['FFE3F5EC', 'FF1E9E62'] : p >= FAROL.amarelo ? ['FFFDF3D7', 'FF9A6B00'] : ['FFFBE3E3', 'FFD23F3F'],
};
const FONTE = 'Calibri';

function carregaExcel() {
  if (window.ExcelJS) return Promise.resolve();
  return new Promise((ok, erro) => {
    const sc = document.createElement('script');
    sc.src = 'assets/exceljs.min.js';
    sc.onload = ok; sc.onerror = () => erro(new Error('Não encontrei assets/exceljs.min.js'));
    document.head.appendChild(sc);
  });
}

// HTML da estratégia (o mesmo da tela) → { titulo, lead, itens[] } em texto puro
function textoDe(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const limpa = el => el.textContent.replace(/\s+/g, ' ').trim();
  const blocos = [];
  doc.querySelectorAll('h3').forEach(h => {
    const b = { titulo: limpa(h), lead: '', itens: [] };
    let el = h.nextElementSibling;
    while (el && el.tagName !== 'H3') {
      if (el.tagName === 'P') b.lead = limpa(el);
      if (el.tagName === 'OL') b.itens = [...el.querySelectorAll('li')].map(limpa);
      el = el.nextElementSibling;
    }
    blocos.push(b);
  });
  return blocos;
}
const semTags = html => html.replace(/<small>/g, ' · ').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const nomeArquivo = (...partes) => 'Farol_Frequencia_' + partes.map(p => String(p).normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '')).filter(Boolean).join('_') + '.xlsx';

// ---- Blocos de formatação ---------------------------------------------------
function cabecalhoEMS(ws, titulo, subtitulo, ncol) {
  ws.mergeCells(1, 1, 1, ncol); ws.mergeCells(2, 1, 2, ncol);
  const c1 = ws.getCell(1, 1), c2 = ws.getCell(2, 1);
  c1.value = titulo; c2.value = subtitulo;
  c1.font = { name: FONTE, size: 15, bold: true, color: { argb: XL.branco } };
  c2.font = { name: FONTE, size: 10, color: { argb: 'FFBFE3F8' } };
  [c1, c2].forEach(c => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: XL.navy } }; c.alignment = { vertical: 'middle', indent: 1 }; });
  ws.getRow(1).height = 26; ws.getRow(2).height = 18;
}

// Tabela com cabeçalho navy, zebra, filtro, linha congelada e colunas de preenchimento
function tabela(ws, linhaIni, colunas, linhas, { preencher = [], cores = {} } = {}) {
  const hdr = ws.getRow(linhaIni);
  colunas.forEach((c, i) => {
    const cel = hdr.getCell(i + 1);
    cel.value = c.t;
    cel.font = { name: FONTE, bold: true, color: { argb: XL.branco }, size: 10 };
    cel.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: XL.navy } };
    cel.alignment = { vertical: 'middle', horizontal: c.al || 'left', wrapText: true };
    ws.getColumn(i + 1).width = c.w;
  });
  hdr.height = 30;
  linhas.forEach((vals, r) => {
    const row = ws.getRow(linhaIni + 1 + r);
    vals.forEach((v, i) => {
      const c = colunas[i], cel = row.getCell(i + 1);
      cel.value = v;
      cel.font = { name: FONTE, size: 10, bold: !!c.b };
      cel.alignment = { vertical: 'middle', horizontal: c.al || 'left', wrapText: !!c.wrap };
      if (c.fmt) cel.numFmt = c.fmt;
      cel.border = { bottom: { style: 'thin', color: { argb: XL.linha } } };
      if (r % 2) cel.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: XL.zebra } };
      if (preencher.includes(i)) cel.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: XL.preencher } };
      const cor = cores[i] && cores[i](r, v);
      if (cor) { cel.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: cor[0] } }; cel.font = { ...cel.font, bold: true, color: { argb: cor[1] } }; }
    });
  });
  const fim = linhaIni + Math.max(linhas.length, 1);
  ws.autoFilter = { from: { row: linhaIni, column: 1 }, to: { row: linhaIni, column: colunas.length } };
  ws.views = [{ state: 'frozen', ySplit: linhaIni, showGridLines: false }];
  // um intervalo só: célula a célula o ExcelJS junta os endereços errado e perde as linhas 2–9
  preencher.forEach(i => {
    if (colunas[i].sn && linhas.length) {
      const col = ws.getColumn(i + 1).letter;
      ws.dataValidations.add(`${col}${linhaIni + 1}:${col}${fim}`, { type: 'list', allowBlank: true, formulae: ['"S,N"'],
        showErrorMessage: true, errorTitle: 'Visitou?', error: 'Use S ou N' });
    }
  });
  ws.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0, paperSize: 9,
    margins: { left: 0.4, right: 0.4, top: 0.5, bottom: 0.5, header: 0.2, footer: 0.2 }, printTitlesRow: `${linhaIni}:${linhaIni}` };
  return fim;
}

// Aba de resumo: indicadores + estratégia em texto
function abaResumo(wb, titulo, subtitulo, kpis, blocos) {
  const ws = wb.addWorksheet('Resumo', { properties: { tabColor: { argb: XL.navy } } });
  ws.columns = [{ width: 4 }, { width: 34 }, { width: 22 }, { width: 70 }];
  cabecalhoEMS(ws, titulo, subtitulo, 4);
  let r = 4;
  ws.getCell(r, 2).value = 'Indicadores'; ws.getCell(r, 2).font = { name: FONTE, size: 12, bold: true, color: { argb: XL.navy } };
  r++;
  kpis.forEach(k => {
    const a = ws.getCell(r, 2), b = ws.getCell(r, 3), c = ws.getCell(r, 4);
    a.value = k.lb; b.value = k.v; c.value = k.sb || '';
    a.font = { name: FONTE, size: 10, color: { argb: 'FF5787A2' } };
    b.font = { name: FONTE, size: 12, bold: true, color: { argb: k.cor ? k.cor[1] : XL.navy } };
    c.font = { name: FONTE, size: 10, color: { argb: 'FF5787A2' } };
    if (k.fmt) b.numFmt = k.fmt;
    if (k.cor) b.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: k.cor[0] } };
    b.alignment = { horizontal: 'center' };
    [a, b, c].forEach(x => x.border = { bottom: { style: 'thin', color: { argb: XL.linha } } });
    r++;
  });
  blocos.forEach(bl => {
    r++;
    ws.getCell(r, 2).value = bl.titulo; ws.getCell(r, 2).font = { name: FONTE, size: 12, bold: true, color: { argb: XL.navy } };
    r++;
    if (bl.lead) {
      ws.mergeCells(r, 2, r, 4);
      const c = ws.getCell(r, 2); c.value = bl.lead;
      c.font = { name: FONTE, size: 10.5, italic: true, color: { argb: 'FF1F2D44' } };
      c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: XL.gelo } };
      c.alignment = { wrapText: true, vertical: 'top', indent: 1 };
      ws.getRow(r).height = Math.max(20, Math.ceil(bl.lead.length / 120) * 15 + 6);
      r++;
    }
    bl.itens.forEach((t, i) => {
      ws.getCell(r, 1).value = `${i + 1}.`; ws.getCell(r, 1).font = { name: FONTE, size: 10, bold: true, color: { argb: XL.navy } };
      ws.getCell(r, 1).alignment = { vertical: 'top', horizontal: 'right' };
      ws.mergeCells(r, 2, r, 4);
      const c = ws.getCell(r, 2); c.value = t;
      c.font = { name: FONTE, size: 10 }; c.alignment = { wrapText: true, vertical: 'top' };
      ws.getRow(r).height = Math.max(16, Math.ceil(t.length / 120) * 14 + 4);
      r++;
    });
  });
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1, fitToHeight: 0, paperSize: 9 };
  return ws;
}

// ---- Linhas das abas de médicos ----------------------------------------------
const ordenaMed = (a, b) => a.cod.localeCompare(b.cod) || ORDEM.indexOf(a.g) - ORDEM.indexOf(b.g)
  || (QORD[a.q] || 9) - (QORD[b.q] || 9) || a.nome.localeCompare(b.nome);
const entraEm = m => m.cedo === m.tarde ? ciclo(m.cedo) : `entre ${ciclo(m.cedo)} e ${ciclo(m.tarde)}`;

function abaLista(wb, nome, meds, comRep, cor) {
  const ws = wb.addWorksheet(nome, { properties: { tabColor: { argb: cor } } });
  const cols = [
    ...(comRep ? [{ t: 'Setor', w: 11 }, { t: 'Representante', w: 26 }] : []),
    { t: 'CRM / ID', w: 12 }, { t: 'Médico', w: 34, b: true }, { t: 'Especialidade', w: 20 }, { t: 'Quartil', w: 8, al: 'center' },
    { t: 'Base Zero', w: 9, al: 'center' }, { t: `Visitas ${D.janela}`, w: 11, al: 'center' }, { t: 'Freq.', w: 8, al: 'center', fmt: '0%' },
    { t: 'Grupo', w: 13, al: 'center' }, { t: 'O que fazer', w: 46, wrap: true },
    { t: 'Visitou? (S/N)', w: 10, al: 'center', sn: true }, { t: 'Data', w: 11, al: 'center', fmt: 'dd/mm/yyyy' }, { t: 'Observação', w: 30, wrap: true },
  ];
  const off = comRep ? 2 : 0;
  const linhas = meds.map(m => [
    ...(comRep ? [m.cod, (SET.find(s => s.cod === m.cod) || {}).rep || ''] : []),
    m.id, m.nome, m.esp, m.q, m.b0 ? 'SIM' : '', `${m.real}/${m.obj}`, m.freq / 100,
    GRUPOS[m.g].nome, semTags(oQueFazer(m)), '', null, '',
  ]);
  const gi = off + 7;
  tabela(ws, 1, cols, linhas, { preencher: [off + 9, off + 10, off + 11], cores: { [gi]: r => XL.grupos[meds[r].g] } });
  return ws;
}

// ---- Planilha do GD ---------------------------------------------------------
async function baixarGD() {
  await carregaExcel();
  const d = st.dist, nome = nomeGD(d);
  const sets = SET.filter(s => s.dist === d);
  const meds = MED.filter(m => distDe(m.cod) === d && m.meta);
  const a = agrega(MED.filter(m => distDe(m.cod) === d));
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Farol da Frequência'; wb.created = new Date();
  const sub = `${D.linha} · distrito ${d} · GD ${nome} · ciclo ${CICLO} · dados ${D.janela} (${fmtData(D.data)}) · só médicos Q1–Q3, meta ${FAROL.verde}%`;

  abaResumo(wb, `Estratégia do GD · ${nome}`, sub, [
    { lb: `Q1–Q3 com frequência (${D.janela})`, v: a.p / 100, fmt: '0.0%', sb: `${a.cf} de ${a.n} médicos · meta ${FAROL.verde}% = ${a.alvo} médicos`, cor: XL.farol(a.p) },
    { lb: `Projeção ${CICLO} · pior caso`, v: a.projMin / 100, fmt: '0.0%', sb: 'cumprindo Proteger e Conquistar', cor: XL.farol(a.projMin) },
    { lb: `Projeção ${CICLO} · melhor caso`, v: a.projMax / 100, fmt: '0.0%', sb: `convertendo também os Possível (${SAI} sem visita)`, cor: XL.farol(a.projMax) },
    { lb: 'Se ninguém visitar a lista', v: a.semNada / 100, fmt: '0.0%', sb: 'só os Garantido' },
    { lb: `Visitas Q1–Q3 no plano de ${CICLO}`, v: a.visitas, sb: `≈ ${Math.ceil(a.visitas / SEMANAS_CICLO)} por semana no distrito` },
    { lb: 'Setores na meta (hoje → projeção pior caso)', v: `${sets.filter(s => s.p >= FAROL.verde).length} → ${sets.filter(s => s.projMin >= FAROL.verde).length}`, sb: `de ${sets.length} setores` },
  ], textoDe(estrategiaGD(a, sets)));

  // Setores
  const ws = wb.addWorksheet('Setores', { properties: { tabColor: { argb: 'FF5787A2' } } });
  const ordem = { vago: 0, campo: 1, cobrar: 2, manter: 3 };
  const ss = sets.map(s => ({ ...s, ac: acaoGD(s) })).sort((x, y) => ordem[x.ac] - ordem[y.ac] || x.projMin - y.projMin);
  tabela(ws, 1, [
    { t: 'Setor', w: 11 }, { t: 'Representante', w: 30, b: true }, { t: 'Médicos Q1–Q3', w: 10, al: 'center' },
    { t: 'Hoje', w: 9, al: 'center', fmt: '0.0%' }, { t: `${CICLO} pior caso`, w: 10, al: 'center', fmt: '0.0%' }, { t: `${CICLO} melhor caso`, w: 10, al: 'center', fmt: '0.0%' },
    { t: 'Proteger', w: 9, al: 'center' }, { t: 'Conquistar', w: 10, al: 'center' }, { t: 'Possível', w: 9, al: 'center' },
    { t: 'Reconstruir', w: 11, al: 'center' }, { t: 'Garantido', w: 10, al: 'center' }, { t: `Visitas em ${CICLO}`, w: 10, al: 'center' },
    { t: 'Visitas por semana', w: 10, al: 'center' }, { t: 'Ação do GD', w: 12, al: 'center' }, { t: 'Recomendação', w: 60, wrap: true },
  ], ss.map(s => [s.cod, s.rep, s.n, s.p / 100, s.projMin / 100, s.projMax / 100, s.proteger, s.conquistar, s.possivel,
    s.reconstruir, s.garantido, s.visitas, Math.ceil(s.visitas / SEMANAS_CICLO), ACOES_GD[s.ac].nome, ACOES_GD[s.ac].txt(s)]), {
    cores: {
      3: r => XL.farol(ss[r].p), 4: r => XL.farol(ss[r].projMin), 5: r => XL.farol(ss[r].projMax), 13: r => XL.acoes[ss[r].ac],
    },
  });

  abaLista(wb, `Lista do ciclo ${CICLO}`, meds.filter(m => PLANO.includes(m.g)).sort(ordenaMed), true, 'FFE3A008');
  abaReconstruir(wb, meds, true);
  await salvaWB(wb, nomeArquivo(D.linha, d, nome, CICLO));
}

function abaReconstruir(wb, meds, comRep) {
  const lista = meds.filter(m => m.g === 'reconstruir').sort(ordenaMed);
  const ws = wb.addWorksheet('Reconstruir', { properties: { tabColor: { argb: 'FFD23F3F' } } });
  const off = comRep ? 2 : 0;
  tabela(ws, 1, [
    ...(comRep ? [{ t: 'Setor', w: 11 }, { t: 'Representante', w: 26 }] : []),
    { t: 'CRM / ID', w: 12 }, { t: 'Médico', w: 34, b: true }, { t: 'Especialidade', w: 20 }, { t: 'Quartil', w: 8, al: 'center' },
    { t: `Visitas ${D.janela}`, w: 11, al: 'center' }, { t: `Sem visita desde ${SAI}`, w: 12, al: 'center' },
    { t: 'Entra na frequência', w: 18, al: 'center' }, { t: 'O que fazer', w: 40, wrap: true },
    { t: `Visitou em ${CICLO}? (S/N)`, w: 11, al: 'center', sn: true }, { t: 'Observação', w: 30, wrap: true },
  ], lista.map(m => [
    ...(comRep ? [m.cod, (SET.find(s => s.cod === m.cod) || {}).rep || ''] : []),
    m.id, m.nome, m.esp, m.q, `${m.real}/${m.obj}`, m.real === 0 ? 'SIM' : '', entraEm(m),
    'Visitar todo ciclo, sem falhar; se não faz sentido no painel, levar ao GD', '', '',
  ]), { preencher: [off + 8, off + 9], cores: { [off + 5]: (r, v) => v === 'SIM' ? XL.grupos.reconstruir : null } });
}

// ---- Planilha do rep --------------------------------------------------------
async function baixarRep() {
  await carregaExcel();
  const s = SET.find(x => x.cod === st.setor);
  const meds = (porSetor[s.cod] || []).filter(m => m.meta);
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Farol da Frequência'; wb.created = new Date();
  const sub = `${D.linha} · setor ${s.cod} · GD ${nomeGD(s.dist)} · ciclo ${CICLO} · dados ${D.janela} (${fmtData(D.data)}) · só médicos Q1–Q3, meta ${FAROL.verde}%`;

  abaResumo(wb, `Estratégia do rep · ${s.rep}`, sub, [
    { lb: `Q1–Q3 com frequência (${D.janela})`, v: s.p / 100, fmt: '0.0%', sb: `${s.cf} de ${s.n} médicos · meta ${FAROL.verde}% = ${s.alvo} médicos`, cor: XL.farol(s.p) },
    { lb: `Projeção ${CICLO} · pior caso`, v: s.projMin / 100, fmt: '0.0%', sb: 'cumprindo Proteger e Conquistar', cor: XL.farol(s.projMin) },
    { lb: `Projeção ${CICLO} · melhor caso`, v: s.projMax / 100, fmt: '0.0%', sb: `convertendo também os Possível (${SAI} sem visita)`, cor: XL.farol(s.projMax) },
    { lb: 'Se não visitar a lista', v: s.semNada / 100, fmt: '0.0%', sb: 'só os Garantido' },
    { lb: `Visitas Q1–Q3 em ${CICLO}`, v: s.visitas, sb: `≈ ${Math.ceil(s.visitas / SEMANAS_CICLO)} por semana` },
    ...ORDEM.map(g => ({ lb: GRUPOS[g].nome, v: s[g], sb: GRUPOS[g].dica(CICLO), cor: XL.grupos[g] })),
  ], textoDe(estrategia(s, porSetor[s.cod] || [])));

  abaLista(wb, `Lista do ciclo ${CICLO}`, meds.filter(m => PLANO.includes(m.g)).sort(ordenaMed), false, 'FFE3A008');
  abaReconstruir(wb, meds, false);

  const gar = meds.filter(m => m.g === 'garantido').sort(ordenaMed);
  const ws = wb.addWorksheet('Garantido', { properties: { tabColor: { argb: 'FF1E9E62' } } });
  tabela(ws, 1, [
    { t: 'CRM / ID', w: 12 }, { t: 'Médico', w: 34, b: true }, { t: 'Especialidade', w: 20 }, { t: 'Quartil', w: 8, al: 'center' },
    { t: `Visitas ${D.janela}`, w: 11, al: 'center' }, { t: 'Freq.', w: 8, al: 'center', fmt: '0%' }, { t: 'Observação', w: 50, wrap: true },
  ], gar.map(m => [m.id, m.nome, m.esp, m.q, `${m.real}/${m.obj}`, m.freq / 100,
    `Garantido em ${CICLO}; manter a visita para não virar Proteger em ${ciclo(2)}`]));

  await salvaWB(wb, nomeArquivo(D.linha, s.cod, s.rep, CICLO));
}

async function salvaWB(wb, arquivo) {
  const buf = await wb.xlsx.writeBuffer();
  const url = URL.createObjectURL(new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
  const a = document.createElement('a');
  a.href = url; a.download = arquivo;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  return arquivo;
}

async function baixarPlanilha(btn) {
  const txt = btn.textContent;
  btn.disabled = true; btn.textContent = 'Gerando…';
  try { st.view === 'gd' ? await baixarGD() : await baixarRep(); }
  catch (e) { alert('Não foi possível gerar a planilha: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = txt; }
}
