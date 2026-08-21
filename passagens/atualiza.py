#!/usr/bin/env python3
"""
Rotina do painel de passagens: coleta, gera e publica, e resume em uma linha.

A ULTIMA linha da saida e sempre "ALERTA: ..." ou "SEM ALERTA: ...", para a
tarefa agendada e o workflow saberem se vale avisar o usuario sem ler o resto.

Regra do alerta (a pedido do usuario: "quando estiver abaixo da media"):
  - comum: menor preco vigente do destino cruza para baixo a media movel de
    30 dias com folga de 3%; precisa de 14+ dias de base.
  - forte: menor preco vigente no percentil 10 de tudo que ja foi visto.
Sem base suficiente, a linha diz quantos dias de base ja ha.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

DESTINOS = ("LYS", "GVA", "LIS", "CGH", "SDU", "GIG", "CNF")
NOME = {"LYS": "Lyon", "GVA": "Genebra", "LIS": "Lisboa",
        "CGH": "Congonhas", "SDU": "Santos Dumont", "GIG": "Galeão",
        "CNF": "Belo Horizonte"}
FOLGA = 0.97
BASE_MINIMA_DIAS = 14


def roda(script, *args):
    p = subprocess.run([sys.executable, str(BASE / script), *args],
                       capture_output=True, text=True)
    print(p.stdout.rstrip())
    if p.stderr.strip():
        print(p.stderr.rstrip(), file=sys.stderr)
    return p.returncode


def analisa():
    h = json.loads((BASE / "historico.json").read_text(encoding="utf-8"))
    alertas, resumo = [], []

    # Lua de mel: a melhor oferta vigente do grupo inteiro (so o voo; o
    # posicionamento aparece no painel). Alerta proprio quando houver base.
    try:
        from coletor import LUA_ROTAS, melhores_do_grupo
        m = melhores_do_grupo(h, LUA_ROTAS, 1)
        if m:
            d, ida, volta = m[0]
            ch = f"{d}|{(volta - ida).days}"
            preco = h["radar"][ch][ida.isoformat()][-1][1]
            resumo.append(f"Lua de mel: {d} {ida.strftime('%d/%m')} "
                          f"R$ {preco:,}".replace(",", "."))
    except Exception as e:
        resumo.append(f"Lua de mel sem leitura ({type(e).__name__})")
    for dest in DESTINOS:
        por_dia = {}
        celulas = []
        ultimo = -1
        for ch, por_data in (h.get("radar") or {}).items():
            d, dur = ch.split("|")
            if d != dest:
                continue
            for ida, serie in por_data.items():
                for idx, preco in serie:
                    if idx not in por_dia or preco < por_dia[idx]:
                        por_dia[idx] = preco
                    ultimo = max(ultimo, idx)
                celulas.append(serie[-1])
        if not por_dia:
            resumo.append(f"{NOME[dest]} sem leitura")
            continue
        vigentes = [c[1] for c in celulas if c[0] >= ultimo - 1]
        menor = min(vigentes) if vigentes else None
        dias = len(por_dia)
        if menor is None:
            resumo.append(f"{NOME[dest]} sem leitura vigente")
            continue
        resumo.append(f"{NOME[dest]} R$ {menor:,}".replace(",", "."))
        if dias < BASE_MINIMA_DIAS:
            resumo[-1] += f" (base {dias}/{BASE_MINIMA_DIAS} dias)"
            continue
        precos = sorted(por_dia.values())
        p10 = precos[max(0, len(precos) // 10 - 1)]
        ult30 = [v for k, v in por_dia.items() if k > ultimo - 30]
        media = sum(ult30) / len(ult30)
        if menor <= p10:
            alertas.append(f"{NOME[dest]} no piso historico: R$ {menor:,} "
                           f"(percentil 10: R$ {p10:,})".replace(",", "."))
        elif menor < media * FOLGA:
            alertas.append(f"{NOME[dest]} abaixo da media 30d: R$ {menor:,} "
                           f"contra R$ {int(media):,}".replace(",", "."))
    return alertas, resumo


def main():
    rc_coleta = roda("coletor.py")
    rc_pagina = roda("pagina.py")
    if rc_pagina != 0:
        print("ALERTA: o painel NAO foi publicado nesta rodada; ver erros acima")
        return 1
    try:
        alertas, resumo = analisa()
    except Exception as e:
        print(f"aviso: analise falhou ({type(e).__name__}: {e})")
        alertas, resumo = [], []
    sufixo = "; ".join(resumo) if resumo else "sem resumo"
    if rc_coleta != 0:
        print(f"ALERTA: rodada de coleta vazia (painel republicado com o que havia); {sufixo}")
        return 1
    if alertas:
        print(f"ALERTA: {'; '.join(alertas)}; {sufixo}")
    else:
        print(f"SEM ALERTA: {sufixo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
