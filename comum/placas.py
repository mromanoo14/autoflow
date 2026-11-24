"""
Gera placas no padrão Mercosul (ABC1D23) de forma determinística a partir do id
do veículo. Assim o seed e o teste de carga (Locust) conhecem as mesmas placas
sem precisar consultar o banco.

A multiplicação por um número primo (7919) "embaralha" os ids; como 7919 não
divide 26 nem 10, a função é bijetora: cada id gera uma placa diferente.
"""
LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ESPACO = 26 ** 4 * 10 ** 3  # 4 letras e 3 dígitos


def placa_do_id(veiculo_id: int) -> str:
    n = (veiculo_id * 7919) % _ESPACO
    n, d3 = divmod(n, 10)
    n, d2 = divmod(n, 10)
    n, l4 = divmod(n, 26)
    n, d1 = divmod(n, 10)
    n, l3 = divmod(n, 26)
    n, l2 = divmod(n, 26)
    l1 = n % 26
    return f"{LETRAS[l1]}{LETRAS[l2]}{LETRAS[l3]}{d1}{LETRAS[l4]}{d2}{d3}"
