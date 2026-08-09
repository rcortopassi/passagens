#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor de passagens a partir de BSB, ida e volta, em tres grupos (abas):
  - Europa: Lyon, Genebra e Lisboa, 2 adultos (o painel original), janela
    FIXA da viagem de 2027;
  - Sao Paulo: Congonhas (CGH), 1 adulto;
  - Rio de Janeiro: Santos Dumont (SDU) e Galeao (GIG), 2 adultos.
As abas domesticas nao tem viagem marcada: o objetivo e ir QUANDO ESTIVER
BARATO. A janela delas e ROLANTE (partidas de amanha ate ROL_DIAS a frente,
estadias curtas) e anda sozinha a cada rodada. Mesma analise para todos.

Fonte: Google Flights, por duas portas (reconhecimento de 05/08/2026):
  1. Busca completa: GET /travel/flights?tfs=<protobuf> devolve HTML com o bloco
     AF_initDataCallback ds:1, que traz os itinerarios completos (companhias,
     escalas, horarios, duracao, preco total 2 adultos em BRL) e o bloco de
     "price insights" (preco atual x faixa tipica da rota).
  2. GetCalendarPicker (RPC): calendario de ~84 dias em uma chamada, por
     duracao. So funciona para rota com cache global (LIS e as domesticas
     CGH, SDU e GIG, conferido em 08/08/2026: 77 datas cada). LYS e GVA nao
     tem cache nem na interface oficial: o radar delas e por busca completa
     rotativa, que de qualquer forma alimenta a serie por companhia.

Janela do usuario: partidas de 01/01/2027 a 18/03/2027, estadia de 7 a 14
noites (centro em 10), viagem inteira terminando ate 25/03/2027 (fim da
Quaresma, assumido Quinta-feira Santa).

Regras herdadas dos outros coletores (precos, takemehome):
  - Fonte que volta vazia e FALHA, nao sucesso (challenge vem com HTTP 200).
  - Historico nunca sobrescreve: acrescenta. Um ponto por dia por serie.
  - Dois donos escrevem no mesmo historico (Actions + Mac): antes de coletar,
    compara com o publicado e parte do que tiver a coleta MAIS RECENTE.
  - Campo ausente nunca vira zero.
"""
import json
import os
import re
import sys
import time
import random
from datetime import date, datetime, timedelta, timezone

from curl_cffi import requests as rq

AQUI = os.path.dirname(os.path.abspath(__file__))
HISTORICO = os.path.join(AQUI, "historico.json")
PUBLICADO = "https://rafaelcortopassi.pythonanywhere.com/passagens/historico.json"

DESTINOS = ("LYS", "GVA", "LIS", "CGH", "SDU", "GIG")
NOME_DESTINO = {"LYS": "Lyon", "GVA": "Genebra", "LIS": "Lisboa",
                "CGH": "Congonhas", "SDU": "Santos Dumont", "GIG": "Galeão"}
ORIGEM = "BSB"
# Passageiros por destino: Europa e Rio a 2 adultos, Congonhas a 1.
ADULTOS = {"LYS": 2, "GVA": 2, "LIS": 2, "CGH": 1, "SDU": 2, "GIG": 2}
# Rotas com cache de calendario no Google: lidas inteiras a cada rodada.
# LYS e GVA nao tem cache e seguem no rodizio de buscas completas.
CAL_DESTINOS = ("LIS", "CGH", "SDU", "GIG")
ROTATIVOS = ("LYS", "GVA")

# Janela da viagem da EUROPA (fixa)
PARTIDA_INI = date(2027, 1, 1)
VOLTA_MAX = date(2027, 3, 25)      # fim da Quaresma (Quinta-feira Santa)
DUR_MIN, DUR_MAX = 7, 14           # noites
PARTIDA_FIM = VOLTA_MAX - timedelta(days=DUR_MIN)   # 2027-03-18

# Janela ROLANTE das rotas domesticas: sem viagem marcada, a ideia e enxergar
# quando esta barato para ir. Anda um dia por dia, sozinha.
DOMESTICOS = ("CGH", "SDU", "GIG")
ROL_DIAS = 120                     # horizonte de partidas (~4 meses)
ROL_DUR_MIN, ROL_DUR_MAX = 2, 7    # noites (escapada curta a uma semana)


def janela(dest):
    """(partida_ini, partida_fim, volta_max, dur_min, dur_max) do destino."""
    if dest in DOMESTICOS:
        ini = agora().date() + timedelta(days=1)
        fim = ini + timedelta(days=ROL_DIAS - 1)
        return ini, fim, fim + timedelta(days=ROL_DUR_MAX), ROL_DUR_MIN, ROL_DUR_MAX
    return PARTIDA_INI, PARTIDA_FIM, VOLTA_MAX, DUR_MIN, DUR_MAX

# Datas de radar viram indice de dias desde esta base, para compactar o JSON
BASE_DIA = date(2026, 8, 1)

# Quantas buscas completas rotativas por destino sem calendario, por rodada
ROTATIVAS_POR_DESTINO = 12
# Quantos pares ja conhecidos como mais baratos re-sondar por destino
MELHORES_POR_DESTINO = 5

TZ_BSB = timezone(timedelta(hours=-3))

DATACENTER = os.environ.get("PASSAGENS_DATACENTER") == "1"

_dec = json.JSONDecoder()


def agora():
    return datetime.now(TZ_BSB)


def hoje_str():
    return agora().strftime("%Y-%m-%d")


def dia_idx(d):
    """date -> indice compacto"""
    return (d - BASE_DIA).days


def log(*a):
    print(*a, flush=True)


def busca_completa(dest, ida, volta):
    """Uma busca de verdade, pela RPC GetShoppingResults (a mesma do site).

    A pagina HTML so traz itinerarios embutidos quando a rota tem cache; para
    rota fina (LYS, GVA) eles chegam por esta RPC, entao ela e a porta unica.
    Devolve (itinerarios, insights) ou lanca erro.

    itinerarios: lista de dicts {cias, preco, paradas, escalas, dur_min}
    insights: [status, atual, tipico_min, tipico_max] ou None
    """
    leg = lambda a, b, dt: [[[[a, 0]]], [[[b, 0]]], None, 0, None, None, dt,
                            None, None, None, None, None, None, None, 3]
    spec = [None, None, 1, None, [], 1, [ADULTOS[dest], 0, 0, 0], None, None,
            None, None, None, None,
            [leg(ORIGEM, dest, ida), leg(dest, ORIGEM, volta)],
            None, None, None, 1]
    inner = [[], spec, 0, 0, 0, 1]
    freq = json.dumps([None, json.dumps(inner)])
    tent = 1 if DATACENTER else 3
    ultimo = None
    for i in range(tent):
        try:
            r = rq.post(
                "https://www.google.com/_/FlightsFrontendUi/data/"
                "travel.frontend.flights.FlightsFrontendService/GetShoppingResults",
                params={"hl": "pt-BR", "gl": "BR", "curr": "BRL", "rt": "c"},
                data={"f.req": freq},
                headers={"content-type":
                         "application/x-www-form-urlencoded;charset=UTF-8"},
                impersonate="chrome", timeout=60,
                cookies={"CONSENT": "YES+cb.20240101-00-p0.en+FX+000"})
            if r.status_code != 200:
                ultimo = f"HTTP {r.status_code}"
            else:
                idx = r.text.find('[["wrb.fr"')
                if idx < 0:
                    ultimo = "resposta sem wrb.fr (challenge provavel)"
                else:
                    data, _ = _dec.raw_decode(r.text[idx:])
                    p = json.loads(data[0][2])
                    its = []
                    for bi in (2, 3):
                        bloco = p[bi] if len(p) > bi else None
                        if not bloco or not isinstance(bloco, list) or not bloco[0]:
                            continue
                        for it in bloco[0]:
                            v = _le_itinerario(it)
                            if v:
                                its.append(v)
                    if its:
                        return its, _le_insights(p)
                    # rota com data valida nunca vem vazia de verdade
                    ultimo = "0 itinerarios (challenge provavel)"
        except Exception as e:
            ultimo = f"{type(e).__name__}: {e}"
        if i < tent - 1:
            time.sleep(10)
    raise RuntimeError(ultimo or "sem resposta")


def _le_itinerario(it):
    try:
        info = it[0]
        preco = it[1][0][1]
        if not preco:
            return None
        nomes = info[1] or []
        escalas = [e[1] for e in (info[13] or [])] if len(info) > 13 and info[13] else []
        return {
            "cias": "+".join(nomes),
            "preco": int(preco),
            "paradas": len(escalas),
            "escalas": ",".join(escalas),
            "dur_min": int(info[9]) if info[9] else None,
        }
    except (IndexError, TypeError, KeyError):
        return None


def _le_insights(p):
    """p[5] = [status, [None, atual], ?, ?, [None, tipico_min], [None, tipico_max], ...]

    status observado: 1 baixo, 2 e 3 normal, 4 e 5 alto.
    """
    try:
        s = p[5]
        if not s:
            return None
        atual = s[1][1] if s[1] else None
        tip_min = s[4][1] if len(s) > 4 and s[4] else None
        tip_max = s[5][1] if len(s) > 5 and s[5] else None
        return [s[0], atual, tip_min, tip_max]
    except (IndexError, TypeError):
        return None


def calendario(dest, dur, ini, fim):
    """GetCalendarPicker: menor preco por data de partida, duracao fixa,
    partidas de ini a fim (a RPC devolve a janela inteira pedida; conferido
    com 150 dias em uma chamada em 08/08/2026).

    Devolve lista de (date_ida, date_volta, preco). So rende para rota com
    cache (CAL_DESTINOS). Vazio nao e erro aqui: rota fina legitimamente nao
    tem cache; quem decide se e falha e o chamador, comparando com o
    rendimento esperado.
    """
    ida_ref = ini + timedelta(days=14)
    volta_ref = ida_ref + timedelta(days=dur)
    leg = lambda a, b, dt: [[[[a, 0]]], [[[b, 0]]], None, 0, None, None, dt,
                            None, None, None, None, None, None, None, 3]
    spec = [None, None, 1, None, [], 1, [ADULTOS[dest], 0, 0, 0], None, None,
            None, None, None, None,
            [leg(ORIGEM, dest, ida_ref.isoformat()),
             leg(dest, ORIGEM, volta_ref.isoformat())],
            None, None, None, 1]
    inner = [None, spec, [ini.isoformat(), fim.isoformat()],
             None, [dur, dur]]
    freq = json.dumps([None, json.dumps(inner)])
    tent = 1 if DATACENTER else 2
    ultimo = None
    for i in range(tent):
        try:
            r = rq.post(
                "https://www.google.com/_/FlightsFrontendUi/data/"
                "travel.frontend.flights.FlightsFrontendService/GetCalendarPicker",
                params={"hl": "pt-BR", "gl": "BR", "curr": "BRL", "rt": "c"},
                data={"f.req": freq},
                headers={"content-type":
                         "application/x-www-form-urlencoded;charset=UTF-8"},
                impersonate="chrome", timeout=45,
                cookies={"CONSENT": "YES+cb.20240101-00-p0.en+FX+000"})
            if r.status_code != 200:
                ultimo = f"HTTP {r.status_code}"
                continue
            idx = r.text.find('[["wrb.fr"')
            if idx < 0:
                ultimo = "resposta sem wrb.fr"
                continue
            data, _ = _dec.raw_decode(r.text[idx:])
            payload = json.loads(data[0][2])
            out = []
            for dia in payload[1] or []:
                if dia[2]:
                    out.append((date.fromisoformat(dia[0]),
                                date.fromisoformat(dia[1]),
                                int(dia[2][0][1])))
            return out
        except Exception as e:
            ultimo = f"{type(e).__name__}: {e}"
        time.sleep(8)
    raise RuntimeError(ultimo or "sem resposta")


# -------------------------------------------------------------------- historico
def _historico_vazio():
    return {
        "versao": 1,
        "ultima": None,          # instante ISO da ultima coleta OK (arbitragem)
        "rodizio": {},           # posicao do rodizio por destino
        "radar": {},             # "LIS|10" -> {"2027-01-15": [[dia_idx, preco]...]}
        "voos": {},              # "GVA|2027-01-15|2027-01-25" -> [[dia_idx, [[cias, preco, paradas, dur]...]]...]
        "insights": {},          # mesma chave -> [[dia_idx, status, atual, tmin, tmax]...]
        "rodadas": [],           # diagnostico das ultimas rodadas
    }


def carrega():
    """Local x publicado: vale o que tiver a coleta MAIS RECENTE (nao a maior)."""
    local = None
    if os.path.exists(HISTORICO):
        try:
            with open(HISTORICO, encoding="utf-8") as f:
                local = json.load(f)
        except Exception as e:
            log(f"aviso: historico local ilegivel ({e}); ignorando")
    pub = None
    try:
        r = rq.get(PUBLICADO, impersonate="chrome", timeout=30)
        if r.status_code == 200:
            pub = r.json()
    except Exception as e:
        log(f"aviso: historico publicado inacessivel ({e})")
    if local is None and pub is None:
        return _historico_vazio()
    if local is None:
        return pub
    if pub is None:
        return local
    tl = local.get("ultima") or ""
    tp = pub.get("ultima") or ""
    escolhido = pub if tp > tl else local
    log(f"arbitragem: local={tl or '-'} publicado={tp or '-'} -> "
        f"{'publicado' if escolhido is pub else 'local'}")
    return escolhido


def grava(h):
    tmp = HISTORICO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, HISTORICO)


def _poe_ponto_dia(serie, idx, valor):
    """Um ponto por dia: se o dia ja tem ponto, substitui (ultima leitura vale)."""
    if serie and serie[-1][0] == idx:
        serie[-1] = [idx, valor]
    else:
        serie.append([idx, valor])


def registra_radar(h, dest, dur, ida, preco):
    ch = f"{dest}|{dur}"
    pordata = h["radar"].setdefault(ch, {})
    serie = pordata.setdefault(ida.isoformat(), [])
    _poe_ponto_dia(serie, dia_idx(agora().date()), preco)


def registra_voos(h, dest, ida, volta, its):
    ch = f"{dest}|{ida.isoformat()}|{volta.isoformat()}"
    serie = h["voos"].setdefault(ch, [])
    # por companhia (combinacao), o menor preco do dia
    porcia = {}
    for it in its:
        c = it["cias"]
        if c not in porcia or it["preco"] < porcia[c][1]:
            porcia[c] = [c, it["preco"], it["paradas"], it["dur_min"]]
    resumo = sorted(porcia.values(), key=lambda x: x[1])
    _poe_ponto_dia(serie, dia_idx(agora().date()), resumo)
    # o menor do dia tambem alimenta o radar
    dur = (volta - ida).days
    if resumo:
        registra_radar(h, dest, dur, ida, resumo[0][1])


def registra_intradia(h, dest, preco):
    """Serie intradiaria: menor preco visto na SONDA desta rodada, por destino.

    E ela que permite medir melhor horario e dia da semana de COMPRA: o radar
    guarda so um ponto por dia e joga fora a variacao dentro do dia. A sonda
    reconsulta a cada rodada aproximadamente os mesmos pares (os mais baratos
    conhecidos), entao a serie compara precos do MESMO cesto hora a hora.
    Ponto = [horas desde BASE_DIA em Brasilia, preco]. Limitada aos ultimos
    6000 pontos por destino (uns 8 meses de rodadas horarias).
    """
    agora_ = agora()
    hora_idx = dia_idx(agora_.date()) * 24 + agora_.hour
    serie = h.setdefault("intradia", {}).setdefault(dest, [])
    serie.append([hora_idx, preco])
    if len(serie) > 6000:
        del serie[:len(serie) - 6000]


def registra_insights(h, dest, ida, volta, ins):
    if not ins:
        return
    ch = f"{dest}|{ida.isoformat()}|{volta.isoformat()}"
    serie = h["insights"].setdefault(ch, [])
    _poe_ponto_dia(serie, dia_idx(agora().date()),
                   [ins[0], ins[1], ins[2], ins[3]])


# --------------------------------------------------- conferencia direta (teste)
GOL_SEO_URL = "https://www.voegol.com.br/br/voos/brasilia-para-sao-paulo"


def conferencia_gol(h):
    """Le as tarifas que a PROPRIA GOL anuncia no site dela para BSB<->CGH.

    Fonte: o cache de tarifas (airTRFX/EveryMundo) embutido nas paginas de
    ofertas do voegol.com.br, renderizado no servidor e fora do desafio do
    Akamai; e o mesmo dado "a partir de" que o site mostra ao público, com
    carimbo de "visto ha N horas". Cada pagina traz o par nas duas direcoes.

    Reconhecimento de 09/08/2026: a BUSCA completa (escolhendo datas) da GOL,
    da LATAM e da Azul fica atras do Akamai Bot Manager e nao e viavel por
    rodada automatica; esta e a parte do site da companhia que da para
    conferir de hora em hora. Preco de 1 adulto, SO IDA, por direcao; a soma
    das duas direcoes e comparavel ao radar de Congonhas (1 adulto, ida e
    volta), porque tarifa domestica e vendida por trecho.

    Serie em h["diretas"]["GOL|BSB|CGH"] = [[dia_idx, [data_anunciada,
    preco]], ...], um ponto por dia (ultima leitura do dia vale).
    """
    r = rq.get(GOL_SEO_URL, impersonate="chrome", timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("pagina sem __NEXT_DATA__ (mudou o layout?)")
    fares = []

    def acha(o):
        if isinstance(o, dict):
            if o.get("__typename") == "Fare":
                fares.append(o)
            for v in o.values():
                acha(v)
        elif isinstance(o, list):
            for v in o:
                acha(v)

    acha(json.loads(m.group(1)))
    n = 0
    for f in fares:
        o, d = f.get("originAirportCode"), f.get("destinationAirportCode")
        if {o, d} != {"BSB", "CGH"} or f.get("flightType") != "ONE_WAY":
            continue
        preco, ida = f.get("totalPrice"), f.get("departureDate")
        if not preco or not ida:
            continue
        serie = h.setdefault("diretas", {}).setdefault(f"GOL|{o}|{d}", [])
        _poe_ponto_dia(serie, dia_idx(agora().date()), [ida, preco])
        n += 1
    if not n:
        raise RuntimeError("pagina sem tarifa BSB<->CGH (cache da GOL vazio?)")
    return n


def poda_alem_do_horizonte(h):
    """Tira das rotas domesticas datas de ida alem do horizonte rolante.

    Sobra da migracao de 08/08/2026 (as domesticas nasceram com a janela fixa
    de 2027 e mudaram para a rolante no mesmo dia) e defesa contra uma rodada
    concorrente republicar essas chaves. Depois de limpo, nunca dispara:
    o coletor so registra dentro do horizonte. Datas que ficaram para TRAS
    nao sao tocadas; elas sao a historia do painel.
    """
    podadas = 0
    for dest in DOMESTICOS:
        lim = janela(dest)[1].isoformat()
        for ch in [c for c in h.get("radar", {}) if c.split("|")[0] == dest]:
            pordata = h["radar"][ch]
            for ida in [i for i in pordata if i > lim]:
                del pordata[ida]
                podadas += 1
            if not pordata:
                del h["radar"][ch]
        for campo in ("voos", "insights"):
            for ch in [c for c in h.get(campo, {})
                       if c.split("|")[0] == dest and c.split("|")[1] > lim]:
                del h[campo][ch]
                podadas += 1
    if podadas:
        log(f"poda: {podadas} entradas domesticas alem do horizonte")


# ------------------------------------------------------------------ grade/rodizio
def pares_validos():
    """Todos os pares (ida, dur) dentro da janela."""
    pares = []
    d = PARTIDA_INI
    while d <= PARTIDA_FIM:
        for dur in range(DUR_MIN, DUR_MAX + 1):
            if d + timedelta(days=dur) <= VOLTA_MAX:
                pares.append((d, dur))
        d += timedelta(days=1)
    return pares


def ordem_rodizio(pares):
    """Duracao 9-11 primeiro (centro do interesse), depois o resto."""
    centro = [p for p in pares if 9 <= p[1] <= 11]
    resto = [p for p in pares if not (9 <= p[1] <= 11)]
    return centro + resto


def melhores_conhecidos(h, dest, n):
    """Os n pares (ida, volta) mais baratos ja vistos no radar deste destino.

    Ignora partidas que ja passaram: na janela rolante das rotas domesticas o
    radar acumula datas que ficam para tras, e sondar voo de ontem e pedir
    resposta vazia.
    """
    hoje = agora().date()
    vistos = []
    for ch, pordata in h["radar"].items():
        d, dur = ch.split("|")
        if d != dest:
            continue
        for ida_s, serie in pordata.items():
            if serie:
                ida = date.fromisoformat(ida_s)
                if ida <= hoje:
                    continue
                vistos.append((serie[-1][1], ida, ida + timedelta(days=int(dur))))
    vistos.sort()
    out, ja = [], set()
    for preco, ida, volta in vistos:
        chave = (ida, volta)
        if chave not in ja:
            ja.add(chave)
            out.append((ida, volta))
        if len(out) >= n:
            break
    return out


# ----------------------------------------------------------------------- rodada
def rodada():
    h = carrega()
    poda_alem_do_horizonte(h)
    inicio = agora()
    ok, falhas = {}, {}
    fonte = "actions" if os.environ.get("GITHUB_ACTIONS") else "mac"

    # 1) Radar pelo calendario, todas as duracoes, nas rotas com cache
    for cdest in CAL_DESTINOS:
        ini, fim, vmax, dmin, dmax = janela(cdest)
        total_cal = 0
        for dur in range(dmin, dmax + 1):
            try:
                dias = calendario(cdest, dur, ini, fim)
                uteis = 0
                for ida, volta, preco in dias:
                    if ini <= ida <= fim and volta <= vmax:
                        registra_radar(h, cdest, dur, ida, preco)
                        uteis += 1
                total_cal += uteis
                log(f"calendario {cdest} dur={dur}: {uteis} datas")
            except Exception as e:
                falhas[f"calendario {cdest} {dur}"] = str(e)[:200]
                log(f"FALHA calendario {cdest} dur={dur}: {e}")
            time.sleep(2 + random.random() * 2)
        if total_cal == 0:
            falhas[f"calendario {cdest}"] = "todas as duracoes vieram vazias"
        else:
            ok[f"calendario {cdest}"] = total_cal

    # 1b) Conferencia direta no site da GOL (BSB<->CGH), mesma frequencia
    try:
        ok["conferencia GOL"] = conferencia_gol(h)
        log(f"conferencia GOL: {ok['conferencia GOL']} direcoes")
    except Exception as e:
        falhas["conferencia GOL"] = str(e)[:200]
        log(f"FALHA conferencia GOL: {e}")

    # 2) Radar rotativo por busca completa: destinos sem cache de calendario
    pares = ordem_rodizio(pares_validos())
    desafios_seguidos = 0
    for dest in ROTATIVOS:
        pos = h["rodizio"].get(dest, 0)
        feitos = 0
        for i in range(ROTATIVAS_POR_DESTINO):
            ida, dur = pares[(pos + i) % len(pares)]
            volta = ida + timedelta(days=dur)
            try:
                its, ins = busca_completa(dest, ida.isoformat(), volta.isoformat())
                registra_voos(h, dest, ida, volta, its)
                registra_insights(h, dest, ida, volta, ins)
                feitos += 1
                desafios_seguidos = 0
                log(f"busca {dest} {ida} +{dur}d: {len(its)} itinerarios, "
                    f"menor R$ {min(x['preco'] for x in its)}")
            except Exception as e:
                falhas[f"busca {dest} {ida}"] = str(e)[:200]
                desafios_seguidos += 1
                log(f"FALHA busca {dest} {ida}: {e}")
                if desafios_seguidos >= 3:
                    log("3 desafios seguidos; interrompendo as buscas da rodada")
                    break
            time.sleep(3 + random.random() * 3)
        h["rodizio"][dest] = (pos + feitos) % len(pares)
        if feitos:
            ok[f"rotativas {dest}"] = feitos
        if desafios_seguidos >= 3:
            break

    # 3) Sonda dos pares mais baratos ja conhecidos (todos os destinos)
    if desafios_seguidos < 3:
        for dest in DESTINOS:
            n = MELHORES_POR_DESTINO if dest != "LIS" else MELHORES_POR_DESTINO * 2
            sondados = 0
            melhor_da_sonda = None
            for ida, volta in melhores_conhecidos(h, dest, n):
                try:
                    its, ins = busca_completa(dest, ida.isoformat(), volta.isoformat())
                    registra_voos(h, dest, ida, volta, its)
                    registra_insights(h, dest, ida, volta, ins)
                    menor = min(x["preco"] for x in its)
                    if melhor_da_sonda is None or menor < melhor_da_sonda:
                        melhor_da_sonda = menor
                    sondados += 1
                    desafios_seguidos = 0
                except Exception as e:
                    falhas[f"sonda {dest} {ida}"] = str(e)[:200]
                    desafios_seguidos += 1
                    if desafios_seguidos >= 3:
                        break
                time.sleep(3 + random.random() * 3)
            if sondados:
                ok[f"sonda {dest}"] = sondados
                registra_intradia(h, dest, melhor_da_sonda)
            log(f"sonda {dest}: {sondados} pares")
            if desafios_seguidos >= 3:
                break

    # So carimba "ultima" se alguma coisa entrou; rodada 100% vazia nao
    # pode ganhar a arbitragem de ninguem.
    if ok:
        h["ultima"] = inicio.isoformat(timespec="seconds")
    h["rodadas"].append({
        "quando": inicio.isoformat(timespec="seconds"),
        "fonte": fonte,
        "ok": ok,
        "falhas": falhas,
        "dur_s": int((agora() - inicio).total_seconds()),
    })
    h["rodadas"] = h["rodadas"][-200:]
    grava(h)

    log(f"\nrodada {fonte}: {sum(ok.values())} coletas ok, {len(falhas)} falhas, "
        f"{int((agora() - inicio).total_seconds())}s")
    if not ok:
        log("RODADA VAZIA: nenhuma fonte rendeu; ver falhas acima")
        return False
    return True


if __name__ == "__main__":
    sucesso = rodada()
    sys.exit(0 if sucesso else 1)
