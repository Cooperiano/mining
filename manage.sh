#!/bin/bash
# One-click miner management — status, deploy, kill
# Usage: ./manage.sh [status|deploy|kill <id>]

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

BOLD='\033[1m'
GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
NC='\033[0m'

case "${1:-status}" in

status)
  echo -e "${BOLD}=== Running Instances ===${NC}"
  python3 -c "
import subprocess, re
r=subprocess.run(['vastai','show','instances'],capture_output=True,text=True,timeout=15)
clean=re.sub(r'\x1b\[[0-9;]*m','',r.stdout)
for l in clean.split('\n'):
    p=l.split()
    if len(p)>=6 and p[1].isdigit() and p[3]=='running':
        rid,machine,gpu=p[1],p[2],f'{p[4]} {p[5]}'
        ru=subprocess.run(['vastai','ssh-url',rid],capture_output=True,text=True,timeout=10)
        m=re.search(r'@([^:]+):(\d+)',ru.stdout.strip())
        if not m: print(f'  {rid} {gpu:<16} m{machine}  no SSH'); continue
        host,port=m.group(1),m.group(2)
        try:
            r2=subprocess.run(['ssh','-q','-o','StrictHostKeyChecking=no','-o','ConnectTimeout=6',
                f'root@{host}','-p',port,
                'p=\$(pgrep -c alpha-miner 2>/dev/null||echo 0);'
                'h=\$(grep \"hashrate_th_s=\" /root/mining/miner.log 2>/dev/null|tail -1|grep -oP \"[0-9.]+(?= tmac)\" 2>/dev/null||echo 0);'
                'v=\$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null|paste -sd+ | tr -d \"\\n\");'
                'c=\$(nvidia-smi --query-gpu=count --format=csv,noheader,nounits 2>/dev/null|tr -d \"\\n\");'
                'echo \"p=\$p h=\$h v=\$v c=\$c\"'],
                capture_output=True,text=True,timeout=10)
            pm=re.search(r'p=(\d+)',r2.stdout); hm=re.search(r'h=([\d.]+)',r2.stdout)
            vm=re.search(r'v=(\d+)',r2.stdout); cm=re.search(r'c=(\d+)',r2.stdout)
            pc=int(pm.group(1))if pm else 0; th=float(hm.group(1))if hm else 0
            vram=int(vm.group(1))if vm else 0; gpus=int(cm.group(1))if cm else 1
        except: pc=th=vram=gpus=0
        # 显存检查: 单卡正常 ~4.5G, 多卡应该是倍数, 过低=没跑起来, 过高=重复进程
        vram_status=''
        if vram>0 and gpus>0:
            vram_per_gpu=vram/gpus
            if vram_per_gpu<1000: vram_status=' [显存过低]'
            elif vram_per_gpu>5500: vram_status=f' [显存异常 {vram_per_gpu/1024:.1f}G/卡]'
        if pc>0 and th>0: ms=f'✅ {th:.0f} TH/s'
        elif pc>0: ms='⏳ booting'
        else: ms='❌ no miner'
        print(f'  {rid} {gpu:<16} m{machine}  {ms}{vram_status}')
" 2>/dev/null
  ;;

deploy)
  echo -e "${BOLD}=== Autodeploy ===${NC}"
  python3 "$DIR/autodeploy_cron.py"
  ;;

parallel)
  echo -e "${BOLD}=== Parallel Deploy ===${NC}"
  python3 "$DIR/parallel_deploy.py" "${@:2}"
  ;;

kill)
  id="${2:?Usage: ./manage.sh kill <instance_id>}"
  echo -e "${RED}Destroying $id...${NC}"
  echo y | vastai destroy instance "$id"
  sed -i '' "/$id/d" .vast_deployed 2>/dev/null
  ;;

hashrate)
  python3 "$DIR/hashrate_report.py"
  ;;

log)
  tail -f "$DIR/autodeploy.log" 2>/dev/null || echo "No autodeploy log yet"
  ;;

*)
  echo "Usage: ./manage.sh [status|deploy|parallel|kill <id>|hashrate|log]"
  ;;

esac
