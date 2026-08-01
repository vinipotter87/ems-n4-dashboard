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
    """Usado exclusivamente pelo fluxo SPI OESTE — nunca deve pegar um arquivo com "leste" no nome."""
    arquivos = listar_arquivos(folder_id)
    for a in arquivos:
        nome = a["name"].upper()
        if "LESTE" in nome:
            continue
        if mes.upper() in nome and any(p.upper() in nome for p in prefixos):
            return a
    return None


def encontrar_produtividade_leste(folder_id: str, mes: str) -> dict | None:
    """
    Localiza o arquivo de Produtividade LESTE do mês.
    Preferência: arquivo com "leste" explícito no nome (formato usado até JUN).
    Fallback: arquivo combinado OESTE+LESTE sem "leste" no nome (a partir de JUL) —
    o filtro por prefixo de setor em processar_produtividade separa LESTE corretamente.
    """
    arquivos = listar_arquivos(folder_id)
    mes_up   = mes.upper()
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
        if "leste" in nome and "produtividade" in nome and any(t in nome for t in termos_mes):
            return a
    for a in arquivos:
        nome = a["name"].lower()
        if "leste" not in nome and "produtividade" in nome and any(t in nome for t in termos_mes):
            return a
    return None


def encontrar_produto_leste(folder_id: str, mes: str, linha: str) -> dict | None:
    """
    Localiza o arquivo de Produto LESTE (NEXUS ou VITAL) do mês na pasta.
    Preferência: arquivo com "leste" explícito no nome (formato usado até JUN).
    Fallback: arquivo combinado OESTE+LESTE sem "leste" no nome (ex: a partir de
    JUL alguns meses vêm com as duas regionais no mesmo arquivo) — o filtro por
    prefixo de setor em processar_produto já separa LESTE corretamente.
    """
    arquivos = listar_arquivos(folder_id)
    mes_up   = mes.upper()
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
        if "leste" in nome and linha.lower() in nome and any(t in nome for t in termos_mes):
            return a
    for a in arquivos:
        nome = a["name"].lower()
        if "leste" not in nome and "spi" not in nome and linha.lower() in nome and any(t in nome for t in termos_mes):
            return a
    return None


def encontrar_qualquer_xlsx(folder_id: str) -> dict | None:
    """Retorna o primeiro xlsx/xls/xlsm na pasta (para jornada)."""
    arquivos = listar_arquivos(folder_id)
    for a in arquivos:
        if a["name"].lower().endswith((".xlsx", ".xls", ".xlsm")):
            return a
    return None


def encontrar_jornada_leste(folder_id: str) -> dict | None:
    """Localiza o arquivo de Jornada da Evolução da LESTE na pasta (pode conter outros arquivos regionais)."""
    arquivos = listar_arquivos(folder_id)
    for a in arquivos:
        if "leste" in a["name"].lower():
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


def is_leste(setor_id: str) -> bool:
    return setor_id.startswith("1105") or setor_id.startswith("1165")


def get_distrito_id(setor_id: str) -> str:
    return setor_id[:6] + "000"


def get_linha(setor_id: str) -> str:
    if setor_id.startswith("11030"):
        return "NEXUS"
    if setor_id.startswith("11630"):
        return "VITAL"
    return "DESCONHECIDO"


def get_linha_leste(setor_id: str) -> str:
    if setor_id.startswith("1105"):
        return "NEXUS"
    if setor_id.startswith("1165"):
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


def atualizar_gds_mapping(novos_gds: dict[str, str], distritos_key: str = "distritos"):
    """
    Atualiza os nomes de GD no mapping.json quando o arquivo mensal traz
    um nome diferente do registrado.
    novos_gds = {distrito_id: nome_completo_do_gd}
    distritos_key: "distritos" (SPI OESTE) ou "distritos_leste" (LESTE)
    """
    path = ROOT / "config/mapping.json"
    with open(path, encoding="utf-8") as f:
        mapping = json.load(f)

    atualizado = False
    for did, novo_nm in novos_gds.items():
        meta = mapping[distritos_key].get(did, {})
        antigo_nm = meta.get("nm", "")
        if novo_nm and novo_nm != antigo_nm:
            print(f"  📝 GD atualizado [{did}]: '{antigo_nm}' → '{novo_nm}'")
            mapping[distritos_key].setdefault(did, {})
            mapping[distritos_key][did]["nm"] = novo_nm
            mapping[distritos_key][did]["ab"] = abreviar_nome(novo_nm)
            atualizado = True

    if atualizado:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        print("  ✓ mapping.json atualizado com novos nomes de GD.")


# ── Processamento Produtividade ────────────────────────────────────────────────

def processar_produtividade(xlsx_bytes: bytes, mes: str, regional: str = "SPI") -> tuple[list, list]:
    """
    Retorna (linhas_distritos, linhas_reps).

    regional: "SPI" (SPI OESTE, prefixos 11030/11630) ou "LESTE" (prefixos 1105/1165).

    Princípio de estabilidade de identificadores:
      - setor_id   (8 dígitos) → NUNCA muda → chave primária do rep
      - distrito_id (6 dígitos + 000) → NUNCA muda → chave primária do distrito
      - nome do rep     → vem SEMPRE do arquivo do mês atual
      - nome do GD      → vem SEMPRE do arquivo do mês atual (col. Gerente se existir)
                          fallback: mapping.json (atualizado automaticamente quando há mudança)
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, linha_fn, distritos_key = is_leste, get_linha_leste, "distritos_leste"
    else:
        filtro_fn, linha_fn, distritos_key = is_spi, get_linha, "distritos"

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
        if not parsed or not filtro_fn(parsed["setor_id"]):
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
            "linha":           linha_fn(parsed["setor_id"]),
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
        atualizar_gds_mapping(gd_nomes_mes, distritos_key)
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
            meta = mapping[distritos_key].get(did, {})
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

    print(f"  ✓ Produtividade {regional}: {len(reps)} reps, {len(distritos)} distritos")
    return distritos, reps


# ── Processamento Produto ──────────────────────────────────────────────────────

def processar_produto(xlsx_bytes: bytes, mes: str, linha: str, regional: str = "SPI") -> tuple[list, list, list]:
    """
    Processa arquivo de produto.
    Tenta detectar se há quebra por rep/setor.

    Retorna:
        (registros_regional, registros_distrito, registros_rep)
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, ugn_esperada = is_leste, "LESTE"
    else:
        filtro_fn, ugn_esperada = is_spi, "SPI"

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

        ugn = str(row.get(col_ugn, ugn_esperada)).strip() if col_ugn else ugn_esperada
        if col_ugn and ugn.upper() != ugn_esperada:
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
            # Setor terminado em "00" é o SUBTOTAL do GD (soma dos reps do distrito),
            # não uma venda adicional — confirmado: GD_row == sum(reps do distrito).
            # Incluir essa linha junto com os reps individuais contaria tudo em dobro.
            if parsed and filtro_fn(parsed["setor_id"]) and not parsed["vago"] and not parsed["setor_id"].endswith("00"):
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

    # Remove produtos sem cota atribuída no mês (sem meta oficial — não deve
    # entrar no scorecard nem distorcer a média de atingimento por produto).
    produtos_com_cota = {r["produto"] for r in registros_rep if r["cota"] is not None}
    produtos_sem_cota = {r["produto"] for r in registros_rep} - produtos_com_cota
    if produtos_sem_cota:
        print(f"  ℹ  Produto(s) sem cota no mês — removido(s): {', '.join(sorted(produtos_sem_cota))}")
        registros_rep      = [r for r in registros_rep      if r["produto"] not in produtos_sem_cota]
        registros_regional = [r for r in registros_regional if r["produto"] not in produtos_sem_cota]

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


def encontrar_visitas_leste(folder_id: str, mes: str) -> dict | None:
    """Localiza o arquivo combinado (NEXUS+VITAL) de Visitas GD da LESTE para o mês."""
    arquivos = listar_arquivos(folder_id)
    mes_up   = mes.upper()
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
        if "leste" in nome and any(t in nome for t in termos_mes):
            return a
    return None


def processar_visitas(xlsx_bytes: bytes, mes: str, linha: str, regional: str = "SPI") -> list:
    """
    Processa arquivo de Visitas GD.
    Filtra apenas GDs da regional informada (SPI: 11030*/11630* · LESTE: 1105*/1165*).

    Colunas esperadas:
      Distrital           → 'setor_id - nome'  (setor_id termina em 00 → é o próprio GD)
      Real. Contatos      → contatos realizados
      Obj. Acomp. GDD     → objetivo de acompanhamentos
      Real. Acomp. GDD    → acompanhamentos realizados
      Cob. Acomp. GDD     → % cobertura (0-1 ou 0-100)
      Qtde. dias Acomp. GDD → dias de acompanhamento

    A coluna Distrital é a fonte mais confiável do nome do GD (o próprio GD é a
    linha), então este arquivo também sincroniza mapping.json automaticamente.
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, linha_fn, distritos_key = is_leste, get_linha_leste, "distritos_leste"
    else:
        filtro_fn, linha_fn, distritos_key = is_spi, get_linha, "distritos"

    df   = pd.read_excel(io.BytesIO(xlsx_bytes))
    col0 = df.columns[0]

    # Pré-varredura: sincroniza nomes de GD no mapping.json antes de montar os registros
    gd_nomes_mes: dict[str, str] = {}
    for _, row in df.iterrows():
        parsed = parse_setor(str(row.get(col0, "")).strip())
        if parsed and filtro_fn(parsed["setor_id"]):
            did = get_distrito_id(parsed["setor_id"])
            gd_nomes_mes[did] = "Vago" if parsed["vago"] else parsed["nome"]

    if gd_nomes_mes:
        atualizar_gds_mapping(gd_nomes_mes, distritos_key)

    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    registros = []
    for _, row in df.iterrows():
        distrital_raw = str(row.get(col0, "")).strip()
        parsed = parse_setor(distrital_raw)
        if not parsed or not filtro_fn(parsed["setor_id"]):
            continue
        if linha_fn(parsed["setor_id"]) != linha:
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
        meta        = mapping[distritos_key].get(distrito_id, {})

        registros.append({
            "mes":        mes,
            "linha":      linha,
            "setor_id":   parsed["setor_id"],
            "nome":       "Vago" if parsed["vago"] else parsed["nome"],
            "distrito_id": distrito_id,
            "ab":         meta.get("ab", ""),
            "contatos":   contatos,
            "obj":        obj,
            "real":       real,
            "cob_pct":    cob_pct,
            "dias":       dias,
        })

    print(f"  ✓ Visitas {linha} {mes} [{regional}]: {len(registros)} GDs")
    return registros


def eh_visitas_formato_distrital(xlsx_bytes: bytes) -> bool:
    """
    True se a primeira coluna do arquivo é 'Distrital' (formato antigo: 1 linha
    por GD). Qualquer outra coisa (ex: 'Setor') é o formato novo, por representante.
    Decide pela ESTRUTURA real do arquivo, não pelo nome — nome de arquivo sozinho
    não é confiável pra distinguir os dois formatos (já causou um bug real).
    """
    import pandas as pd
    df = pd.read_excel(io.BytesIO(xlsx_bytes), nrows=0)
    return str(df.columns[0]).strip().lower() == "distrital"


def encontrar_visitas_combinado(folder_id: str, mes: str) -> dict | None:
    """
    Localiza o arquivo de Visitas no formato novo (a partir de jul/2026): 1 linha
    por representante (coluna 'Setor', não mais 'Distrital'), combinado OESTE+LESTE,
    sem separação por linha no nome do arquivo (ex: 'VISITAS ACOMPANHADAS JULHO.xlsx').
    """
    arquivos = listar_arquivos(folder_id)
    mes_up   = mes.upper()
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
        if "visita" in nome and any(t in nome for t in termos_mes):
            return a
    return None


def processar_visitas_por_rep(xlsx_bytes: bytes, mes: str, linha: str, regional: str = "SPI") -> list:
    """
    Formato novo de Visitas GD (a partir de jul/2026): 1 linha por representante
    (Obj./Real. Acomp. GDD individuais), não mais 1 linha por GD ('Distrital').

    Agrega somando os reps de cada distrito, pra manter o mesmo contrato de saída
    de sempre (visitas_{linha}_{mes}: 1 registro por GD/distrito) — decisão
    confirmada com o usuário: soma dos reps do distrito = Obj./Real. do GD.
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, linha_fn, distritos_key = is_leste, get_linha_leste, "distritos_leste"
    else:
        filtro_fn, linha_fn, distritos_key = is_spi, get_linha, "distritos"

    df   = pd.read_excel(io.BytesIO(xlsx_bytes))
    col0 = df.columns[0]

    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    agg: dict = {}
    for _, row in df.iterrows():
        parsed = parse_setor(str(row.get(col0, "")).strip())
        if not parsed or parsed["vago"] or not filtro_fn(parsed["setor_id"]):
            continue
        if linha_fn(parsed["setor_id"]) != linha:
            continue

        did = get_distrito_id(parsed["setor_id"])
        if did not in agg:
            meta = mapping[distritos_key].get(did, {})
            agg[did] = {
                "distrito_id": did, "nm": meta.get("nm", ""), "ab": meta.get("ab", ""),
                "contatos": 0.0, "obj": 0.0, "real": 0.0, "dias": 0.0, "tem_real": False,
            }

        contatos = parse_float(row.get("Real. Contatos"))
        obj      = parse_float(row.get("Obj. Acomp. GDD"))
        real     = parse_float(row.get("Real. Acomp. GDD"))
        dias     = parse_float(row.get("Qtde. dias Acomp. GDD"))
        if contatos is not None: agg[did]["contatos"] += contatos
        if obj is not None:      agg[did]["obj"]      += obj
        if real is not None:
            agg[did]["real"] += real
            agg[did]["tem_real"] = True
        if dias is not None:     agg[did]["dias"] += dias

    registros = []
    for did, d in agg.items():
        obj  = d["obj"] or None
        real = d["real"] if d["tem_real"] else None
        cob_pct = round(real / obj * 100, 1) if (real is not None and obj and obj > 0) else None
        registros.append({
            "mes":        mes,
            "linha":      linha,
            "setor_id":   did,
            "nome":       d["nm"],
            "distrito_id": did,
            "ab":         d["ab"],
            "contatos":   d["contatos"] or None,
            "obj":        obj,
            "real":       real,
            "cob_pct":    cob_pct,
            "dias":       round(d["dias"], 1) if d["dias"] else None,
        })

    print(f"  ✓ Visitas (por rep, agregado por distrito) {linha} {mes} [{regional}]: {len(registros)} distritos")
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
        if "pex" in nome and "leste" not in nome and any(t in nome for t in termos):
            return a
    # Fallback: qualquer xlsx na pasta (exclui arquivos LESTE)
    for a in arquivos:
        if a["name"].lower().endswith((".xlsx", ".xls", ".xlsm")) and "leste" not in a["name"].lower():
            return a
    return None


def encontrar_pex_leste(folder_id: str, mes: str) -> dict | None:
    """Encontra o arquivo PEX LESTE do mês na pasta (ex: 'PEX ABRIL LESTE')."""
    arquivos = listar_arquivos(folder_id)
    meses_map = {
        "JAN": ["jan","janeiro"], "FEV": ["fev","fevereiro"],
        "MAR": ["mar","marco","março"], "ABR": ["abr","abril"],
        "MAI": ["mai","maio"], "JUN": ["jun","junho"],
        "JUL": ["jul","julho"], "AGO": ["ago","agosto"],
        "SET": ["set","setembro"], "OUT": ["out","outubro"],
        "NOV": ["nov","novembro"], "DEZ": ["dez","dezembro"],
    }
    termos = meses_map.get(mes.upper(), [mes.lower()])
    for a in arquivos:
        nome = a["name"].lower()
        if "pex" in nome and "leste" in nome and any(t in nome for t in termos):
            return a
    return None


def processar_pex(xlsx_bytes: bytes, mes: str, regional: str = "SPI") -> list:
    """
    Lê o arquivo PEX mensal.
    Colunas: SETOR, NOME, FRENTE, MEDAL (URL ícone), PT. (score 0-100), PTS. MAX.
    Filtra pela regional informada e deriva medalha pelo score.
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, linha_fn, distritos_key = is_leste, get_linha_leste, "distritos_leste"
    else:
        filtro_fn, linha_fn, distritos_key = is_spi, get_linha, "distritos"

    df = pd.read_excel(io.BytesIO(xlsx_bytes))
    print(f"  → Colunas PEX: {list(df.columns)}")

    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    # Detectar colunas flexivelmente
    col_setor  = detect_col(df.columns, ["setor"])       or df.columns[0]
    col_nome   = detect_col(df.columns, ["nome"])        or df.columns[1]
    col_pts    = detect_col(df.columns, ["pontuacao pex", "pt.", "pontos", "score", "pts"])
    col_medal  = detect_col(df.columns, ["medal"])

    registros = []
    for _, row in df.iterrows():
        setor_id = str(row.get(col_setor, "")).strip()
        if not setor_id.isdigit() or not filtro_fn(setor_id):
            continue

        nome   = str(row.get(col_nome, "")).strip()
        pts    = parse_float(row.get(col_pts)) if col_pts else None
        if pts is None:
            continue

        # Medalha: URL do ícone → fallback score
        url_val  = str(row.get(col_medal, "")).strip() if col_medal else ""
        medalha  = get_medalha_url(url_val) or get_medalha_pts(pts)

        distrito_id = get_distrito_id(setor_id)
        linha       = linha_fn(setor_id)
        meta        = mapping[distritos_key].get(distrito_id, {})

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
    print(f"  ✓ PEX {mes} [{regional}]: {len(registros)} representantes classificados")
    return registros


# ── Processamento Jornada da Evolução ─────────────────────────────────────────

def processar_jornada(xlsx_bytes: bytes, regional: str = "SPI") -> list:
    """
    Lê o arquivo de Jornada da Evolução.
    Estrutura esperada: colunas separadas 'Setor' (código), 'Colaborador' (nome) e 'Posição atual'.
    Também suporta formato legado 'XXXXXXXX - Nome' em coluna única.
    Níveis válidos: Start, Performance, Destaque.

    O arquivo pode trazer representantes de outras regionais (export nacional) —
    filtra_fn restringe apenas aos setores da regional pedida.
    """
    import pandas as pd

    if regional == "LESTE":
        filtro_fn, linha_fn = is_leste, get_linha_leste
    else:
        filtro_fn, linha_fn = is_spi, get_linha

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
            if setor_id and setor_id.isdigit() and filtro_fn(setor_id):
                registros.append({
                    "setor_id":      setor_id,
                    "nome":          nome,
                    "distrito_id":   get_distrito_id(setor_id),
                    "linha":         linha_fn(setor_id),
                    "classificacao": classif,
                })
            elif regional == "SPI" and nome and nome.lower() not in ("nan", "none"):
                # SPI não identificado mas tem nome — guarda sem setor (comportamento legado;
                # não se aplica à LESTE pois o arquivo é compartilhado entre regionais)
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
            if parsed and filtro_fn(parsed["setor_id"]):
                registros.append({
                    "setor_id":      parsed["setor_id"],
                    "nome":          parsed["nome"],
                    "distrito_id":   get_distrito_id(parsed["setor_id"]),
                    "linha":         linha_fn(parsed["setor_id"]),
                    "classificacao": classif,
                })

    print(f"  ✓ Jornada {regional}: {len(registros)} representantes classificados")
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


def atualizar_config_aba(gc, sh, mes: str, aba: str = "config", regional_label: str = "SPI OESTE"):
    import gspread
    from datetime import datetime

    try:
        ws = sh.worksheet(aba)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=aba, rows=20, cols=5)

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
        ["regional", regional_label],
        ["divisao", "Cardiometabolico"]
    ])
    print(f"  ✓ Config '{aba}' atualizada: meses disponíveis = {meses}")


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

def criar_stubs_sem_produtividade(mes: str, rep_nex: list, rep_vit: list, regional: str = "SPI") -> tuple[list, list]:
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

    A classificação da Jornada da Evolução (Destaque/Performance/Start) NÃO é
    tocada aqui — o front-end busca em jornada_LESTE/jornada por nome/setor_id
    e já cai em "Start" automaticamente pra quem não estiver lá (ex: contratação
    recente ainda não reportada no arquivo de jornada).
    """
    distritos_key = "distritos_leste" if regional == "LESTE" else "distritos"
    with open(ROOT / "config/mapping.json") as f:
        mapping = json.load(f)

    # Extrai reps únicos: chave = setor_id (estável), nome = do arquivo do mês.
    # Setor terminado em "00" é o próprio GD (pool pessoal dele no arquivo de
    # produto) — não é um rep da equipe, então fica de fora daqui.
    reps_map: dict = {}
    for r in rep_nex + rep_vit:
        sid = r["setor_id"]
        if sid and sid.endswith("00"):
            continue
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
            meta = mapping[distritos_key].get(did, {})
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
    parser.add_argument("--regional",     choices=["SPI", "LESTE"], default="SPI",
                        help="Regional a ingerir com --mes (default: SPI OESTE). LESTE ingere só Produtividade → abas *_LESTE_{mes}.")
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

        if jornada_folder and args.regional == "LESTE":
            arq_jornada = encontrar_jornada_leste(jornada_folder)
            if not arq_jornada:
                print("❌ Nenhum arquivo de Jornada LESTE encontrado na pasta.")
            else:
                print(f"📥 Baixando jornada LESTE: {arq_jornada['name']}...")
                xlsx_jornada = baixar_xlsx(arq_jornada["id"])
                jornada_data = processar_jornada(xlsx_jornada, regional="LESTE")
                escrever_aba(gc, sh, "jornada_LESTE", jornada_data, force=True)  # sempre sobrescreve
                print("✅ Jornada LESTE atualizada.\n")
        elif jornada_folder:
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
    if args.mes and args.regional == "LESTE":
        mes = args.mes.upper()
        print(f"\n══ INGESTÃO LESTE {mes}/2026 ══\n")

        folder_produto = os.getenv("DRIVE_PRODUTO") or os.getenv("DRIVE_DADOS_FOLDER")

        rep_nex, rep_vit = [], []
        for linha_produto in ["NEXUS", "VITAL"]:
            print(f"\n📥 Baixando Produto {linha_produto} LESTE...")
            arq_p = encontrar_produto_leste(folder_produto, mes, linha_produto)
            if arq_p:
                print(f"  → {arq_p['name']}")
                xlsx_p = baixar_xlsx(arq_p["id"])
                reg_p, dist_p, rep_p = processar_produto(xlsx_p, mes, linha_produto, regional="LESTE")
                escrever_aba(gc, sh, f"produtos_{linha_produto}_LESTE_{mes}",      reg_p,  args.force)
                escrever_aba(gc, sh, f"produtos_dist_{linha_produto}_LESTE_{mes}", dist_p, args.force)
                escrever_aba(gc, sh, f"produtos_rep_{linha_produto}_LESTE_{mes}",  rep_p,  args.force)
                if linha_produto == "NEXUS": rep_nex = rep_p
                else: rep_vit = rep_p
            else:
                print(f"  ⚠  Produto {linha_produto} LESTE {mes} não encontrado — ignorando")

        print(f"\n📥 Procurando Produtividade LESTE...")
        folder_prod = os.getenv("DRIVE_PRODUTIVIDADE") or os.getenv("DRIVE_DADOS_FOLDER")
        arq_prod = encontrar_produtividade_leste(folder_prod, mes)
        if not arq_prod:
            print(f"⚠  Arquivo Produtividade LESTE {mes} não encontrado — gerando stubs a partir do Produto")
            print(f"   Identificador estável: setor_id / distrito_id")
            print(f"   Jornada da Evolução: mantida (lookup por nome/setor_id em jornada_LESTE,")
            print(f"   quem não estiver lá cai em 'Start' — ex: contratação recente)")
            distritos, reps = criar_stubs_sem_produtividade(mes, rep_nex, rep_vit, regional="LESTE")
        else:
            print(f"  → {arq_prod['name']}")
            xlsx_prod = baixar_xlsx(arq_prod["id"])
            distritos, reps = processar_produtividade(xlsx_prod, mes, regional="LESTE")

        escrever_aba(gc, sh, f"distritos_LESTE_{mes}", distritos, args.force)
        escrever_aba(gc, sh, f"reps_LESTE_{mes}",      reps,      args.force)

        print("\n📋 Atualizando config_LESTE...")
        atualizar_config_aba(gc, sh, mes, aba="config_LESTE", regional_label="LESTE")

        print(f"\n✅ Ingestão LESTE {mes} concluída.\n")

    elif args.mes:
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

        pex_folder = os.getenv("DRIVE_PEX")
        if not pex_folder:
            print("❌ DRIVE_PEX não configurado no .env")
            sys.exit(1)

        if args.regional == "LESTE":
            print(f"\n══ PEX LESTE {mes}/2026 ══\n")
            arq_pex = encontrar_pex_leste(pex_folder, mes)
            if not arq_pex:
                print(f"❌ Arquivo PEX LESTE {mes} não encontrado na pasta DRIVE_PEX.")
                sys.exit(1)
            print(f"📥 Baixando PEX LESTE: {arq_pex['name']}...")
            xlsx_pex = baixar_xlsx(arq_pex["id"])
            pex_data = processar_pex(xlsx_pex, mes, regional="LESTE")
            escrever_aba(gc, sh, f"pex_LESTE_{mes}", pex_data, force=True)  # sempre sobrescreve
            print(f"✅ PEX LESTE {mes} atualizado.\n")
        else:
            print(f"\n══ PEX {mes}/2026 ══\n")
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

        visitas_folder = os.getenv("DRIVE_VISITAS_GD")
        if not visitas_folder:
            print("❌ DRIVE_VISITAS_GD não configurado no .env")
            sys.exit(1)

        if args.regional == "LESTE":
            print(f"\n══ VISITAS GD LESTE {mes}/2026 ══\n")
            processado = False
            arq = encontrar_visitas_leste(visitas_folder, mes)
            if arq:
                xlsx_bytes = baixar_xlsx(arq["id"])
                if eh_visitas_formato_distrital(xlsx_bytes):
                    print(f"📥 Visitas LESTE {mes} (formato Distrital) → {arq['name']}")
                    for linha in ["NEXUS", "VITAL"]:
                        dados = processar_visitas(xlsx_bytes, mes, linha, regional="LESTE")
                        if dados:
                            escrever_aba(gc, sh, f"visitas_{linha}_LESTE_{mes}", dados, args.force)
                    processado = True
                # se não for Distrital, ignora este achado — cai pro formato novo abaixo
            if not processado:
                arq = encontrar_visitas_combinado(visitas_folder, mes)
                if arq:
                    xlsx_bytes = baixar_xlsx(arq["id"])
                    if eh_visitas_formato_distrital(xlsx_bytes):
                        print(f"⚠  Arquivo '{arq['name']}' é formato Distrital mas não achado como tal — verifique o nome do arquivo.")
                    else:
                        print(f"📥 Visitas {mes} (formato novo, por representante) → {arq['name']}")
                        for linha in ["NEXUS", "VITAL"]:
                            dados = processar_visitas_por_rep(xlsx_bytes, mes, linha, regional="LESTE")
                            if dados:
                                escrever_aba(gc, sh, f"visitas_{linha}_LESTE_{mes}", dados, args.force)
                        processado = True
            if not processado:
                print(f"  ⚠  Nenhum arquivo de Visitas LESTE {mes} encontrado — ignorando")
            print(f"\n✅ Visitas GD LESTE {mes} concluído.\n")
        else:
            print(f"\n══ VISITAS GD {mes}/2026 ══\n")
            processado = False
            for linha in ["NEXUS", "VITAL"]:
                arq = encontrar_visitas(visitas_folder, mes, linha)
                if not arq:
                    continue
                xlsx_bytes = baixar_xlsx(arq["id"])
                if not eh_visitas_formato_distrital(xlsx_bytes):
                    continue  # provavelmente é o arquivo novo combinado — tratado abaixo
                print(f"📥 Visitas {linha} {mes} (formato Distrital) → {arq['name']}")
                dados = processar_visitas(xlsx_bytes, mes, linha)
                if dados:
                    escrever_aba(gc, sh, f"visitas_{linha}_{mes}", dados, args.force)
                    processado = True
            if not processado:
                arq = encontrar_visitas_combinado(visitas_folder, mes)
                if arq:
                    xlsx_bytes = baixar_xlsx(arq["id"])
                    if eh_visitas_formato_distrital(xlsx_bytes):
                        print(f"⚠  Arquivo '{arq['name']}' é formato Distrital mas não achado como tal — verifique o nome do arquivo.")
                    else:
                        print(f"📥 Visitas {mes} (formato novo, por representante) → {arq['name']}")
                        for linha in ["NEXUS", "VITAL"]:
                            dados = processar_visitas_por_rep(xlsx_bytes, mes, linha)
                            if dados:
                                escrever_aba(gc, sh, f"visitas_{linha}_{mes}", dados, args.force)
                        processado = True
            if not processado:
                print(f"  ⚠  Nenhum arquivo de Visitas {mes} encontrado — ignorando")
            print(f"\n✅ Visitas GD {mes} concluído.\n")


if __name__ == "__main__":
    main()
