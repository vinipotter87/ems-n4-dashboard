# salvar_leitura_mercado.ps1 — grava em inputs_powerbi/mercado/ as tabelas que o leitor do Raio X
# (scripts/raiox_leitor.js, window.__clipAll('TAG')) copiou para a área de transferência.
# Uso:  powershell -File scripts\salvar_leitura_mercado.ps1 -Tag TAG
# Só grava se a etiqueta bater e se cada tabela tiver o número de linhas esperado.
param([Parameter(Mandatory = $true)][string]$Tag)

$t = Get-Clipboard -Raw
try { $j = $t | ConvertFrom-Json } catch { Write-Output "FALHA: a area de transferencia nao tem JSON (outra coisa foi copiada). Refaca o __clipAll e rode de novo."; exit 1 }
if ($j.tag -ne $Tag) { Write-Output "FALHA: etiqueta '$($j.tag)', esperado '$Tag'. Refaca o __clipAll e rode de novo."; exit 1 }

$raiz = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $env:TEMP "mercado_lote.json"
[IO.File]::WriteAllText($tmp, $t, (New-Object Text.UTF8Encoding $false))

$py = @'
import json, sys, pathlib
lote = json.load(open(sys.argv[1], encoding="utf-8"))
dest = pathlib.Path(sys.argv[2]) / "inputs_powerbi" / "mercado"
dest.mkdir(parents=True, exist_ok=True)
falhas = 0
for r in lote["items"]:
    ok = len(r["rows"]) == r["expected"]
    if ok:
        (dest / (r["name"] + ".json")).write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    else:
        falhas += 1
    print(("OK   " if ok else "FALHA"), r["name"], len(r["rows"]), "/", r["expected"])
sys.exit(1 if falhas else 0)
'@
$pyf = Join-Path $env:TEMP "mercado_lote.py"
[IO.File]::WriteAllText($pyf, $py, (New-Object Text.UTF8Encoding $false))
$env:PYTHONIOENCODING = "utf-8"
python $pyf $tmp $raiz
exit $LASTEXITCODE
