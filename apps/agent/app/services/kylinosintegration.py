"""
银河麒麟系统集成服务
实现系统服务集成、安全机制集成、资源监控等功能
"""
import logging
import subprocess
import platform
import psutil
from typing import Dict, Optional, List
import os

logger = logging.getLogger(__name__)


class KylinOSIntegrationService:
    """银河麒麟系统集成服务"""
    
    def __init__(self):
        try:
            self.is_kylin_os = self._detect_kylin_os()
            system_name = platform.system()
            logger.info(f"检测到操作系统: {system_name}, 是否为银河麒麟: {self.is_kylin_os}")
        except Exception as e:
            logger.warning(f"初始化KylinOS集成服务失败: {e}")
            self.is_kylin_os = False
    
    def _detect_kylin_os(self) -> bool:
        """检测是否为银河麒麟系统"""
        try:
            # Windows系统直接返回False，避免调用系统命令导致问题
            if platform.system().lower() == 'windows':
                return False
            
            # 检查发行版信息（Linux特有）
            if os.path.exists('/etc/kylin-release'):
                return True
            
            # 检查系统信息（使用更安全的方式）
            try:
                system_info = platform.platform().lower()
                if 'kylin' in system_info or 'neokylin' in system_info:
                    return True
            except Exception:
                pass
            
            # 检查系统命令（仅Linux）
            try:
                result = subprocess.run(
                    ['uname', '-a'], 
                    capture_output=True, 
                    text=True, 
                    timeout=2,
                    check=False
                )
                if result.returncode == 0 and 'kylin' in result.stdout.lower():
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass
            
            return False
        except KeyboardInterrupt:
            # 如果被中断，直接返回False
            return False
        except Exception as e:
            logger.debug(f"检测操作系统失败: {e}")
            return False
    
    def get_system_info(self) -> Dict:
        """
        获取系统信息
        
        Returns:
            系统信息字典
        """
        try:
            info = {
                "os_name": platform.system(),
                "os_version": platform.version(),
                "os_release": platform.release(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "is_kylin_os": self.is_kylin_os
            }
            
            # 如果是银河麒麟系统，获取额外信息
            if self.is_kylin_os:
                info["kylin_version"] = self._get_kylin_version()
                info["kylin_edition"] = self._get_kylin_edition()
            
            return info
        except Exception as e:
            logger.error(f"获取系统信息失败: {e}")
            return {"error": str(e)}
    
    def _get_kylin_version(self) -> Optional[str]:
        """获取银河麒麟版本"""
        try:
            if os.path.exists('/etc/kylin-release'):
                with open('/etc/kylin-release', 'r') as f:
                    return f.read().strip()
        except:
            pass
        return None
    
    def _get_kylin_edition(self) -> Optional[str]:
        """获取银河麒麟版本（桌面/服务器）"""
        try:
            # 检查是否为服务器版
            if os.path.exists('/etc/.kyinfo'):
                with open('/etc/.kyinfo', 'r') as f:
                    content = f.read()
                    if 'server' in content.lower():
                        return "server"
                    return "desktop"
        except:
            pass
        return None
    
    def monitor_system_resources(self) -> Dict:
        """
        监控系统资源
        
        Returns:
            系统资源使用情况
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # 获取网络统计
            net_io = psutil.net_io_counters()
            
            resources = {
                "cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count(),
                    "freq": psutil.cpu_freq().current if psutil.cpu_freq() else None
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "percent": memory.percent
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                }
            }
            
            # 如果是银河麒麟系统，添加系统服务状态
            if self.is_kylin_os:
                resources["system_services"] = self._get_system_services_status()
            
            return resources
        except Exception as e:
            logger.error(f"监控系统资源失败: {e}")
            return {"error": str(e)}
    
    def _get_system_services_status(self) -> Dict:
        """获取系统服务状态（银河麒麟）"""
        try:
            # 检查关键系统服务
            services = {
                "network": self._check_service("NetworkManager"),
                "firewall": self._check_service("firewalld"),
                "security": self._check_service("kylin-security")
            }
            return services
        except Exception as e:
            logger.warning(f"获取系统服务状态失败: {e}")
            return {}
    
    def _check_service(self, service_name: str) -> str:
        """检查服务状态"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.stdout.strip() if result.returncode == 0 else "inactive"
        except:
            return "unknown"
    
    def execute_system_command(self, command: str, require_sudo: bool = False) -> Dict:
        """
        执行系统命令（需要谨慎使用）
        
        Args:
            command: 命令字符串
            require_sudo: 是否需要sudo权限
        
        Returns:
            执行结果
        """
        try:
            if require_sudo and not self.is_kylin_os:
                return {"error": "非银河麒麟系统不支持sudo命令"}
            
            # 安全限制：只允许特定命令
            allowed_commands = [
                "systemctl status",
                "systemctl list-units",
                "df -h",
                "free -h",
                "uptime",
                "whoami",
                "uname -a"
            ]
            
            if not any(cmd in command for cmd in allowed_commands):
                return {"error": "命令不在允许列表中"}
            
            if require_sudo:
                command = f"sudo {command}"
            
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"error": "命令执行超时"}
        except Exception as e:
            logger.error(f"执行系统命令失败: {e}")
            return {"error": str(e)}
    
    def get_security_status(self) -> Dict:
        """
        获取安全状态（银河麒麟系统）
        
        Returns:
            安全状态信息
        """
        if not self.is_kylin_os:
            return {"error": "非银河麒麟系统"}
        
        try:
            security_info = {
                "firewall_status": self._check_service("firewalld"),
                "selinux_status": self._get_selinux_status(),
                "security_updates": self._check_security_updates()
            }
            
            return security_info
        except Exception as e:
            logger.error(f"获取安全状态失败: {e}")
            return {"error": str(e)}
    
    def _get_selinux_status(self) -> str:
        """获取SELinux状态"""
        try:
            result = subprocess.run(
                ['getenforce'],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except:
            return "unknown"
    
    def _check_security_updates(self) -> Dict:
        """检查安全更新"""
        try:
            # 检查是否有安全更新可用
            result = subprocess.run(
                ['yum', 'check-update', '--security'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return {
                "has_updates": result.returncode == 100,  # 100表示有更新
                "output": result.stdout[:500] if result.stdout else ""
            }
        except:
            return {"has_updates": False, "error": "无法检查更新"}
    
    def create_system_shortcut(self, name: str, command: str, icon: Optional[str] = None) -> Dict:
        """
        创建系统级快捷方式（银河麒麟系统）
        
        Args:
            name: 快捷方式名称
            command: 命令
            icon: 图标路径（可选）
        
        Returns:
            创建结果
        """
        if not self.is_kylin_os:
            return {"error": "非银河麒麟系统"}
        
        try:
            # 创建.desktop文件
            desktop_dir = os.path.expanduser("~/.local/share/applications")
            os.makedirs(desktop_dir, exist_ok=True)
            
            desktop_file = os.path.join(desktop_dir, f"{name}.desktop")
            
            content = f"""[Desktop Entry]
Name={name}
Exec={command}
Type=Application
"""
            if icon:
                content += f"Icon={icon}\n"
            
            with open(desktop_file, 'w') as f:
                f.write(content)
            
            # 设置可执行权限
            os.chmod(desktop_file, 0o755)
            
            return {
                "success": True,
                "desktop_file": desktop_file,
                "message": f"快捷方式 {name} 创建成功"
            }
        except Exception as e:
            logger.error(f"创建快捷方式失败: {e}")
            return {"error": str(e)}


# 全局银河麒麟系统集成服务实例
kylin_os_integration_service = KylinOSIntegrationService()





