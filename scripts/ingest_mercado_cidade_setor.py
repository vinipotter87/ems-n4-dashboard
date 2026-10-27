"""
ingest_mercado_cidade_setor.py — Presc. share das marcas-chave por SETOR × CIDADE (e, somando,
distrito × cidade), cruzando duas fontes que já existem no projeto:

  1. Export por médico do Raio X (Prescrição | Análise de Performance, "Analisar por" =
     Médico | Nome - CRM - Espec., FILTRO UGN = SPI, uma marca por arquivo — o mesmo export
     da página CRM Chave): inputs_powerbi/crm_chave_rx/{MARCA}_{MES}.xlsx
     colunas: Médico | Nome - CRM - Espec., Painel, |, Rx Mercado, Market Share, Penetração
  2. Export "Painel Velos (Visitado)" da Qualificação do Painel Médico (UGN = SPI), que traz
     Setor, CRM e Cidade de cada médico do painel (todas as linhas da regional):
     SQUAD N4/farol-frequencia/inputs/qualificacao/PAINEL_VISITADO_SPI_{AAAA-MM-DD}.xlsx

Junção por CRM. Dentro de uma linha (1103 Nexus / 1163 Vital) cada médico está em um só setor,
então o Rx do médico vai inteiro para (setor, cidade do consultório). O export por médico cobre
as duas linhas (o mesmo arquivo serve NEXUS e VITAL; OZIVY vale para as duas).
Validado em 27/10/2026: somando por cidade, bate com a leitura "Médico | Cidade" do Raio X.

Uso:
    python scripts/ingest_mercado_cidade_setor.py --mes AGO [--painel ARQUIVO] [--dry-run]

Escreve a aba mercado_cidade_setor (só nível SETOR; o distrito é a soma dos setores na página):
    mes, regional, linha, marca, setor, nome, distrito, cidade, painel, prescritores,
    rx_mercado, rx_marca, share
"""

import sys, re, json, glob, argparse, unicodedata
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import ingest

PASTA_RX = ingest.ROOT / "inputs_powerbi" / "crm_chave_rx"
PASTA_MERCADO = ingest.ROOT / "inputs_powerbi" / "mercado"
PASTA_PAINEL = Path(r"C:/Users/vinic/SQUAD N4/farol-frequencia/inputs/qualificacao")
REGIONAL = "SPI"
LINHAS = {"NEXUS": "1103", "VITAL": "1163"}
MARCAS = {"NEXUS": ["CONCARDIO", "LYBERDIA", "OZIVY"], "VITAL": ["BUPIUM XL", "LINADIB", "LINADIB DUO", "OZIVY"]}


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().strip()


def ler_xlsx(path):
    import openpyxl, warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws = openpyxl.load_workbook(path, read_only=True).active
        return [r for r in ws.iter_rows(values_only=True) if r and any(v is not None for v in r)]


def painel_por_crm(path):
    """{CRM: {(setor8, CIDADE), ...}} + {(setor8, CIDADE): nº de médicos do painel}"""
    rows = ler_xlsx(path)
    h = [norm(x) for x in rows[0]]
    iS, iC, iCid = h.index("SETOR"), h.index("CRM"), h.index("CIDADE")
    por_crm, painel = defaultdict(set), defaultdict(int)
    for r in rows[1:]:
        if len(r) <= max(iS, iC, iCid) or not r[iS]:
            continue
        setor, crm, cid = str(r[iS])[:8], norm(r[iC]), norm(r[iCid])
        if setor[:4] not in LINHAS.values() or not crm or not cid:
            continue
        por_crm[crm].add((setor, cid))
        painel[(setor, cid)] += 1
    return por_crm, painel


def nomes_setores():
    """'11030101' -> 'Lucas Marchi Grossi' a partir das leituras GDU | Setor / Distrital já salvas."""
    nomes = {}
    for f in list(PASTA_MERCADO.glob("RX_*_SETOR_*.json")) + list(PASTA_MERCADO.glob("RX_*_DISTRITAL_*.json")):
        for r in json.loads(f.read_text(encoding="utf-8"))["rows"]:
            m = re.match(r"^(\d{8})\s*-\s*(.+)$", str(r[0]).replace("\xa0", " ").strip())
            if m:
                nomes[m.group(1)] = m.group(2).strip()
    return nomes


def crm_do_rotulo(txt):
    partes = str(txt).split(" - ")
    return norm(partes[-2]) if len(partes) >= 2 else ""


def processar(mes, painel_path):
    por_crm, painel = painel_por_crm(painel_path)
    nomes = nomes_setores()
    out = []
    for linha, prefixo in LINHAS.items():
        for marca in MARCAS[linha]:
            arq = PASTA_RX / f"{marca.replace(' ', '_')}_{mes}.xlsx"
            if not arq.exists():
                print(f"  ⚠  sem export por médico: {arq.name}")
                continue
            rows = ler_xlsx(arq)
            agg = defaultdict(lambda: {"rx": 0.0, "marca": 0.0, "presc": 0})
            medicos = casados = 0
            for r in rows[1:]:
                if not r[0] or str(r[0]).strip() == "Total":
                    continue
                medicos += 1
                alvos = [(s, c) for s, c in por_crm.get(crm_do_rotulo(r[0]), ()) if s.startswith(prefixo)]
                if not alvos:
                    continue
                casados += 1
                rx = float(r[3] or 0); share = float(r[4] or 0)
                for s, c in alvos:  # na prática 1 setor por linha; se houver 2, divide
                    a = agg[(s, c)]
                    a["rx"] += rx / len(alvos); a["marca"] += rx * share / len(alvos); a["presc"] += 1
            for (setor, cid), a in agg.items():
                if a["rx"] <= 0:
                    continue
                out.append({
                    "mes": mes, "regional": REGIONAL, "linha": linha, "marca": marca,
                    "setor": setor, "nome": nomes.get(setor, ""), "distrito": setor[:6] + "00", "cidade": cid,
                    "painel": painel.get((setor, cid), 0), "prescritores": a["presc"],
                    "rx_mercado": round(a["rx"], 2), "rx_marca": round(a["marca"], 2),
                    "share": round(a["marca"] / a["rx"] * 100, 2),
                })
            tot = sum(a["rx"] for (s, _), a in agg.items())
            print(f"  ✓ {marca} {linha}: {medicos} médicos no export, {casados} no painel {prefixo}, "
                  f"{sum(1 for _ in agg)} setor×cidade, Rx {tot:,.0f}".replace(",", "."))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True)
    ap.add_argument("--painel", help="export Painel Velos (Visitado); padrão: o mais recente em farol-frequencia/inputs/qualificacao")
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    args = ap.parse_args()
    mes = args.mes.upper()
    if mes not in ingest.MESES_VALIDOS:
        sys.exit(f"Mês inválido: {mes}")
    painel = Path(args.painel) if args.painel else max(PASTA_PAINEL.glob("PAINEL_VISITADO_SPI_*.xlsx"), key=lambda p: p.name)
    print(f"Painel: {painel.name}")
    dados = processar(mes, painel)
    if not dados:
        sys.exit("Nada a gravar.")
    print(f"\nTotal {mes}: {len(dados)} linhas setor×cidade")
    if args.dry:
        for a in dados[:3]:
            print("   ", a)
        return
    gc, sh = ingest.conectar_sheets()
    ingest.anexar_aba_por_mes(gc, sh, "mercado_cidade_setor", dados, mes)
    print(f"Mercado por setor × cidade {mes} publicado.")


if __name__ == "__main__":
    main()
