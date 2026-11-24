"""
Etapa 1 - Medição e Observabilidade.

Todas as métricas do sistema ficam aqui, para que monolito e microsserviços
usem exatamente os mesmos nomes e o Grafana consiga compará-los lado a lado.

Tipos usados (exigidos no enunciado):
  - Counter   -> só cresce (requisições, erros, queries, cache hit/miss...)
  - Gauge     -> sobe e desce (requisições em andamento, estado do circuit breaker...)
  - Histogram -> distribuição (latência, queries por requisição) -> permite P50/P95/P99
"""
import os
import time

from flask import Response, g, request
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram,
                               generate_latest)

SERVICO = os.getenv("SERVICO", "desconhecido")
INSTANCIA = os.getenv("INSTANCIA", SERVICO)

# ---------------------------------------------------------------- HTTP (RED)
HTTP_REQUESTS = Counter(
    "http_requests_total", "Total de requisições HTTP recebidas",
    ["servico", "instancia", "metodo", "endpoint", "status"])

HTTP_ERRORS = Counter(
    "http_errors_total", "Respostas de erro HTTP por classe (4xx/5xx)",
    ["servico", "instancia", "endpoint", "classe"])

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "Latência das requisições HTTP",
    ["servico", "instancia", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75,
             1.0, 2.5, 5.0, 10.0))

HTTP_IN_PROGRESS = Gauge(
    "http_requests_in_progress", "Requisições sendo processadas agora",
    ["servico", "instancia"])

HTTP_RESPONSE_BYTES = Counter(
    "http_response_bytes_total", "Bytes enviados no corpo das respostas",
    ["servico", "instancia", "comprimido"])

# ---------------------------------------------------------------- Banco de dados
DB_QUERIES = Counter(
    "db_queries_total", "Total de queries SQL executadas",
    ["servico", "instancia", "endpoint"])

DB_QUERIES_PER_REQUEST = Histogram(
    "db_queries_per_request", "Quantidade de queries SQL por requisição HTTP",
    ["servico", "instancia", "endpoint"],
    buckets=(0, 1, 2, 3, 5, 10, 25, 50, 100, 250, 500))

DB_CONNECTIONS_OPENED = Counter(
    "db_connections_opened_total",
    "Conexões físicas abertas com o banco (sem pool = 1 por query)",
    ["servico", "instancia"])

DB_POOL_IN_USE = Gauge(
    "db_pool_connections_in_use", "Conexões do pool emprestadas neste momento",
    ["servico", "instancia"])

# ---------------------------------------------------------------- Cache
CACHE_HITS = Counter("cache_hits_total", "Acertos de cache",
                     ["servico", "instancia", "cache"])
CACHE_MISSES = Counter("cache_misses_total", "Faltas de cache",
                       ["servico", "instancia", "cache"])
CACHE_SIZE = Gauge("cache_size", "Itens atualmente no cache",
                   ["servico", "instancia", "cache"])

# ---------------------------------------------------------------- Resiliência
CB_STATE = Gauge(
    "circuit_breaker_state",
    "Estado do circuit breaker (0=Fechado, 1=Aberto, 2=Meio-Aberto)",
    ["servico", "instancia", "destino"])
CB_TRANSITIONS = Counter(
    "circuit_breaker_transitions_total", "Mudanças de estado do circuit breaker",
    ["servico", "instancia", "destino", "para"])
CLIENT_RETRIES = Counter(
    "http_client_retries_total", "Retentativas feitas em chamadas entre serviços",
    ["servico", "instancia", "destino"])
FALLBACKS = Counter(
    "fallbacks_total", "Respostas servidas por fallback (degradação controlada)",
    ["servico", "instancia", "destino"])
CLIENT_LATENCY = Histogram(
    "http_client_request_duration_seconds",
    "Latência das chamadas de saída para outros serviços",
    ["servico", "instancia", "destino", "resultado"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0))

CHAOS_ACTIVE = Gauge("chaos_active", "1 quando a injeção de falhas está ligada",
                     ["servico", "instancia", "modo"])

# ---------------------------------------------------------------- Negócio
VEICULOS_VISUALIZADOS = Counter(
    "negocio_veiculos_visualizados_total", "Páginas de veículo visualizadas",
    ["servico", "marca"])
PROPOSTAS_CRIADAS = Counter(
    "negocio_propostas_criadas_total", "Propostas de compra registradas",
    ["servico", "forma_pagamento"])
VALOR_PROPOSTAS = Counter(
    "negocio_valor_propostas_reais_total",
    "Soma dos valores ofertados nas propostas (R$)", ["servico"])
TICKET_MEDIO = Gauge(
    "negocio_ticket_medio_propostas_reais",
    "Valor médio (R$) das últimas 100 propostas recebidas", ["servico"])


def rotulos():
    return {"servico": SERVICO, "instancia": INSTANCIA}


def endpoint_atual():
    """Usa a *regra* da rota (/veiculos/<int:veiculo_id>) e não a URL, para não
    explodir a cardinalidade das séries no Prometheus."""
    try:
        if request.url_rule is not None:
            return request.url_rule.rule
    except RuntimeError:  # fora de contexto de requisição (ex.: seed)
        return "fora_de_requisicao"
    return "rota_inexistente"


def contar_query():
    """Chamado pela camada de banco a cada SQL executado."""
    endpoint = endpoint_atual()
    DB_QUERIES.labels(**rotulos(), endpoint=endpoint).inc()
    try:
        g.db_queries = getattr(g, "db_queries", 0) + 1
    except RuntimeError:
        pass


def instrumentar(app):
    """Registra hooks no Flask e expõe /metrics (modelo Pull do Prometheus).

    IMPORTANTE: chame instrumentar() ANTES de ativar a compressão; o Flask
    executa os after_request em ordem inversa, então assim a compressão roda
    primeiro e aqui medimos o tamanho real (já comprimido) da resposta."""

    @app.before_request
    def _inicio():
        if request.path == "/metrics":
            return
        g.inicio = time.perf_counter()
        g.db_queries = 0
        g.instrumentado = True
        HTTP_IN_PROGRESS.labels(**rotulos()).inc()

    @app.after_request
    def _fim(resposta):
        if not getattr(g, "instrumentado", False):
            return resposta
        endpoint = endpoint_atual()
        duracao = time.perf_counter() - g.inicio
        status = resposta.status_code

        HTTP_REQUESTS.labels(**rotulos(), metodo=request.method,
                             endpoint=endpoint, status=str(status)).inc()
        HTTP_LATENCY.labels(**rotulos(), endpoint=endpoint).observe(duracao)
        if status >= 400:
            HTTP_ERRORS.labels(**rotulos(), endpoint=endpoint,
                               classe=f"{status // 100}xx").inc()
        DB_QUERIES_PER_REQUEST.labels(**rotulos(), endpoint=endpoint).observe(
            getattr(g, "db_queries", 0))

        if not resposta.direct_passthrough:
            comprimido = "sim" if resposta.headers.get("Content-Encoding") else "nao"
            HTTP_RESPONSE_BYTES.labels(**rotulos(), comprimido=comprimido).inc(
                resposta.calculate_content_length() or 0)
        resposta.headers["X-Servido-Por"] = INSTANCIA
        resposta.headers["X-DB-Queries"] = str(getattr(g, "db_queries", 0))
        return resposta

    @app.teardown_request
    def _sempre(_erro=None):
        if getattr(g, "instrumentado", False):
            HTTP_IN_PROGRESS.labels(**rotulos()).dec()
            g.instrumentado = False

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    @app.get("/saude")
    def saude():
        return {"status": "ok", "servico": SERVICO, "instancia": INSTANCIA}
