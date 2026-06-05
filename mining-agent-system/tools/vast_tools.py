#!/usr/bin/env python3
"""
Vast.ai工具包装 - 为Agent提供GPU租赁能力
包装现有的vast管理功能，提供统一的接口
"""

from __future__ import annotations
import subprocess
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from dataclasses import dataclass

@dataclass
class GPUOffer:
    """GPU优惠信息"""
    offer_id: str
    gpu_model: str
    num_gpus: int
    price_per_gpu: float
    total_price: float
    reliability: float
    geolocation: str
    verified: bool
    direct_port_count: int

@dataclass
class InstanceInfo:
    """实例信息"""
    instance_id: str
    gpu_model: str
    num_gpus: int
    status: str
    price_per_hour: float
    ssh_host: str | None
    ssh_port: int | None
    created_at: str

class VastTools:
    """Vast.ai操作工具集"""

    def __init__(self, mining_dir: str = "/Users/juliancooper/Desktop/projects/mining"):
        self.mining_dir = Path(mining_dir)

    def _run_command(self, cmd: List[str], timeout: int = 30) -> tuple[int, str, str]:
        """执行命令并返回结果"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "TIMEOUT"
        except Exception as e:
            return -1, "", str(e)

    def search_best_offers(
        self,
        gpu_model: str = "RTX_5090",
        max_price: float = 0.60,
        min_reliability: float = 0.95,
        verified_only: bool = True
    ) -> List[GPUOffer]:
        """搜索最优GPU优惠"""

        # 构建搜索查询
        filters = f"gpu_name={gpu_model} rentable=true"
        if verified_only:
            filters += " verified=true"
        if max_price:
            filters += f" dph_total<={max_price}"

        cmd = ["vastai", "search", "offers", filters, "-o", "dph_total", "--raw"]

        returncode, stdout, stderr = self._run_command(cmd, timeout=60)

        if returncode != 0:
            print(f"搜索失败: {stderr}")
            return []

        try:
            data = json.loads(stdout)
            # vastai search offers 返回直接数组
            if isinstance(data, list):
                raw_offers = data[:20]
            else:
                raw_offers = data.get('offers', [])[:20]

            offers = []
            for offer in raw_offers:
                offers.append(GPUOffer(
                    offer_id=str(offer.get('id', '')),
                    gpu_model=offer.get('gpu_name', 'Unknown'),
                    num_gpus=offer.get('num_gpus', 1),
                    price_per_gpu=offer.get('dph_total', offer.get('min_bid', 0.0)) / max(offer.get('num_gpus', 1), 1),
                    total_price=offer.get('dph_total', offer.get('min_bid', 0.0)),
                    reliability=offer.get('reliability2', 0.0),
                    geolocation=offer.get('geolocation', 'Unknown'),
                    verified=offer.get('verified', False),
                    direct_port_count=offer.get('direct_port_count', 0)
                ))

            return offers
        except Exception as e:
            print(f"解析搜索结果失败: {e}")
            return []

    def create_instance(
        self,
        offer_id: str,
        label: str = "agent-deployed"
    ) -> Dict[str, Any]:
        """创建新实例"""

        cmd = [
            "vastai", "create", "instance", str(offer_id),
            "--image", "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime",
            "--disk", "30",
            "--ssh",
            "--direct",
            "--label", label
        ]

        returncode, stdout, stderr = self._run_command(cmd, timeout=120)

        if returncode != 0:
            return {
                "success": False,
                "error": stderr,
                "instance_id": None
            }

        # 解析JSON返回值
        instance_id = None
        try:
            result_json = json.loads(stdout)
            if isinstance(result_json, dict):
                instance_id = str(result_json.get("new_contract", ""))
        except (json.JSONDecodeError, Exception):
            # 回退到文本解析
            match = re.search(r'(\d+)', stdout)
            if match:
                instance_id = match.group(1)

        return {
            "success": True,
            "instance_id": instance_id,
            "output": stdout
        }

    def list_instances(self) -> List[InstanceInfo]:
        """列出所有实例"""

        cmd = ["vastai", "show", "instances", "--raw"]
        returncode, stdout, stderr = self._run_command(cmd)

        if returncode != 0:
            return []

        try:
            data = json.loads(stdout)
            # vastai show instances --raw 返回直接数组（或空数组）
            if isinstance(data, list):
                raw_instances = data
            else:
                raw_instances = data.get('instances', [])

            instances = []
            for inst in raw_instances:
                instances.append(InstanceInfo(
                    instance_id=str(inst.get('id', '')),
                    gpu_model=inst.get('gpu_name', 'Unknown'),
                    num_gpus=inst.get('num_gpus', 1),
                    status=inst.get('status', 'unknown'),
                    price_per_hour=inst.get('dph_total', 0.0),
                    ssh_host=None,
                    ssh_port=None,
                    created_at=inst.get('created', '')
                ))

            return instances
        except Exception as e:
            print(f"解析实例列表失败: {e}")
            return []

    def destroy_instance(self, instance_id: str) -> Dict[str, Any]:
        """销毁实例"""

        cmd = ["bash", "-c", f"echo y | vastai destroy instance {instance_id}"]
        returncode, stdout, stderr = self._run_command(cmd, timeout=30)

        return {
            "success": returncode == 0,
            "output": stdout,
            "error": stderr if returncode != 0 else None
        }

    def get_instance_ssh(self, instance_id: str) -> tuple[str | None, int | None]:
        """获取实例SSH连接信息"""

        cmd = ["vastai", "ssh-url", str(instance_id)]
        returncode, stdout, stderr = self._run_command(cmd)

        if returncode != 0:
            return None, None

        # 解析SSH URL格式: root@host:port
        match = re.search(r'@([^:]+):(\d+)', stdout)
        if match:
            return match.group(1), int(match.group(2))

        return None, None

    def check_instance_health(self, instance_id: str) -> Dict[str, Any]:
        """检查实例健康状态"""

        ssh_host, ssh_port = self.get_instance_ssh(instance_id)
        if not ssh_host:
            return {
                "healthy": False,
                "reason": "无法获取SSH连接信息"
            }

        # 检查nvidia-smi
        cmd = [
            "ssh", "-q",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"root@{ssh_host}", "-p", str(ssh_port),
            "nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used",
            "--format=csv,noheader,nounits"
        ]

        returncode, stdout, stderr = self._run_command(cmd, timeout=30)

        if returncode != 0:
            return {
                "healthy": False,
                "reason": f"GPU检查失败: {stderr}"
            }

        # 解析GPU状态
        gpu_info = []
        for line in stdout.strip().split('\n'):
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 4:
                gpu_info.append({
                    "name": parts[0],
                    "utilization": int(parts[1]) if parts[1].isdigit() else 0,
                    "temperature": int(parts[2]) if parts[2].isdigit() else 0,
                    "memory_used_mb": int(parts[3]) if parts[3].isdigit() else 0
                })

        # 检查是否有alpha-miner进程
        miner_cmd = [
            "ssh", "-q",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"root@{ssh_host}", "-p", str(ssh_port),
            "pgrep", "-c", "alpha-miner"
        ]

        miner_returncode, miner_stdout, _ = self._run_command(miner_cmd, timeout=10)
        miner_running = miner_returncode == 0 and miner_stdout.strip().isdigit() and int(miner_stdout.strip()) > 0

        return {
            "healthy": True,
            "gpus": gpu_info,
            "miner_running": miner_running,
            "ssh_accessible": True
        }