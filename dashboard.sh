#!/bin/bash
# Pearl miner status dashboard — v5 (AlphaPool API)
# Usage: ./dashboard.sh [-w SECONDS]

command -v ggrep &>/dev/null && GREP="ggrep" || GREP="grep"
PYTHON="$(command -v $PYTHON 2>/dev/null || command -v python 2>/dev/null || echo python)"

INTERVAL=0
[ "$1" = "-w" ] && [ -n "$2" ] && INTERVAL=$2
WALLET="REDACTED_WALLET"
API="https://pearl.alphapool.tech/api/miner/$WALLET"

do_row() {
    printf "│ %-10s │ %-16s │ %9.1f │ %8.1f │ %6s │\n" \
        "${1:0:10}" "${2:0:16}" "${3:-0}" "${4:-0}" "${5:-?}"
}

run() {
    now=$(date '+%H:%M:%S')
    echo "┌────────────┬──────────────────┬───────────┬──────────┬────────┐"
    echo "│  PEARL Mining Dashboard               $(printf '%20s' "$now") │"
    echo "├────────────┼──────────────────┼───────────┼──────────┼────────┤"
    echo "│ Machine    │ GPU              │ Live TH/s │  1h TH/s │      W │"
    echo "├────────────┼──────────────────┼───────────┼──────────┼────────┤"
    
    # Fetch API data
    data=$(curl -s --connect-timeout 5 "$API" 2>/dev/null)
    [ -z "$data" ] && { echo "│ API unreachable"; return; }
    
    balance=$(echo "$data" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"balance_prl\"]:.2f}')" 2>/dev/null)
    paid=$(echo "$data" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"total_paid_prl\"]:.2f}')" 2>/dev/null)
    total_1h=$(echo "$data" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['estHash1h'])" 2>/dev/null)
    
    total_live=0
    workers=$(echo "$data" | $PYTHON -c "
import sys, json
d = json.load(sys.stdin)
for w in d.get('workers', []):
    if w['online']:
        live = float(w['hashrate_live'].split()[0])
        h1 = float(w['hashrate_1h'].split()[0])
        diff = int(w['difficulty'])
        print(f'{w[\"name\"]}|{live}|{h1}|{diff}')
" 2>/dev/null)

    while IFS='|' read -r name live h1 diff; do
        [ -z "$name" ] && continue
        case "$name" in
            *5090x4*)     g_short="5090 #$(echo $name | $GREP -oP 'gpu\K[0-9]+')" ;;
            miner2.gpu*)  g_short="4060Ti #$(echo $name | $GREP -oP 'gpu\K[0-9]+')" ;;
            miner2)       g_short="4060Ti" ;;
            miner1)       g_short="RTX 3080" ;;
            miner3)       g_short="RTX 3060" ;;
            *)            g_short="$name" ;;
        esac
        
        # Map worker to machine
        m=""
        case "$name" in
            miner1)          m="station" ;;
            miner2.*)        m="lab1" ;;
            miner3)          m="laptop" ;;
            5090x4*)         m=$(echo "$name" | $GREP -oP '5090[x0-9a-z-]+' | head -1) ;;
            *)               m="$name" ;;
        esac
        
        do_row "$m" "$g_short" "$live" "$h1" "—"
        total_live=$(echo "$total_live + $live" | bc 2>/dev/null || echo "$total_live")
    done <<< "$workers"
    
    echo "├────────────┼──────────────────┼───────────┼──────────┼────────┤"
    printf "│ %-10s │ %-16s │ %9.1f │ %8s │ %6s │\n" "TOTAL" "—" "$total_live" "$total_1h" "—"
    echo "├────────────┴──────────────────┴───────────┴──────────┴────────┤"
    printf "│  Balance: %-6s PRL   |   Total Paid: %-8s PRL                │\n" "$balance" "$paid"
    echo "└──────────────────────────────────────────────────────────────┘"
}

if [ "$INTERVAL" -gt 0 ]; then
    while true; do
        frame=$(run)
        printf '\033[H%s\033[J' "$frame"  # atomic overwrite
        sleep "$INTERVAL"
    done
else
    run
fi
