"""
Etapa 3 - Dados e Armazenamento: camada de acesso ao banco.

- usar_pool=False  -> versão ingênua: abre e fecha uma conexão física A CADA query
- usar_pool=True   -> Connection Pooling: conexões abertas uma vez e reaproveitadas

Toda query passa por aqui e incrementa db_queries_total, o que permite provar no
Grafana a queda de queries por requisição quando o N+1 vira JOIN.

Suporta PostgreSQL (docker) e SQLite (para rodar/testar sem Docker).
DATABASE_URL exemplos:
    postgresql://loja:loja@postgres:5432/loja
    sqlite:///loja.db
"""
import os
import queue
import sqlite3
import threading
from contextlib import contextmanager

from comum import metricas

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
except ImportError:  # permite rodar só com SQLite
    psycopg2 = None


class BancoDados:
    def __init__(self, url=None, usar_pool=True, tamanho_pool=10):
        self.url = url or os.getenv("DATABASE_URL", "sqlite:///loja.db")
        self.usar_pool = usar_pool
        self.tamanho_pool = tamanho_pool
        self.sqlite = self.url.startswith("sqlite")
        self._pool = None
        self._lock = threading.Lock()
        # Semáforo faz a thread ESPERAR por uma conexão livre em vez de falhar
        self._vagas = threading.BoundedSemaphore(tamanho_pool)

    # ------------------------------------------------------------ conexões
    def _abrir_conexao_fisica(self):
        metricas.DB_CONNECTIONS_OPENED.labels(**metricas.rotulos()).inc()
        if self.sqlite:
            caminho = self.url.replace("sqlite:///", "")
            con = sqlite3.connect(caminho, check_same_thread=False, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            return con
        return psycopg2.connect(self.url)

    def _obter_pool(self):
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    if self.sqlite:
                        self._pool = queue.LifoQueue()
                        for _ in range(self.tamanho_pool):
                            self._pool.put(self._abrir_conexao_fisica())
                    else:
                        self._pool = psycopg2.pool.ThreadedConnectionPool(
                            minconn=2, maxconn=self.tamanho_pool, dsn=self.url)
                        # as conexões do pool contam como abertas
                        metricas.DB_CONNECTIONS_OPENED.labels(
                            **metricas.rotulos()).inc(2)
        return self._pool

    @contextmanager
    def conexao(self):
        if not self.usar_pool:
            # ANTI-PADRÃO (baseline): handshake TCP + autenticação a cada uso
            con = self._abrir_conexao_fisica()
            try:
                yield con
            finally:
                con.close()
            return

        self._vagas.acquire()
        pool = self._obter_pool()
        con = pool.get() if self.sqlite else pool.getconn()
        metricas.DB_POOL_IN_USE.labels(**metricas.rotulos()).inc()
        try:
            yield con
        finally:
            metricas.DB_POOL_IN_USE.labels(**metricas.rotulos()).dec()
            if self.sqlite:
                pool.put(con)
            else:
                pool.putconn(con)
            self._vagas.release()

    # ------------------------------------------------------------ execução
    def _sql(self, sql):
        return sql.replace("%s", "?") if self.sqlite else sql

    def _cursor(self, con):
        if self.sqlite:
            return con.cursor()
        return con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def consultar(self, sql, params=(), um=False):
        """SELECT -> lista de dicts (ou um dict / None se um=True)."""
        metricas.contar_query()
        with self.conexao() as con:
            cur = self._cursor(con)
            cur.execute(self._sql(sql), params)
            linhas = [dict(l) for l in cur.fetchall()]
            cur.close()
            if not self.sqlite:
                con.rollback()  # encerra a transação de leitura
        if um:
            return linhas[0] if linhas else None
        return linhas

    def executar(self, sql, params=(), retornar=False):
        """INSERT/UPDATE/DDL. Com retornar=True devolve a 1a linha (RETURNING)."""
        metricas.contar_query()
        with self.conexao() as con:
            cur = self._cursor(con)
            cur.execute(self._sql(sql), params)
            linha = cur.fetchone() if retornar else None
            con.commit()
            cur.close()
        return dict(linha) if linha else None

    def inserir_lote(self, tabela, colunas, linhas):
        """Inserção em lote (usada pelo seed)."""
        cols = ", ".join(colunas)
        with self.conexao() as con:
            cur = con.cursor()
            if self.sqlite:
                marcadores = ", ".join("?" for _ in colunas)
                cur.executemany(
                    f"INSERT INTO {tabela} ({cols}) VALUES ({marcadores})", linhas)
            else:
                psycopg2.extras.execute_values(
                    cur, f"INSERT INTO {tabela} ({cols}) VALUES %s", linhas,
                    page_size=1000)
            con.commit()
            cur.close()
