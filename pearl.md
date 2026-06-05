
AlphaPoolPearl
Dashboard
Blocks
Miners
Get Started
FAQ
mainnet · h 66,255 · 15:14:20
Dashboard
Blocks
Miners
Get Started
FAQ
All pools →
Get Started
Three commands. ~30 seconds. No signup, no whitelist, no KYC.

Step 1
Get a Pearl address
Install the Pearl wallet and generate an address starting with prl1p…. Save your seed phrase offline. This is where your payouts go.

Step 2
Run alpha-miner
One curl + one ./alpha-miner command. Linux x86_64, every NVIDIA tensor-core GPU from Volta to Blackwell, including Hopper (V100, RTX 30/40/50, A100, L4/L40, H100/H200, B100/B200, CMP 100-210). Auto-detects all your GPUs.

Step 3
Watch payouts arrive
First share in ~10 seconds. PPLNS payouts every 4 hours, 0.5 PRL minimum. Track live on the Dashboard by pasting your address.

Before you start
If your rig already mines any GPU coin, the one-liner below just works. The binary is statically linked — its only runtime dependency is the NVIDIA driver (already present on any mining rig).
GPU: NVIDIA Volta through Blackwell + Hopper (V100, Titan V, CMP 100-210, RTX 30/40/50, A100, L4/L40, H100/H200, B100/B200). Turing (RTX 20-series, T4, CMP 30HX/40HX/50HX) is the only current gap — pending upstream kernels.
OS: Linux x86_64 (Ubuntu 14.04+, Debian 8+, RHEL 7+, glibc 2.18+) or Windows via WSL2 — verified working on Windows 11 with NVIDIA RTX cards. Native Windows .exe on the way.
Renting cloud GPUs? Use the Docker / RunPod / vast.ai tab — one docker run command, works anywhere with NVIDIA Docker.
Driver: Any reasonably modern NVIDIA driver (R470+ for Ampere, R525+ for Ada, R550+ for Blackwell). Already installed on any mining rig.
Network: Outbound TCP to us2.alphapool.tech:5566. No inbound ports needed.
VRAM: ~2 GB per GPU. ~36 MB disk for the binary.
Quickstart
Pro tip: if vardiff isn't converging well for your hardware (most common on multi-rig HiveOS / mixed-card setups), pin a static difficulty by setting --password "x;d=4096". Pick a value matched to your card — table in the Static difficulty tab below.
Pick the endpoint closest to you for lowest share latency.

North America: us1.alphapool.tech:5566 (East) / us2.alphapool.tech:5566 (West)
Europe: eu1.alphapool.tech:5566 / eu2.alphapool.tech:5566
Russia / Eurasia: ru1.alphapool.tech:5566
Asia: sg1.alphapool.tech:5566

:5566 = pooled PPLNS, smooth 5% fee payouts.
Solo mining is temporarily paused while we re-integrate it in a more fitting location. Pooled (PPLNS) is unaffected.

Static difficulty by card class
Add --password "x;d=<DIFFICULTY>" to your command line (or set PEARL_DIFFICULTY=<N> for Docker) to pin a static share difficulty. Recommended for multi-GPU rigs and any setup where vardiff doesn't ratchet quickly. Wrong difficulty just means bumpier stats — you don't lose shares.

Card class	--password "x;d=…"
V100 / CMP 100-210	4096
RTX 2070 / 2080	16384
RTX 3060 Ti / 3070	131072
RTX 3080 / 3090 / CMP 70HX/90HX	262144
A100 / data-center Ampere	131072
RTX 4070 / 4080	262144
RTX 4090 / 5080	524288
RTX 5090 / H100 / H200 / B100	1048576
Linux (one-liner)
Windows (docker wrapper)
Docker / RunPod / vast.ai
Solo mode
Static difficulty
Multi-GPU / advanced
Run as systemd service
Copy
# 1) Download the miner — source: https://github.com/AlphaMine-Tech/alpha-miner
# Linux x86_64, supports Volta/Ampere/Ada/Hopper/Blackwell auto-detect
curl -L -o alpha-miner https://pearl.alphapool.tech/downloads/alpha-miner
chmod +x alpha-miner

# 2) Replace YOUR_PRL_ADDRESS with your prl1p... wallet address, then run
./alpha-miner \
  --pool stratum+tcp://us2.alphapool.tech:5566 \
  --address prl1pYOUR_PRL_ADDRESS \
  --worker rig01
Hardware support
RTX 30-series
3060–3090 Ti
Ampere · ✓ supported by alpha-miner binary
RTX 40-series
4060–4090
Ada · ✓ supported by alpha-miner binary
RTX 50-series
5060 Ti–5090
Blackwell · ✓ supported by alpha-miner binary
A100 / L4 / L40 · CMP 70HX/90HX/170HX/220HX
Ampere/Ada (consumer + datacenter)
✓ supported by alpha-miner binary (force --backend ampere)
H100 / H200 / B100 / B200
Hopper / Blackwell DC
✓ supported by alpha-miner binary (Hopper SM_90 + Blackwell kernels in current build)
V100 / Titan V / CMP 100-210
Volta (SM_70)
✓ supported by alpha-miner binary (since 2026-05-15)
RTX 20-series · T4
Turing (SM_75)
✓ supported by alpha-miner binary
Windows · Linux · HiveOS
✓ supported today
Windows users mine via the one-click installer (see Get Started → Windows tab) or WSL2. Verified on RTX 30/40/50 series + A100/H100. macOS / AMD on the roadmap.
Pre-Volta cards (Pascal GTX 10-series and older) lack the tensor cores Pearl's NoisyGEMM PoW needs. CPU mining is not supported. Need help? Hit our Discord — real humans.

AlphaPool · Pearl AlphaMine on YT ↗
Low-fee Pearl (PRL) mining. Operated from US East (US1, low-latency NA). PoUW · PPLNS 5% / Solo 5% · payouts every 4h.
All pools →
Pearl website
Pearl on GitHub
Pearl on X
FAQ
Pearl Research Labs is not affiliated with AlphaPool. We just run the infrastructure.
© 2026 AlphaPool
Discord