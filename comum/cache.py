"""
Etapa 4 - Cache em memória LRU com TTL.

- LRU (Least Recently Used): quando enche, descarta o item usado há mais tempo.
- TTL (Time To Live): cada item expira depois de N segundos.
- OrderedDict dá get/put/descartar em O(1).
- Cada acerto/falta vira métrica (cache_hits_total / cache_misses_total),
  que o Grafana usa para mostrar a taxa de Cache Hit vs Cache Miss.
"""
import threading
import time
from collections import OrderedDict
from functools import wraps

from comum import metricas

_AUSENTE = object()


class CacheLRU:
    def __init__(self, nome, tamanho_max=256, ttl_segundos=30):
        self.nome = nome
        self.tamanho_max = tamanho_max
        self.ttl = ttl_segundos
        self._dados = OrderedDict()  # chave -> (expira_em, valor)
        self._lock = threading.Lock()

    def _rot(self):
        return {**metricas.rotulos(), "cache": self.nome}

    def obter(self, chave):
        with self._lock:
            item = self._dados.get(chave, _AUSENTE)
            if item is not _AUSENTE:
                expira_em, valor = item
                if expira_em > time.monotonic():
                    self._dados.move_to_end(chave)  # marca como usado recentemente
                    metricas.CACHE_HITS.labels(**self._rot()).inc()
                    return valor
                del self._dados[chave]  # expirou (TTL)
            metricas.CACHE_MISSES.labels(**self._rot()).inc()
            metricas.CACHE_SIZE.labels(**self._rot()).set(len(self._dados))
            return _AUSENTE

    def guardar(self, chave, valor):
        with self._lock:
            self._dados[chave] = (time.monotonic() + self.ttl, valor)
            self._dados.move_to_end(chave)
            while len(self._dados) > self.tamanho_max:
                self._dados.popitem(last=False)  # descarta o menos usado (LRU)
            metricas.CACHE_SIZE.labels(**self._rot()).set(len(self._dados))

    def limpar(self):
        with self._lock:
            self._dados.clear()
            metricas.CACHE_SIZE.labels(**self._rot()).set(0)

    def __len__(self):
        return len(self._dados)


def em_cache(cache: CacheLRU, chave_fn=None):
    """Decorator: @em_cache(meu_cache) sobre uma função cara."""
    def decorador(funcao):
        @wraps(funcao)
        def envoltorio(*args, **kwargs):
            chave = chave_fn(*args, **kwargs) if chave_fn else (args, tuple(sorted(kwargs.items())))
            valor = cache.obter(chave)
            if valor is _AUSENTE:
                valor = funcao(*args, **kwargs)
                if valor is not None:  # não guardamos "não encontrado"
                    cache.guardar(chave, valor)
            return valor
        return envoltorio
    return decorador
