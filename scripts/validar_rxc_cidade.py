import json, glob, re, os, sys
MES = sys.argv[1] if len(sys.argv) > 1 else "AGO"
P = "C:/Users/vinic/ems-n4-dashboard/inputs_powerbi/mercado/"
def num(t):
    t = str(t).replace("\xa0"," ").replace("%","").replace(".","").replace(",",".").strip()
    try: return float(t)
    except: return None
cid = {}
for f in glob.glob(P + f"RX_*_CIDADE_{MES}.json"):
    m = re.match(rf"RX_(.+)_(NEXUS|VITAL)_SPI_CIDADE_{MES}", os.path.basename(f)[:-5])
    for r in json.load(open(f, encoding="utf-8"))["rows"]:
        c = r[0].replace("\xa0"," ").upper()
        if c == "TOTAL": continue
        cid[(m.group(1), m.group(2), c)] = num(r[3]) if len(r) >= 5 else (num(r[3]) if len(r) == 4 and "%" in r[3] else 0.0)
ok = bad = 0; por = {}; lidas = {}
for f in sorted(glob.glob(P + f"RXC_*_CID-*_{MES}.json")):
    m = re.match(rf"RXC_(.+)_(NEXUS|VITAL)_SPI_CID-(.+)_{MES}", os.path.basename(f)[:-5])
    marca, linha, c = m.group(1), m.group(2), m.group(3).replace("-"," ")
    por[linha] = por.get(linha, 0) + 1
    lidas.setdefault((linha, c), []).append(marca)
    rows = json.load(open(f, encoding="utf-8"))["rows"]
    ems = [r for r in rows if r[0].replace("\xa0"," ").upper().startswith(marca.replace("_"," ")+" (EMS)")]
    if ems:
        vals = ems[0][1:]
        if len(vals) >= 3: s = num(vals[1])
        elif len(vals) == 2: s = num(vals[1]) if "%" in str(vals[1]) else (0.0 if (num(vals[1]) or 0) < 0 else num(vals[0]))
        else: s = num(vals[0]) if "%" in str(vals[0]) else None
    else: s = 0.0
    rs = cid.get((marca, linha, c))
    if rs is None: flag = "SEM REF"
    elif s is None or abs(s - rs) > 1.5: flag = f"DIVERGE ems {s} vs cidade {rs}"
    else: flag = ""
    if flag: bad += 1; print(os.path.basename(f), flag)
    else: ok += 1
print("ok", ok, "| problemas", bad, "| por linha", por)
for k, v in sorted(lidas.items()):
    if len(v) < (3 if k[0] == "NEXUS" else 4): print("  incompleta", k, v)
