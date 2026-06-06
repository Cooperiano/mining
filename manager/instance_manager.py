"""Per-instance manager architecture (Actor Model).

Each vast.ai instance gets its own ``InstanceManager`` running in a dedicated
thread.  A ``DataCollector`` thread refreshes shared state (vastai instances,
AlphaPool workers, config) periodically.  An ``InstanceOrchestrator`` discovers
new instances, spawns managers, and removes managers for gone instances.

This replaces the batch-oriented ``autodeploy_cycle()`` with independent
per-instance lifecycles that run on their own schedules.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from manager.locks import InstanceLock
from manager.vast import (
    GPU_HASHRATES,
    _calc_max_price_per_gpu,
    _deploy_instance_inner,
    _kill_instance_inner,
    _load_electron_config,
    _min_th_for_model,
    _parse_gpu_model,
    _run,
    _snapshot_instances,
    _state_dir,
    _vastai,
    API_URL,
    change_bid,
)
from manager.audit import log_event
from manager.bid_manager import (
    TIER_NO_ACTION_REPLACE_RECOMMENDED,
    calc_bid_adjustment,
    calc_margin_per_hr,
    calc_max_bid,
    classify_margin,
    get_or_create_entry,
    mark_explicitly_killed,
    record_bid_action,
    update_consecutive_tier,
)
from manager.recorder import record_kill_decision


# ──────────────────────────────────────────────
# SharedState — thread-safe data store
# ──────────────────────────────────────────────

class SharedState:
    """Shared data refreshed by DataCollector, read by InstanceManagers.

    Uses a ``threading.Lock`` around each swap so readers always see a
    consistent snapshot.  Python's GIL makes dict reads atomic, but we
    guard against torn reads during ``_refresh()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._instances: dict[str, dict[str, Any]] = {}   # inst_id → entry
        self._workers: list[dict[str, Any]] = []           # AlphaPool workers
        self._config: dict[str, Any] = {}
        self.updated_at: float = 0.0

    # ── writers (called by DataCollector) ──

    def refresh(self) -> None:
        """Fetch vastai instances + AlphaPool workers + config, then swap."""
        cfg = _load_electron_config()
        instances: dict[str, dict[str, Any]] = {}
        workers: list[dict[str, Any]] = []

        # Fetch vastai instances
        rc, raw, _ = _vastai(["show", "instances", "--raw"], timeout=15)
        if rc == 0:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            inst_id = str(entry.get("id", ""))
                            if inst_id:
                                instances[inst_id] = entry
                    _snapshot_instances(data)
            except json.JSONDecodeError:
                pass

        # Fetch AlphaPool workers
        try:
            import urllib.request
            req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                api_data = json.loads(resp.read())
                workers = api_data.get("workers", [])
        except Exception:
            pass

        # Atomic swap
        with self._lock:
            self._instances = instances
            self._workers = workers
            self._config = cfg
            self.updated_at = time.time()

    # ── readers (called by InstanceManagers) ──

    @property
    def config(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def get_instance(self, inst_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._instances.get(inst_id)

    def all_instance_ids(self) -> set[str]:
        with self._lock:
            return set(self._instances.keys())

    def get_workers_for_tag(self, tag: str) -> list[dict[str, Any]]:
        """Return AlphaPool workers explicitly tagged with this instance suffix."""
        pattern = re.compile(rf"-{re.escape(tag)}\.gpu\d+$", re.IGNORECASE)
        with self._lock:
            return [
                w for w in self._workers
                if isinstance(w, dict) and pattern.search(str(w.get("name", "")))
            ]

    def get_all_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._workers)


# ──────────────────────────────────────────────
# InstanceManager — one per instance, own thread
# ──────────────────────────────────────────────

class InstanceManager:
    """Owns the lifecycle of a single vast.ai instance.

    State machine::

        new → deploying → running → killing → stopped
                                    ↑          │
                                    └── (redeployed)

    Each state has its own check interval.  The manager reads from
    ``SharedState`` and acts independently — no global cycle clock.
    """

    def __init__(self, inst_id: str, shared: SharedState) -> None:
        self.inst_id = inst_id
        self.shared = shared
        self.state: str = "new"
        self.last_action: float = 0.0
        self.consecutive_failures: int = 0
        self.health_failures: int = 0
        self.redeploy_attempts: int = 0
        self.quarantined: bool = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── public API ──

    def start(self) -> None:
        """Spawn the manager thread."""
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"mgr-{self.inst_id}"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the manager to stop."""
        self._stop_event.set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── main loop ──

    def _run_loop(self) -> None:
        log_event("manager_start", instance_id=self.inst_id,
                  details=f"state={self.state}")
        while not self._stop_event.is_set():
            cfg = self.shared.config
            if not cfg.get("automation_enabled", True):
                self._wait(30)
                continue

            try:
                if self.state == "new":
                    self._handle_new(cfg)
                elif self.state == "deploying":
                    self._handle_deploying(cfg)
                elif self.state == "running":
                    self._handle_running(cfg)
                elif self.state == "killing":
                    self._handle_killing(cfg)
                elif self.state == "stopped":
                    break
            except Exception as exc:
                log_event("manager_error", instance_id=self.inst_id,
                          details=f"state={self.state} error={exc}")

            self._wait(self._check_interval(cfg))

        log_event("manager_stop", instance_id=self.inst_id,
                  details=f"final_state={self.state}")

    def _check_interval(self, cfg: dict) -> float:
        """How many seconds to sleep between checks for current state."""
        if self.state in ("new", "deploying"):
            return 10
        return float(cfg.get("instance_check_interval_sec", 60))

    def _wait(self, seconds: float) -> None:
        self._stop_event.wait(timeout=max(1, seconds))

    # ── state handlers ──

    def _handle_new(self, cfg: dict) -> None:
        """Deploy miner to this new instance."""
        inst = self.shared.get_instance(self.inst_id)
        if not inst:
            # Instance disappeared before we could deploy
            self.state = "stopped"
            return

        if inst.get("actual_status") != "running":
            return  # not ready yet, wait

        dry_run = bool(cfg.get("dry_run", False))
        auto_deploy = bool(cfg.get("auto_deploy_enabled", True))
        if not auto_deploy:
            # Skip deploy but still monitor
            self.state = "running"
            return
        if dry_run:
            log_event("dry_deploy", instance_id=self.inst_id,
                      details="would deploy (dry run)")
            self.state = "running"
            return

        log_event("manager_deploy", instance_id=self.inst_id,
                  details="starting deployment")

        lock = InstanceLock(self.inst_id)
        if not lock.acquire():
            return  # locked, try again later
        try:
            self.state = "deploying"
            result = _deploy_instance_inner(self.inst_id)
            self.last_action = time.time()
            if self._deploy_succeeded(result):
                self.state = "running"
                self.consecutive_failures = 0
                log_event("manager_deploy_ok", instance_id=self.inst_id,
                          details=result[:200])
            else:
                self.consecutive_failures += 1
                log_event("manager_deploy_fail", instance_id=self.inst_id,
                          details=result[:200])
                retry_limit = int(cfg.get("consecutive_failures_before_destroy", 3))
                if self.consecutive_failures >= retry_limit:
                    self.state = "stopped"
                else:
                    self.state = "new"
        finally:
            lock.release()

    def _handle_deploying(self, cfg: dict) -> None:
        """Wait for deploy to complete (placeholder — deploy is sync)."""
        # deploy_instance is synchronous, so this state is transitional
        self.state = "running"

    def _handle_running(self, cfg: dict) -> None:
        """Monitor: check cost + hashrate for this instance."""
        inst = self.shared.get_instance(self.inst_id)
        if not inst:
            self.state = "stopped"
            return

        if inst.get("actual_status") != "running":
            # If this was an interruptible instance and not explicitly killed,
            # it was likely preempted — record for bid history (V2 will use this)
            if inst.get("is_bid", False):
                from manager.bid_manager import increment_preemption, get_or_create_entry
                state_dir = str(self._state_dir())
                entry = get_or_create_entry(state_dir, self.inst_id)
                if not entry.get("explicitly_killed", False):
                    increment_preemption(state_dir, self.inst_id)
                    log_event("preemption_detected", instance_id=self.inst_id,
                              details=f"preemption_count={entry.get('preemption_count', 0) + 1}")
            self.state = "stopped"
            return

        if self.quarantined:
            return

        # Local health is the strongest signal that a deployed instance is
        # actually mining. Pool data may lag and deployed.json may be stale.
        local_health = self._inspect_local_health(inst)
        if local_health["needs_redeploy"]:
            self.health_failures += 1
            log_event("local_health_fail", instance_id=self.inst_id,
                      details=f"{local_health['issue']} ({self.health_failures})")
            threshold = int(cfg.get("consecutive_failures_before_destroy", 3))
            if self.health_failures >= threshold:
                self._redeploy(cfg, local_health["issue"])
            return
        if local_health["checked"]:
            self.health_failures = 0

        # ── Dynamic bid check (interruptible only) ──
        if self._should_check_bid(inst, cfg):
            self._handle_dynamic_bid(inst, cfg)
            # V1: never changes state to killed/stopped here

        # ── Cost check ──
        if self._is_overpriced(inst, cfg):
            self._kill(inst, cfg, "too_expensive")
            return

        # ── Performance check ──
        tag = self._extract_tag()
        if tag:
            workers = self.shared.get_workers_for_tag(tag)
            if self._is_underperforming(workers, cfg):
                self._kill(inst, cfg, "underperforming")
                return

    def _handle_killing(self, cfg: dict) -> None:
        """Kill completed — instance is gone."""
        self.state = "stopped"

    # ── decision helpers ──

    def _is_overpriced(self, inst: dict, cfg: dict) -> bool:
        """Check if this instance's price per GPU exceeds its threshold."""
        num_gpus = inst.get("num_gpus", 1)
        gpu_name = inst.get("gpu_name", "RTX 5090")
        try:
            price_total = float(inst.get("dph_total", 0))
        except (TypeError, ValueError):
            return False
        price_per_gpu = price_total / num_gpus if num_gpus > 0 else price_total
        threshold = _calc_max_price_per_gpu(gpu_name)

        if price_per_gpu > threshold:
            log_event("overpriced", instance_id=self.inst_id,
                      details=f"${price_per_gpu:.2f}/GPU > ${threshold:.2f}")
            return True
        return False

    def _is_underperforming(self, workers: list[dict], cfg: dict) -> bool:
        """Check if this instance's workers are below hashrate threshold."""
        if not workers:
            return False

        for w in workers:
            if not w.get("online"):
                continue
            try:
                live = float(w["hashrate_live"].split()[0])
                h1 = float(w.get("hashrate_1h", "0").split()[0]) if w.get("hashrate_1h") else 0
            except (ValueError, KeyError):
                continue

            name = w["name"]
            gpu_model = _parse_gpu_model(name)
            if gpu_model is None:
                continue

            min_th = _min_th_for_model(gpu_model)

            # Use 1h average for stable kill decisions
            if h1 >= min_th:
                continue
            if live >= min_th:
                continue  # recovering

            # Warm-up protection: skip if 1h avg is < 30% of threshold
            if h1 < min_th * 0.3:
                log_event("warmup_skip", instance_id=self.inst_id,
                          details=f"h1={h1:.0f} < 30% of {min_th:.0f}")
                continue

            log_event("underperforming", instance_id=self.inst_id,
                      details=f"live={live:.0f} h1={h1:.0f} < min={min_th:.0f}")
            return True

        return False

    # ── action helpers ──

    @staticmethod
    def _deploy_succeeded(result: str) -> bool:
        """Accept both legacy and current deploy success prefixes."""
        return result.startswith("Deployed:") or result.startswith("OK:")

    def _inspect_local_health(self, inst: dict) -> dict[str, Any]:
        """Check SSH/miner/GPU health without treating pool lag as failure.

        Returns:
            checked: SSH command returned useful output.
            needs_redeploy: local evidence says the miner is not running.
            issue: concise reason for logs.
        """
        pool_workers = self.shared.get_workers_for_tag(self._extract_tag())
        pool_online = any(w.get("online") for w in pool_workers if isinstance(w, dict))

        rc, ssh_url, _ = _vastai(["ssh-url", self.inst_id], timeout=10)
        match = re.search(r"@([^:]+):(\d+)", ssh_url.strip()) if rc == 0 else None
        if not match:
            # If pool is still online, do not redeploy or kill just because SSH is down.
            return {
                "checked": False,
                "needs_redeploy": False,
                "issue": "SSH unavailable; pool online" if pool_online else "SSH unavailable",
            }

        host, port = match.group(1), match.group(2)
        remote_cmd = (
            "echo MINER=$(pgrep -c alpha-miner 2>/dev/null || true); "
            "nvidia-smi --query-gpu=utilization.gpu,memory.used "
            "--format=csv,noheader,nounits 2>/dev/null | sed 's/^/GPU=/'"
        )
        cmd = [
            "ssh", "-q", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
            f"root@{host}", "-p", port, remote_cmd,
        ]
        rc2, output, _ = _run(cmd, timeout=15)
        if rc2 != 0 or "MINER=" not in output:
            return {
                "checked": False,
                "needs_redeploy": False,
                "issue": "SSH check failed",
            }

        miner_match = re.search(r"MINER=(\d+)", output)
        miner_running = bool(miner_match and int(miner_match.group(1)) > 0)
        gpu_rows = [
            (int(m.group(1)), int(m.group(2)))
            for m in re.finditer(r"GPU=\s*(\d+),\s*(\d+)", output)
        ]

        if not miner_running:
            return {"checked": True, "needs_redeploy": True, "issue": "miner not running"}
        if not gpu_rows:
            return {"checked": True, "needs_redeploy": True, "issue": "GPU metrics unavailable"}

        avg_util = sum(row[0] for row in gpu_rows) / len(gpu_rows)
        min_vram = min(row[1] for row in gpu_rows)
        if avg_util < 20 and not pool_online:
            return {
                "checked": True,
                "needs_redeploy": True,
                "issue": f"low GPU load ({avg_util:.0f}%) and no pool worker",
            }
        if min_vram < 500 and not pool_online:
            return {
                "checked": True,
                "needs_redeploy": True,
                "issue": "low VRAM and no pool worker",
            }

        return {"checked": True, "needs_redeploy": False, "issue": "healthy"}

    def _redeploy(self, cfg: dict, reason: str) -> None:
        """Redeploy miner on a running instance with cooldown and attempt cap."""
        dry_run = bool(cfg.get("dry_run", False))
        auto_deploy = bool(cfg.get("auto_deploy_enabled", True))
        if not auto_deploy:
            log_event("redeploy_skip", instance_id=self.inst_id,
                      details=f"auto_deploy disabled; {reason}")
            return
        if dry_run:
            log_event("dry_redeploy", instance_id=self.inst_id,
                      details=f"would redeploy: {reason}")
            self.health_failures = 0
            return

        cooldown = float(cfg.get("redeploy_cooldown_sec", 300))
        if self.last_action and time.time() - self.last_action < cooldown:
            log_event("redeploy_cooldown", instance_id=self.inst_id,
                      details=f"{reason}; waiting {cooldown:.0f}s")
            return

        max_attempts = int(cfg.get("max_redeploy_attempts", 2))
        if self.redeploy_attempts >= max_attempts:
            self.quarantined = True
            log_event("quarantine", instance_id=self.inst_id,
                      details=f"redeploy attempts exhausted: {reason}")
            return

        lock = InstanceLock(self.inst_id)
        if not lock.acquire():
            return

        try:
            self.redeploy_attempts += 1
            self.last_action = time.time()
            log_event("manager_redeploy", instance_id=self.inst_id,
                      details=f"{reason}; attempt {self.redeploy_attempts}/{max_attempts}")
            result = _deploy_instance_inner(self.inst_id)
            if self._deploy_succeeded(result):
                self.state = "running"
                self.health_failures = 0
                log_event("manager_redeploy_ok", instance_id=self.inst_id,
                          details=result[:200])
            else:
                log_event("manager_redeploy_fail", instance_id=self.inst_id,
                          details=result[:200])
        finally:
            lock.release()

    def _kill(self, inst: dict, cfg: dict, reason: str) -> None:
        """Kill this instance.

        Respects granular kill switches:
          - too_expensive → cost_kill_enabled
          - underperforming → performance_kill_enabled
          - manual/other → auto_destroy_enabled (fallback)
        """
        dry_run = bool(cfg.get("dry_run", False))

        # ── Granular kill enable check ──
        if reason == "too_expensive":
            allowed = bool(cfg.get("cost_kill_enabled", False))
        elif reason == "underperforming":
            allowed = bool(cfg.get("performance_kill_enabled", False))
        else:
            allowed = bool(cfg.get("auto_destroy_enabled", False))

        if dry_run or not allowed:
            log_event("dry_kill", instance_id=self.inst_id,
                      details=f"would kill ({reason}); enabled={allowed}, dry_run={dry_run}")
            return

        lock = InstanceLock(self.inst_id)
        if not lock.acquire():
            return  # locked, try again later

        try:
            gpu_name = inst.get("gpu_name", "")
            num_gpus = inst.get("num_gpus", 1)
            gpu_model = _parse_gpu_model(gpu_name) or gpu_name.lower().replace(" ", "_")
            try:
                dph_total = float(inst.get("dph_total", 0))
            except (TypeError, ValueError):
                dph_total = 0.0
            price_per_gpu = dph_total / num_gpus if num_gpus > 0 else dph_total

            # ── Blacklist decision ──
            should_blacklist = False
            if reason == "too_expensive":
                should_blacklist = bool(cfg.get("cost_blacklist_enabled", True))
            elif reason == "underperforming":
                should_blacklist = bool(cfg.get("performance_blacklist_enabled", False))
            # manual/redeploy/other reasons never blacklist
            # preempted/ssh_unavailable/pool_lag do not reach _kill() in normal flow

            # Build reason string
            if reason == "too_expensive":
                threshold = _calc_max_price_per_gpu(gpu_name)
                reason_str = f"${price_per_gpu:.2f}/GPU ({gpu_name}) exceeds max ${threshold:.2f}"
            else:
                reason_str = f"underperforming {gpu_model}"

            result = _kill_instance_inner(self.inst_id, reason_str, blacklist=should_blacklist)
            self.last_action = time.time()

            executed = result.startswith("Destroyed:")
            if executed:
                self.state = "killing"
                # Mark as explicitly killed (not preempted) for bid history
                mark_explicitly_killed(str(self._state_dir()), self.inst_id)

            record_kill_decision(
                instance_id=self.inst_id,
                machine_id=str(inst.get("machine_id", "")),
                trigger="orchestrator",
                reason_type=reason,
                executed=executed,
                gpu_model=gpu_model,
                num_gpus=num_gpus,
                price_per_gpu=price_per_gpu,
                dph_total=dph_total,
                details=result[:200],
            )
        finally:
            lock.release()

    # ── dynamic bid helpers ──

    def _should_check_bid(self, inst: dict, cfg: dict) -> bool:
        """Return True if dynamic bid adjustment should run for this instance."""
        if not cfg.get("dynamic_bid_enabled", False):
            return False
        # Only interruptible/spot instances
        if not inst.get("is_bid", False):
            return False
        # Warm-up protection
        protection_min = float(cfg.get("new_instance_protection_minutes", 15))
        if self.last_action and (time.time() - self.last_action) < protection_min * 60:
            return False
        # Must have workers with h1_th data
        tag = self._extract_tag()
        if not tag:
            return False
        workers = self.shared.get_workers_for_tag(tag)
        return any(w.get("online") for w in workers if isinstance(w, dict))

    def _handle_dynamic_bid(self, inst: dict, cfg: dict) -> None:
        """V1: profit-aware bid adjustment. Only changes bid, never destroy/create/deploy."""
        tag = self._extract_tag()
        workers = self.shared.get_workers_for_tag(tag)

        # Calculate margin and classify
        margin = calc_margin_per_hr(inst, workers, cfg)
        tier = classify_margin(margin, cfg)

        # Get current bid price from instance data
        try:
            current_bid = float(inst.get("min_bid", 0))
        except (TypeError, ValueError):
            current_bid = 0.0

        # Get DLPerf/$ for quality gate
        try:
            dlperf_per_dollar = float(inst.get("dlperf_per_dphtotal", 0))
        except (TypeError, ValueError):
            dlperf_per_dollar = None

        # GPU model for history tracking
        gpu_name = inst.get("gpu_name", "")
        gpu_model = _parse_gpu_model(gpu_name) or gpu_name.lower().replace(" ", "_")

        # State directory for bid history
        state_dir = str(self._state_dir())

        # Update consecutive tier count
        history_entry = update_consecutive_tier(state_dir, self.inst_id, tier)

        # Ensure entry exists with metadata
        if not history_entry.get("gpu_model"):
            get_or_create_entry(state_dir, self.inst_id, gpu_model, current_bid)

        # Log NO_ACTION_REPLACE_RECOMMENDED (V1: no auto-action)
        if tier == TIER_NO_ACTION_REPLACE_RECOMMENDED:
            log_event("bid_replace_recommended", instance_id=self.inst_id,
                      details=f"margin=${margin:.4f}/hr negative — replacement recommended (V1: no action)")
            return

        # Calculate max bid (the ONLY hard ceiling)
        max_bid = calc_max_bid(inst, workers, cfg)

        # Calculate potential adjustment
        new_bid = calc_bid_adjustment(
            current_bid, max_bid, tier, history_entry, cfg,
            dlperf_per_dollar=dlperf_per_dollar,
        )

        if new_bid is None:
            return  # no change needed or hysteresis conditions not met

        # Determine action/reason for logging
        if new_bid > current_bid:
            action = "raise"
            # Check if preempted recently for reason
            hist = history_entry.get("history", [])
            reason = "preempted_recently" if any(
                h.get("action") == "raise" and h.get("reason") == "preempted_recently"
                and (time.time() - h.get("ts", 0)) < 7200
                for h in reversed(hist[-10:])
            ) else "tier_defense"
        else:
            action = "lower"
            reason = "stable_safe"

        dry_run = bool(cfg.get("dry_run", False))
        now = time.time()

        if dry_run:
            # HARD RULE: dry_run=true MUST NEVER call vastai change bid
            log_event("dry_bid_adjust", instance_id=self.inst_id,
                      details=f"would {action} bid ${current_bid:.4f} → ${new_bid:.4f} "
                              f"(tier={tier} margin=${margin:.4f}/hr max=${max_bid:.4f} "
                              f"reason={reason})")
        else:
            rc, stdout, stderr = change_bid(self.inst_id, new_bid)
            if rc == 0:
                log_event("bid_adjust", instance_id=self.inst_id,
                          details=f"{action} bid ${current_bid:.4f} → ${new_bid:.4f} "
                                  f"(tier={tier} margin=${margin:.4f}/hr max=${max_bid:.4f} "
                                  f"reason={reason})")
            else:
                log_event("bid_adjust_fail", instance_id=self.inst_id,
                          details=f"vastai change bid failed: rc={rc} {stderr[:100]}")
                return  # don't record failed adjustment

        # Record the action
        record_bid_action(state_dir, self.inst_id, {
            "ts": now,
            "bid_before": current_bid,
            "bid_after": new_bid,
            "action": action,
            "tier": tier,
            "margin_per_hr": margin,
            "reason": reason,
        })

    @staticmethod
    def _state_dir() -> str:
        """Return the state directory path, respecting PEARL_STATE_DIR env var."""
        return str(_state_dir())

    def _extract_tag(self) -> str:
        """Extract the instance tag (last 4 chars of ID) for worker matching."""
        return self.inst_id[-4:] if len(self.inst_id) >= 4 else self.inst_id


# ──────────────────────────────────────────────
# InstanceOrchestrator — manages manager lifecycle
# ──────────────────────────────────────────────

class InstanceOrchestrator:
    """Discovers vast.ai instances and spawns one ``InstanceManager`` per instance.

    Three threads:
    1. **DataCollector** — refreshes ``SharedState`` every ``tick_interval_sec``
    2. **Orchestrator loop** — syncs manager pool with discovered instances
    3. N × **InstanceManager** — one per running instance

    Usage::

        orch = InstanceOrchestrator()
        orch.start()
        # ... runs until orch.stop() ...
        orch.stop()
    """

    def __init__(self) -> None:
        self.shared = SharedState()
        self.managers: dict[str, InstanceManager] = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()  # guards self.managers

    # ── public API ──

    def start(self) -> None:
        """Start the data collector and orchestrator threads."""
        log_event("orchestrator_start", details="starting")

        # Initial data fetch
        self.shared.refresh()

        # DataCollector thread
        threading.Thread(
            target=self._collect_loop, daemon=True, name="data-collector"
        ).start()

        # Orchestrator thread
        threading.Thread(
            target=self._orchestrate_loop, daemon=True, name="orchestrator"
        ).start()

    def stop(self) -> None:
        """Signal all threads to stop and wait for managers to finish."""
        log_event("orchestrator_stop", details="stopping")
        self._stop_event.set()

        with self._lock:
            for mgr in self.managers.values():
                mgr.stop()

    def status(self) -> dict[str, Any]:
        """Return current orchestrator status for monitoring."""
        with self._lock:
            mgr_status = {
                mid: {"state": m.state, "alive": m.is_alive}
                for mid, m in self.managers.items()
            }
        return {
            "running": not self._stop_event.is_set(),
            "managers": mgr_status,
            "shared_updated_at": self.shared.updated_at,
        }

    # ── background threads ──

    def _collect_loop(self) -> None:
        """Periodically refresh shared data."""
        while not self._stop_event.is_set():
            try:
                self.shared.refresh()
            except Exception as exc:
                log_event("collect_error", details=str(exc))

            cfg = self.shared.config
            interval = float(cfg.get("tick_interval_sec", 30))
            self._stop_event.wait(timeout=max(5, interval))

    def _orchestrate_loop(self) -> None:
        """Periodically sync manager pool with discovered instances."""
        while not self._stop_event.is_set():
            try:
                self._sync_managers()
            except Exception as exc:
                log_event("orchestrate_error", details=str(exc))

            cfg = self.shared.config
            interval = float(cfg.get("orchestrator_interval_sec", 30))
            self._stop_event.wait(timeout=max(5, interval))

    def _sync_managers(self) -> None:
        """Add managers for new instances, stop managers for gone instances."""
        current_ids = self.shared.all_instance_ids()

        with self._lock:
            managed_ids = set(self.managers.keys())

            # Spawn new managers
            deployed = self._deployed_ids()
            bad = self._bad_ids()

            for inst_id in current_ids - managed_ids:
                inst = self.shared.get_instance(inst_id)
                if not inst or inst.get("actual_status") != "running":
                    continue

                mgr = InstanceManager(inst_id, self.shared)
                # If already deployed, skip to monitoring
                if inst_id in deployed:
                    mgr.state = "running"
                elif inst_id in bad:
                    mgr.state = "stopped"
                    continue

                self.managers[inst_id] = mgr
                mgr.start()
                log_event("manager_spawned", instance_id=inst_id,
                          details=f"state={mgr.state}")

            # Stop managers for gone instances
            for inst_id in managed_ids - current_ids:
                mgr = self.managers.pop(inst_id, None)
                if mgr:
                    mgr.stop()
                    log_event("manager_removed", instance_id=inst_id,
                              details="instance gone")

            # Also stop managers that have reached "stopped" state
            dead = [
                mid for mid, m in self.managers.items()
                if m.state == "stopped" and not m.is_alive
            ]
            for mid in dead:
                del self.managers[mid]
                log_event("manager_cleaned", instance_id=mid)

    # ── helpers ──

    @staticmethod
    def _deployed_ids() -> set[str]:
        """Load deployed instance IDs from state file."""
        from manager.vast import _deployed_ids as _vast_deployed_ids
        return _vast_deployed_ids()

    @staticmethod
    def _bad_ids() -> set[str]:
        """Load bad instance IDs from state file."""
        from manager.vast import _bad_ids as _vast_bad_ids
        return _vast_bad_ids()
