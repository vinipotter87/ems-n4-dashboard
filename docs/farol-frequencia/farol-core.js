// Farol da Frequência — regras compartilhadas (página do farol e RPS).
// Meta: % dos médicos Q1–Q3 com frequência (Freq. ≥80% no Power BI). Q4 e sem quartil ficam fora
// (não são prioridade e não pontuam no PEX). Tudo dentro de window.FarolCore para não colidir
// com as variáveis da página que inclui o arquivo.
window.FarolCore = (function () {
  const FAROL = { verde: 90, amarelo: 80 };
  const QUARTIS_META = ['Q1', 'Q2', 'Q3'];
  const JANELA = 5;            // ciclos na janela móvel
  // Médico com frequência = Freq. ≥80% no Power BI, que arredonda para cima em degraus de 20%
  // (2/3 → 80%, 3/4 → 80%). Na prática: visitas/objetivo > 60%.
  const precisaDe = meses => Math.floor(3 * meses / 5) + 1;
  const MESES = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];
  const ORDEM = ['proteger', 'conquistar', 'possivel', 'reconstruir', 'garantido'];
  const PLANO = ['proteger', 'conquistar', 'possivel'];        // o que exige visita no ciclo
  const QORD = { Q1: 1, Q2: 2, Q3: 3, Q4: 4 };
  const pct = (a, b) => b ? a / b * 100 : 0;

  // Ciclos: a janela do export é [MES_INI–MES_FIM]; o próximo ciclo é o seguinte ao fim
  function janela(txt) {
    const [ini, fim] = (txt || 'MAI–SET').split('–').map(m => MESES.indexOf(m));
    const ciclo = m => MESES[(fim + m) % 12];   // m=1 → próximo ciclo
    return { INI: ini, FIM: fim, ciclo, CICLO: ciclo(1), SAI: MESES[ini], FECHADO: MESES[fim] };
  }

  // O export não traz o mês de cada visita, então quando um ciclo antigo sai da janela
  // não se sabe se ele tinha visita: calcula melhor e pior caso.
  // Depois de m ciclos, com "novas" visitas nesses ciclos:
  function proj(obj, real, m, novas) {
    const meses = Math.min(obj + m, JANELA);
    const ficam = Math.min(obj, Math.max(0, JANELA - m));          // ciclos antigos que continuam na janela
    return {
      melhor: Math.min(real, ficam) + novas,                         // visitas antigas nos ciclos mais recentes
      pior: Math.max(0, real - (obj - ficam)) + novas,               // visitas antigas nos ciclos que saem
      precisa: precisaDe(meses),
    };
  }

  // [setor, id, nome, esp, quartil, base0, obj, real, freq, cfreq, freqAnterior]
  function classifica(r) {
    const [cod, id, nome, esp, q, b0, obj, real, freq, cf] = r;
    const m = { cod, id, nome, esp, q, b0, obj, real, freq, cf, meta: QUARTIS_META.includes(q) };
    const sem = proj(obj, real, 1, 0), com = proj(obj, real, 1, 1);
    if (sem.pior >= sem.precisa) m.g = 'garantido';
    else if (com.pior >= com.precisa) m.g = cf ? 'proteger' : 'conquistar';
    else if (com.melhor >= com.precisa) m.g = 'possivel';
    else {
      m.g = 'reconstruir';
      // primeiro ciclo em que entra visitando todo ciclo a partir do próximo
      const entra = caso => { for (let k = 2; k <= JANELA; k++) { const p = proj(obj, real, k, k); if (p[caso] >= p.precisa) return k; } return JANELA; };
      m.cedo = entra('melhor'); m.tarde = entra('pior');
    }
    return m;
  }

  function agrega(lista) {
    const a = { n: 0, cf: 0, q4n: 0, q4cf: 0, zerado: 0, Q1: 0, Q2: 0, Q3: 0 };
    ORDEM.forEach(g => { a[g] = 0; a[g + 'Q'] = { Q1: 0, Q2: 0, Q3: 0 }; a[g + 'F'] = {}; });   // gF = médicos por Freq. hoje (0, 20 … 100)
    lista.forEach(m => {
      if (!m.meta) { a.q4n++; a.q4cf += m.cf; return; }
      a.n++; a.cf += m.cf; a[m.g]++; a[m.g + 'Q'][m.q]++;
      a[m.g + 'F'][m.freq] = (a[m.g + 'F'][m.freq] || 0) + 1;
      if (m.real === 0) a.zerado++;
    });
    a.p = pct(a.cf, a.n);
    a.q4p = pct(a.q4cf, a.q4n);
    a.projMin = pct(a.garantido + a.proteger + a.conquistar, a.n);           // cumprindo o plano, pior caso
    a.projMax = pct(a.garantido + a.proteger + a.conquistar + a.possivel, a.n);
    a.semNada = pct(a.garantido, a.n);                                       // se não visitar ninguém (pior caso)
    a.visitas = a.proteger + a.conquistar + a.possivel;
    a.alvo = Math.ceil(a.n * FAROL.verde / 100 - 1e-9);                      // médicos com frequência p/ bater a meta
    return a;
  }

  return { FAROL, QUARTIS_META, JANELA, precisaDe, MESES, ORDEM, PLANO, QORD, pct, janela, proj, classifica, agrega };
})();
