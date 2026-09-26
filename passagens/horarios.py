#!/usr/bin/env python3
"""
Horarios dos voos de um destino de data marcada (hoje, so Belo Horizonte),
para o e-mail de aviso: o usuario decide a compra sem abrir o painel.

Pedido de 26/09/2026: as DATAS da viagem nao mudam, so os horarios. O
historico guarda o menor preco por companhia, sem horario, entao este script
consulta na hora os dois trechos avulsos (so ida) pela pagina de resultados
do Google Voos, que devolve partida, chegada e numero do voo. O preco de cada
trecho e para os passageiros do destino (2 adultos em CNF); ida mais volta
avulsas somam o mesmo que o bilhete de ida e volta (conferido em 26/09/2026:
R$ 469 + R$ 471 = R$ 940 contra R$ 939).

Uso: python3 passagens/horarios.py [CNF]
Imprime os trechos ordenados por preco e, no fim, a combinacao mais barata.
"""
import base64
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import coletor as c  # noqa: E402


def _hora(x):
    if not x:
        return "?"
    return f"{x[0]:02d}h{(x[1] if len(x) > 1 else 0):02d}"


def trecho(dest, origem, destino, data):
    """Voos so de ida de origem a destino na data, com horario e preco."""
    perna = (c._pb(2, data) + c._pb(13, c._pb(2, origem))
             + c._pb(14, c._pb(2, destino)))
    m = c._pb(3, perna)
    m += b"".join(c._pb(8, 1) for _ in range(c.adultos_de(dest)))
    m += c._pb(9, 1) + c._pb(19, 2)          # 19 = 2: so ida
    tfs = base64.urlsafe_b64encode(m).decode().rstrip("=")
    r = c.rq.get("https://www.google.com/travel/flights/search",
                 params={"tfs": tfs, "hl": "pt-BR", "gl": "BR", "curr": "BRL"},
                 impersonate="chrome", timeout=60,
                 cookies={"CONSENT": "YES+cb.20240101-00-p0.en+FX+000"})
    achou = re.search(r"AF_initDataCallback\(\{key: 'ds:1'", r.text)
    if r.status_code != 200 or not achou:
        raise RuntimeError(f"pagina sem resultados (HTTP {r.status_code})")
    p, _ = c._dec.raw_decode(r.text[r.text.find("data:", achou.start()) + 5:])
    voos = {}
    for bi in (2, 3):
        bloco = p[bi] if len(p) > bi else None
        if not bloco or not isinstance(bloco, list) or not bloco[0]:
            continue
        for it in bloco[0]:
            try:
                info, preco = it[0], it[1][0][1]
            except (IndexError, TypeError):
                continue
            if not preco:
                continue
            numero = " ".join(f"{s[22][0]}{s[22][1]}" for s in (info[2] or [])
                              if len(s) > 22 and s[22])
            escalas = len(info[13] or []) if len(info) > 13 else 0
            v = {"sai": _hora(info[5]), "chega": _hora(info[8]),
                 "cia": "+".join(info[1] or []), "voo": numero,
                 "escalas": escalas, "preco": int(preco)}
            voos[(v["sai"], v["voo"])] = v
    if not voos:
        raise RuntimeError("nenhum voo na pagina")
    return sorted(voos.values(), key=lambda v: (v["preco"], v["sai"]))


def reais(n):
    return f"R$ {n:,}".replace(",", ".")


def main(dest="CNF"):
    if dest not in c.FIXOS:
        print(f"{dest} nao e destino de data marcada")
        return 1
    ida, volta = (d.isoformat() for d in c.FIXOS[dest])
    orig, iata = c.rota_de(dest)
    pernas = []
    for rotulo, o, d, dt in (("IDA", orig, iata, ida), ("VOLTA", iata, orig, volta)):
        try:
            voos = trecho(dest, o, d, dt)
        except Exception as e:
            print(f"{rotulo} {dt}: falha ({e})")
            return 1
        pernas.append(voos)
        dia = f"{dt[8:10]}/{dt[5:7]}"
        print(f"{rotulo} {dia} ({o} para {d}, {c.adultos_de(dest)} adultos):")
        for v in voos:
            esc = "direto" if not v["escalas"] else f"{v['escalas']} escala(s)"
            print(f"  {v['sai']} a {v['chega']}  {v['cia']} {v['voo']}, {esc}: "
                  f"{reais(v['preco'])}")
        time.sleep(2)
    menor_ida = min(v["preco"] for v in pernas[0])
    menor_volta = min(v["preco"] for v in pernas[1])
    horas = lambda voos, p: ", ".join(f"{v['sai']} {v['cia']}"
                                      for v in voos if v["preco"] == p)
    print(f"MAIS BARATO: {reais(menor_ida + menor_volta)} os dois; "
          f"ida {reais(menor_ida)} ({horas(pernas[0], menor_ida)}); "
          f"volta {reais(menor_volta)} ({horas(pernas[1], menor_volta)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
