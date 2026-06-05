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
    _snapshot_instances,
    _vastai,
    API_URL,
)
from manager.audit import log_event
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
        """Return AlphaPool workers whose name ends with the given instance tag."""
        with self._lock:
            return [
                w for w in self._workers
                if isinstance(w, dict) and tag in w.get("name", "")
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
            result = _deploy_instance_inner(self.inst_id)
            self.last_action = time.time()
            if result.startswith("OK:"):
                self.state = "running"
                self.consecutive_failures = 0
                log_event("manager_deploy_ok", instance_id=self.inst_id,
                          details=result[:200])
            else:
                self.consecutive_failures += 1
                log_event("manager_deploy_fail", instance_id=self.inst_id,
                          details=result[:200])
                # Too many failures → stop managing
                if self.consecutive_failures >= 3:
                    self.state = "stopped"
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
            self.state = "stopped"
            return

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

    def _kill(self, inst: dict, cfg: dict, reason: str) -> None:
        """Kill this instance."""
        dry_run = bool(cfg.get("dry_run", False))
        auto_destroy = bool(cfg.get("auto_destroy_enabled", False))

        if dry_run or not auto_destroy:
            log_event("dry_kill", instance_id=self.inst_id,
                      details=f"would kill ({reason})")
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

            # Build reason string
            if reason == "too_expensive":
                threshold = _calc_max_price_per_gpu(gpu_name)
                reason_str = f"${price_per_gpu:.2f}/GPU ({gpu_name}) exceeds max ${threshold:.2f}"
            else:
                reason_str = f"underperforming {gpu_model}"

            result = _kill_instance_inner(self.inst_id, reason_str)
            self.last_action = time.time()

            executed = result.startswith("Destroyed:")
            if executed:
                self.state = "killing"

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
