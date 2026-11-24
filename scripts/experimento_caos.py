"""
Experimento de Caos controlado - rode ENQUANTO o Locust estiver com 100+ usuários.

Linha do tempo padrão:
  t=0s    estado estável (registra o estado dos circuit breakers)
  t=60s   ATIVA a falha no serviço de propostas (100% de erro 500)
  t=150s  DESATIVA a falha -> circuit breaker passa por MEIO-ABERTO e FECHA
  t=210s  fim

Hipótese: "Mesmo com o serviço de Propostas 100% indisponível, o Gateway
mantém >= 99% das respostas sem erro 5xx, deixando os anúncios dos veículos
no ar com as propostas degradadas (fallback), e o P95 volta ao normal em
menos de 15 s após o Circuit Breaker abrir."

    python scripts/experimento_caos.py                  # modo erro
    python scripts/experimento_caos.py --modo latencia  # 3 s de atraso (testa o timeout)
"""
import argparse
import json
import time
import urllib.request

PROPOSTAS = "http://localhost:5002"
GATEWAY = "http://localhost:8000"


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def estado():
    try:
        circ = get(f"{GATEWAY}/api/resiliencia")["circuitos"]
        return ", ".join(f"{c['destino']}={c['estado']}" for c in circ)
    except Exception as e:  # noqa: BLE001
        return f"(gateway sem resposta: {e})"


def aguardar(segundos):
    fim = time.time() + segundos
    while time.time() < fim:
        log("   circuitos: " + estado())
        time.sleep(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", default="erro", choices=["erro", "latencia"])
    ap.add_argument("--antes", type=int, default=60)
    ap.add_argument("--durante", type=int, default=90)
    ap.add_argument("--depois", type=int, default=60)
    a = ap.parse_args()

    log("FASE 1 - estado estável"); aguardar(a.antes)
    log(f"FASE 2 - ATIVANDO CAOS ({a.modo})")
    log(get(f"{PROPOSTAS}/caos/ativar-falha?modo={a.modo}&taxa=1.0&latencia_ms=3000"))
    aguardar(a.durante)
    log("FASE 3 - DESATIVANDO CAOS (recuperação)")
    log(get(f"{PROPOSTAS}/caos/desativar"))
    aguardar(a.depois)
    log("Fim do experimento. Confira no Grafana: Estado do Circuit Breaker, "
        "Fallbacks/s e Disponibilidade.")


if __name__ == "__main__":
    main()
