"""
Lê os CSVs gerados pelo Locust (--csv) e monta a tabela Baseline vs Otimizado
pronta para colar no relatório.

    python scripts/comparar_resultados.py resultados/baseline resultados/otimizado
"""
import csv
import sys


def ler_agregado(prefixo):
    with open(f"{prefixo}_stats.csv", newline="", encoding="utf-8") as f:
        linhas = {l["Name"]: l for l in csv.DictReader(f)}
    a = linhas["Aggregated"]
    req, falhas = int(a["Request Count"]), int(a["Failure Count"])
    return {
        "RPS": float(a["Requests/s"]),
        "P50 (ms)": float(a["50%"]),
        "P95 (ms)": float(a["95%"]),
        "P99 (ms)": float(a["99%"]),
        "Taxa de erro (%)": 100 * falhas / req if req else 0.0,
        "Requisições": req,
    }, linhas


def variacao(nome, antes, depois):
    if antes == 0:
        return "-"
    pct = (depois - antes) / antes * 100
    melhor = pct > 0 if nome in ("RPS", "Requisições") else pct < 0
    return f"{pct:+.1f}% {'(melhor)' if melhor else '(pior)' if pct else ''}"


def main(base, otim):
    a, la = ler_agregado(base)
    b, lb = ler_agregado(otim)
    print("| Métrica | Baseline (monolito) | Otimizado (microsserviços) | Variação |")
    print("|---|---|---|---|")
    for k in a:
        fmt = "{:.0f}" if k == "Requisições" else "{:.2f}"
        print(f"| {k} | {fmt.format(a[k])} | {fmt.format(b[k])} | {variacao(k, a[k], b[k])} |")

    print("\nP95 por endpoint (ms):\n")
    print("| Endpoint | Baseline | Otimizado |")
    print("|---|---|---|")
    for nome in la:
        if nome != "Aggregated" and nome in lb:
            print(f"| {nome} | {la[nome]['95%']} | {lb[nome]['95%']} |")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
