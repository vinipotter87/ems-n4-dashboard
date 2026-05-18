"""
ingest.py — Ingere dados mensais do Drive para o Google Sheets.

Uso:
    python scripts/ingest.py --mes ABR
    python scripts/ingest.py --mes ABR --force       (sobrescreve abas existentes)
    python scripts/ingest.py --jornada               (atualiza a jornada da evolução)
    python scripts/ingest.py --mes ABR --jornada     (faz tudo junto)
"""

import os, sys, json, argparse, io
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

MESES_VALIDOS = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]


# ── Google Drive helpers ───────────────────────────────────────────────────────

def get_drive_service():
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def listar_arquivos(folder_id: str) -> list[dict]:
    svc = get_drive_service()
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,mimeType)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True
    ).execute()
    return res.get("files", [])


def listar_subpastas(folder_id: str) -> list[dict]:
    """Lista subpastas dentro de uma pasta do Drive."""
    svc = get_drive_service()
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True
    ).execute()
    return res.get("files", [])


def encontrar_subfolder(folder_id: str, nome_parcial: str) -> str | None:
    """Encontra o ID de uma subpasta pelo nome (parcial, case-insensitive)."""
    subpastas = listar_subpastas(folder_id)
    for sp in subpastas:
        if nome_parcial.lower() in sp["name"].lower():
            return sp["id"]
    return None


def baixar_xlsx(file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    svc = get_drive_service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl  = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def encontrar_arquivo(folder_id: str, mes: str, prefixos: list[str]) -> dict | None:
    arquivos = listar_arquivos(folder_id)
    for a in arquivos:
        nome = a["name"].upper()
        if mes.upper() in nome and any(p.upper() in nome for p in prefixos):
            return a
    return None


def encontrar_qualquer_xlsx(folder_id: str) -> dict | None:
    """Retorna o primeiro xlsx/xls/xlsm na pasta (para jornada)."""
    arquivos = listar_arquivos(folder_id)
    for a in arquivos:
        if a["name"].lower().endswith((".xlsx", ".xls", ".xlsm")):
            return a
    return None


# ── Parsing helpers ────────────────────────────────────────────────────────────

def parse_pct(val) -> float | None:
    """'83%' → 83.0 · '0.83' → 83.0 · None → None"""
    if val is None or val == "" or str(val).strip() == "":
        return None
    s = str(val).strip().replace("%", "").replace(",", ".")
    if s.lower() in ("nan", "none", "#n/a", "n/a", "-"):
        return None
    try:
        import math
        f = float(s)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f * 100 if f <= 1.5 else f, 1)
    except ValueError:
        return None


def parse_float(val) -> float | None:
    if val is None or val == "":
        return None
    s = str(val).replace(",", "").replace('"', "").strip()
    if s.lower() in ("nan", "none", "#n/a", "n/a", "-"):
        return None
    try:
        import math
        f = float(s)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except ValueError:
        return None


def parse_setor(setor_raw: str) -> dict | None:
    """'11030101 - Gabriele Jovelina Santos' → {setor_id, nome, vago}"""
    if not setor_raw or "-" not in str(setor_raw):
        return None
    partes = str(setor_raw).split(" - ", 1)
    if len(partes) != 2:
        return None
    setor_id = partes[0].strip()
    nome     = partes[1].strip()
    if not setor_id.isdigit():
        return None
    vago = (
        "VAGO" in nome.upper()
        or "NÃO VISITADO" in nome.upper()
        or "NAO VISITADO" in nome.upper()
        or setor_id.endswith("9999")
    )
    return {"setor_id": setor_id, "nome": nome, "vago": vago}


def is_spi(setor_id: str) -> bool:
    return setor_id.startswith("11030") or setor_id.startswith("11630")


def get_distrito_id(setor_id: str) -> str:
    return setor_id[:6] + "000"


def get_linha(setor_id: str) -> str:
    if setor_id.startswith("11030"):
        return "NEXUS"
    if setor_id.startswith("11630"):
        return "VITAL"
    return "DESCONHECIDO"


def detect_col(df_columns, keywords: list[str]) -> str | None:
    """Encontra coluna cujo nome contém alguma das keywords (case-insensitive)."""
    for col in df_columns:
        cn = str(col).lower()
        if any(k.lower() in cn for k in keywords):
            return col
    return None


def abreviar_nome(nome: str) -> str:
    """
    Gera a abreviação de um nome para exibição no dashboard.
    'João Rafael de Franca Nunes Leardini' → 'João Leardini'
    'Murillo Cesar Barbosa dos Santos'     → 'Murillo Santos'
    """
    partes = [p for p in nome.split() if p and p.lower() not in ("de","da","do","dos","das","e")]
    if len(partes) <= 2:
        return nome
    return partes[0] + " " + partes[-1]


def atualizar_gds_mapping(novos_gds: dict[str, str]):
    """
    Atualiza os nomes de GD no mapping.json quando o arquivo mensal traz
    um nome diferente do registrado.
    novos_gds = {distrito_id: nome_completo_do_gd}
    """
    path = ROOT / "config/mapping.json"
    with open(path, encoding="utf-8") as f:
        mapping = json.load(f)

    atualizado = False
    for did, novo_nm in novos_gds.items():
        meta = mapping["distritos"].get(did, {})
        antigo_nm = meta.get("nm", "")
        if novo_nm and novo_nm != antigo_nm:
            print(f"  📝 GD atualizado [{did}]: '{antigo_nm}' → '{novo_nm}'")
            mapping["distritos"].setdefault(did, {})
            mapping["distritos"][did]["nm"] = novo_nm
            mapping["distritos"][did]["ab"] = abreviar_nome(novo_nm)
            atualizado = True

    if atualizado:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        print("  ✓ mapping.json atualizado com novos nomes de GD.")


# ── Processamento Produtividade ────────────────────────────────────────────────

def processar_produtividade(xlsx_bytes: bytes, mes: str) -> tuple[list, list]:
    """
    Retorna (linhas_distritos, linhas_reps).

    Princípio de estabilidade de identificadores:
      - setor_id   (8 dígitos) → NUNCA muda → chave primária do rep
      - distrito_id (6 dígitos + 000) → NUNCA muda → chave primária do distrito
      - nome do rep     → vem SEMPRE do arquivo do mês atual
      - nome do GD      → vem SEMPRE do arquivo do mês atual (col. Gerente se existir)
                          fallback: mapping.json (atualizado automaticamente quando há mudança)
    """
    import pandas as pd

    df = pd.read_excel(io.BytesIO(xlsx_bytes))
    col_setor = df.columns[0]

    # Detecta coluna de Gerente Distrital (nome do GD) se presente no arquivo
    col_gd = detect_col(df.columns, ["gerente", "gd", "gestor", "district manager", "manager"])

    # Mapa: distrito_id → nome do GD extraído do arquivo do mês
    gd_nomes_mes: dict[str, str] = {}

    reps = []
    for _, row in df.iterrows():
        setor_raw = str(row.get(col_setor, ""))
        parsed    = parse_setor(setor_raw)
        if not parsed or not is_spi(parsed["setor_id"]):
            continue

        did = get_distrito_id(parsed["setor_id"])

        # Captura nome do GD do arquivo (apenas uma vez por distrito)
        if col_gd and did not in gd_nomes_mes:
            gd_raw = str(row.get(col_gd, "")).strip()
            if gd_raw and gd_raw.lower() not in ("nan", "none", ""):
                gd_nomes_mes[did] = gd_raw

        prod_real = parse_float(row.get("MDV Real. Ponderado"))
        obj_mdv   = parse_float(row.get("Obj. MDV"))
        prod_pct  = round((prod_real / obj_mdv) * 100, 1) if prod_real and obj_mdv and obj_mdv > 0 else None

        reps.append({
            "mes":             mes,
            "setor_id":        parsed["setor_id"],
            "nome":            parsed["nome"],   # nome do rep: sempre do arquivo do mês
            "vago":            parsed["vago"],
            "distrito_id":     did,
            "linha":           get_linha(parsed["setor_id"]),
            "prod":            prod_pct,
            "q1":              parse_pct(row.get("Q1")),
            "q2":              parse_pct(row.get("Q2")),
            "q3":              parse_pct(row.get("Q3")),
            "q4":              parse_pct(row.get("Q4")),
            "cob_painel":      parse_pct(row.get("Cob. Painel")),
            "dias_trabalhados": parse_float(row.get("Dias Trabalhados")),
        })

    # Agregar distritos
    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    # Se o arquivo trouxe novos nomes de GD, atualiza mapping.json automaticamente
    if gd_nomes_mes:
        atualizar_gds_mapping(gd_nomes_mes)
        # Recarrega para usar os nomes recém-gravados
        with open(ROOT / "config/mapping.json") as f:
            mapping = json.load(f)
    else:
        if col_gd is None:
            print(f"  ℹ  Coluna de Gerente não detectada — usando nomes de GD do mapping.json")

    distritos_agg = {}
    for rep in reps:
        did = rep["distrito_id"]
        if did not in distritos_agg:
            # Prioridade: arquivo do mês → mapping.json
            meta = mapping["distritos"].get(did, {})
            nm   = gd_nomes_mes.get(did) or meta.get("nm", "")
            ab   = abreviar_nome(nm) if gd_nomes_mes.get(did) else meta.get("ab", nm)
            distritos_agg[did] = {
                "mes": mes, "distrito_id": did, "linha": rep["linha"],
                "ab": ab, "nm": nm,
                "prods_vals": [], "reps_ativos": 0
            }
        if not rep["vago"] and rep["prod"] is not None:
            distritos_agg[did]["prods_vals"].append(rep["prod"])
            distritos_agg[did]["reps_ativos"] += 1

    distritos = []
    thresholds = mapping["diagnostico_thresholds"]
    for did, d in distritos_agg.items():
        prod_media = round(sum(d["prods_vals"]) / len(d["prods_vals"]) / 100, 3) if d["prods_vals"] else None
        dg = "crit"
        if prod_media is not None:
            if prod_media >= thresholds["ok"]:   dg = "ok"
            elif prod_media >= thresholds["warn"]: dg = "warn"
        distritos.append({
            "mes": mes, "distrito_id": did, "linha": d["linha"],
            "ab": d["ab"], "nm": d["nm"],
            "prod": prod_media, "reps_ativos": d["reps_ativos"], "diagnostico": dg,
        })

    print(f"  ✓ Produtividade: {len(reps)} reps SPI, {len(distritos)} distritos")
    return distritos, reps


# ── Processamento Produto ──────────────────────────────────────────────────────

def processar_produto(xlsx_bytes: bytes, mes: str, linha: str) -> tuple[list, list, list]:
    """
    Processa arquivo de produto.
    Tenta detectar se há quebra por rep/setor.

    Retorna:
        (registros_regional, registros_distrito, registros_rep)
    """
    import pandas as pd

    df = pd.read_excel(io.BytesIO(xlsx_bytes))
    col_produto = df.columns[0]

    # Detectar coluna de setor/rep
    col_setor_rep = detect_col(df.columns, ["setor", "representante", "código setor", "cod. setor"])
    col_ugn       = detect_col(df.columns, ["ugn", "regional"])
    col_ating     = detect_col(df.columns, ["ating", "% ating", "atingimento"])
    col_cresc     = detect_col(df.columns, ["cresc", "crescimento"])
    col_cob       = detect_col(df.columns, ["cob.", "cobertura"])

    registros_rep = []
    registros_regional = []

    for _, row in df.iterrows():
        produto = str(row.get(col_produto, "")).strip()
        if not produto or produto.upper().startswith("TOTAL") or produto.upper().startswith("FILTRO"):
            continue

        ugn = str(row.get(col_ugn, "SPI")).strip() if col_ugn else "SPI"
        if col_ugn and ugn.upper() != "SPI":
            continue

        cota       = parse_float(row.get("Cota"))
        realizado  = parse_float(row.get("Realizado"))
        ating_raw  = parse_pct(row.get(col_ating)) if col_ating else None
        # Calcular ating se não vier na planilha
        ating_pct  = ating_raw if ating_raw is not None else (
            round(realizado / cota * 100, 1) if cota and realizado and cota > 0 else None
        )
        crescimento = parse_pct(row.get(col_cresc)) if col_cresc else None
        cobertura   = parse_pct(row.get(col_cob)) if col_cob else None

        if col_setor_rep:
            setor_raw = str(row.get(col_setor_rep, ""))
            parsed    = parse_setor(setor_raw)
            if parsed and is_spi(parsed["setor_id"]) and not parsed["vago"]:
                registros_rep.append({
                    "mes":          mes,
                    "linha":        linha,
                    "produto":      produto,
                    "setor_id":     parsed["setor_id"],
                    "nome":         parsed["nome"],
                    "distrito_id":  get_distrito_id(parsed["setor_id"]),
                    "cota":         cota,
                    "realizado":    realizado,
                    "ating_pct":    ating_pct,
                    "crescimento":  crescimento,
                    "cobertura":    cobertura,
                })
        else:
            # Sem quebra de rep: salva como regional
            registros_regional.append({
                "mes":         mes,
                "linha":       linha,
                "produto":     produto,
                "cota":        cota,
                "realizado":   realizado,
                "ating_pct":   ating_pct,
                "crescimento": crescimento,
                "cobertura":   cobertura,
            })

    # Se tem dados por rep → agrega para regional e distrito
    if registros_rep:
        # Regional: soma cota/realizado por produto
        reg_agg: dict = {}
        for r in registros_rep:
            p = r["produto"]
            if p not in reg_agg:
                reg_agg[p] = {"cotas": [], "realizados": [], "crescimentos": [], "coberturas": []}
            if r["cota"]       is not None: reg_agg[p]["cotas"].append(r["cota"])
            if r["realizado"]  is not None: reg_agg[p]["realizados"].append(r["realizado"])
            if r["crescimento"] is not None: reg_agg[p]["crescimentos"].append(r["crescimento"])
            if r["cobertura"]  is not None: reg_agg[p]["coberturas"].append(r["cobertura"])

        for produto, agg in reg_agg.items():
            cota_r = sum(agg["cotas"])       if agg["cotas"]      else None
            real_r = sum(agg["realizados"])  if agg["realizados"] else None
            at_r   = round(real_r / cota_r * 100, 1) if cota_r and real_r and cota_r > 0 else None
            cresc_r = round(sum(agg["crescimentos"]) / len(agg["crescimentos"]), 1) if agg["crescimentos"] else None
            cob_r   = round(sum(agg["coberturas"])   / len(agg["coberturas"]),   1) if agg["coberturas"]  else None
            registros_regional.append({
                "mes": mes, "linha": linha, "produto": produto,
                "cota": cota_r, "realizado": real_r, "ating_pct": at_r,
                "crescimento": cresc_r, "cobertura": cob_r,
            })

        # Distrito: soma por (produto × distrito_id)
        dist_agg: dict = {}
        for r in registros_rep:
            key = (r["produto"], r["distrito_id"])
            if key not in dist_agg:
                dist_agg[key] = {"cotas": [], "realizados": [], "distrito_id": r["distrito_id"], "produto": r["produto"]}
            if r["cota"]      is not None: dist_agg[key]["cotas"].append(r["cota"])
            if r["realizado"] is not None: dist_agg[key]["realizados"].append(r["realizado"])

        registros_distrito = []
        for (produto, distrito_id), agg in dist_agg.items():
            cota_d = sum(agg["cotas"])      if agg["cotas"]      else None
            real_d = sum(agg["realizados"]) if agg["realizados"] else None
            at_d   = round(real_d / cota_d * 100, 1) if cota_d and real_d and cota_d > 0 else None
            registros_distrito.append({
                "mes": mes, "linha": linha, "produto": produto,
                "distrito_id": distrito_id, "cota": cota_d, "realizado": real_d, "ating_pct": at_d,
            })
    else:
        registros_distrito = []

    n_rep  = len(registros_rep)
    n_dist = len(registros_distrito)
    n_reg  = len(registros_regional)
    print(f"  ✓ Produto {linha}: {n_reg} regional · {n_dist} por distrito · {n_rep} por rep")
    return registros_regional, registros_distrito, registros_rep


# ── Processamento Visitas GD ──────────────────────────────────────────────────

def encontrar_visitas(folder_id: str, mes: str, linha: str) -> dict | None:
    """
    Localiza o arquivo de Visitas GD para o mês e linha.
    Padrões detectados:
      NEXUS: contém 'nexus' OU (contém 'visitas' E NÃO contém 'vital')
      VITAL: contém 'vital'
    """
    arquivos = listar_arquivos(folder_id)
    mes_up   = mes.upper()

    # Mapeamento de nomes por extenso para busca no filename
    extenso_map = {
        "JAN": ["jan","janeiro"], "FEV": ["fev","fevereiro"],
        "MAR": ["mar","marco","março"], "ABR": ["abr","abril"],
        "MAI": ["mai","maio"],  "JUN": ["jun","junho"],
        "JUL": ["jul","julho"], "AGO": ["ago","agosto"],
        "SET": ["set","setembro"], "OUT": ["out","outubro"],
        "NOV": ["nov","novembro"], "DEZ": ["dez","dezembro"],
    }
    termos_mes = [mes_up.lower()] + extenso_map.get(mes_up, [])

    for a in arquivos:
        nome = a["name"].lower()
        if not nome.endswith((".xlsx", ".xls", ".xlsm", ".xlsb")):
            continue
        if not any(t in nome for t in termos_mes):
            continue
        if linha == "VITAL" and "vital" in nome:
            return a
        if linha == "NEXUS":
            if "nexus" in nome:
                return a
            # Arquivo sem "nexus" nem "vital" = NEXUS por padrão
            if "vital" not in nome:
                return a
    return None


def processar_visitas(xlsx_bytes: bytes, mes: str, linha: str) -> list:
    """
    Processa arquivo de Visitas GD.
    Filtra apenas GDs da SPI (11030* = NEXUS, 11630* = VITAL).

    Colunas esperadas:
      Distrital           → 'setor_id - nome'
      Real. Contatos      → contatos realizados
      Obj. Acomp. GDD     → objetivo de acompanhamentos
      Real. Acomp. GDD    → acompanhamentos realizados
      Cob. Acomp. GDD     → % cobertura (0-1 ou 0-100)
      Qtde. dias Acomp. GDD → dias de acompanhamento
    """
    import pandas as pd

    df = pd.read_excel(io.BytesIO(xlsx_bytes))

    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    registros = []
    for _, row in df.iterrows():
        distrital_raw = str(row.get(df.columns[0], "")).strip()
        parsed = parse_setor(distrital_raw)
        if not parsed or not is_spi(parsed["setor_id"]):
            continue
        if get_linha(parsed["setor_id"]) != linha:
            continue

        obj      = parse_float(row.get("Obj. Acomp. GDD"))
        real     = parse_float(row.get("Real. Acomp. GDD"))
        # Sempre calcula a partir de real/obj para evitar ambiguidade do Excel:
        # Excel armazena 207.1% como 2.071 (decimal). parse_pct usa threshold 1.5
        # e falha para coberturas > 150%. Cálculo direto elimina o problema.
        if obj is not None and real is not None and obj > 0:
            cob_pct = round(real / obj * 100, 1)
        else:
            cob_pct = parse_pct(row.get("Cob. Acomp. GDD"))
        dias     = parse_float(row.get("Qtde. dias Acomp. GDD"))
        contatos = parse_float(row.get("Real. Contatos"))

        distrito_id = get_distrito_id(parsed["setor_id"])
        meta        = mapping["distritos"].get(distrito_id, {})

        registros.append({
            "mes":        mes,
            "linha":      linha,
            "setor_id":   parsed["setor_id"],
            "nome":       parsed["nome"],
            "distrito_id": distrito_id,
            "ab":         meta.get("ab", ""),
            "contatos":   contatos,
            "obj":        obj,
            "real":       real,
            "cob_pct":    cob_pct,
            "dias":       dias,
        })

    print(f"  ✓ Visitas {linha} {mes}: {len(registros)} GDs SPI")
    return registros


# ── Processamento PEX ────────────────────────────────────────────────────────

# Mapeamento dos ícones do Flaticon → nome da medalha
_MEDAL_ICON_MAP = {
    "7645279":  "OURO",
    "7645294":  "PRATA",
    "7645366":  "BRONZE",
    "4539472":  "ATENÇÃO",
    "16206667": "CRÍTICO",
}


def get_medalha_pts(pts: float) -> str:
    """Deriva medalha pela pontuação conforme regras do BOOK 2026."""
    if pts >= 99.5: return "OURO"
    if pts >= 95:   return "PRATA"
    if pts >= 80:   return "BRONZE"
    if pts >= 75:   return "ATENÇÃO"
    return "CRÍTICO"


def get_medalha_url(url: str) -> str | None:
    """Extrai medalha da URL do ícone Flaticon como validação cruzada."""
    import re
    m = re.search(r"(\d+)\.png$", url or "")
    return _MEDAL_ICON_MAP.get(m.group(1)) if m else None


def encontrar_pex(folder_id: str, mes: str) -> dict | None:
    """Encontra o arquivo PEX do mês na pasta (ex: 'PEX FEV.xlsx')."""
    arquivos = listar_arquivos(folder_id)
    meses_map = {
        "JAN": ["jan","janeiro"], "FEV": ["fev","fevereiro"],
        "MAR": ["mar","marco","março"], "ABR": ["abr","abril"],
        "MAI": ["mai","maio"], "JUN": ["jun","junho"],
    }
    termos = meses_map.get(mes.upper(), [mes.lower()])
    for a in arquivos:
        nome = a["name"].lower()
        if "pex" in nome and any(t in nome for t in termos):
            return a
    # Fallback: qualquer xlsx na pasta
    for a in arquivos:
        if a["name"].lower().endswith((".xlsx", ".xls", ".xlsm")):
            return a
    return None


def processar_pex(xlsx_bytes: bytes, mes: str) -> list:
    """
    Lê o arquivo PEX mensal.
    Colunas: SETOR, NOME, FRENTE, MEDAL (URL ícone), PT. (score 0-100), PTS. MAX.
    Filtra apenas SPI (11030* / 11630*) e deriva medalha pelo score.
    """
    import pandas as pd

    df = pd.read_excel(io.BytesIO(xlsx_bytes))
    print(f"  → Colunas PEX: {list(df.columns)}")

    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    # Detectar colunas flexivelmente
    col_setor  = detect_col(df.columns, ["setor"])       or df.columns[0]
    col_nome   = detect_col(df.columns, ["nome"])        or df.columns[1]
    col_pts    = detect_col(df.columns, ["pt.", "pts", "pontos", "score"])
    col_medal  = detect_col(df.columns, ["medal"])

    registros = []
    for _, row in df.iterrows():
        setor_id = str(row.get(col_setor, "")).strip()
        if not setor_id.isdigit() or not is_spi(setor_id):
            continue

        nome   = str(row.get(col_nome, "")).strip()
        pts    = parse_float(row.get(col_pts)) if col_pts else None
        if pts is None:
            continue

        # Medalha: URL do ícone → fallback score
        url_val  = str(row.get(col_medal, "")).strip() if col_medal else ""
        medalha  = get_medalha_url(url_val) or get_medalha_pts(pts)

        distrito_id = get_distrito_id(setor_id)
        linha       = get_linha(setor_id)
        meta        = mapping["distritos"].get(distrito_id, {})

        registros.append({
            "mes":        mes,
            "setor_id":   setor_id,
            "nome":       nome,
            "distrito_id": distrito_id,
            "linha":      linha,
            "ab":         meta.get("ab", ""),
            "pts":        round(pts, 1),
            "medalha":    medalha,
        })

    # Ordenar por pontuação decrescente
    registros.sort(key=lambda r: r["pts"], reverse=True)
    print(f"  ✓ PEX {mes}: {len(registros)} representantes SPI classificados")
    return registros


# ── Processamento Jornada da Evolução ─────────────────────────────────────────

def processar_jornada(xlsx_bytes: bytes) -> list:
    """
    Lê o arquivo de Jornada da Evolução.
    Estrutura esperada: colunas separadas 'Setor' (código), 'Colaborador' (nome) e 'Posição atual'.
    Também suporta formato legado 'XXXXXXXX - Nome' em coluna única.
    Níveis válidos: Start, Performance, Destaque.
    """
    import pandas as pd

    df = pd.read_excel(io.BytesIO(xlsx_bytes))
    print(f"  → Colunas encontradas: {list(df.columns)}")

    # Detectar coluna de código de setor (apenas código numérico)
    col_setor   = detect_col(df.columns, ["setor"])
    # Detectar coluna de nome do colaborador
    col_nome    = detect_col(df.columns, ["colaborador", "representante"])
    # Detectar coluna de classificação/posição
    col_classif = detect_col(df.columns, ["posição", "posicao", "jornada", "classif",
                                           "nível", "nivel", "etapa", "estágio", "estagio", "fase"])

    if col_classif is None:
        col_classif = df.columns[-1]
        print(f"  ⚠  Coluna de classificação não detectada — usando '{col_classif}'")

    registros = []
    for _, row in df.iterrows():
        classif = str(row.get(col_classif, "")).strip()
        if not classif or classif.lower() in ("nan", "none", ""):
            continue

        # Caso 1: colunas separadas Setor + Colaborador
        if col_setor and col_nome:
            setor_id = str(row.get(col_setor, "")).strip()
            nome     = str(row.get(col_nome,  "")).strip()
            if setor_id and setor_id.isdigit() and is_spi(setor_id):
                registros.append({
                    "setor_id":      setor_id,
                    "nome":          nome,
                    "distrito_id":   get_distrito_id(setor_id),
                    "linha":         get_linha(setor_id),
                    "classificacao": classif,
                })
            elif nome and nome.lower() not in ("nan", "none"):
                # SPI não identificado mas tem nome — guarda sem setor
                registros.append({
                    "setor_id":      setor_id if setor_id.isdigit() else "",
                    "nome":          nome,
                    "distrito_id":   "",
                    "linha":         "",
                    "classificacao": classif,
                })
        else:
            # Caso 2: formato legado 'XXXXXXXX - Nome'
            setor_raw = str(row.get(col_setor or df.columns[0], "")).strip()
            parsed = parse_setor(setor_raw)
            if parsed and is_spi(parsed["setor_id"]):
                registros.append({
                    "setor_id":      parsed["setor_id"],
                    "nome":          parsed["nome"],
                    "distrito_id":   get_distrito_id(parsed["setor_id"]),
                    "linha":         get_linha(parsed["setor_id"]),
                    "classificacao": classif,
                })

    print(f"  ✓ Jornada: {len(registros)} representantes classificados")
    return registros


# ── Google Sheets writer ───────────────────────────────────────────────────────

def escrever_aba(gc, sh, nome_aba: str, dados: list[dict], force: bool):
    import gspread

    try:
        ws = sh.worksheet(nome_aba)
        if not force:
            print(f"  ⚠  Aba '{nome_aba}' já existe. Use --force para sobrescrever.")
            return
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=nome_aba, rows=500, cols=30)

    if not dados:
        print(f"  ⚠  Sem dados para '{nome_aba}'")
        return

    headers = list(dados[0].keys())
    linhas  = [headers] + [[str(row.get(h, "")) for h in headers] for row in dados]
    ws.update(linhas)
    print(f"  ✓ Aba '{nome_aba}': {len(dados)} registros escritos")


def atualizar_config_aba(gc, sh, mes: str):
    import gspread
    from datetime import datetime

    try:
        ws = sh.worksheet("config")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="config", rows=20, cols=5)

    dados = ws.get_all_records()
    meses_str = next((r["valor"] for r in dados if r["chave"] == "meses_disponiveis"), "")
    meses = [m.strip() for m in meses_str.split(",") if m.strip()]

    if mes not in meses:
        meses.append(mes)

    ORDEM = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    meses = sorted(meses, key=lambda m: ORDEM.index(m) if m in ORDEM else 99)

    ws.update([
        ["chave", "valor"],
        ["meses_disponiveis", ",".join(meses)],
        ["mes_padrao", mes],
        ["ultima_atualizacao", datetime.utcnow().isoformat()],
        ["versao", "5.0"],
        ["regional", "SPI OESTE"],
        ["divisao", "Cardiometabolico"]
    ])
    print(f"  ✓ Config atualizada: meses disponíveis = {meses}")


# ── Conectar ao Sheets ─────────────────────────────────────────────────────────

def conectar_sheets():
    import gspread
    import google.auth

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    creds, _ = google.auth.default(scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.getenv("SPREADSHEET_ID"))
    return gc, sh


# ── Main ───────────────────────────────────────────────────────────────────────

def criar_stubs_sem_produtividade(mes: str, rep_nex: list, rep_vit: list) -> tuple[list, list]:
    """
    Quando não há arquivo de Produtividade, cria stubs de distritos e reps
    a partir dos dados de produto por rep.

    Princípio de estabilidade de identificadores:
      - setor_id / distrito_id / linha → NUNCA mudam → usados como chave
      - nome do rep  → vem do arquivo de produto DO MÊS (reflete o nome atual)
      - nome do GD   → vem do mapping.json (única fonte disponível no modo produto-only)
                       Se o GD mudou, atualize manualmente em config/mapping.json
                       e rode: python scripts/ingest.py --mes <MES> --produto-only --force
      - métricas MDV, Q1-Q4, cobertura → None (sem arquivo de Produtividade)
    """
    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    # Extrai reps únicos: chave = setor_id (estável), nome = do arquivo do mês
    reps_map: dict = {}
    for r in rep_nex + rep_vit:
        sid = r["setor_id"]
        if sid and sid not in reps_map:
            reps_map[sid] = {
                "mes":              mes,
                "setor_id":         sid,
                "nome":             r["nome"],   # nome do rep: do arquivo do mês
                "vago":             False,
                "distrito_id":      r["distrito_id"],
                "linha":            r["linha"],
                "prod":             None,
                "q1":               None,
                "q2":               None,
                "q3":               None,
                "q4":               None,
                "cob_painel":       None,
                "dias_trabalhados": None,
            }

    reps = list(reps_map.values())

    # Agrega distritos — nome do GD vem do mapping.json (produto-only: sem outra fonte)
    thresholds = mapping["diagnostico_thresholds"]
    distritos_map: dict = {}
    for rep in reps:
        did = rep["distrito_id"]
        if did not in distritos_map:
            meta = mapping["distritos"].get(did, {})
            distritos_map[did] = {
                "mes": mes, "distrito_id": did, "linha": rep["linha"],
                "ab": meta.get("ab", ""), "nm": meta.get("nm", ""),
                "prod": None, "reps_ativos": 0, "diagnostico": "—",
            }
        distritos_map[did]["reps_ativos"] += 1

    distritos = list(distritos_map.values())
    print(f"  ✓ Stubs gerados a partir do produto: {len(reps)} reps · {len(distritos)} distritos")
    print(f"  ℹ  Nomes dos reps: do arquivo de produto {mes} (refletem o nome atual)")
    print(f"  ℹ  Nomes dos GDs:  do mapping.json (se houver mudança de GD, atualize manualmente)")
    print(f"  ⚠  MDV e indicadores de produtividade: vazios (sem arquivo de Produtividade para {mes})")
    return distritos, reps


def main():
    parser = argparse.ArgumentParser(description="Ingere dados mensais para o Google Sheets")
    parser.add_argument("--mes",          choices=MESES_VALIDOS, help="Mês a ingerir (ex: ABR)")
    parser.add_argument("--force",        action="store_true",   help="Sobrescrever abas existentes")
    parser.add_argument("--jornada",      action="store_true",   help="Atualizar Jornada da Evolução")
    parser.add_argument("--pex",          action="store_true",   help="Ingerir PEX mensal")
    parser.add_argument("--visitas",      action="store_true",   help="Ingerir Visitas GD")
    parser.add_argument("--produto-only", action="store_true",   dest="produto_only",
                        help="Ingere apenas produto (sem Produtividade). Cria stubs de distritos/reps com nomes do mês.")
    args = parser.parse_args()

    if not args.mes and not args.jornada and not args.pex and not args.visitas:
        parser.error("Informe --mes, --jornada, --pex ou combinações.")

    gc, sh = conectar_sheets()

    # ════════════════════════════════════════════════════════
    #  JORNADA DA EVOLUÇÃO
    # ════════════════════════════════════════════════════════
    if args.jornada:
        print("\n══ JORNADA DA EVOLUÇÃO ══\n")
        drive_root = os.getenv("DRIVE_DADOS_FOLDER")

        # Tenta DRIVE_JORNADA primeiro, depois procura subpasta pelo nome
        jornada_folder = os.getenv("DRIVE_JORNADA")
        if not jornada_folder:
            print("🔍 Procurando subpasta 'jornada' dentro de DRIVE_DADOS_FOLDER...")
            jornada_folder = encontrar_subfolder(drive_root, "jornada")
            if not jornada_folder:
                print("❌ Subpasta 'jornada da evolucao' não encontrada.")
                print("   Configure DRIVE_JORNADA no .env com o ID da pasta.")
                if not args.mes:
                    sys.exit(1)
            else:
                print(f"  ✓ Subpasta encontrada: {jornada_folder}")

        if jornada_folder:
            arq_jornada = encontrar_qualquer_xlsx(jornada_folder)
            if not arq_jornada:
                print("❌ Nenhum arquivo xlsx encontrado na pasta de jornada.")
            else:
                print(f"📥 Baixando jornada: {arq_jornada['name']}...")
                xlsx_jornada = baixar_xlsx(arq_jornada["id"])
                jornada_data = processar_jornada(xlsx_jornada)
                escrever_aba(gc, sh, "jornada", jornada_data, force=True)  # sempre sobrescreve
                print("✅ Jornada atualizada.\n")

    # ════════════════════════════════════════════════════════
    #  DADOS MENSAIS
    # ════════════════════════════════════════════════════════
    if args.mes:
        mes = args.mes.upper()
        modo = "PRODUTO-ONLY" if args.produto_only else "COMPLETO"
        print(f"\n══ INGESTÃO {mes}/2026 [{modo}] ══\n")

        folder_produto = os.getenv("DRIVE_PRODUTO") or os.getenv("DRIVE_DADOS_FOLDER")

        # ── Produtos NEXUS (sempre) ──
        print("📥 Baixando Produto NEXUS...")
        arq_nex = encontrar_arquivo(folder_produto, mes, ["NEXUS", "Nexus", "nexus"])
        if arq_nex:
            print(f"  → {arq_nex['name']}")
            xlsx_nex = baixar_xlsx(arq_nex["id"])
            reg_nex, dist_nex, rep_nex = processar_produto(xlsx_nex, mes, "NEXUS")
            escrever_aba(gc, sh, f"produtos_NEXUS_{mes}",      reg_nex,  args.force)
            escrever_aba(gc, sh, f"produtos_dist_NEXUS_{mes}", dist_nex, args.force)
            escrever_aba(gc, sh, f"produtos_rep_NEXUS_{mes}",  rep_nex,  args.force)
        else:
            print(f"  ⚠  Produto NEXUS {mes} não encontrado")
            rep_nex = []

        # ── Produtos VITAL (sempre) ──
        print("\n📥 Baixando Produto VITAL...")
        arq_vit = encontrar_arquivo(folder_produto, mes, ["VITAL", "vital"])
        if arq_vit:
            print(f"  → {arq_vit['name']}")
            xlsx_vit = baixar_xlsx(arq_vit["id"])
            reg_vit, dist_vit, rep_vit = processar_produto(xlsx_vit, mes, "VITAL")
            escrever_aba(gc, sh, f"produtos_VITAL_{mes}",      reg_vit,  args.force)
            escrever_aba(gc, sh, f"produtos_dist_VITAL_{mes}", dist_vit, args.force)
            escrever_aba(gc, sh, f"produtos_rep_VITAL_{mes}",  rep_vit,  args.force)
        else:
            print(f"  ⚠  Produto VITAL {mes} não encontrado")
            rep_vit = []

        if args.produto_only:
            # ── Modo produto-only: stubs de distritos/reps com nomes do mês ──
            print(f"\n📋 Criando stubs de distritos/reps (sem Produtividade)...")
            print(f"   Identificador estável: setor_id / distrito_id")
            print(f"   Nome: extraído do produto {mes} (reflete nome atual do representante)")
            distritos, reps = criar_stubs_sem_produtividade(mes, rep_nex, rep_vit)
            escrever_aba(gc, sh, f"distritos_{mes}", distritos, args.force)
            escrever_aba(gc, sh, f"reps_{mes}",      reps,      args.force)
        else:
            # ── Modo completo: baixa Produtividade ──
            print("\n📥 Baixando Produtividade...")
            folder_prod = os.getenv("DRIVE_PRODUTIVIDADE") or os.getenv("DRIVE_DADOS_FOLDER")
            arq_prod = encontrar_arquivo(folder_prod, mes, ["Produtividade", "produtividade"])
            if not arq_prod:
                # Tenta pasta alternativa
                folder_prod_spi = os.getenv("DRIVE_PRODUTIVIDADE_SPI")
                if folder_prod_spi:
                    arq_prod = encontrar_arquivo(folder_prod_spi, mes, ["Produtividade", "produtividade"])
            if not arq_prod:
                print(f"❌ Arquivo Produtividade {mes} não encontrado no Drive")
                print(f"   Dica: se não há produtividade para {mes}, use --produto-only")
                sys.exit(1)

            print(f"  → {arq_prod['name']}")
            xlsx_prod = baixar_xlsx(arq_prod["id"])
            distritos, reps = processar_produtividade(xlsx_prod, mes)
            escrever_aba(gc, sh, f"distritos_{mes}", distritos, args.force)
            escrever_aba(gc, sh, f"reps_{mes}",      reps,      args.force)

        # ── Atualizar config ──
        print("\n📋 Atualizando config...")
        atualizar_config_aba(gc, sh, mes)

        print(f"\n✅ Ingestão {mes} [{modo}] concluída.\n")

    # ════════════════════════════════════════════════════════
    #  PEX MENSAL
    # ════════════════════════════════════════════════════════
    if args.pex:
        if not args.mes:
            parser.error("--pex requer --mes (ex: --pex --mes FEV)")
        mes = args.mes.upper()
        print(f"\n══ PEX {mes}/2026 ══\n")

        pex_folder = os.getenv("DRIVE_PEX")
        if not pex_folder:
            print("❌ DRIVE_PEX não configurado no .env")
            sys.exit(1)

        arq_pex = encontrar_pex(pex_folder, mes)
        if not arq_pex:
            print(f"❌ Arquivo PEX {mes} não encontrado na pasta DRIVE_PEX.")
            print(f"   Adicione o arquivo 'PEX {mes}.xlsx' na pasta e tente novamente.")
            sys.exit(1)

        print(f"📥 Baixando PEX: {arq_pex['name']}...")
        xlsx_pex  = baixar_xlsx(arq_pex["id"])
        pex_data  = processar_pex(xlsx_pex, mes)
        escrever_aba(gc, sh, f"pex_{mes}", pex_data, force=True)  # sempre sobrescreve
        print(f"✅ PEX {mes} atualizado.\n")

    # ════════════════════════════════════════════════════════
    #  VISITAS GD
    # ════════════════════════════════════════════════════════
    if args.visitas:
        if not args.mes:
            parser.error("--visitas requer --mes (ex: --visitas --mes MAR)")
        mes = args.mes.upper()
        print(f"\n══ VISITAS GD {mes}/2026 ══\n")

        visitas_folder = os.getenv("DRIVE_VISITAS_GD")
        if not visitas_folder:
            print("❌ DRIVE_VISITAS_GD não configurado no .env")
            sys.exit(1)

        for linha in ["NEXUS", "VITAL"]:
            print(f"📥 Baixando Visitas {linha} {mes}...")
            arq = encontrar_visitas(visitas_folder, mes, linha)
            if not arq:
                print(f"  ⚠  Arquivo Visitas {linha} {mes} não encontrado — ignorando")
                continue
            print(f"  → {arq['name']}")
            xlsx_bytes = baixar_xlsx(arq["id"])
            dados = processar_visitas(xlsx_bytes, mes, linha)
            if dados:
                escrever_aba(gc, sh, f"visitas_{linha}_{mes}", dados, args.force)

        print(f"\n✅ Visitas GD {mes} concluído.\n")


if __name__ == "__main__":
    main()
