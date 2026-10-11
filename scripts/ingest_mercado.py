"""
ingest_mercado.py — Publica "Dados de Mercado" (Prescription Share + Market Share de
demanda + concorrentes) no Google Sheets, a partir das leituras do Power BI Raio X.

Uso:
    python scripts/ingest_mercado.py --mes AGO             (publica no Sheets)
    python scripts/ingest_mercado.py --mes AGO --dry-run   (só mostra o que seria escrito)

Lê os JSON em inputs_powerbi/mercado/ (um por tabela lida do Raio X):
    RX_{MARCA}_{LINHA}_{REGIONAL}_SETOR_{MES}.json      Prescrição | Análise de Performance, GDU | Setor
    RX_{MARCA}_{LINHA}_{REGIONAL}_DISTRITAL_{MES}.json  mesma página, GDU | Distrital
    DEM_{MARCA}_{LINHA}_{REGIONAL}_SETOR_{MES}.json     Demanda | Análise de Concorrentes, GDU | Setor
    DEM_{MARCA}_{LINHA}_{REGIONAL}_REGIONAL_{MES}.json  mesma página, "Analisar por (1)" vazio

Escreve nas abas mercado_rx e mercado_demanda (série histórica, um ciclo ao lado do outro).
"""

import sys, json, argparse, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingest

PASTA = ingest.ROOT / "inputs_powerbi" / "mercado"
LINHAS = ("NEXUS", "VITAL")
REGIONAIS = ("SPI", "LESTE")
NIVEIS = ("SETOR", "DISTRITAL", "REGIONAL")


def num(txt):
    """'16.909.927' -> 16909927.0 ; '-9,2%' -> -9.2 ; '' -> None"""
    t = str(txt).replace("\xa0", " ").replace("%", "").strip()
    if not t:
        return None
    try:
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def limpar(txt):
    return str(txt).replace("\xa0", " ").strip()


def parse_nome_arquivo(path: Path):
    """RX_BUPIUM_XL_VITAL_SPI_SETOR_AGO -> (RX, BUPIUM XL, VITAL, SPI, SETOR, AGO)"""
    m = re.match(r"^(RX|DEM)_(.+)_(%s)_(%s)_(%s)_([A-Z]{3})$" % (
        "|".join(LINHAS), "|".join(REGIONAIS), "|".join(NIVEIS)), path.stem)
    if not m:
        return None
    tipo, marca, linha, regional, nivel, mes = m.groups()
    return tipo, marca.replace("_", " "), linha, regional, nivel, mes


def split_codigo(txt):
    """'11630301 - Lazara Alexandra' -> ('11630301', 'Lazara Alexandra')"""
    t = limpar(txt)
    m = re.match(r"^(\d{8})\s*-\s*(.*)$", t)
    return (m.group(1), m.group(2)) if m else ("", t)


def nivel_do_codigo(cod):
    if cod.endswith("9999"):
        return "NAO_VISITADO"
    return "DISTRITO" if cod.endswith("00") else "SETOR"


def processar_rx(path, marca, linha, regional, nivel_arq, mes):
    dados = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in dados["rows"]:
        # A leitura descarta células vazias: quando a marca não teve receita no setor,
        # o Market Share vem em branco e a linha chega com 3 (sem variação) ou 4 colunas.
        if len(r) == 3:
            r = [r[0], r[1], r[2], "0", ""]
        elif len(r) == 4:
            r = [r[0], r[1], r[2], "0", r[3]]
        elif len(r) < 5:
            continue
        rotulo = limpar(r[0])
        if rotulo == "Total":
            # o Total é o mesmo nos dois arquivos; fica só o do DISTRITAL
            if nivel_arq != "DISTRITAL":
                continue
            nivel, cod, nome = "REGIONAL", regional, regional
        else:
            cod, nome = split_codigo(rotulo)
            if nivel_arq == "DISTRITAL":
                nivel = "DISTRITO"
            elif cod.endswith("00"):
                # na visão por setor, a linha xx00 é só o painel próprio do GD
                nivel = "SETOR_GD"
            else:
                nivel = "SETOR"
        out.append({
            "mes": mes, "regional": regional, "linha": linha, "marca": marca,
            "nivel": nivel, "codigo": cod, "nome": nome,
            "distrito": cod[:6] + "00" if cod[:1].isdigit() else "",
            "painel": num(r[1]), "rx_mercado": num(r[2]),
            "share": num(r[3]), "var_pp": num(r[4]),
        })
    return out


def processar_dem(path, marca, linha, regional, nivel_arq, mes):
    dados = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in dados["rows"]:
        if nivel_arq == "REGIONAL":
            if len(r) < 5:
                continue  # linha de total
            cod, nome, nivel = regional, regional, "REGIONAL"
            produto, vals = limpar(r[0]), r[1:5]
        else:
            # Produto que zerou no mês: Valor e Market Share vêm em branco (4 colunas)
            if len(r) == 4 and limpar(r[0]) != "Total":
                r = [r[0], r[1], "0", r[2], "0", r[3]]
            if len(r) < 6:
                continue
            cod, nome = split_codigo(r[0])
            nivel = nivel_do_codigo(cod)
            produto, vals = limpar(r[1]), r[2:6]
        out.append({
            "mes": mes, "regional": regional, "linha": linha, "marca": marca,
            "nivel": nivel, "codigo": cod, "nome": nome,
            "distrito": cod[:6] + "00" if cod[:1].isdigit() else "",
            "produto": produto,
            "eh_marca": "1" if produto.upper() == f"{marca} (EMS)".upper() else "0",
            "valor": num(vals[0]), "cresc_pct": num(vals[1]),
            "share": num(vals[2]), "var_pp": num(vals[3]),
        })
    return out


def derivar_regional(dem):
    """
    Monta as linhas REGIONAL de demanda somando DISTRITO + NAO_VISITADO por produto,
    para os recortes que não têm arquivo _REGIONAL_ próprio. O crescimento e a variação
    de share saem do valor do mês anterior (valor / (1 + cresc)).
    """
    chave = lambda r: (r["mes"], r["regional"], r["linha"], r["marca"])
    com_regional = {chave(r) for r in dem if r["nivel"] == "REGIONAL"}
    grupos = {}
    for r in dem:
        if r["nivel"] not in ("DISTRITO", "NAO_VISITADO") or chave(r) in com_regional:
            continue
        g = grupos.setdefault(chave(r), {})
        p = g.setdefault(r["produto"], {"atual": 0.0, "ant": 0.0, "eh_marca": r["eh_marca"]})
        v, c = r["valor"] or 0.0, r["cresc_pct"]
        p["atual"] += v
        p["ant"] += v / (1 + c / 100) if c is not None and c > -100 else v
    novas = []
    for (mes, regional, linha, marca), prods in grupos.items():
        tot = sum(p["atual"] for p in prods.values())
        tot_ant = sum(p["ant"] for p in prods.values())
        for produto, p in sorted(prods.items(), key=lambda kv: -kv[1]["atual"]):
            share = p["atual"] / tot * 100 if tot else None
            share_ant = p["ant"] / tot_ant * 100 if tot_ant else None
            novas.append({
                "mes": mes, "regional": regional, "linha": linha, "marca": marca,
                "nivel": "REGIONAL", "codigo": regional, "nome": regional, "distrito": "",
                "produto": produto, "eh_marca": p["eh_marca"],
                "valor": round(p["atual"]),
                "cresc_pct": round((p["atual"] / p["ant"] - 1) * 100, 1) if p["ant"] > 0 else None,
                "share": round(share, 2) if share is not None else None,
                "var_pp": round(share - share_ant, 1) if share is not None and share_ant is not None else None,
            })
    return novas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    args = ap.parse_args()
    mes = args.mes.upper()
    if mes not in ingest.MESES_VALIDOS:
        sys.exit(f"Mês inválido: {mes}")

    rx, dem = [], []
    for path in sorted(PASTA.glob(f"*_{mes}.json")):
        info = parse_nome_arquivo(path)
        if not info:
            print(f"  ⚠  Nome fora do padrão, ignorado: {path.name}")
            continue
        tipo, marca, linha, regional, nivel_arq, _ = info
        linhas = (processar_rx if tipo == "RX" else processar_dem)(path, marca, linha, regional, nivel_arq, mes)
        (rx if tipo == "RX" else dem).extend(linhas)
        print(f"  ✓ {path.name}: {len(linhas)} registros")

    if not rx and not dem:
        sys.exit(f"Nenhum arquivo de {mes} em {PASTA}")

    # O Raio X arredonda o share (5%); recalcula com 2 casas a partir dos valores
    totais = {}
    for r in dem:
        k = (r["regional"], r["linha"], r["marca"], r["nivel"], r["codigo"])
        totais[k] = totais.get(k, 0.0) + (r["valor"] or 0.0)
    for r in dem:
        t = totais[(r["regional"], r["linha"], r["marca"], r["nivel"], r["codigo"])]
        if t > 0 and r["valor"] is not None:
            r["share"] = round(r["valor"] / t * 100, 2)

    derivadas = derivar_regional(dem)
    if derivadas:
        dem.extend(derivadas)
        print(f"  ✓ {len(derivadas)} linhas REGIONAL de demanda calculadas a partir dos distritos")

    print(f"\nTotal {mes}: {len(rx)} registros de prescrição, {len(dem)} de demanda")
    if args.dry:
        for amostra in (rx[:2], dem[:2]):
            for a in amostra:
                print("   ", a)
        return

    gc, sh = ingest.conectar_sheets()
    if rx:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_rx", rx, mes)
    if dem:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_demanda", dem, mes)
    print(f"Dados de Mercado {mes} publicados.")


if __name__ == "__main__":
    main()
