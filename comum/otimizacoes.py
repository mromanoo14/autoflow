"""
Etapa 4 - Desempenho de rede.

- Compressão Gzip das respostas (só quando o cliente envia Accept-Encoding: gzip
  e o corpo vale a pena comprimir).
- Cabeçalho Cache-Control por rota, via decorator @cache_control(max_age=...).

Implementado à mão (sem Flask-Compress) para o grupo conseguir explicar cada linha.
"""
import gzip
from functools import wraps

from flask import g, request

TAMANHO_MINIMO = 500  # bytes; abaixo disso o overhead do gzip não compensa
TIPOS_COMPRIMIVEIS = ("application/json", "text/")


def cache_control(max_age=60, publico=True):
    """Marca a rota com Cache-Control: navegador/CDN podem reutilizar a resposta."""
    def decorador(view):
        @wraps(view)
        def envoltorio(*args, **kwargs):
            g.cache_control = f"{'public' if publico else 'private'}, max-age={max_age}"
            return view(*args, **kwargs)
        return envoltorio
    return decorador


def ativar(app, nivel_gzip=6):
    @app.after_request
    def _comprimir(resposta):
        # Cache-Control
        if request.method == "GET" and resposta.status_code == 200:
            resposta.headers["Cache-Control"] = getattr(g, "cache_control", "no-cache")
        else:
            resposta.headers["Cache-Control"] = "no-store"

        # Gzip
        aceita = request.headers.get("Accept-Encoding", "").lower()
        if ("gzip" not in aceita or resposta.direct_passthrough
                or resposta.status_code < 200 or resposta.status_code >= 300
                or "Content-Encoding" in resposta.headers
                or not resposta.mimetype.startswith(TIPOS_COMPRIMIVEIS)):
            return resposta
        corpo = resposta.get_data()
        if len(corpo) < TAMANHO_MINIMO:
            return resposta
        comprimido = gzip.compress(corpo, compresslevel=nivel_gzip)
        resposta.set_data(comprimido)
        resposta.headers["Content-Encoding"] = "gzip"
        resposta.headers["Content-Length"] = str(len(comprimido))
        resposta.headers["X-Tamanho-Original"] = str(len(corpo))
        resposta.vary.add("Accept-Encoding")
        return resposta
