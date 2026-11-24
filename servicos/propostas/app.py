"""
Microsserviço de PROPOSTAS (ofertas de compra dos clientes) + injeção de caos.

  GET  /propostas?veiculo_id=10       -> últimas propostas + total + maior oferta
  GET  /propostas/resumo?ids=1,2,3    -> resumo de vários veículos em 1 query (Batching)
  POST /propostas                     -> registra proposta (métricas de negócio)

Engenharia do Caos (Etapa 5):
  POST|GET /caos/ativar-falha?modo=erro&taxa=1.0             -> responde 500
  POST|GET /caos/ativar-falha?modo=latencia&latencia_ms=3000 -> fica lento
  POST|GET /caos/desativar
  GET      /caos/status
"""
import os
import random
import threading
import time
from collections import deque

from flask import Flask, abort, jsonify, request

from comum import metricas, otimizacoes
from comum.db import BancoDados

app = Flask(__name__)
app.json.sort_keys = False
metricas.instrumentar(app)
otimizacoes.ativar(app)

db = BancoDados(usar_pool=True, tamanho_pool=int(os.getenv("DB_POOL", "10")))

FORMAS_PAGAMENTO = ("a_vista", "financiamento", "consorcio", "troca")
ultimos_valores = deque(maxlen=100)
_lock_valores = threading.Lock()

# ------------------------------------------------------------------ CAOS
caos = {"ativo": False, "modo": None, "taxa": 1.0, "latencia_ms": 0}
ROTAS_LIVRES = ("/caos", "/metrics", "/saude")


def _atualizar_gauge_caos():
    for modo in ("erro", "latencia"):
        metricas.CHAOS_ACTIVE.labels(**metricas.rotulos(), modo=modo).set(
            1 if caos["ativo"] and caos["modo"] == modo else 0)


_atualizar_gauge_caos()


@app.before_request
def injetar_falha():
    if not caos["ativo"] or request.path.startswith(ROTAS_LIVRES):
        return None
    if random.random() >= caos["taxa"]:
        return None
    if caos["modo"] == "latencia":
        time.sleep(caos["latencia_ms"] / 1000)
        return None
    return jsonify(erro="Falha injetada pelo experimento de caos"), 500


@app.route("/caos/ativar-falha", methods=["GET", "POST"])
def ativar_falha():
    dados = request.get_json(silent=True) or request.args
    modo = dados.get("modo", "erro")
    if modo not in ("erro", "latencia"):
        abort(400, description="modo deve ser 'erro' ou 'latencia'")
    caos.update(ativo=True, modo=modo,
                taxa=float(dados.get("taxa", 1.0)),
                latencia_ms=int(dados.get("latencia_ms", 3000)))
    _atualizar_gauge_caos()
    app.logger.warning("CAOS ATIVADO: %s", caos)
    return jsonify(caos)


@app.route("/caos/desativar", methods=["GET", "POST"])
def desativar_falha():
    caos.update(ativo=False, modo=None)
    _atualizar_gauge_caos()
    return jsonify(caos)


@app.get("/caos/status")
def status_caos():
    return jsonify(caos)


# ------------------------------------------------------------------ PROPOSTAS
@app.get("/propostas")
@otimizacoes.cache_control(max_age=15)
def listar():
    veiculo_id = request.args.get("veiculo_id", type=int)
    if veiculo_id is None:
        abort(400, description="Informe ?veiculo_id=")
    itens = db.consultar(
        """SELECT id, cliente, CAST(valor AS FLOAT) AS valor, forma_pagamento, status
             FROM propostas WHERE veiculo_id = %s ORDER BY id DESC LIMIT 10""",
        (veiculo_id,))
    resumo = db.consultar(
        """SELECT COUNT(*) AS total, CAST(MAX(valor) AS FLOAT) AS maior_oferta
             FROM propostas WHERE veiculo_id = %s""", (veiculo_id,), um=True)
    return jsonify(veiculo_id=veiculo_id, total=resumo["total"],
                   maior_oferta=resumo["maior_oferta"], itens=itens)


@app.get("/propostas/resumo")
@otimizacoes.cache_control(max_age=15)
def resumo_lote():
    """BATCHING: em vez de o gateway chamar 50x /propostas (N+1 via HTTP),
    ele pede o resumo dos 50 veículos de uma vez (IN + GROUP BY)."""
    try:
        ids = [int(x) for x in request.args.get("ids", "").split(",") if x][:200]
    except ValueError:
        abort(400, description="ids deve ser uma lista de inteiros")
    if not ids:
        return jsonify({})
    marcadores = ", ".join(["%s"] * len(ids))
    linhas = db.consultar(
        f"""SELECT veiculo_id, COUNT(*) AS total, CAST(MAX(valor) AS FLOAT) AS maior_oferta
              FROM propostas WHERE veiculo_id IN ({marcadores})
             GROUP BY veiculo_id""", tuple(ids))
    return jsonify({str(l["veiculo_id"]): {"interessados": l["total"],
                                           "maior_oferta": l["maior_oferta"]}
                    for l in linhas})


@app.post("/propostas")
def criar():
    dados = request.get_json(silent=True) or {}
    try:
        veiculo_id = int(dados["veiculo_id"])
        valor = round(float(dados["valor"]), 2)
        forma = dados.get("forma_pagamento", "a_vista")
        assert valor > 0 and forma in FORMAS_PAGAMENTO
    except (KeyError, ValueError, TypeError, AssertionError):
        abort(400, description="Envie veiculo_id, valor (> 0) e forma_pagamento "
                               f"({', '.join(FORMAS_PAGAMENTO)})")
    nova = db.executar(
        """INSERT INTO propostas (veiculo_id, cliente, valor, forma_pagamento)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (veiculo_id, str(dados.get("cliente", "anonimo"))[:80], valor, forma),
        retornar=True)

    metricas.PROPOSTAS_CRIADAS.labels(servico=metricas.SERVICO, forma_pagamento=forma).inc()
    metricas.VALOR_PROPOSTAS.labels(servico=metricas.SERVICO).inc(valor)
    with _lock_valores:
        ultimos_valores.append(valor)
        metricas.TICKET_MEDIO.labels(servico=metricas.SERVICO).set(
            sum(ultimos_valores) / len(ultimos_valores))
    return jsonify(id=nova["id"], veiculo_id=veiculo_id, valor=valor,
                   forma_pagamento=forma, status="em_analise"), 201


@app.errorhandler(400)
@app.errorhandler(404)
def erro_cliente(e):
    return jsonify(erro=e.description), e.code


if __name__ == "__main__":
    app.run(port=5002)
