#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# tst_report.sh
# estado do ambiente de teste: contagens (alimentador, inbox, radar/, banco)
# e, sem --counts, os dry-runs do nowcast (lacunas/interpolações e
# sequências projetadas).  Só leitura (banco aberto com mode=ro).
#
# uso: tst_report.sh [-r raiz] [--counts] [args dos dry-runs: -s CGU-250 --from ISO ...]
#
# 2026.out  mlabru  initial version (Linux/Bash)

set -euo pipefail

TST_ENV_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

LS_ROOT="$( cd "${TST_ENV_DIR}/../../.." && pwd )/03.dat/tst"
LB_COUNTS_ONLY=false
LARR_DRY=()

while [ $# -gt 0 ]; do
    case "$1" in
        -r) LS_ROOT="$2"; shift 2 ;;
        --counts) LB_COUNTS_ONLY=true; shift ;;
        *) LARR_DRY+=("$1"); shift ;;
    esac
done

# shellcheck source=/dev/null
source "${LS_ROOT}/env.sh"

[ -n "${VIRTUAL_ENV:-}" ] || { [ -f ~/.venv/bin/activate ] && source ~/.venv/bin/activate; }

# < contagens >------------------------------------------------------------------------

python3 - <<'EOF'
import json, os, pathlib, sqlite3

lpth_root = pathlib.Path(os.environ["MET_TST_ROOT"])
lpth_db = pathlib.Path(os.environ["VOL_DBASE_FILE"])

lpth_cursor = lpth_root / "feed" / "cursor.json"
ldct = json.loads(lpth_cursor.read_text()) if lpth_cursor.exists() else {}
print(f"  feed: entregues {ldct.get('delivered', 0)}, descartados {ldct.get('dropped', 0)}"
      f" | inbox {sum(1 for _ in (lpth_root / 'inbox').rglob('*.mvol'))}"
      f" | radar/ {sum(1 for _ in (lpth_root / 'radar').rglob('*.mvol'))}")

if not lpth_db.exists():
    print("  banco: ainda não criado")
    raise SystemExit(0)

lconn = sqlite3.connect(f"file:{lpth_db}?mode=ro", uri=True)

def q(fs_sql):
    try:
        return lconn.execute(fs_sql).fetchall()
    except sqlite3.OperationalError as lerr:
        return f"({lerr})"

print(f"  vol_raw_observations {q('SELECT COUNT(*) FROM vol_raw_observations')}"
      f" | volumes (total, has_mvol) {q('SELECT COUNT(*), SUM(has_mvol) FROM volumes')}")
print(f"  cappi_products (preset, origin, status, n) "
      f"{q('SELECT preset, origin, status, COUNT(*) FROM cappi_products GROUP BY 1, 2, 3')}")
print(f"  sequences (quality, n) {q('SELECT quality, COUNT(*) FROM sequences GROUP BY 1')}"
      f" | cappi_pending {q('SELECT COUNT(*) FROM cappi_pending')}")

# 25.oflow: GIFs gerados e a última verificação de cada par
lpth_out = pathlib.Path(os.environ.get("OFL_PATH", lpth_root / "oflow")) / "data" / "output"
if lpth_out.is_dir():
    print(f"  oflow: GIFs {sum(1 for _ in lpth_out.glob('*_now_*.gif'))}")
    for lpth_v in sorted(lpth_out.glob("*_verify.jsonl")):
        llst = [ll for ll in lpth_v.read_text().splitlines() if ll.strip()]
        if not llst:
            continue
        ldct_v = json.loads(llst[-1])
        def csi(fd, fs="30"):
            lx = fd["limiares"].get(fs, {}).get("csi")
            return "-" if lx is None else f"{lx:.2f}"
        ls_b = " ".join(f"{ls}={csi(ld)}" for ls, ld in ldct_v["backends"].items())
        print(f"  oflow {lpth_v.stem[:-7]}: {len(llst)} verificação(ões); última CSI30 "
              f"{ls_b} persistência={csi(ldct_v['persistencia'])}")
EOF

${LB_COUNTS_ONLY} && exit 0

# < dry-runs do nowcast >--------------------------------------------------------------

cd "${NWC_PATH}"
export PYTHONPATH="${TST_NWC_DIR}/apps:${TST_NWC_DIR}/apps/util"

echo
python3 "${TST_NWC_DIR}/apps/nwcInterpolate.py" --dry-run "${LARR_DRY[@]}" 2> /dev/null
echo
python3 "${TST_NWC_DIR}/apps/nwcSequences.py" --dry-run "${LARR_DRY[@]}" 2> /dev/null

# < the end >--------------------------------------------------------------------------
