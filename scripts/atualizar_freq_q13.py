"""Frequência Q1–Q3 (indicador do PEX) da Regional LESTE, por setor, para a linha
"Indicador PEX · Q1–Q3" do Panorama de Frequência em docs/leste.html.

O Panorama mostra o painel inteiro (Q1 a Q4), mas o PEX só pontua a frequência dos médicos
Q1–Q3 (meta 90%). A SPI e o Clínica & Saúde já têm esse número pelo Farol da Frequência
(farol-frequencia/dados/freq_q13.js); a Leste não tem Farol, então ele sai daqui, do mesmo
export que alimenta a frequência da Leste:

  Power BI "Velos - Produtividade EMS" → Médico | Frequência → FILTRO UGN = LESTE, sem marcar
  linha → tabela "Detalhamento da Frequência" → Dados com layout atual (14 colunas, quartil por médico).

Uso:
  python -I scripts/atualizar_freq_q13.py --arquivo "C:/Users/vinic/Downloads/Detalhamento da Frequência (N).xlsx" --ciclo OUT

Grava o bloco entre os marcadores FREQ_Q13_PEX no leste.html. Cada ciclo fica ao lado dos
anteriores (o mesmo ciclo é recalculado no lugar). Por setor, mesma conta do Farol:
[médicos Q1–Q3, com frequência, Freq 0, 20, 40, 60, 80, 100, n Q1, cf Q1, n Q2, cf Q2, n Q3, cf Q3].
"""
import argparse, json, re, sys, warnings
from datetime import datetime
from pathlib import Path

import openpyxl

LESTE = Path(__file__).resolve().parents[1] / "docs" / "leste.html"
PREFIXOS = ("1105", "1165")  # Nexus e Vital da Leste
QUARTIS = ("Q1", "Q2", "Q3")
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
INI, FIM = "// FREQ_Q13_PEX:INICIO", "// FREQ_Q13_PEX:FIM"


def parar(msg):
    sys.exit("✘ " + msg)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--arquivo", required=True, help="export Detalhamento da Frequência (UGN = LESTE)")
    ap.add_argument("--ciclo", required=True, help="ciclo do Panorama em que o export entra (o mesmo do FREQ_SETORES_RAW), ex.: OUT")
    a = ap.parse_args()
    ciclo = a.ciclo.upper()
    if ciclo not in MESES:
        parar(f"ciclo inválido: {a.ciclo}")
    p = Path(a.arquivo)
    warnings.filterwarnings("ignore")
    rows = list(openpyxl.load_workbook(p, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    if len(rows[0]) != 14:
        parar(f"{p.name}: {len(rows[0])} colunas; esperado 14 (Detalhamento da Frequência, Dados com layout atual)")
    rodape = " ".join(str(c) for r in rows if len(r) < 14 or not r[13] for c in r if c)
    if not re.search(r"dc_ugn é LESTE\b", rodape):
        parar(f"{p.name}: rodapé não confirma UGN = LESTE")
    if "dc_linha" in rodape:
        parar(f"{p.name}: export com linha marcada; exporte sem marcar linha")

    por, painel = {}, {}
    for r in rows[1:]:
        if len(r) < 14 or not r[13]:
            continue
        cod = str(r[13]).split(" - ")[0].strip()
        if cod[:4] not in PREFIXOS:
            continue
        freq = r[11] if isinstance(r[11], (int, float)) else 0
        cf = int(r[7] or 0)
        pn = painel.setdefault(cod, [0] * 7)
        pn[0] += 1; pn[1 + min(max(int(freq) // 20, 0), 5)] += 1
        if r[3] not in QUARTIS:
            continue
        v = por.setdefault(cod, [0] * 14)
        v[0] += 1; v[1] += cf
        v[2 + min(max(int(freq) // 20, 0), 5)] += 1
        k = 8 + 2 * QUARTIS.index(r[3])
        v[k] += 1; v[k + 1] += cf
    if len(por) < 20:
        parar(f"{p.name}: só {len(por)} setores da Leste com médicos Q1–Q3")

    s = LESTE.read_text(encoding="utf-8")
    # o painel do export tem de ser o mesmo publicado no ciclo (senão o Q1–Q3 não conversa com a tabela)
    m = re.search(r"\n  " + ciclo + r": `(.*?)`", s[s.index("var FREQ_SETORES_RAW = {"):], re.S)
    if not m:
        parar(f"leste.html não tem o ciclo {ciclo} no FREQ_SETORES_RAW; publique a frequência do ciclo antes")
    pub = {l.split("|")[0]: [int(x) for x in l.split("|")[4:11]] for l in m.group(1).strip().split("\n")}
    iguais = sum(1 for k, v in pub.items() if painel.get(k) == v)
    print(f"  painel do export × publicado em {ciclo}: {iguais} de {len(pub)} setores iguais")
    if iguais < len(pub) * 0.9:
        parar("o export não é o mesmo do ciclo publicado; confira o ciclo ou republique a frequência")

    i, j = s.find(INI), s.find(FIM)
    atual = {}
    if i >= 0:
        bloco = s[i:j]
        atual = json.loads(bloco[bloco.index("{"):bloco.rindex("}") + 1])
    atual[ciclo] = {"data": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d"), "setores": dict(sorted(por.items()))}
    atual = dict(sorted(atual.items(), key=lambda kv: MESES.index(kv[0])))
    novo = (INI + " (gerado por scripts/atualizar_freq_q13.py — não editar à mão)\n"
            "window.FREQ_Q13_PEX = " + json.dumps(atual, ensure_ascii=False, separators=(",", ":")) + ";\n")
    if i >= 0:
        s = s[:i] + novo + s[j:]
    else:
        k = s.index("// ── Indicador PEX · Q1–Q3")  # logo antes das funções que leem o bloco
        s = s[:k] + novo + FIM + "\n" + s[k:]
    LESTE.write_text(s, encoding="utf-8", newline="\n")
    n = sum(v[0] for v in por.values()); c = sum(v[1] for v in por.values())
    print(f"✔ leste.html: Q1–Q3 {ciclo} · {len(por)} setores · {c} de {n} médicos Q1–Q3 com frequência ({c / n * 100:.1f}%)")


if __name__ == "__main__":
    main()
