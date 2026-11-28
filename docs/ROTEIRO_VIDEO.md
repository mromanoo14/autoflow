# Roteiro do vídeo (10 a 15 min)

Segue os 5 blocos obrigatórios do enunciado. Escrito para 5 integrantes (I1 a I5).
No Windows, rode os comandos no **Git Bash**.

## Antes de gravar (uns 30 minutos antes)

1. `docker compose up -d --build` e conferir os 5 alvos **UP** em http://localhost:9090/targets.
2. Rodar `./scripts/rodar_comparativo.sh` (cerca de 7 min) e guardar a tabela que ele imprime
   (sem Python, os números estão em `resultados/*.html`).
3. Abrir: VS Code, Git Bash, Locust (:8089), Prometheus (:9090/targets), Grafana (:3000, admin/admin,
   dashboard AutoFlow, "Last 15 minutes", atualização 5s) e o README no GitHub (diagrama).
4. Uns 2 minutos antes do bloco 2, deixar duas cargas em segundo plano, cada uma num terminal:
   ```bash
   docker compose run --rm -e MODO_CONSULTA=n1 locust -f /mnt/locust/locustfile.py --headless -u 50 -r 10 -t 10m --host http://gateway:8000
   docker compose run --rm locust -f /mnt/locust/locustfile.py --headless -u 20 -r 5 -t 10m --host http://monolito:8001
   ```

## Blocos

| Tempo | Quem | Na tela | Pontos da fala |
|---|---|---|---|
| **1. Introdução e Arquitetura** 0:00–2:00 | I1 | README (diagrama), `docker compose ps` | Problema de negócio: picos de acesso em feirões e campanhas derrubam o site e a loja perde clientes. Monolito ingênuo (8001) contra Gateway + Estoque (2 réplicas, Nginx Round Robin, eixo X do AKF) + Propostas (8000). |
| **2. Observabilidade e BD** 2:00–3:00 | I2 | `comum/metricas.py`, :8000/metrics, `prometheus.yml`, :9090/targets | Counter, Gauge e Histogram; métricas de negócio; modelo pull a cada 5 s; 5 alvos UP. |
| 3:00–5:00 | I2 | `estoque/app.py`, terminal, painel "Queries SQL por requisição" | `curl -sI "localhost:8080/veiculos?modo=n1" \| grep X-DB-Queries` (51) e `modo=join` (1). Ctrl+C na carga N+1 e rodar a mesma sem `-e MODO_CONSULTA=n1`: a linha cai de 51 para 1 em menos de 1 min. Monolito segue em 101. Painel de conexões: sem pool vs com pool. |
| **3. Rede, Cache e Plataforma** 5:00–6:00 | I3 | `docker compose logs monolito \| head -8` e `docker compose logs estoque-1 \| head -8` | Aviso "development server" no monolito; "Starting gunicorn" + gthread nos serviços. |
| 6:00–7:00 | I3 | curl com `Accept-Encoding: gzip` nas portas 8001 e 8000, `otimizacoes.py`, painel de bytes/s | 12,8 KB sem gzip contra ~2,3 KB com gzip (−82%); Cache-Control. |
| 7:00–8:00 | I3 | `cache.py`, painéis "Taxa de Cache Hit" e "Hit vs Miss" | LRU (OrderedDict, 256 itens, TTL 30 s), distribuição 80/20, hit > 80%. `curl -X POST localhost:8080/cache/limpar` (2x) e as faltas sobem e voltam. Busca por placa O(1). Depois, Ctrl+C nas duas cargas. |
| **4. Carga e Caos ao vivo** 8:00–9:30 | I4 | Locust: 150 usuários, ramp 15, host `http://gateway:8000`; painel P50/P95/P99 | Think time 1–3 s; leitura de P95 e P99 (colunas 95%ile e 99%ile). |
| 9:30–10:00 | I5 | `python scripts/experimento_caos.py --antes 30 --durante 90 --depois 45` | Hipótese: com Propostas fora, ≥ 99% sem 5xx e os anúncios no ar. |
| 10:00–11:30 | I5 | Painéis de resiliência, :8000/api/veiculos/7, `resiliencia.py` | Retries → breaker ABERTO → fallback; disponibilidade ~100%; falhas 0 no Locust; proposta recebe 202. |
| 11:30–13:00 | I5 | Grafana, :8000/api/resiliencia | MEIO-ABERTO → FECHADO; fila de propostas zera; hipótese confirmada (ou explicar o que houve). |
| **5. Conclusão** 13:00–14:30 | Todos | Tabela antes x depois | RPS, P50, P95, P99 e erro, antes x depois; uma lição por integrante. |

Sem Python no host, ative o caos pelo navegador: http://localhost:5002/caos/ativar-falha?modo=erro e,
90 s depois, http://localhost:5002/caos/desativar.

Dicas: gravem bloco por bloco (OBS Studio) e juntem no final (Clipchamp). Se a máquina sofrer com 150
usuários, usem 100 (o mínimo pedido) e deem pelo menos 6 GB de memória ao Docker Desktop.
