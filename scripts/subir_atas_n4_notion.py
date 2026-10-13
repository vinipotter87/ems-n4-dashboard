"""
subir_atas_n4_notion.py — publica na aba budget_lancamentos as atas de N4 copiadas do Notion
(inputs_notion/atas_n4/<MES_REUNIAO>_<distrito>.json), no mesmo formato das atas anexadas no
modo apresentação: duas linhas por ata, gd = "N4:<distrito>", crm = "ata|<mês dos dados>"
(mês anterior ao da reunião), produto N4_ATA (combinados) e N4_ATA_DOC (texto integral).
Não sobrescreve ata que já exista para o mesmo distrito e mês.

Uso (cwd = ems-n4-dashboard, PYTHONIOENCODING=utf-8):
    python scripts/subir_atas_n4_notion.py --dry-run
    python scripts/subir_atas_n4_notion.py
"""
import sys, json, time, random, string, argparse, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingest

PASTA = Path(__file__).parent.parent / "inputs_notion" / "atas_n4"
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
ROT = {"ABR": "Abr", "MAI": "Mai", "JUN": "Jun", "JUL": "Jul", "AGO": "Ago", "SET": "Set"}
STATUS = {"Pendente", "Em andamento", "Resolvido", "Não executado"}


def novo_id(pref):
    return pref + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(13))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    a = ap.parse_args()
    gc, sh = ingest.conectar_sheets()
    ws = sh.worksheet("budget_lancamentos")
    vals = ws.get_all_values()
    cab = vals[0]
    existentes = {(dict(zip(cab, r)).get("gd"), dict(zip(cab, r)).get("crm")) for r in vals[1:] if dict(zip(cab, r)).get("produto") == "N4_ATA"}
    hoje, novas = datetime.date.today().isoformat(), []
    for arq in sorted(PASTA.glob("*.json"), key=lambda p: (MESES.index(p.stem[:3]), p.stem)):
        d = json.loads(arq.read_text(encoding="utf-8"))
        mes_r = d["mes_reuniao"]
        mes_d = MESES[MESES.index(mes_r) - 1]
        gd, crm = "N4:" + d["distrito"], "ata|" + mes_d
        if (gd, crm) in existentes:
            print(f"  = já existe: {arq.name}")
            continue
        titulo = f"ATA N4 — {ROT[mes_r]}/26 | {d['gd_nome']}"
        itens = []
        for k, i in enumerate(d["itens"], 1):
            texto = (i.get("tema", "") + ": " if i.get("tema") else "") + str(i.get("texto", "")).strip()
            st = i.get("status") if i.get("status") in STATUS else "Pendente"
            itens.append({"n": k, "texto": texto, "resp": str(i.get("resp", "")).strip(), "prazo": str(i.get("prazo", "")).strip(), "status": st})
        ata = {"titulo": titulo, "data": d.get("data_reuniao", ""), "arquivo": "Notion — " + d.get("titulo_notion", ""), "gd": d["gd_nome"], "daReuniao": True, "itens": itens}
        doc = {"titulo": titulo, "arquivo": "Notion — " + d.get("titulo_notion", ""), "origem": d.get("pagina_url", ""), "texto": d["texto"]}
        j_ata, j_doc = json.dumps(ata, ensure_ascii=False), json.dumps(doc, ensure_ascii=False)
        if max(len(j_ata), len(j_doc)) > 49000:
            print(f"  ⚠ {arq.name}: texto grande demais para uma célula ({len(j_doc)}) — pulado")
            continue
        base = {"gd": gd, "linha": d["linha"], "crm": crm, "medico": titulo, "valor": "0", "data": hoje, "editado": "FALSE"}
        for prod, pref, acao in (("N4_ATA", "n4a", j_ata), ("N4_ATA_DOC", "n4d", j_doc)):
            linha = dict(base, id=novo_id(pref), produto=prod, acao=acao, criadoEm=str(int(time.time() * 1000) + len(novas)))
            novas.append([linha.get(c, "") for c in cab])
        print(f"  + {titulo}  (dados de {mes_d}, {len(itens)} combinados, {len(d['texto'])} caracteres)")
    print(f"\n{len(novas) // 2} atas novas ({len(novas)} linhas)")
    if a.dry or not novas:
        return
    ws.append_rows(novas, value_input_option="RAW")
    print("Publicado em budget_lancamentos.")


if __name__ == "__main__":
    main()
