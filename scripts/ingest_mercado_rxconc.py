"""
ingest_mercado_rxconc.py — publica na aba `mercado_rx_conc` do Sheets o share de PRESCRIÇÃO de
cada marca do mercado das marcas-chave (página "Prescrição | Análise de Concorrentes" do Raio X).

Lê os JSONs `inputs_powerbi/mercado/RXC_{MARCA}_{LINHA}_{REGIONAL}_{ESCOPO}_{MES}.json`
(gravados por raiox_leitor_rxconc.js + salvar_leitura_mercado.ps1), onde ESCOPO é `REGIONAL`
ou o código do distrito (ex.: 11030100). Cada linha da tabela do Raio X traz o share do mês
anterior, o share do mês e a penetração (diferença em pontos percentuais).

Uso (cwd = ems-n4-dashboard, PYTHONIOENCODING=utf-8):
    python scripts/ingest_mercado_rxconc.py --mes AGO --dry-run
    python scripts/ingest_mercado_rxconc.py --mes AGO

Regrava o mês inteiro (todas as regionais encontradas), preservando os outros meses.
"""
import sys, json, argparse, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingest

PASTA = Path(__file__).parent.parent / "inputs_powerbi" / "mercado"
MARCAS = ["LINADIB DUO", "BUPIUM XL", "CONCARDIO", "LYBERDIA", "LINADIB", "OZIVY"]  # nomes compostos primeiro


def num(txt):
    t = str(txt).replace("\xa0", " ").replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


def linha_para_registro(cels):
    """[produto, anterior, atual, penetração]; células vazias somem na leitura, então com 3
    células é preciso descobrir qual share faltou (a penetração é sempre a última, sem %)."""
    produto = cels[0].replace("\xa0", " ").strip()
    vals = cels[1:]
    ant = atual = pen = None
    if len(vals) >= 3:
        ant, atual, pen = num(vals[0]), num(vals[1]), num(vals[2])
    elif len(vals) == 2:
        a, pen = num(vals[0]), num(vals[1])
        if "%" in str(vals[1]):          # dois shares, sem penetração
            ant, atual, pen = a, num(vals[1]), None
        elif pen is not None and pen < 0:  # saiu do mercado no mês: só tinha share anterior
            ant, atual = a, 0.0
        else:                            # entrou no mês: só tem share atual
            ant, atual = 0.0, a
    elif len(vals) == 1:
        atual = num(vals[0]) if "%" in str(vals[0]) else None
    return produto, ant, atual, pen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    a = ap.parse_args()
    mes = a.mes.upper()

    registros, arquivos = [], sorted(PASTA.glob(f"RXC_*_{mes}.json"))
    if not arquivos:
        sys.exit(f"Nenhum arquivo RXC_*_{mes}.json em {PASTA}")
    for arq in arquivos:
        m = re.match(rf"RXC_(.+)_(NEXUS|VITAL)_(SPI|LESTE)_(REGIONAL|\d{{8}})_{mes}$", arq.stem)
        if not m:
            print(f"  ⚠  nome fora do padrão: {arq.name}")
            continue
        marca, linha, regional, escopo = m.group(1).replace("_", " "), m.group(2), m.group(3), m.group(4)
        d = json.loads(arq.read_text(encoding="utf-8"))
        n = 0
        for cels in d["rows"]:
            if cels[0].strip() == "Total":
                continue
            produto, ant, atual, pen = linha_para_registro(cels)
            registros.append({
                "mes": mes, "regional": regional, "linha": linha, "marca": marca,
                "nivel": "REGIONAL" if escopo == "REGIONAL" else "DISTRITO",
                "codigo": "" if escopo == "REGIONAL" else escopo,
                "produto": produto, "eh_marca": "1" if produto.upper() == f"{marca} (EMS)" else "0",
                "share": "" if atual is None else atual,
                "share_ant": "" if ant is None else ant,
                "var_pp": "" if pen is None else pen,
            })
            n += 1
        print(f"  ✓ {arq.name}: {n} produtos")

    print(f"\nTotal {mes}: {len(registros)} linhas de prescrição por concorrente ({len(arquivos)} tabelas)")
    if a.dry:
        for r in registros[:4]:
            print("   ", r)
        return
    gc, sh = ingest.conectar_sheets() if hasattr(ingest, "conectar_sheets") else (None, None)
    ingest.anexar_aba_por_mes(gc, sh, "mercado_rx_conc", registros, mes)
    print(f"Prescrição por concorrente {mes} publicada.")


if __name__ == "__main__":
    main()
