import asyncio
import ctypes
import shutil
import time

import httpx
import psutil

from .config import ROOT, settings

_nvml = None
_cache = (0, {})


def resources():
    global _nvml
    ram = psutil.virtual_memory()
    disk = shutil.disk_usage(ROOT)
    result = {'ram_total': ram.total, 'ram_available': ram.available, 'ram_used': ram.used, 'disk_free': disk.free, 'disk_total': disk.total, 'gpu': None, 'commit_total': None, 'commit_limit': None, 'observed_at': time.time()}
    try:
        import pynvml
        if _nvml is None:
            pynvml.nvmlInit()
            _nvml = pynvml.nvmlDeviceGetHandleByIndex(0)
        memory = pynvml.nvmlDeviceGetMemoryInfo(_nvml)
        result['gpu'] = {'name': pynvml.nvmlDeviceGetName(_nvml), 'total': memory.total, 'used': memory.used, 'free': memory.free, 'utilization': pynvml.nvmlDeviceGetUtilizationRates(_nvml).gpu, 'temperature': pynvml.nvmlDeviceGetTemperature(_nvml, 0), 'source': 'NVML'}
    except Exception:
        result['gpu_monitor_status'] = 'NVML unavailable; GPU memory is unknown.'
    if hasattr(ctypes, 'windll'):
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(k, ctypes.c_ulonglong) for k in ['total_phys', 'avail_phys', 'total_page', 'avail_page', 'total_virtual', 'avail_virtual', 'avail_ext']]
        data = MemoryStatus()
        data.length = ctypes.sizeof(data)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(data)):
            result.update(commit_limit=data.total_page, commit_total=data.total_page-data.avail_page)
    return result


async def services(refresh=False):
    global _cache
    if not refresh and _cache[0] > time.monotonic()-10:
        return _cache[1]
    async with httpx.AsyncClient(timeout=4) as client:
        async def get(url):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                return None
        comfy, ollama = await asyncio.gather(get(settings['comfy_url']+'/system_stats'), get(settings['ollama_url']+'/api/tags'))
    value = {'comfy': {'connected': comfy is not None, 'version': comfy.get('system', {}).get('comfyui_version') if comfy else None}, 'ollama': {'connected': ollama is not None, 'models': ollama.get('models', []) if ollama else []}}
    _cache = (time.monotonic(), value)
    return value
