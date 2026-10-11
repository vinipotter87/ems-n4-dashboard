"""
validar_leitura_mercado.py — Confere as tabelas lidas do Raio X antes da ingestão.

Uso:
    python scripts/validar_leitura_mercado.py --mes SET [--regional SPI]

Para cada marca-chave da regional, exige os 3 arquivos do mês em inputs_powerbi/mercado/
(RX ... SETOR, RX ... DISTRITAL, DEM ... SETOR) e confere marca/linha no seletor, mês no
título da tabela, número de linhas, prefixo dos setores e, na demanda, se a soma dos
distritos bate com o Total. Sai com código 1 se algo estiver faltando ou errado.
"""

import sys, json, re, argparse
from pathlib import Path

RAIZ = Path(__file__).parent.parent
PASTA = RAIZ / "inputs_powerbi" / "mercado"
MARCAS = {"NEXUS": ["CONCARDIO", "LYBERDIA", "OZIVY"], "VITAL": ["BUPIUM XL", "LINADIB", "LINADIB DUO", "OZIVY"]}
PREFIXO = {("SPI", "NEXUS"): "1103", ("SPI", "VITAL"): "1163", ("LESTE", "NEXUS"): "1105", ("LESTE", "VITAL"): "1165"}
MES_PT = {"JAN": "jan", "FEV": "fev", "MAR": "mar", "ABR": "abr", "MAI": "mai", "JUN": "jun",
          "JUL": "jul", "AGO": "ago", "SET": "set", "OUT": "out", "NOV": "nov", "DEZ": "dez"}


def num(t):
    try:
        return float(str(t).replace("\xa0", " ").replace("%", "").replace(".", "").replace(",", ".").strip())
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True)
    ap.add_argument("--regional", default="SPI")
    ap.add_argument("--ano", default="26")
    a = ap.parse_args()
    mes, reg = a.mes.upper(), a.regional.upper()
    token = f"de [{MES_PT[mes]}/{a.ano}]"
    problemas, ok = [], 0

    for linha, marcas in MARCAS.items():
        for marca in marcas:
            for tipo, nivel in (("RX", "SETOR"), ("RX", "DISTRITAL"), ("DEM", "SETOR")):
                nome = f"{tipo}_{marca.replace(' ', '_')}_{linha}_{reg}_{nivel}_{mes}"
                arq = PASTA / f"{nome}.json"
                if not arq.exists():
                    problemas.append(f"FALTA   {nome}")
                    continue
                d = json.loads(arq.read_text(encoding="utf-8"))
                erros = []
                # leituras antigas (primeiro ciclo) não gravaram seletor nem título: só confere se existirem
                if d.get("slicers") and d["slicers"][0] != f"MARCAS CHAVES {linha} (grupo) + {marca} (mercado)":
                    erros.append(f"seletor de marca = {d['slicers'][0]}")
                if "titulo" in d and token not in re.sub(r"\s+", " ", d["titulo"]):
                    erros.append(f"mês do título = {d.get('titulo')!r}")
                if len(d["rows"]) != d["expected"]:
                    erros.append(f"{len(d['rows'])}/{d['expected']} linhas")
                esperado_hdr = "GDU | Setor" if nivel == "SETOR" else "GDU | Distrital"
                if d["hdr"][0] != esperado_hdr:
                    erros.append(f"analisar por = {d['hdr'][0]}")
                cods = {r[0][:4] for r in d["rows"] if r[0][:1].isdigit()}
                if cods != {PREFIXO[(reg, linha)]}:
                    erros.append(f"prefixos de setor = {sorted(cods)} (filtro de Linha/UGN errado?)")
                if tipo == "DEM":
                    soma, total, tem_marca = 0.0, None, False
                    for r in d["rows"]:
                        if r[0].strip() == "Total":
                            total = num(r[1])
                        elif len(r) >= 6:
                            cod = r[0][:8]
                            if cod.endswith("00") or cod.endswith("9999"):
                                soma += num(r[2]) or 0.0
                            if r[1].replace("\xa0", " ").strip().upper() == f"{marca} (EMS)":
                                tem_marca = True
                    if total is None or abs(soma - total) > max(50.0, total * 0.0005):
                        erros.append(f"soma dos distritos {soma:.0f} x Total {total}")
                    if not tem_marca:
                        erros.append("produto da marca (EMS) não aparece")
                if erros:
                    problemas.append(f"ERRADO  {nome}: " + "; ".join(erros))
                else:
                    ok += 1

    # Leitura defasada: logo após trocar Linha/marca a tabela pode ainda mostrar a marca anterior
    # (cabeçalho e período já certos). Dois sinais: Total do Rx por setor ≠ Total do Rx por distrito
    # da mesma marca, e duas marcas da mesma linha com tabelas idênticas.
    for linha, marcas in MARCAS.items():
        vistos = {}
        for marca in marcas:
            base = f"RX_{marca.replace(' ', '_')}_{linha}_{reg}"
            tot = {}
            for nivel in ("SETOR", "DISTRITAL"):
                arq = PASTA / f"{base}_{nivel}_{mes}.json"
                if not arq.exists():
                    continue
                rows = json.loads(arq.read_text(encoding="utf-8"))["rows"]
                t = [r for r in rows if r[0].strip() == "Total"]
                tot[nivel] = t[0][1:] if t else None
                chave = (nivel, json.dumps([r[1:] for r in rows]))
                if chave in vistos:
                    problemas.append(f"ERRADO  {base}_{nivel}_{mes}: tabela idêntica à de {vistos[chave]} (leitura defasada, reler)")
                vistos[chave] = marca
            if len(tot) == 2 and tot["SETOR"] != tot["DISTRITAL"]:
                problemas.append(f"ERRADO  {base}_*_{mes}: Total por setor {tot['SETOR']} x por distrito {tot['DISTRITAL']} (uma das leituras está defasada, reler as duas)")

    esperados = sum(len(m) for m in MARCAS.values()) * 3
    print(f"{ok}/{esperados} tabelas de {mes} ({reg}) conferidas sem problema")
    for p in problemas:
        print("  " + p)
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
