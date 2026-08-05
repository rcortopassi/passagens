#!/usr/bin/env python3
"""
Gera passagens.html a partir do template.html + historico.json E PUBLICA.

O HTML sai autonomo: os dados vao embutidos no proprio arquivo, sem fetch,
para ser servido como estatico no PythonAnywhere (mesmo esquema dos paineis
de precos, de alugueis e do agregador).

Publicar e o comportamento PADRAO, de proposito: pagina gerada e pagina no ar.

Uso:
  python3 passagens/pagina.py               # gera, valida e publica
  python3 passagens/pagina.py --sem-deploy  # so gera, para inspecionar local
  python3 passagens/pagina.py --force       # publica mesmo com o JS quebrado
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
TEMPLATE = BASE / "template.html"
HIST = BASE / "historico.json"
SAIDA = BASE / "passagens.html"
MARCA = "/*__DADOS__*/{}"


def valida_js(path):
    """new Function(script) sem erro de sintaxe, igual aos outros paineis."""
    m = re.search(r"<script>([\s\S]*)</script>", path.read_text(encoding="utf-8"))
    if not m:
        return False, "nao achei o <script> inline"
    try:
        p = subprocess.run(
            ["node", "-e", "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
                           "try{new Function(s);console.log('OK')}"
                           "catch(e){console.log('ERRO: '+e.message);process.exit(2)}});"],
            input=m.group(1), text=True, capture_output=True, timeout=60)
    except FileNotFoundError:
        return True, "node nao encontrado; pulei a validacao"
    except subprocess.TimeoutExpired:
        return False, "validacao do JS estourou o tempo"
    return p.returncode == 0, (p.stdout or p.stderr).strip()


def historico():
    """Mesma arbitragem do coletor: vale a coleta MAIS RECENTE, local ou
    publicada. Rodar so o pagina.py para mexer no visual sem coletar nao pode
    publicar o historico parado deste Mac por cima do que o Actions juntou.
    """
    try:
        sys.path.insert(0, str(BASE))
        from coletor import carrega
    except Exception as e:
        print(f"  ..   Sem a arbitragem do coletor ({type(e).__name__}); "
              f"seguindo so com o historico local.")
        return json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
    h = carrega()
    if h.get("ultima"):
        HIST.write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    return h


def enxuga(h):
    """Tira do JSON embutido o que a pagina nao le."""
    h = dict(h)
    h["rodadas"] = (h.get("rodadas") or [])[-30:]
    h.pop("rodizio", None)
    return h


def main():
    h = historico()
    if not h.get("radar") and not h.get("voos"):
        print("ERRO: historico sem nenhuma coleta. Rode o coletor primeiro.")
        return 1
    tpl = TEMPLATE.read_text(encoding="utf-8")
    if MARCA not in tpl:
        print(f"ERRO: nao achei a marca {MARCA} no template.")
        return 1
    dados = json.dumps(enxuga(h), ensure_ascii=False, separators=(",", ":"))
    dados = dados.replace("</", "<\\/")
    SAIDA.write_text(tpl.replace(MARCA, dados), encoding="utf-8")

    kb = SAIDA.stat().st_size / 1024
    n_series = sum(len(v) for v in (h.get("radar") or {}).values())
    print(f"Gerado {SAIDA.name}: {kb:.0f} KB, {n_series} series de radar, "
          f"{len(h.get('voos') or {})} pares sondados, ultima coleta {h.get('ultima')}.")

    ok, msg = valida_js(SAIDA)
    print(f"Validacao do JS: {msg}")
    if not ok and "--force" not in sys.argv:
        print("ABORTADO: o JS esta quebrado, nao publiquei. Corrija (ou use --force).")
        return 1

    if "--sem-deploy" in sys.argv:
        print("Deploy pulado (--sem-deploy).")
        return 0

    p = subprocess.run([sys.executable, str(BASE / "deploy.py")],
                       capture_output=True, text=True)
    print(p.stdout.rstrip())
    if p.stderr.strip():
        print(p.stderr.rstrip(), file=sys.stderr)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
