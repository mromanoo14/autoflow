"""
Microsserviço de ESTOQUE (veículos e marcas) - versão otimizada.

Roda com 2 réplicas (estoque-1 e estoque-2) atrás do Nginx -> Eixo X do Cubo AKF.

Demonstrações:
  GET /veiculos?modo=n1       -> problema N+1 (1 query da lista + 1 de marca por veículo)
  GET /veiculos?modo=join     -> Eager Loading com JOIN (1 query só)  [padrão]
  GET /veiculos/<id>          -> cache LRU + TTL (cache_hits_total / cache_misses_total)
  GET /veiculos/busca?placa=  -> índice em dict O(1); &algoritmo=linear para O(n)
"""
import os

from flask import Flask, abort, jsonify, request

from comum import metricas, otimizacoes
from comum.cache import CacheLRU, em_cache
from comum.db import BancoDados

app = Flask(__name__)
app.json.sort_keys = False
metricas.instrumentar(app)   # 1o: métricas (medem o tamanho já comprimido)
otimizacoes.ativar(app)      # 2o: gzip + Cache-Control

db = BancoDados(usar_pool=True, tamanho_pool=int(os.getenv("DB_POOL", "10")))
MODO_PADRAO = os.getenv("MODO_CONSULTA", "join")
cache_veiculos = CacheLRU("veiculo_detalhe",
                          tamanho_max=int(os.getenv("CACHE_TAMANHO", "256")),
                          ttl_segundos=int(os.getenv("CACHE_TTL", "30")))

# CAST evita que o Postgres devolva Decimal (que viraria string no JSON)
COLUNAS = ("v.id, v.placa, v.modelo, v.versao, v.ano, v.km, v.cor, v.combustivel, "
           "v.cambio, CAST(v.preco AS FLOAT) AS preco, v.status, v.marca_id")


# ------------------------------------------------------------------ N+1 vs JOIN
def listar_n_mais_1(limite, deslocamento):
    """ANTI-PADRÃO: 1 query para a lista + 1 query de marca POR veículo."""
    veiculos = db.consultar(
        f"SELECT {COLUNAS} FROM veiculos v ORDER BY v.id LIMIT %s OFFSET %s",
        (limite, deslocamento))
    for v in veiculos:  # <- aqui nasce o N+1
        marca = db.consultar("SELECT nome FROM marcas WHERE id = %s",
                             (v["marca_id"],), um=True)
        v["marca"] = marca["nome"]
    return veiculos


def listar_com_join(limite, deslocamento):
    """CORREÇÃO: Eager Loading - o banco junta tudo em UMA ida e volta."""
    return db.consultar(
        f"""SELECT {COLUNAS}, m.nome AS marca
              FROM veiculos v
              JOIN marcas m ON m.id = v.marca_id
             ORDER BY v.id LIMIT %s OFFSET %s""",
        (limite, deslocamento))


@app.get("/veiculos")
@otimizacoes.cache_control(max_age=30)
def listar():
    pagina = max(1, request.args.get("pagina", 1, type=int))
    tamanho = min(100, max(1, request.args.get("tamanho", 50, type=int)))
    modo = request.args.get("modo", MODO_PADRAO)
    deslocamento = (pagina - 1) * tamanho
    if modo == "n1":
        itens = listar_n_mais_1(tamanho, deslocamento)
    else:
        itens = listar_com_join(tamanho, deslocamento)
    return jsonify(pagina=pagina, modo=modo, itens=itens)


# ------------------------------------------------------------------ cache LRU/TTL
@em_cache(cache_veiculos, chave_fn=lambda veiculo_id: veiculo_id)
def buscar_veiculo(veiculo_id):
    return db.consultar(
        f"""SELECT {COLUNAS}, v.descricao, m.nome AS marca
              FROM veiculos v JOIN marcas m ON m.id = v.marca_id
             WHERE v.id = %s""", (veiculo_id,), um=True)


@app.get("/veiculos/<int:veiculo_id>")
@otimizacoes.cache_control(max_age=60)
def detalhe(veiculo_id):
    veiculo = buscar_veiculo(veiculo_id)
    if veiculo is None:
        abort(404, description="Veículo não encontrado")
    metricas.VEICULOS_VISUALIZADOS.labels(
        servico=metricas.SERVICO, marca=veiculo["marca"]).inc()
    return jsonify(veiculo)


@app.post("/cache/limpar")
def limpar_cache():
    cache_veiculos.limpar()
    return {"ok": True}


# ------------------------------------------------------------------ O(1) vs O(n)
_indice_placa = None  # dict placa -> veículo, montado uma vez


def obter_indice():
    global _indice_placa
    if _indice_placa is None:
        linhas = db.consultar(
            f"SELECT {COLUNAS}, m.nome AS marca FROM veiculos v "
            "JOIN marcas m ON m.id = v.marca_id")
        _indice_placa = {l["placa"]: l for l in linhas}
    return _indice_placa


@app.get("/veiculos/busca")
@otimizacoes.cache_control(max_age=60)
def busca():
    placa = request.args.get("placa", "").strip().upper().replace("-", "")
    if not placa:
        abort(400, description="Informe ?placa=")
    indice = obter_indice()
    if request.args.get("algoritmo") == "linear":
        lista = list(indice.values())
        veiculo = next((v for v in lista if v["placa"] == placa), None)  # O(n)
    else:
        veiculo = indice.get(placa)  # O(1) - tabela hash
    if veiculo is None:
        abort(404, description="Placa não encontrada")
    return jsonify(veiculo)


@app.errorhandler(400)
@app.errorhandler(404)
def erro_cliente(e):
    return jsonify(erro=e.description), e.code


if __name__ == "__main__":
    # Só para desenvolvimento. Em produção usamos Gunicorn/Waitress (ver README).
    app.run(port=5001)
