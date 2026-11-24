"""
Cria as tabelas e popula o banco com dados fictícios de uma loja de veículos.
Roda uma única vez (container "seed" no docker-compose) ou manualmente:

    python -m comum.seed
"""
import random
import time

from comum.db import BancoDados
from comum.placas import placa_do_id

TOTAL_VEICULOS = 2000
TOTAL_PROPOSTAS = 20000

MARCAS = {
    "Volkswagen": ["Gol", "Polo", "Virtus", "T-Cross", "Nivus", "up!", "Saveiro", "Amarok"],
    "Chevrolet": ["Onix", "Onix Plus", "Tracker", "Spin", "S10", "Cruze", "Montana"],
    "Fiat": ["Argo", "Mobi", "Cronos", "Pulse", "Fastback", "Strada", "Toro"],
    "Toyota": ["Corolla", "Corolla Cross", "Yaris", "Hilux", "SW4", "Etios"],
    "Hyundai": ["HB20", "HB20S", "Creta", "Tucson"],
    "Honda": ["City", "Civic", "HR-V", "WR-V", "Fit"],
    "Renault": ["Kwid", "Sandero", "Logan", "Duster", "Oroch", "Captur"],
    "Jeep": ["Renegade", "Compass", "Commander"],
    "Ford": ["Ka", "EcoSport", "Ranger", "Territory", "Fiesta"],
    "Nissan": ["Kicks", "Versa", "Frontier", "Sentra"],
    "Peugeot": ["208", "2008", "3008"],
    "Citroën": ["C3", "C4 Cactus", "C3 Aircross"],
    "BYD": ["Dolphin", "Dolphin Mini", "Song Plus", "Seal"],
    "Caoa Chery": ["Tiggo 5x", "Tiggo 7", "Tiggo 8", "Arrizo 6"],
    "Mitsubishi": ["L200", "Pajero Sport", "Eclipse Cross", "ASX"],
    "Kia": ["Sportage", "Cerato", "Stonic", "Niro"],
}
VERSOES = ["1.0", "1.0 TSI", "1.0 Turbo", "1.3", "1.6", "2.0", "Comfort", "Highline",
           "LTZ", "XEi", "Altis", "Limited", "Sport", "Premier", "Drive", "Trekking"]
CORES = ["Branco", "Prata", "Preto", "Cinza", "Vermelho", "Azul", "Bege"]
COMBUSTIVEIS = ["Flex", "Flex", "Flex", "Gasolina", "Diesel", "Híbrido", "Elétrico"]
CAMBIOS = ["Manual", "Automático", "Automático", "CVT"]
STATUS = ["disponivel"] * 8 + ["reservado", "vendido"]
CLIENTES = ["Ana Souza", "Bruno Lima", "Carla Dias", "Diego Rocha", "Elisa Prado",
            "Felipe Nunes", "Gabriela Melo", "Hugo Pires", "Iara Campos", "João Reis"]
PAGAMENTOS = ["a_vista", "financiamento", "financiamento", "consorcio", "troca"]

DDL = [
    """CREATE TABLE IF NOT EXISTS marcas (
           id INTEGER PRIMARY KEY,
           nome VARCHAR(40) NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS veiculos (
           id INTEGER PRIMARY KEY,
           placa VARCHAR(7) UNIQUE NOT NULL,
           marca_id INTEGER NOT NULL REFERENCES marcas(id),
           modelo VARCHAR(40) NOT NULL,
           versao VARCHAR(40) NOT NULL,
           ano INTEGER NOT NULL,
           km INTEGER NOT NULL,
           cor VARCHAR(20) NOT NULL,
           combustivel VARCHAR(20) NOT NULL,
           cambio VARCHAR(20) NOT NULL,
           preco NUMERIC(12,2) NOT NULL,
           status VARCHAR(12) NOT NULL,
           descricao TEXT)""",
    """CREATE TABLE IF NOT EXISTS propostas (
           id {serial},
           veiculo_id INTEGER NOT NULL,
           cliente VARCHAR(80) NOT NULL,
           valor NUMERIC(12,2) NOT NULL,
           forma_pagamento VARCHAR(20) NOT NULL,
           status VARCHAR(12) NOT NULL DEFAULT 'em_analise',
           criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_propostas_veiculo ON propostas(veiculo_id)",
    "CREATE INDEX IF NOT EXISTS idx_veiculos_marca ON veiculos(marca_id)",
]


def popular(db: BancoDados):
    serial = ("INTEGER PRIMARY KEY AUTOINCREMENT" if db.sqlite
              else "SERIAL PRIMARY KEY")
    for comando in DDL:
        db.executar(comando.format(serial=serial))

    if db.consultar("SELECT COUNT(*) AS n FROM veiculos", um=True)["n"] > 0:
        print("[seed] banco já populado, nada a fazer")
        return

    rnd = random.Random(42)
    nomes_marcas = list(MARCAS)
    db.inserir_lote("marcas", ["id", "nome"],
                    [(i + 1, n) for i, n in enumerate(nomes_marcas)])

    veiculos, precos = [], {}
    for i in range(1, TOTAL_VEICULOS + 1):
        marca_id = rnd.randint(1, len(nomes_marcas))
        marca = nomes_marcas[marca_id - 1]
        modelo = rnd.choice(MARCAS[marca])
        ano = rnd.randint(2012, 2026)
        idade = 2026 - ano
        km = 0 if idade == 0 else rnd.randint(5000, 18000) * idade
        preco = round(max(25000, rnd.uniform(70000, 260000) * (0.93 ** idade)), -2)
        precos[i] = preco
        cor, comb = rnd.choice(CORES), rnd.choice(COMBUSTIVEIS)
        descricao = (f"{marca} {modelo} {ano}, {cor.lower()}, {km} km, {comb.lower()}. "
                     "Revisões em dia, único dono, laudo cautelar aprovado. " * 4)
        veiculos.append((i, placa_do_id(i), marca_id, modelo, rnd.choice(VERSOES), ano, km,
                         cor, comb, rnd.choice(CAMBIOS), preco, rnd.choice(STATUS), descricao))
    db.inserir_lote("veiculos", ["id", "placa", "marca_id", "modelo", "versao", "ano", "km",
                                 "cor", "combustivel", "cambio", "preco", "status",
                                 "descricao"], veiculos)

    propostas = []
    for _ in range(TOTAL_PROPOSTAS):
        vid = rnd.randint(1, TOTAL_VEICULOS)
        propostas.append((vid, rnd.choice(CLIENTES),
                          round(precos[vid] * rnd.uniform(0.85, 1.0), -2),
                          rnd.choice(PAGAMENTOS),
                          rnd.choice(["em_analise", "aprovada", "recusada"])))
    db.inserir_lote("propostas", ["veiculo_id", "cliente", "valor", "forma_pagamento",
                                  "status"], propostas)
    print(f"[seed] {len(nomes_marcas)} marcas, {TOTAL_VEICULOS} veículos, "
          f"{TOTAL_PROPOSTAS} propostas inseridos")


if __name__ == "__main__":
    for tentativa in range(30):  # espera o Postgres aceitar conexões
        try:
            popular(BancoDados(usar_pool=False))
            break
        except Exception as erro:  # noqa: BLE001
            print(f"[seed] banco indisponível ({erro}); tentando de novo...")
            time.sleep(2)
    else:
        raise SystemExit("[seed] não foi possível conectar ao banco")
