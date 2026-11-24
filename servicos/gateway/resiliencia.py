"""
Etapa 5 - Padrões de Resiliência para chamadas entre serviços.

  1. Timeout            -> nunca esperar indefinidamente por outro serviço
  2. Retry + Exponential Backoff (com jitter) -> tenta de novo, esperando 0.1s, 0.2s, 0.4s...
  3. Circuit Breaker    -> FECHADO -> (falhas demais) -> ABERTO -> (espera) -> MEIO-ABERTO
  4. Fallback           -> quem chama decide a resposta degradada quando tudo falha
  + Connection Pooling HTTP (requests.Session + HTTPAdapter com keep-alive)
"""
import random
import threading
import time

import requests
from requests.adapters import HTTPAdapter

from comum import metricas

FECHADO, ABERTO, MEIO_ABERTO = 0, 1, 2
NOMES = {FECHADO: "fechado", ABERTO: "aberto", MEIO_ABERTO: "meio_aberto"}


class CircuitoAbertoErro(Exception):
    """Lançada sem nem tentar a chamada: o circuito está aberto (fail fast)."""


class ServicoIndisponivelErro(Exception):
    """A chamada falhou mesmo depois das retentativas."""


class CircuitBreaker:
    def __init__(self, destino, limite_falhas=5, tempo_aberto=10.0,
                 sucessos_para_fechar=2):
        self.destino = destino
        self.limite_falhas = limite_falhas        # falhas seguidas para abrir
        self.tempo_aberto = tempo_aberto          # segundos antes de testar de novo
        self.sucessos_para_fechar = sucessos_para_fechar
        self.estado = FECHADO
        self.falhas_seguidas = 0
        self.sucessos_meio_aberto = 0
        self.aberto_em = 0.0
        self.teste_em_andamento = False
        self._lock = threading.Lock()
        self._publicar()

    def _publicar(self):
        metricas.CB_STATE.labels(**metricas.rotulos(), destino=self.destino).set(self.estado)

    def _mudar(self, novo):
        if novo != self.estado:
            self.estado = novo
            metricas.CB_TRANSITIONS.labels(**metricas.rotulos(), destino=self.destino,
                                           para=NOMES[novo]).inc()
            self._publicar()

    def permite_chamada(self):
        with self._lock:
            if self.estado == ABERTO:
                if time.monotonic() - self.aberto_em < self.tempo_aberto:
                    return False
                self._mudar(MEIO_ABERTO)  # tempo de espera passou: vamos testar
                self.sucessos_meio_aberto = 0
                self.teste_em_andamento = False
            if self.estado == MEIO_ABERTO:
                if self.teste_em_andamento:
                    return False  # só 1 requisição de teste por vez
                self.teste_em_andamento = True
            return True

    def registrar_sucesso(self):
        with self._lock:
            self.falhas_seguidas = 0
            if self.estado == MEIO_ABERTO:
                self.teste_em_andamento = False
                self.sucessos_meio_aberto += 1
                if self.sucessos_meio_aberto >= self.sucessos_para_fechar:
                    self._mudar(FECHADO)

    def registrar_falha(self):
        with self._lock:
            self.falhas_seguidas += 1
            if self.estado == MEIO_ABERTO or self.falhas_seguidas >= self.limite_falhas:
                self.teste_em_andamento = False
                self.aberto_em = time.monotonic()
                self._mudar(ABERTO)

    def situacao(self):
        return {"destino": self.destino, "estado": NOMES[self.estado],
                "falhas_seguidas": self.falhas_seguidas}


def criar_sessao_http(tamanho_pool=50):
    """Connection Pooling HTTP: reaproveita conexões TCP (keep-alive) entre
    chamadas, em vez de fazer handshake a cada requisição ao microsserviço."""
    sessao = requests.Session()
    adaptador = HTTPAdapter(pool_connections=10, pool_maxsize=tamanho_pool,
                            max_retries=0)  # retry é nosso, com backoff e métricas
    sessao.mount("http://", adaptador)
    sessao.mount("https://", adaptador)
    sessao.headers["Accept-Encoding"] = "gzip"
    return sessao


class ClienteResiliente:
    def __init__(self, sessao, destino, url_base, breaker, timeout=(0.5, 1.0),
                 tentativas=3, backoff_base=0.1, backoff_max=1.0):
        self.sessao = sessao
        self.destino = destino
        self.url_base = url_base.rstrip("/")
        self.breaker = breaker
        self.timeout = timeout          # (conexão, leitura) em segundos
        self.tentativas = tentativas
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

    def _espera(self, tentativa):
        # Exponential backoff com "full jitter": evita que todas as threads
        # tentem de novo no mesmo instante (efeito manada)
        teto = min(self.backoff_max, self.backoff_base * (2 ** tentativa))
        return random.uniform(teto / 2, teto)

    def chamar(self, metodo, caminho, idempotente=True, **kwargs):
        if not self.breaker.permite_chamada():
            raise CircuitoAbertoErro(self.destino)

        tentativas = self.tentativas if idempotente else 1  # POST não se repete
        ultimo_erro = None
        for tentativa in range(tentativas):
            inicio = time.perf_counter()
            try:
                resp = self.sessao.request(metodo, self.url_base + caminho,
                                           timeout=self.timeout, **kwargs)
                if resp.status_code >= 500:
                    raise ServicoIndisponivelErro(f"HTTP {resp.status_code}")
                metricas.CLIENT_LATENCY.labels(**metricas.rotulos(), destino=self.destino,
                                               resultado="sucesso").observe(
                    time.perf_counter() - inicio)
                self.breaker.registrar_sucesso()  # 2xx/3xx/4xx: o serviço está vivo
                return resp
            except (requests.Timeout, requests.ConnectionError,
                    ServicoIndisponivelErro) as erro:
                ultimo_erro = erro
                metricas.CLIENT_LATENCY.labels(**metricas.rotulos(), destino=self.destino,
                                               resultado="falha").observe(
                    time.perf_counter() - inicio)
                ultima = tentativa == tentativas - 1
                if ultima or self.breaker.estado != FECHADO:
                    break
                metricas.CLIENT_RETRIES.labels(**metricas.rotulos(),
                                               destino=self.destino).inc()
                time.sleep(self._espera(tentativa))

        self.breaker.registrar_falha()
        raise ServicoIndisponivelErro(f"{self.destino}: {ultimo_erro}")
