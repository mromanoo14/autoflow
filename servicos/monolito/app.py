"""
VERSÃO INICIAL INGÊNUA (BASELINE) - Monolito da loja de veículos.

Tudo num processo só, com os gargalos de propósito:
  [x] Servidor de desenvolvimento do Flask (app.run)
  [x] Sem connection pool: abre/fecha conexão com o banco a CADA query
  [x] N+1: para cada veículo, 1 query de marca + 1 query de resumo de propostas
  [x] Busca por placa carrega o estoque inteiro e percorre a lista: O(n)
  [x] Sem cache, sem gzip, sem Cache-Control
  [x] Sem timeout/retry/circuit breaker (tudo acoplado: se o banco engasga, tudo cai)

Já vem instrumentado com as MESMAS métricas dos microsserviços, para que o
Grafana mostre o "antes" e o "depois" lado a lado (servico="monolito").
"""
import os

from flask import Flask, abort, jsonify, request

from comum import metricas
from comum.db import BancoDados

app = Flask(__name__)
app.json.sort_keys = False
metricas.instrumentar(app)

db = BancoDados(usar_pool=False)  # <- sem pool

COLUNAS = ("id, placa, modelo, versao, ano, km, cor, combustivel, cambio, "
           "CAST(preco AS FLOAT) AS preco, status, marca_id")
FORMAS_PAGAMENTO = ("a_vista", "financiamento", "consorcio", "troca")


@app.get("/api/veiculos")
def listar_veiculos():
    pagina = max(1, request.args.get("pagina", 1, type=int))
    tamanho = min(100, max(1, request.args.get("tamanho", 50, type=int)))
    veiculos = db.consultar(f"SELECT {COLUNAS} FROM veiculos ORDER BY id LIMIT %s OFFSET %s",
                            (tamanho, (pagina - 1) * tamanho))
    for v in veiculos:  # N+1 (na verdade 2N+1)
        v["marca"] = db.consultar("SELECT nome FROM marcas WHERE id = %s",
                                  (v["marca_id"],), um=True)["nome"]
        r = db.consultar("SELECT COUNT(*) AS total, CAST(MAX(valor) AS FLOAT) AS maior "
                         "FROM propostas WHERE veiculo_id = %s", (v["id"],), um=True)
        v["interessados"] = r["total"]
        v["maior_oferta"] = r["maior"]
    return jsonify(pagina=pagina, modo="n1", itens=veiculos)


@app.get("/api/veiculos/<int:veiculo_id>")
def detalhe_veiculo(veiculo_id):
    veiculo = db.consultar(f"SELECT {COLUNAS}, descricao FROM veiculos WHERE id = %s",
                           (veiculo_id,), um=True)
    if veiculo is None:
        abort(404, description="Veículo não encontrado")
    veiculo["marca"] = db.consultar("SELECT nome FROM marcas WHERE id = %s",
                                    (veiculo["marca_id"],), um=True)["nome"]
    itens = db.consultar("SELECT id, cliente, CAST(valor AS FLOAT) AS valor, forma_pagamento, "
                         "status FROM propostas WHERE veiculo_id = %s ORDER BY id DESC "
                         "LIMIT 10", (veiculo_id,))
    r = db.consultar("SELECT COUNT(*) AS total, CAST(MAX(valor) AS FLOAT) AS maior "
                     "FROM propostas WHERE veiculo_id = %s", (veiculo_id,), um=True)
    veiculo["propostas"] = {"veiculo_id": veiculo_id, "total": r["total"],
                            "maior_oferta": r["maior"], "itens": itens}
    metricas.VEICULOS_VISUALIZADOS.labels(servico=metricas.SERVICO,
                                          marca=veiculo["marca"]).inc()
    return jsonify(veiculo)


@app.get("/api/veiculos/busca")
def busca_veiculo():
    placa = request.args.get("placa", "").strip().upper().replace("-", "")
    if not placa:
        abort(400, description="Informe ?placa=")
    todos = db.consultar("SELECT v.id, v.placa, v.modelo, v.versao, v.ano, v.km, v.cor, "
                         "v.combustivel, v.cambio, CAST(v.preco AS FLOAT) AS preco, v.status, "
                         "v.marca_id, m.nome AS marca FROM veiculos v "
                         "JOIN marcas m ON m.id = v.marca_id")
    for v in todos:  # O(n) a cada requisição
        if v["placa"] == placa:
            return jsonify(v)
    abort(404, description="Placa não encontrada")


@app.post("/api/propostas")
def criar_proposta():
    dados = request.get_json(silent=True) or {}
    try:
        veiculo_id, valor = int(dados["veiculo_id"]), round(float(dados["valor"]), 2)
        forma = dados.get("forma_pagamento", "a_vista")
        assert valor > 0 and forma in FORMAS_PAGAMENTO
    except (KeyError, ValueError, TypeError, AssertionError):
        abort(400, description="Envie veiculo_id, valor (> 0) e forma_pagamento")
    nova = db.executar("INSERT INTO propostas (veiculo_id, cliente, valor, forma_pagamento) "
                       "VALUES (%s, %s, %s, %s) RETURNING id",
                       (veiculo_id, str(dados.get("cliente", "anonimo"))[:80], valor, forma),
                       retornar=True)
    metricas.PROPOSTAS_CRIADAS.labels(servico=metricas.SERVICO, forma_pagamento=forma).inc()
    metricas.VALOR_PROPOSTAS.labels(servico=metricas.SERVICO).inc(valor)
    return jsonify(id=nova["id"], veiculo_id=veiculo_id, valor=valor,
                   forma_pagamento=forma, status="em_analise"), 201


@app.errorhandler(400)
@app.errorhandler(404)
def erro_cliente(e):
    return jsonify(erro=e.description), e.code


if __name__ == "__main__":
    # ANTI-PADRÃO: servidor de desenvolvimento em "produção"
    app.run(host="0.0.0.0", port=int(os.getenv("PORTA", "8001")), threaded=True)
