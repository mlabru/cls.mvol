# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

tst_feed
alimentador do ambiente de teste: entrega no inbox (o "servidor" do
vol_sync.sh, VOL_REMOTE_DIR) os próximos .mvol reais de TST_SRC
(03.dat/lmc15.ori), em ordem cronológica pelo horário do nome, simulando a
chegada dos volumes do radar.

- hardlink (os.link): não ocupa espaço e nunca altera o original -- o rsync
  --remove-source-files do vol_sync.sh só remove o link do inbox
- cursor em <MET_TST_ROOT>/feed/cursor.json: cada execução continua de onde
  a anterior parou
- --drop-every K / --drop P: deixa volumes de fora (nunca entregues), para
  criar lacunas e exercitar a interpolação; os descartados vão para
  feed/dropped.txt (epoch|caminho relativo) e os entregues para
  feed/delivered.txt

uso (com o env.sh do ambiente carregado):
    python3 tst_feed.py --hours 2 [--drop-every 7] [--dry-run]
    python3 tst_feed.py --count 50

2026.out  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import argparse
import json
import os
import pathlib
import random
import sys

# < constants >────────────────────────────────────────────────────────────────────────

# extensão dos volumes
CS_EXT = ".mvol"

# < funções >──────────────────────────────────────────────────────────────────────────

def arg_parse(flst_argv: list | None = None) -> argparse.Namespace:
    """
    argumentos de linha de comando
    """
    lparser = argparse.ArgumentParser(description="entrega .mvol reais no inbox do ambiente de teste")

    lgroup = lparser.add_mutually_exclusive_group(required=True)
    lgroup.add_argument("--hours", type=float, help="entrega as próximas H horas de volumes")
    lgroup.add_argument("--count", type=int, help="entrega os próximos N volumes")

    lparser.add_argument("--drop-every", type=int, default=0, metavar="K",
                         help="descarta o K-ésimo volume de cada série (cria lacunas de 1 slot)")
    lparser.add_argument("--drop", type=float, default=0.0, metavar="P",
                         help="descarta cada volume com probabilidade P")
    lparser.add_argument("--seed", type=int, default=0, help="semente do --drop")
    lparser.add_argument("--dry-run", action="store_true", help="só lista, não entrega")

    # ok
    return lparser.parse_args(flst_argv)

# ─────────────────────────────────────────────────────────────────────────────────────
def check_env() -> tuple:
    """
    confere o ambiente (env.sh) e devolve (raiz, origem, inbox)

    :raises SystemExit: fora de um ambiente de teste coerente
    """
    if os.environ.get("MET_ENV") != "test":
        sys.exit("tst_feed: MET_ENV=test não definido (carregue o env.sh do ambiente)")

    lpth_root = pathlib.Path(os.environ["MET_TST_ROOT"]).resolve()
    lpth_src = pathlib.Path(os.environ["TST_SRC"]).resolve()
    lpth_inbox = pathlib.Path(os.environ["VOL_REMOTE_DIR"]).resolve()

    if lpth_root not in lpth_inbox.parents:
        sys.exit(f"tst_feed: inbox {lpth_inbox} fora de {lpth_root}")

    if lpth_src == lpth_root or lpth_root in lpth_src.parents:
        sys.exit(f"tst_feed: origem {lpth_src} dentro do ambiente")

    # ok
    return lpth_root, lpth_src, lpth_inbox

# ─────────────────────────────────────────────────────────────────────────────────────
def index_source(fpth_src: pathlib.Path) -> list:
    """
    todos os .mvol da origem: [(epoch, série, caminho relativo)], em ordem
    cronológica (empate: pelo caminho)
    """
    import radar.rd_mvol as mv

    llst = []

    for lpth in fpth_src.rglob(f"*{CS_EXT}"):
        try:
            l_mvol = mv.parse_mvol(lpth)

        # nome fora do padrão: não é um volume
        except ValueError:
            continue

        llst.append((int(l_mvol.timestamp.timestamp()),
                     f"{l_mvol.product.station}-{l_mvol.product.range_km}",
                     str(lpth.relative_to(fpth_src))))

    # ok
    return sorted(llst)

# ─────────────────────────────────────────────────────────────────────────────────────
def select(flst_index: list, fi_after: int, ff_hours: float | None,
           fi_count: int | None) -> list:
    """
    os próximos volumes depois do cursor: as próximas ff_hours horas (a
    partir do primeiro pendente) ou os próximos fi_count
    """
    llst = [lt for lt in flst_index if lt[0] > fi_after]

    if not llst:
        return []

    if fi_count is not None:
        # inclui os demais do mesmo instante do último: o cursor é por epoch
        li_last = llst[min(fi_count, len(llst)) - 1][0]
        return llst[:fi_count] + \
               [lt for lt in llst[fi_count:] if lt[0] == li_last]

    li_limit = llst[0][0] + int(ff_hours * 3600)

    # ok
    return [lt for lt in llst if lt[0] < li_limit]

# ─────────────────────────────────────────────────────────────────────────────────────
def main(flst_argv: list | None = None) -> int:
    """
    ponto de entrada

    :returns: 0 = ok
    """
    largs = arg_parse(flst_argv)

    lpth_root, lpth_src, lpth_inbox = check_env()

    lpth_feed = lpth_root / "feed"
    lpth_cursor = lpth_feed / "cursor.json"

    ldct_cursor = json.loads(lpth_cursor.read_text()) if lpth_cursor.exists() else \
                  {"last_epoch": 0, "series_count": {}, "delivered": 0, "dropped": 0}

    llst_next = select(index_source(lpth_src), ldct_cursor["last_epoch"], largs.hours, largs.count)

    if not llst_next:
        print("tst_feed: origem esgotada, nada a entregar")
        return 0

    l_random = random.Random(largs.seed + ldct_cursor["last_epoch"])

    llst_deliver, llst_drop = [], []

    for li_epoch, ls_series, ls_rel in llst_next:
        li_n = ldct_cursor["series_count"].get(ls_series, 0) + 1
        ldct_cursor["series_count"][ls_series] = li_n

        lb_drop = ((largs.drop_every > 0 and 0 == li_n % largs.drop_every) or
                   (largs.drop > 0 and l_random.random() < largs.drop))

        (llst_drop if lb_drop else llst_deliver).append((li_epoch, ls_rel))

    print(f"tst_feed: {len(llst_deliver)} a entregar, {len(llst_drop)} descartados "
          f"({llst_next[0][2]} .. {llst_next[-1][2]})")

    if largs.dry_run:
        for li_epoch, ls_rel in llst_deliver:
            print(f"  + {ls_rel}")
        for li_epoch, ls_rel in llst_drop:
            print(f"  - {ls_rel}")

        # ok
        return 0

    lpth_feed.mkdir(parents=True, exist_ok=True)

    for li_epoch, ls_rel in llst_deliver:
        lpth_dst = lpth_inbox / ls_rel
        lpth_dst.parent.mkdir(parents=True, exist_ok=True)

        # já entregue (execução anterior interrompida antes do cursor)
        if not lpth_dst.exists():
            os.link(lpth_src / ls_rel, lpth_dst)

    with (lpth_feed / "delivered.txt").open("a") as lfh:
        lfh.writelines(f"{li}|{ls}\n" for li, ls in llst_deliver)

    with (lpth_feed / "dropped.txt").open("a") as lfh:
        lfh.writelines(f"{li}|{ls}\n" for li, ls in llst_drop)

    ldct_cursor["last_epoch"] = llst_next[-1][0]
    ldct_cursor["delivered"] += len(llst_deliver)
    ldct_cursor["dropped"] += len(llst_drop)

    # cursor por último: uma execução interrompida repete a entrega (idempotente)
    lpth_cursor.write_text(json.dumps(ldct_cursor, indent=1))

    # ok
    return 0

# ─────────────────────────────────────────────────────────────────────────────────────

if "__main__" == __name__:

    # radar.* do 21.mvol (apps/)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "apps"))

    # run
    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
