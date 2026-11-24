# Roteiro do vídeo (10 a 15 min)

Divida as falas entre os integrantes (I1, I2, I3...). Antes de gravar:
`docker compose up -d --build`, deixe abertas as abas do VS Code, do terminal, do
Locust (:8089), do Prometheus (:9090/targets) e do Grafana (:3000, dashboard AutoFlow,
intervalo "Last 15 minutes"). Rode o `rodar_comparativo` **antes** da gravação para
já ter os números do baseline e do otimizado.

| Tempo | Quem | O que mostrar | O que falar (resumo) |
|---|---|---|---|
| 0:00–2:00 | I1 | README (diagrama Mermaid) | Problema de negócio: o site de uma loja de veículos recebe picos de acesso (feirão, anúncio patrocinado). O monolito ingênuo tem N+1, não usa pool, cache nem gzip e roda em `app.run()`. A arquitetura nova tem Gateway, Estoque (2 réplicas atrás do Nginx) e Propostas. |
| 2:00–3:00 | I2 | `comum/metricas.py`, `prometheus.yml`, :9090/targets | Os três tipos de métrica, as métricas de negócio (visualizações por marca, propostas, ticket médio), o modelo pull e os 5 alvos UP. |
| 3:00–5:00 | I2 | `estoque/app.py` (as duas funções de listagem) + Grafana | Rodar o Locust com `MODO_CONSULTA=n1`, mostrar o painel "Queries por requisição" em ~51 e o painel de conexões. Trocar para JOIN e mostrar a linha caindo para 1. Citar o batching de `/propostas/resumo`. |
| 5:00–6:00 | I3 | `docker compose logs estoque-1` | Gunicorn gthread no lugar do `app.run()`. Explicar por que usamos 1 worker com threads mais réplicas. |
| 6:00–7:00 | I3 | `curl -D -` com gzip, `otimizacoes.py` | Content-Encoding gzip, tamanho original x comprimido (≈ 82% menor) e Cache-Control. |
| 7:00–8:00 | I3 | `cache.py` + painel de Cache Hit | LRU com OrderedDict (O(1)), TTL de 30 s e os 100 carros em destaque recebendo 80% das visitas: taxa de acerto acima de 80%. Busca por placa com dict O(1) contra lista O(n). |
| 8:00–13:00 | I4 | Locust com 150 usuários + Grafana + terminal | Mostrar P95/P99 estáveis e o RPS por réplica (round robin). Rodar `python scripts/experimento_caos.py`. Quando o caos liga: alguns retries, o breaker vai para **ABERTO** (vermelho), os fallbacks/s sobem e a disponibilidade continua perto de 100%. Abrir `/api/veiculos/7` no navegador e mostrar o anúncio no ar com `"indisponivel": true` nas propostas. Enviar uma proposta e mostrar o 202. Quando o caos desliga: **MEIO-ABERTO** e depois **FECHADO**, e a fila de propostas pendentes zera. Mostrar `resiliencia.py` (os três estados). |
| 13:00–15:00 | I1 | Tabela de `comparar_resultados.py` | Números antes x depois (RPS, P50, P95, P99, erro). Lições: medir antes de otimizar, o N+1 é invisível sem métricas e resiliência se prova com caos. |

Dicas: grave em 1080p, aumente a fonte do terminal e do VS Code e use o OBS Studio
(grátis) para capturar a tela. Se o vídeo passar de 15 min, corte as pausas do Locust.
