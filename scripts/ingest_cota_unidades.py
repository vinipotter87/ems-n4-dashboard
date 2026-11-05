"""
ingest_cota_unidades.py — Cota e realizado em UNIDADES por cidade (e PDVs por cidade), para o
bloco "Conta em unidades" do plano de marca-chave no Copiloto de RPS (docs/rps.html).

Fonte: Power BI Raio X → Cota | Análise de Cobertura com "Mensurar por" = Unidades e
"Analisar por" = GDU | Cidade da UTC (aba UNIDADE_CIDADE), mais a Demanda por PDV de cada
marca (abas PDVS_CIDADES_{MARCA}_UN). O piloto (05/11/2026) usa o export do GD Fabiano
(distrito 116301, Vital) no nível DISTRITO; quando o export vier com "Analisar por (1)" =
GDU | Setor, gravar no nível SETOR, um registro por setor × cidade × produto.

Abas gravadas na planilha pública (formato longo, idempotente por mes+regional+linha+nivel+codigo):
  cota_un_cidade : mes, regional, linha, nivel, codigo, cidade, produto, cota_un, real_un, cresc, cob
  cota_un_pdv    : mes, regional, linha, nivel, codigo, produto, pdv, cidade, unidades, part, cresc
  cota_incremento: regional, linha, produto, mes, cota, realizado, var_mm   (--incremento: lido das
                   abas produtos_{LINHA}_{MES} já publicadas; variação da cota em R$ mês a mês)

Uso:
  python scripts/ingest_cota_unidades.py --arquivo "C:/.../UNIDADES_MARCAS_PDVS_CIDADES.xlsx" --mes OUT \
      --regional SPI --linha VITAL --nivel DISTRITO --codigo 116301 [--sem-pdv] [--dry-run]
  python scripts/ingest_cota_unidades.py --incremento --regional SPI            # só a aba de incrementos
"""

import sys, argparse, unicodedata, warnings
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import ingest

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().strip()


def f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def r2(v, nd=1):
    return "" if v is None else round(v, nd)


def ler_planilha(path):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return {ws.title: [r for r in ws.iter_rows(values_only=True) if r and any(v is not None for v in r)] for ws in wb.worksheets}


def processar_cidades(rows, base):
    h = [norm(x) for x in rows[0]]
    iC, iP = h.index("CIDADE DA UTC"), [i for i, x in enumerate(h) if x == "PRODUTO"][0]
    iCota, iReal = h.index("COTA UNIDADES"), h.index("REALIZADO UNIDADES")
    iCres = [i for i, x in enumerate(h) if x.startswith("CRESC")][0]
    out = []
    for r in rows[1:]:
        cidade, produto = norm(r[iC]), norm(r[iP])
        if not produto or cidade in ("", "TOTAL"):
            continue
        cota, real, cres = f(r[iCota]), f(r[iReal]), f(r[iCres])
        if cota is None and real is None:
            continue
        cob = (real or 0) / cota * 100 if cota else None
        out.append(dict(base, cidade=cidade, produto=produto, cota_un=r2(cota), real_un=r2(real),
                        cresc=r2(cres * 100 if cres is not None else None), cob=r2(cob)))
    return out


def processar_pdvs(abas, base):
    out = []
    for nome, rows in abas.items():
        if not nome.upper().startswith("PDVS_") or len(rows) < 2:
            continue
        h = [norm(x) for x in rows[0]]
        iN, iC = h.index("PDV | NOME"), h.index("PDV | CIDADE")
        iU = [i for i, x in enumerate(h) if x.endswith(" UNIDADES")][0]
        produto = h[iU].replace(" UNIDADES", "").strip()
        iPart = [i for i, x in enumerate(h) if x.startswith("PART")]
        iCres = [i for i, x in enumerate(h) if x.startswith("CRESC")]
        for r in rows[1:]:
            pdv, cidade = norm(r[iN]), norm(r[iC])
            if not pdv or pdv == "TOTAL":
                continue
            un = f(r[iU])
            part = f(r[iPart[0]]) if iPart else None
            cres = f(r[iCres[0]]) if iCres else None
            out.append(dict(base, produto=produto, pdv=pdv, cidade=cidade, unidades=r2(un),
                            part=r2(part * 100 if part is not None else None, 2),
                            cresc=r2(cres * 100 if cres is not None else None)))
    return out


def anexar_por_chave(sh, nome_aba, dados, chave):
    """Regrava a aba mantendo as linhas de outras chaves (mes+regional+linha+nivel+codigo)."""
    import gspread
    if not dados:
        print(f"  ⚠  Sem dados para '{nome_aba}'"); return
    headers = list(dados[0].keys())
    try:
        ws = sh.worksheet(nome_aba); existentes = ws.get_all_records()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=nome_aba, rows=4000, cols=max(20, len(headers) + 2)); existentes = []
    k = lambda r: "|".join(str(r.get(c, "")).upper() for c in chave)
    novas = {k(r) for r in dados}
    mantidos = [r for r in existentes if k(r) not in novas]
    linhas = [headers] + [[str(r.get(h, "")) for h in headers] for r in mantidos] + [[str(r.get(h, "")) for h in headers] for r in dados]
    ws.clear(); ws.update(linhas)
    print(f"  ✓ Aba '{nome_aba}': {len(dados)} registros gravados ({len(mantidos)} de outras chaves preservados, total {len(linhas) - 1})")


def incrementos(sh, regional):
    """Cota (R$) por produto e mês na regional, com a variação mês a mês — base da projeção de cota."""
    suf = "_LESTE" if regional == "LESTE" else ""
    out = []
    for linha in ("NEXUS", "VITAL"):
        serie = defaultdict(dict)
        for m in MESES:
            try:
                rows = sh.worksheet(f"produtos_{linha}{suf}_{m}").get_all_records()
            except Exception:
                continue
            for r in rows:
                p = norm(r.get("produto"))
                c, re_ = f(r.get("cota")), f(r.get("realizado"))
                if p and c:
                    serie[p][m] = (c, re_)
        for p, por_mes in serie.items():
            prev = None
            for m in MESES:
                if m not in por_mes:
                    continue
                c, re_ = por_mes[m]
                var = (c / prev - 1) * 100 if prev else None
                out.append(dict(regional=regional, linha=linha, produto=p, mes=m, cota=round(c, 2),
                                realizado=r2(re_, 2), var_mm=r2(var)))
                prev = c
        print(f"  {linha}: {len(serie)} produtos com série de cota")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arquivo"); ap.add_argument("--mes"); ap.add_argument("--regional", default="SPI")
    ap.add_argument("--linha"); ap.add_argument("--nivel", choices=["DISTRITO", "SETOR"], default="DISTRITO")
    ap.add_argument("--codigo", help="distrito (6 dígitos) ou setor (8 dígitos) do export")
    ap.add_argument("--sem-pdv", action="store_true"); ap.add_argument("--incremento", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    regional = a.regional.upper()

    cidades = pdvs = []
    if a.arquivo:
        if not (a.mes and a.linha and a.codigo):
            ap.error("--arquivo exige --mes, --linha e --codigo")
        base = dict(mes=a.mes.upper(), regional=regional, linha=a.linha.upper(), nivel=a.nivel, codigo=str(a.codigo))
        abas = ler_planilha(a.arquivo)
        cidades = processar_cidades(abas["UNIDADE_CIDADE"], base)
        pdvs = [] if a.sem_pdv else processar_pdvs(abas, base)
        tot = defaultdict(lambda: [0.0, 0.0])
        for r in cidades:
            tot[r["produto"]][0] += r["cota_un"] or 0; tot[r["produto"]][1] += r["real_un"] or 0
        print(f"UNIDADE_CIDADE: {len(cidades)} linhas cidade×produto, {len({r['cidade'] for r in cidades})} cidades")
        for p, (c, r) in sorted(tot.items(), key=lambda x: -x[1][0]):
            print(f"   {p:14s} cota {c:8.0f} un  real {r:8.0f} un  cob {r / c * 100 if c else 0:6.1f}%")
        print(f"PDVs: {len(pdvs)} linhas em {len({r['produto'] for r in pdvs})} marcas")

    if a.dry_run:
        print("(dry-run) nada gravado"); return

    gc, sh = ingest.conectar_sheets()
    chave = ["mes", "regional", "linha", "nivel", "codigo"]
    if cidades:
        anexar_por_chave(sh, "cota_un_cidade", cidades, chave)
    if pdvs:
        anexar_por_chave(sh, "cota_un_pdv", pdvs, chave)
    if a.incremento:
        print("Incrementos de cota (R$) por produto e mês…")
        anexar_por_chave(sh, "cota_incremento", incrementos(sh, regional), ["regional"])


if __name__ == "__main__":
    main()
