"""
API GATEWAY - porta de entrada única da arquitetura de microsserviços.

  Cliente -> Gateway :8000 -> Nginx (round robin) -> estoque-1 / estoque-2
                           -> propostas

Rotas públicas (mesmas do monolito, para o teste de carga ser idêntico):
  GET  /api/veiculos?pagina=1[&modo=n1]
  GET  /api/veiculos/<id>
  GET  /api/veiculos/busca?placa=ABC1D23
  POST /api/propostas
  GET  /api/resiliencia     -> estado dos circuit breakers
"""
import os
import threading
import time
from collections import deque

from flask import Flask, jsonify, request

from comum import metricas, otimizacoes
from comum.cache import CacheLRU
from servicos.gateway.resiliencia import (FECHADO, CircuitBreaker,
                                          CircuitoAbertoErro,
                                          ClienteResiliente,
                                          ServicoIndisponivelErro,
                                          criar_sessao_http)

app = Flask(__name__)
app.json.sort_keys = False
app.json.ensure_ascii = False  # acentos legíveis no JSON
metricas.instrumentar(app)
otimizacoes.ativar(app)

sessao = criar_sessao_http(tamanho_pool=int(os.getenv("HTTP_POOL", "100")))

cb_estoque = CircuitBreaker("estoque", limite_falhas=5, tempo_aberto=10)
cb_propostas = CircuitBreaker("propostas", limite_falhas=5, tempo_aberto=10)

estoque = ClienteResiliente(sessao, "estoque",
                            os.getenv("ESTOQUE_URL", "http://localhost:5001"),
                            cb_estoque)
propostas = ClienteResiliente(sessao, "propostas",
                              os.getenv("PROPOSTAS_URL", "http://localhost:5002"),
                              cb_propostas)

# "Último valor bom" de cada resposta: usado como fallback quando o serviço cai.
# TTL longo de propósito (dado um pouco velho > erro para o cliente da loja).
reserva = CacheLRU("fallback_gateway", tamanho_max=5000, ttl_segundos=600)
FALHAS = (CircuitoAbertoErro, ServicoIndisponivelErro)


def fallback(destino):
    metricas.FALLBACKS.labels(**metricas.rotulos(), destino=destino).inc()


def _repassar_query():
    return {k: v for k, v in request.args.items()}


# ------------------------------------------------------------------ rotas
@app.get("/api/veiculos")
@otimizacoes.cache_control(max_age=30)
def listar_veiculos():
    chave = ("lista", tuple(sorted(request.args.items())))
    try:
        dados = estoque.chamar("GET", "/veiculos", params=_repassar_query()).json()
    except FALHAS:
        fallback("estoque")
        guardado = reserva.obter(chave)
        if not isinstance(guardado, dict):
            return jsonify(erro="Estoque indisponível, tente novamente"), 503
        return jsonify({**guardado, "degradado": True})

    # Batching: 1 chamada para o resumo de propostas de todos os veículos da página
    ids = ",".join(str(v["id"]) for v in dados["itens"])
    try:
        resumo = propostas.chamar("GET", "/propostas/resumo",
                                  params={"ids": ids}).json()
    except FALHAS:
        fallback("propostas")
        resumo = {}
        dados["propostas_indisponiveis"] = True
    for v in dados["itens"]:
        info = resumo.get(str(v["id"]), {})
        v["interessados"] = info.get("interessados", 0)
        v["maior_oferta"] = info.get("maior_oferta")
    reserva.guardar(chave, dados)
    return jsonify(dados)


@app.get("/api/veiculos/<int:veiculo_id>")
@otimizacoes.cache_control(max_age=60)
def detalhe_veiculo(veiculo_id):
    try:
        resp = estoque.chamar("GET", f"/veiculos/{veiculo_id}")
    except FALHAS:
        fallback("estoque")
        veiculo = reserva.obter(("veiculo", veiculo_id))
        if not isinstance(veiculo, dict):
            return jsonify(erro="Estoque indisponível, tente novamente"), 503
        return jsonify({**veiculo, "degradado": True})
    if resp.status_code == 404:
        return jsonify(erro="Veículo não encontrado"), 404
    veiculo = resp.json()

    try:
        pr = propostas.chamar("GET", "/propostas",
                              params={"veiculo_id": veiculo_id}).json()
        reserva.guardar(("propostas", veiculo_id), pr)
        veiculo["propostas"] = pr
    except FALHAS:
        # DEGRADAÇÃO CONTROLADA: o anúncio do carro continua no ar; as propostas
        # vêm do último valor conhecido ou ficam vazias com um aviso.
        fallback("propostas")
        anterior = reserva.obter(("propostas", veiculo_id))
        veiculo["propostas"] = dict(anterior) if isinstance(anterior, dict) else {
            "itens": [], "total": None, "maior_oferta": None}
        veiculo["propostas"]["indisponivel"] = True
    reserva.guardar(("veiculo", veiculo_id), veiculo)
    return jsonify(veiculo)


@app.get("/api/veiculos/busca")
@otimizacoes.cache_control(max_age=60)
def busca_veiculo():
    try:
        resp = estoque.chamar("GET", "/veiculos/busca", params=_repassar_query())
    except FALHAS:
        fallback("estoque")
        return jsonify(erro="Busca indisponível, tente novamente"), 503
    return jsonify(resp.json()), resp.status_code


# ------------------------------------------------------------------ escrita
# Fallback para escrita: se Propostas estiver fora, aceitamos a proposta (202)
# e guardamos numa fila em memória que é reenviada quando o serviço volta.
fila_pendente = deque(maxlen=10000)


@app.post("/api/propostas")
def criar_proposta():
    dados = request.get_json(silent=True) or {}
    try:
        resp = propostas.chamar("POST", "/propostas", json=dados, idempotente=False)
        return jsonify(resp.json()), resp.status_code
    except FALHAS:
        fallback("propostas")
        fila_pendente.append(dados)
        return jsonify(status="recebida",
                       mensagem="Proposta recebida! Um vendedor entrará em contato.",
                       pendentes=len(fila_pendente)), 202


def _reenviar_pendentes():
    while True:
        time.sleep(5)
        while fila_pendente and cb_propostas.estado == FECHADO:
            dados = fila_pendente.popleft()
            try:
                propostas.chamar("POST", "/propostas", json=dados, idempotente=False)
            except FALHAS:
                fila_pendente.appendleft(dados)
                break


threading.Thread(target=_reenviar_pendentes, daemon=True).start()


@app.get("/api/resiliencia")
def estado_resiliencia():
    return jsonify(circuitos=[cb_estoque.situacao(), cb_propostas.situacao()],
                   propostas_pendentes=len(fila_pendente))


if __name__ == "__main__":
    app.run(port=8000)
