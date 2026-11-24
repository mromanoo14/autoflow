#!/usr/bin/env bash
# Roda o mesmo teste de carga no baseline e na versão otimizada e compara.
set -e
USUARIOS=${USUARIOS:-150}; DURACAO=${DURACAO:-3m}
for alvo in "baseline http://monolito:8001" "otimizado http://gateway:8000"; do
  set -- $alvo
  echo ">> Teste $1 ($USUARIOS usuários, $DURACAO)"
  docker compose run --rm locust -f /mnt/locust/locustfile.py --headless \
    -u "$USUARIOS" -r 15 -t "$DURACAO" --host "$2" \
    --csv "/mnt/resultados/$1" --html "/mnt/resultados/$1.html"
  sleep 20
done
PY=$(command -v python3 || command -v python || true)
if [ -n "$PY" ]; then
  "$PY" scripts/comparar_resultados.py resultados/baseline resultados/otimizado
else
  echo "Python não encontrado: veja os números em resultados/baseline.html e resultados/otimizado.html"
fi
