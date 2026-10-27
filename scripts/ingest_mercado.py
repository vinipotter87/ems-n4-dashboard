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
    RX_{MARCA}_{LINHA}_{REGIONAL}_CIDADE_{MES}.json     Prescrição | Análise de Performance, Médico | Cidade
                                                        (lido com scripts/raiox_leitor_cidade.js)
    DEM_{MARCA}_{LINHA}_{REGIONAL}_CIDADE_{MES}.json    Demanda | Análise de Concorrentes, GDU | Cidade da UTC
                                                        × Mercado | Produto Gen. Agrup → aba mercado_demanda_cidade

Escreve nas abas mercado_rx, mercado_demanda e mercado_cidade (série histórica, um ciclo ao lado do outro).
    python scripts/ingest_mercado.py --mes SET --apenas-cidade   (só os arquivos _CIDADE_ → aba mercado_cidade)
"""

import sys, json, argparse, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingest

PASTA = ingest.ROOT / "inputs_powerbi" / "mercado"
LINHAS = ("NEXUS", "VITAL")
REGIONAIS = ("SPI", "LESTE")
NIVEIS = ("SETOR", "DISTRITAL", "REGIONAL", "CIDADE")


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
    m = re.match(r"^(RX|DEMP|DEM)_(.+)_(%s)_(%s)_(%s)_([A-Z]{3})$" % (
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


def processar_rx_cidade(path, marca, linha, regional, mes):
    """
    Visão "Médico | Cidade": uma linha por cidade do consultório do médico (não é a cidade do setor).
    A linha Total da tabela vira nivel TOTAL (soma das cidades; médicos sem cidade ficam fora dela,
    por isso o painel aqui é um pouco menor que o da visão por distrito).
    """
    dados = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in dados["rows"]:
        if len(r) == 3:
            r = [r[0], r[1], r[2], "0", ""]
        elif len(r) == 4:
            r = [r[0], r[1], r[2], "0", r[3]]
        elif len(r) < 5:
            continue
        rotulo = limpar(r[0])
        out.append({
            "mes": mes, "regional": regional, "linha": linha, "marca": marca,
            "nivel": "TOTAL" if rotulo == "Total" else "CIDADE",
            "cidade": "TOTAL" if rotulo == "Total" else rotulo.upper(),
            "painel": num(r[1]), "rx_mercado": num(r[2]),
            "share": num(r[3]), "var_pp": num(r[4]),
        })
    return out


def processar_dem_cidade(path, marca, linha, regional, mes):
    """
    Demanda | Análise de Concorrentes com "Analisar por (1)" = GDU | Cidade da UTC: uma linha por
    cidade (do ponto de venda, não do médico) × produto. Colunas: cidade, produto, valor, cresc, share, var.
    """
    dados = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in dados["rows"]:
        if len(r) == 4 and limpar(r[0]) != "Total":
            r = [r[0], r[1], "0", r[2], "0", r[3]]
        if len(r) < 6:
            continue
        cid, produto = limpar(r[0]).upper(), limpar(r[1])
        out.append({
            "mes": mes, "regional": regional, "linha": linha, "marca": marca,
            "cidade": cid, "produto": produto,
            "eh_marca": "1" if produto.upper() == f"{marca} (EMS)".upper() else "0",
            "valor": num(r[2]), "cresc_pct": num(r[3]), "share": num(r[4]), "var_pp": num(r[5]),
        })
    return out


def processar_demp_cidade(path, marca, linha, regional, mes):
    """
    Demanda | Análise de Performance com "Analisar por" = GDU | Cidade da UTC (plano B quando a matriz
    cidade × produto da página de Concorrentes estoura o limite de recursos do Power BI). Uma linha por
    cidade: cidade, mercado, cresc. mercado, EMS, cresc. EMS, market share, penetração. Vira duas linhas
    na aba: a marca (valor EMS) e "DEMAIS PRODUTOS" (mercado − EMS), sem abrir os concorrentes.
    """
    dados = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in dados["rows"]:
        if limpar(r[0]) == "Total":
            continue
        cid = limpar(r[0]).upper()
        mercado = num(r[1]) if len(r) > 1 else None
        if len(r) >= 7:
            ems, cresc, share, var = num(r[3]), num(r[4]), num(r[5]), num(r[6])
        elif len(r) == 4:          # cidade sem venda da marca: só mercado e crescimento
            ems, cresc, share, var = 0.0, None, 0.0, num(r[3])
        else:
            continue
        if mercado is None:
            continue
        base = {"mes": mes, "regional": regional, "linha": linha, "marca": marca, "cidade": cid}
        out.append(dict(base, produto=f"{marca} (EMS)", eh_marca="1", valor=ems, cresc_pct=cresc, share=share, var_pp=var))
        out.append(dict(base, produto="DEMAIS PRODUTOS", eh_marca="0", valor=round(mercado - (ems or 0.0), 2),
                        cresc_pct=num(r[2]) if len(r) > 2 else None, share=None, var_pp=None))
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
    ap.add_argument("--apenas-cidade", action="store_true", dest="apenas_cidade",
                    help="processa só os arquivos _CIDADE_ e escreve só a aba mercado_cidade")
    args = ap.parse_args()
    mes = args.mes.upper()
    if mes not in ingest.MESES_VALIDOS:
        sys.exit(f"Mês inválido: {mes}")

    rx, dem, cid, dcid = [], [], [], []
    for path in sorted(PASTA.glob(f"*_{mes}.json")):
        info = parse_nome_arquivo(path)
        if not info:
            print(f"  ⚠  Nome fora do padrão, ignorado: {path.name}")
            continue
        tipo, marca, linha, regional, nivel_arq, _ = info
        if nivel_arq == "CIDADE":
            if tipo == "RX":
                linhas = processar_rx_cidade(path, marca, linha, regional, mes)
                cid.extend(linhas)
                print(f"  ✓ {path.name}: {len(linhas)} cidades")
            else:
                linhas = (processar_demp_cidade if tipo == "DEMP" else processar_dem_cidade)(path, marca, linha, regional, mes)
                dcid.extend(linhas)
                print(f"  ✓ {path.name}: {len(linhas)} cidade×produto")
            continue
        if args.apenas_cidade:
            continue
        linhas = (processar_rx if tipo == "RX" else processar_dem)(path, marca, linha, regional, nivel_arq, mes)
        (rx if tipo == "RX" else dem).extend(linhas)
        print(f"  ✓ {path.name}: {len(linhas)} registros")

    if not rx and not dem and not cid and not dcid:
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

    # share da demanda por cidade recalculado com 2 casas a partir dos valores
    tot_c = {}
    for r in dcid:
        k = (r["regional"], r["linha"], r["marca"], r["cidade"])
        tot_c[k] = tot_c.get(k, 0.0) + (r["valor"] or 0.0)
    for r in dcid:
        t = tot_c[(r["regional"], r["linha"], r["marca"], r["cidade"])]
        if t > 0 and r["valor"] is not None:
            r["share"] = round(r["valor"] / t * 100, 2)

    print(f"\nTotal {mes}: {len(rx)} registros de prescrição, {len(dem)} de demanda, {len(cid)} por cidade, {len(dcid)} demanda por cidade")
    if args.dry:
        for amostra in (rx[:2], dem[:2], cid[:2], dcid[:2]):
            for a in amostra:
                print("   ", a)
        return

    gc, sh = ingest.conectar_sheets()
    if rx:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_rx", rx, mes)
    if dem:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_demanda", dem, mes)
    if cid:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_cidade", cid, mes)
    if dcid:
        ingest.anexar_aba_por_mes(gc, sh, "mercado_demanda_cidade", dcid, mes)
    print(f"Dados de Mercado {mes} publicados.")


if __name__ == "__main__":
    main()
