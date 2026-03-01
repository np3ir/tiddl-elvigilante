from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class DownloadMetrics:
    """Download metrics"""
    file_path: str
    file_size: int
    download_time: float
    download_speed: float  # MB/s
    retries: int
    integrity_check: bool
    timestamp: str
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

class MetricsCollector:
    """Metrics collector"""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        if self.log_file.parent:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_download(
        self,
        file_path: str,
        file_size: int,
        download_time: float,
        retries: int = 0,
        integrity_check: bool = True
    ):
        """Record download metrics"""
        
        # Avoid division by zero
        if download_time > 0:
            download_speed = (file_size / (1024 * 1024)) / download_time  # MB/s
        else:
            download_speed = 0.0
        
        metrics = DownloadMetrics(
            file_path=str(file_path),
            file_size=file_size,
            download_time=download_time,
            download_speed=download_speed,
            retries=retries,
            integrity_check=integrity_check,
            timestamp=datetime.now().isoformat()
        )
        
        # Append to log file
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(metrics)) + '\n')
        except Exception:
            # Fallback silencioso si falla el logging
            pass

    def get_stats(self) -> dict:
        """Get aggregated statistics"""
        if not self.log_file.exists():
            return {}
        
        metrics = []
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            metrics.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            return {}
        
        if not metrics:
            return {}
        
        total_size = sum(m['file_size'] for m in metrics)
        total_time = sum(m['download_time'] for m in metrics)
        avg_speed = sum(m['download_speed'] for m in metrics) / len(metrics)
        total_retries = sum(m['retries'] for m in metrics)
        success_rate = sum(1 for m in metrics if m['integrity_check']) / len(metrics)
        
        return {
            'total_downloads': len(metrics),
            'total_size_mb': total_size / (1024 * 1024),
            'total_time_sec': total_time,
            'avg_speed_mbps': avg_speed,
            'total_retries': total_retries,
            'success_rate_pct': success_rate * 100
        }
