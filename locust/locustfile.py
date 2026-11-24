"""
Etapa 5 - Teste de carga com Locust.

Simula clientes navegando no site da loja de veículos, com "think time" de 1 a 3 s.
O mesmo script roda contra o baseline (monolito :8001) e contra a versão
otimizada (gateway :8000), garantindo uma comparação justa.

Interface web (para o vídeo):  http://localhost:8089
Headless (gera CSV com P50/P95/P99 e RPS):
    docker compose run --rm locust -f /mnt/locust/locustfile.py --headless \
        -u 150 -r 15 -t 3m --host http://monolito:8001 --csv /mnt/resultados/baseline
    docker compose run --rm locust -f /mnt/locust/locustfile.py --headless \
        -u 150 -r 15 -t 3m --host http://gateway:8000  --csv /mnt/resultados/otimizado

Variáveis opcionais:
    MODO_CONSULTA=n1   -> força o N+1 no estoque (para a demo do Grafana)
"""
import os
import random

from locust import HttpUser, between, task

TOTAL_VEICULOS = int(os.getenv("TOTAL_VEICULOS", "2000"))
MODO = os.getenv("MODO_CONSULTA", "")
CLIENTES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe"]
PAGAMENTOS = ["a_vista", "financiamento", "financiamento", "consorcio", "troca"]

# Cópia de comum/placas.py (o container do Locust não enxerga a pasta comum/)
LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def placa_do_id(veiculo_id):
    n = (veiculo_id * 7919) % (26 ** 4 * 10 ** 3)
    n, d3 = divmod(n, 10)
    n, d2 = divmod(n, 10)
    n, l4 = divmod(n, 26)
    n, d1 = divmod(n, 10)
    n, l3 = divmod(n, 26)
    n, l2 = divmod(n, 26)
    return f"{LETRAS[n % 26]}{LETRAS[l2]}{LETRAS[l3]}{d1}{LETRAS[l4]}{d2}{d3}"


def veiculo_aleatorio():
    """Distribuição realista (Pareto 80/20): 80% das visitas vão para os
    100 carros em destaque. É isso que faz o cache ter bom hit ratio."""
    if random.random() < 0.8:
        return random.randint(1, 100)
    return random.randint(1, TOTAL_VEICULOS)


class ClienteLoja(HttpUser):
    wait_time = between(1, 3)  # think time

    @task(3)
    def listar_veiculos(self):
        params = {"pagina": random.randint(1, 5)}
        if MODO:
            params["modo"] = MODO
        self.client.get("/api/veiculos", params=params, name="/api/veiculos")

    @task(6)
    def ver_veiculo(self):
        self.client.get(f"/api/veiculos/{veiculo_aleatorio()}",
                        name="/api/veiculos/[id]")

    @task(2)
    def buscar_placa(self):
        self.client.get("/api/veiculos/busca",
                        params={"placa": placa_do_id(veiculo_aleatorio())},
                        name="/api/veiculos/busca")

    @task(1)
    def fazer_proposta(self):
        self.client.post("/api/propostas", name="/api/propostas", json={
            "veiculo_id": veiculo_aleatorio(),
            "valor": random.randrange(30000, 250000, 500),
            "forma_pagamento": random.choice(PAGAMENTOS),
            "cliente": random.choice(CLIENTES)})
