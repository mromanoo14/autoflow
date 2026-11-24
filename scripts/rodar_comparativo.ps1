# Windows (PowerShell): roda baseline e otimizado e compara
$Usuarios = if ($env:USUARIOS) { $env:USUARIOS } else { 150 }
$Duracao  = if ($env:DURACAO)  { $env:DURACAO }  else { "3m" }
$alvos = @(@("baseline","http://monolito:8001"), @("otimizado","http://gateway:8000"))
foreach ($a in $alvos) {
  Write-Host ">> Teste $($a[0]) ($Usuarios usuarios, $Duracao)"
  docker compose run --rm locust -f /mnt/locust/locustfile.py --headless `
    -u $Usuarios -r 15 -t $Duracao --host $a[1] `
    --csv "/mnt/resultados/$($a[0])" --html "/mnt/resultados/$($a[0]).html"
  Start-Sleep -Seconds 20
}
python scripts/comparar_resultados.py resultados/baseline resultados/otimizado
