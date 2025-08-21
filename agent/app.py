#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEB应用容器发布Agent
开发环境专用工具，用于构建前端应用容器镜像并发布到DockerHub
支持GUI界面和命令行两种使用方式
"""

from math import log
import os
import sys
import json
import shutil
import zipfile
import tempfile
import subprocess
import threading
import socket
from datetime import datetime
from pathlib import Path
import click

# 尝试导入GUI库
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("警告: 无法导入tkinter，GUI模式不可用")

# 尝试导入webview库用于JS底座
try:
    import webview
    import requests
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False
    print("警告: 无法导入webview或requests，JS底座功能不可用")
    print("请运行: pip install pywebview requests")

# 配置
CONFIG = {
    'DOCKERHUB_USERNAME': os.getenv('DOCKERHUB_USERNAME', ''),
    'DOCKERHUB_TOKEN': os.getenv('DOCKERHUB_TOKEN', ''),
    'MAINTAINER': os.getenv('MAINTAINER', 'HZXY DevOps Team'),
    'SERVICE_PREFIX': os.getenv('SERVICE_PREFIX', 'hzxy'),
    'BASE_IMAGE_NAME': 'hzxy-webapp-base',
    'BUILD_FOLDER': 'builds',
    'CONFIG_FILE': os.path.expanduser('~/.hzxy-agent-config.json'),
    # JS底座配置
    'REMOTE_URL': '',
    'REMOTE_USERNAME': 'Happy',
    'REMOTE_PASSWORD': '',
    'CALLBACK_METHOD': '',
    # 登录接口配置
    'LOGIN_URL': "https://datacenter.zstzpt.com/api/chainAuthLogIn",
    'REQUEST_METHOD': 'POST',
    'CONTENT_TYPE': 'application/json',
    'REQUEST_PARAMS': '{"userName":"{{username}}","passWord":"{{password}}"}',
    'TOKEN_PATH': 'data.token'
}

# 确保构建目录存在
os.makedirs(CONFIG['BUILD_FOLDER'], exist_ok=True)

def load_config():
    """加载配置文件"""
    if os.path.exists(CONFIG['CONFIG_FILE']):
        try:
            with open(CONFIG['CONFIG_FILE'], 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                CONFIG.update(saved_config)
        except Exception as e:
            print(f"加载配置文件失败: {e}")

def save_config():
    """保存配置文件"""
    try:
        config_to_save = {
            'DOCKERHUB_USERNAME': CONFIG['DOCKERHUB_USERNAME'],
            'DOCKERHUB_TOKEN': CONFIG['DOCKERHUB_TOKEN'],
            'MAINTAINER': CONFIG['MAINTAINER'],
            'SERVICE_PREFIX': CONFIG['SERVICE_PREFIX'],
            'BASE_IMAGE_NAME': CONFIG['BASE_IMAGE_NAME'],
            'REMOTE_URL': CONFIG['REMOTE_URL'],
            'REMOTE_USERNAME': CONFIG['REMOTE_USERNAME'],
            'REMOTE_PASSWORD': CONFIG['REMOTE_PASSWORD'],
            'CALLBACK_METHOD': CONFIG['CALLBACK_METHOD'],
            'LOGIN_URL': CONFIG['LOGIN_URL'],
            'REQUEST_METHOD': CONFIG['REQUEST_METHOD'],
            'CONTENT_TYPE': CONFIG['CONTENT_TYPE'],
            'REQUEST_PARAMS': CONFIG['REQUEST_PARAMS'],
            'TOKEN_PATH': CONFIG['TOKEN_PATH']
        }
        with open(CONFIG['CONFIG_FILE'], 'w', encoding='utf-8') as f:
            json.dump(config_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"保存配置文件失败: {e}")

def find_docker_command():
    """查找Docker命令的完整路径"""
    # 常见的Docker安装路径
    docker_paths = [
        '/usr/local/bin/docker',
        '/usr/bin/docker',
        '/Applications/Docker.app/Contents/Resources/bin/docker',
        'docker'  # 如果在PATH中
    ]
    
    for path in docker_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return path
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            continue
    
    return None

def get_available_port(start_port=3000):
    """获取可用端口"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    return None

def get_container_status(container_name):
    """获取容器状态"""
    docker_cmd = find_docker_command()
    if not docker_cmd:
        return None
    
    try:
        # 检查容器是否存在并获取状态
        result = subprocess.run([
            docker_cmd, 'ps', '-a', '--filter', f'name={container_name}', 
            '--format', 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
        ], capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:  # 跳过表头
                parts = lines[1].split('\t')
                if len(parts) >= 2:
                    status = parts[1]
                    ports = parts[2] if len(parts) > 2 else ''
                    return {
                        'running': 'Up' in status,
                        'status': status,
                        'ports': ports
                    }
    except Exception:
        pass
    
    return None

def run_command(cmd, cwd=None, callback=None, env=None):
    """执行命令并返回结果"""
    try:
        if callback:
            # 实时输出模式
            process = subprocess.Popen(
                cmd, shell=True, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, bufsize=1
            )
            
            output_lines = []
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                output_lines.append(line)
                callback(line)
            
            process.wait()
            return process.returncode == 0, '\n'.join(output_lines), ''
        else:
            # 普通模式
            result = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
            return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, '', str(e)

def create_dockerfile(app_name, version, maintainer="HZXY DevOps Team"):
    """创建Dockerfile"""
    dockerfile_content = f'''
FROM nginx:alpine

# 设置工作目录
WORKDIR /usr/share/nginx/html

# 删除默认的nginx页面
RUN rm -rf /usr/share/nginx/html/*

# 复制应用文件
COPY dist.zip /tmp/dist.zip

# 解压应用文件并保持目录结构
RUN cd /tmp && unzip dist.zip && \
    if [ -d "dist" ]; then \
        cp -r dist/* /usr/share/nginx/html/; \
    else \
        cp -r . /usr/share/nginx/html/ && \
        rm -f /usr/share/nginx/html/dist.zip; \
    fi && \
    rm -rf /tmp/dist.zip /tmp/dist

# 添加标签
LABEL app.name="{app_name}"
LABEL app.version="{version}"
LABEL app.build.date="{datetime.now().isoformat()}"
LABEL maintainer="{maintainer}"

# 暴露端口
EXPOSE 80

# 启动nginx
CMD ["nginx", "-g", "daemon off;"]
'''
    return dockerfile_content

def build_image(dist_file_path, app_name, build_time, callback=None):
    """仅构建Docker镜像"""
    docker_cmd = find_docker_command()
    if not docker_cmd:
        error_msg = "❌ 错误: 未找到Docker命令，请确保Docker Desktop已安装并运行"
        if callback:
            callback(error_msg)
        return False
    
    build_dir = Path(CONFIG['BUILD_FOLDER']) / f"{app_name}-{build_time}"
    build_dir.mkdir(parents=True, exist_ok=True)
    
    def log(message):
        print(message)
        if callback:
            callback(message)
    
    try:
        log(f"开始构建应用: {app_name} - {build_time}")
        log(f"构建目录: {build_dir}")
        
        # 复制dist文件
        log("复制dist文件...")
        shutil.copy2(dist_file_path, build_dir / 'dist.zip')
        
        # 创建Dockerfile
        log("创建Dockerfile...")
        dockerfile_content = create_dockerfile(app_name, build_time, CONFIG['MAINTAINER'])
        with open(build_dir / 'Dockerfile', 'w', encoding='utf-8') as f:
            f.write(dockerfile_content)
        
        # 构建镜像
        image_tag = f"{app_name}:{build_time}"
        
        log(f"构建镜像: {image_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} build -t {image_tag} .", 
            cwd=build_dir, 
            callback=log if callback else None
        )
        
        if not success:
            log(f"构建失败: {stderr}")
            return False
        
        log("✅ 构建成功!")
        log(f"镜像标签: {image_tag}")
        
        return True
        
    except Exception as e:
        log(f"构建过程出错: {str(e)}")
        return False
    finally:
        # 清理构建目录
        if build_dir.exists():
            try:
                shutil.rmtree(build_dir)
                log(f"清理构建目录: {build_dir}")
            except Exception as e:
                log(f"清理构建目录失败: {e}")

def build_and_push_image(app_name, version, dist_file_path, username=None, token=None, callback=None):
    """构建并推送Docker镜像"""
    # 首先检查Docker是否可用
    docker_cmd = find_docker_command()
    if not docker_cmd:
        error_msg = "❌ 错误: 未找到Docker命令，请确保Docker Desktop已安装并运行"
        if callback:
            callback(error_msg)
        return False, error_msg
    
    # 使用传入的用户名和token，如果没有则使用CONFIG中的
    dockerhub_username = username or CONFIG['DOCKERHUB_USERNAME']
    dockerhub_token = token or CONFIG['DOCKERHUB_TOKEN']
    
    if not dockerhub_username or not dockerhub_token:
        error_msg = "❌ 错误: 缺少DockerHub用户名或Token"
        if callback:
            callback(error_msg)
        return False, error_msg
    build_dir = Path(CONFIG['BUILD_FOLDER']) / f"{app_name}-{version}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    build_dir.mkdir(parents=True, exist_ok=True)
    
    def log(message):
        print(message)
        if callback:
            callback(message)
    
    try:
        log(f"开始构建应用: {app_name} v{version}")
        log(f"构建目录: {build_dir}")
        
        # 复制dist文件
        log("复制dist文件...")
        shutil.copy2(dist_file_path, build_dir / 'dist.zip')
        
        # 创建Dockerfile
        log("创建Dockerfile...")
        dockerfile_content = create_dockerfile(app_name, version, CONFIG['MAINTAINER'])
        with open(build_dir / 'Dockerfile', 'w', encoding='utf-8') as f:
            f.write(dockerfile_content)
        
        # 构建镜像
        image_tag = f"{dockerhub_username}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:{version}"
        latest_tag = f"{dockerhub_username}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:latest"
        
        log(f"构建镜像: {image_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} build -t {image_tag} -t {latest_tag} .", 
            cwd=build_dir, 
            callback=log if callback else None
        )
        
        if not success:
            return False, f"构建失败: {stderr}"
        
        # 登录DockerHub
        if dockerhub_token:
            log("登录DockerHub...")
            # 使用临时配置禁用凭据存储
            login_cmd = f"echo '{dockerhub_token}' | {docker_cmd} login -u {dockerhub_username} --password-stdin"
            
            # 设置环境变量禁用凭据存储
            import os
            env = os.environ.copy()
            env['DOCKER_CONFIG'] = '/tmp/.docker'
            
            # 创建临时Docker配置目录
            temp_docker_dir = Path('/tmp/.docker')
            temp_docker_dir.mkdir(exist_ok=True)
            
            # 创建config.json禁用凭据存储
            config_content = '{"credsStore": ""}'
            with open(temp_docker_dir / 'config.json', 'w') as f:
                f.write(config_content)
            
            success, _, stderr = run_command(login_cmd, env=env)
            if not success:
                return False, f"DockerHub登录失败: {stderr}"
        
        # 推送镜像（使用相同的环境变量）
        push_env = env if dockerhub_token else None
        
        log(f"推送镜像: {image_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} push {image_tag}", 
            env=push_env,
            callback=log if callback else None
        )
        if not success:
            return False, f"推送失败: {stderr}"
        
        log(f"推送镜像: {latest_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} push {latest_tag}", 
            env=push_env,
            callback=log if callback else None
        )
        if not success:
            return False, f"推送latest标签失败: {stderr}"
        
        log("✅ 发布成功!")
        log(f"镜像地址: {image_tag}")
        log(f"最新标签: {latest_tag}")
        
        return True, f"成功发布镜像: {image_tag}"
        
    except Exception as e:
        return False, f"发布过程出错: {str(e)}"
    finally:
        # 清理构建目录
        if build_dir.exists():
            try:
                shutil.rmtree(build_dir)
                log(f"清理构建目录: {build_dir}")
            except Exception as e:
                log(f"清理构建目录失败: {e}")

class PublisherGUI:
    """GUI界面类"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HZXY WEB应用容器发布工具")
        self.root.geometry("1000x800")
        self.root.resizable(True, True)
        
        # 设置样式
        style = ttk.Style()
        style.theme_use('clam')
        
        # 构建历史数据
        self.builds = []  # 存储构建历史
        self.builds_tree = None  # 构建列表树形控件
        self.builds_file = os.path.expanduser("~/.hzxy-builds.json")
        self.structure_tree = None  # 目录结构树形控件
        self.log_text = False  # 日志文本控件
        
        # JS底座临时文件管理
        self.js_base_temp_dir = None
        
        self.setup_ui()
        self.load_settings()
        self.load_builds()
    
    def setup_ui(self):
        """设置UI界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="🚀 HZXY WEB应用容器发布工具", font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # 左侧面板 - 配置和构建
        left_panel = ttk.Frame(main_frame)
        left_panel.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        left_panel.columnconfigure(0, weight=1)
        
        # DockerHub配置
        config_frame = ttk.LabelFrame(left_panel, text="DockerHub配置", padding="10")
        config_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(config_frame, text="用户名:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.username_var = tk.StringVar()
        ttk.Entry(config_frame, textvariable=self.username_var).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        ttk.Label(config_frame, text="Token:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.token_var = tk.StringVar()
        token_entry = ttk.Entry(config_frame, textvariable=self.token_var, show="*")
        token_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        
        ttk.Label(config_frame, text="维护者:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.maintainer_var = tk.StringVar()
        maintainer_entry = ttk.Entry(config_frame, textvariable=self.maintainer_var)
        maintainer_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        maintainer_entry.insert(0, "HZXY DevOps Team")
        
        ttk.Label(config_frame, text="服务前缀:").grid(row=3, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.service_prefix_var = tk.StringVar()
        service_prefix_entry = ttk.Entry(config_frame, textvariable=self.service_prefix_var)
        service_prefix_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        service_prefix_entry.insert(0, "hzxy")
        
        ttk.Label(config_frame, text="基础镜像名:").grid(row=4, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.base_image_name_var = tk.StringVar()
        base_image_name_entry = ttk.Entry(config_frame, textvariable=self.base_image_name_var)
        base_image_name_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        base_image_name_entry.insert(0, "hzxy-webapp-base")
        
        ttk.Button(config_frame, text="保存配置", command=self.save_settings).grid(row=0, column=2, rowspan=5)
        
        # JS底座配置
        js_base_frame = ttk.LabelFrame(left_panel, text="JS底座配置", padding="10")
        js_base_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        js_base_frame.columnconfigure(1, weight=1)
        
        ttk.Label(js_base_frame, text="远程地址:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.remote_url_var = tk.StringVar()
        remote_url_entry = ttk.Entry(js_base_frame, textvariable=self.remote_url_var)
        remote_url_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        remote_url_entry.insert(0, "https://datacenter.zstzpt.com/Brain/SuperChain")
        
        ttk.Label(js_base_frame, text="用户名:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.remote_username_var = tk.StringVar()
        remote_username_entry = ttk.Entry(js_base_frame, textvariable=self.remote_username_var)
        remote_username_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        
        ttk.Label(js_base_frame, text="密码:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.remote_password_var = tk.StringVar()
        remote_password_entry = ttk.Entry(js_base_frame, textvariable=self.remote_password_var, show="*")
        remote_password_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        
        # 登录接口配置区域
        login_config_frame = ttk.LabelFrame(js_base_frame, text="登录接口配置", padding="5")
        login_config_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 5))
        login_config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(login_config_frame, text="接口地址:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.login_url_var = tk.StringVar()
        login_url_entry = ttk.Entry(login_config_frame, textvariable=self.login_url_var)
        login_url_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        login_url_entry.insert(0, "https://datacenter.zstzpt.com/api/chainAuthLogIn")
        
        ttk.Label(login_config_frame, text="请求类型:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(3, 0))
        self.request_method_var = tk.StringVar()
        method_combo = ttk.Combobox(login_config_frame, textvariable=self.request_method_var, values=["POST", "GET", "PUT"], state="readonly")
        method_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(3, 0))
        method_combo.set("POST")
        
        ttk.Label(login_config_frame, text="Content-Type:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5), pady=(3, 0))
        self.content_type_var = tk.StringVar()
        content_type_combo = ttk.Combobox(login_config_frame, textvariable=self.content_type_var, values=["application/json", "application/x-www-form-urlencoded", "multipart/form-data"], state="readonly")
        content_type_combo.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(3, 0))
        content_type_combo.set("application/json")
        
        ttk.Label(login_config_frame, text="请求参数:").grid(row=3, column=0, sticky=tk.W, padx=(0, 5), pady=(3, 0))
        self.request_params_text = scrolledtext.ScrolledText(login_config_frame, height=3, width=40)
        self.request_params_text.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(3, 0))
        self.request_params_text.insert('1.0', '{"userName":"{{username}}","passWord":"{{password}}"}')
        
        ttk.Label(login_config_frame, text="Token路径:").grid(row=4, column=0, sticky=tk.W, padx=(0, 5), pady=(3, 0))
        self.token_path_var = tk.StringVar()
        token_path_entry = ttk.Entry(login_config_frame, textvariable=self.token_path_var)
        token_path_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(3, 0))
        token_path_entry.insert(0, "data.token")
        
        ttk.Button(login_config_frame, text="🔧 自动生成回调", command=self.generate_callback).grid(row=5, column=0, columnspan=2, pady=(5, 0))
        
        ttk.Label(js_base_frame, text="回调方法:").grid(row=4, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.callback_text = scrolledtext.ScrolledText(js_base_frame, height=6, width=50)
        self.callback_text.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        # 默认回调方法模板
        default_callback = """// 免登录回调方法
// 返回格式: {token: 'your_token', success: true}
function getAuthToken(username, password) {
    // 在这里实现您的登录逻辑
    // 例如: 调用API获取token
    return {
        token: 'example_token',
        success: true
    };
}"""
        self.callback_text.insert('1.0', default_callback)
        
        ttk.Button(js_base_frame, text="🌐 启动JS底座", command=self.start_js_base).grid(row=5, column=0, columnspan=2, pady=(10, 0))
        
        # 新建构建
        build_frame = ttk.LabelFrame(left_panel, text="新建构建", padding="10")
        build_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        build_frame.columnconfigure(1, weight=1)
        
        ttk.Label(build_frame, text="应用名称:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.app_name_var = tk.StringVar()
        app_entry = ttk.Entry(build_frame, textvariable=self.app_name_var)
        app_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        app_entry.insert(0, "例如: ai-zhaoshang")
        app_entry.bind('<FocusIn>', lambda e: app_entry.delete(0, tk.END) if app_entry.get() == "例如: ai-zhaoshang" else None)
        
        ttk.Label(build_frame, text="dist.zip文件:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.file_path_var = tk.StringVar()
        ttk.Entry(build_frame, textvariable=self.file_path_var, state="readonly").grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        ttk.Button(build_frame, text="选择文件", command=self.select_file).grid(row=1, column=2, pady=(5, 0))
        
        self.build_btn = ttk.Button(build_frame, text="🔨 开始构建", command=self.start_build, style='Accent.TButton')
        self.build_btn.grid(row=2, column=0, columnspan=3, pady=(10, 0))
        
        # 目录结构展示
        structure_frame = ttk.LabelFrame(left_panel, text="应用目录结构", padding="10")
        structure_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        structure_frame.columnconfigure(0, weight=1)
        structure_frame.rowconfigure(0, weight=1)
        
        # 创建目录结构树形控件
        self.structure_tree = ttk.Treeview(structure_frame, height=10)
        self.structure_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 滚动条
        structure_scrollbar = ttk.Scrollbar(structure_frame, orient=tk.VERTICAL, command=self.structure_tree.yview)
        structure_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.structure_tree.configure(yscrollcommand=structure_scrollbar.set)
        
        # 配置左侧面板权重
        left_panel.rowconfigure(3, weight=1)
        
        # 右侧面板 - 构建列表和日志
        right_panel = ttk.Frame(main_frame)
        right_panel.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(1, weight=1)
        
        # 构建历史列表
        builds_frame = ttk.LabelFrame(right_panel, text="构建历史", padding="10")
        builds_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        builds_frame.columnconfigure(0, weight=1)
        builds_frame.rowconfigure(0, weight=1)
        
        # 创建Treeview
        columns = ('app_name', 'build_time', 'status', 'container_status', 'test_url')
        self.builds_tree = ttk.Treeview(builds_frame, columns=columns, show='headings', height=8)
        
        # 设置列标题
        self.builds_tree.heading('app_name', text='应用名称')
        self.builds_tree.heading('build_time', text='构建时间')
        self.builds_tree.heading('status', text='构建状态')
        self.builds_tree.heading('container_status', text='容器状态')
        self.builds_tree.heading('test_url', text='访问地址')
        
        # 设置列宽
        self.builds_tree.column('app_name', width=120)
        self.builds_tree.column('build_time', width=150)
        self.builds_tree.column('status', width=80)
        self.builds_tree.column('container_status', width=100)
        self.builds_tree.column('test_url', width=150)
        
        self.builds_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 滚动条
        builds_scrollbar = ttk.Scrollbar(builds_frame, orient=tk.VERTICAL, command=self.builds_tree.yview)
        builds_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.builds_tree.configure(yscrollcommand=builds_scrollbar.set)
        

        # 绑定双击事件打开访问地址
        self.builds_tree.bind('<Double-1>', self.on_build_double_click)
        
        # 操作按钮框架
        actions_frame = ttk.Frame(builds_frame)
        actions_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        
        ttk.Button(actions_frame, text="🧪 本地测试", command=self.test_selected_build).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="⏹️ 停止容器", command=self.stop_selected_container).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="🚀 发布到DockerHub", command=self.publish_selected_build).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="📋 生成Compose模板", command=self.generate_compose_for_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="🗑️ 删除构建", command=self.delete_selected_build).pack(side=tk.LEFT)
        
        # 日志输出
        log_frame = ttk.LabelFrame(right_panel, text="构建日志", padding="10")
        log_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 清空日志按钮
        ttk.Button(log_frame, text="清空日志", command=self.clear_log).grid(row=1, column=0, sticky=tk.E, pady=(5, 0))
        
        # 配置主面板权重
        main_frame.rowconfigure(1, weight=1)
    
    def show_zip_structure(self, zip_path):
        """显示zip文件的目录结构"""
        print("show_zip_structure")
        if not self.structure_tree:
            return
            
        try:
            # 清空现有内容
            for item in self.structure_tree.get_children():
                self.structure_tree.delete(item)
            print("XXXXXX")
            # 读取zip文件内容
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                print("YYYYYYY")
                file_list = zip_file.namelist()
                
                print("\n=== ZIP文件内容调试 ===")
                print(f"原始文件列表 ({len(file_list)}个):")
                for i, f in enumerate(file_list):
                    print(f"  {i}: '{f}'")
                
                # 构建树形结构
                nodes = {}
                print("\n=== 路径解析调试 ===")
                
                for file_path in sorted(file_list):
                    if not file_path or file_path == '.':
                        continue
                        
                    parts = [p for p in file_path.split('/') if p]  # 过滤空字符串
                    print(f"\n文件路径: '{file_path}' -> 部分: {parts}")
                    
                    # 逐级构建路径
                    for i in range(len(parts)):
                        current_parts = parts[:i+1]
                        current_path = '/'.join(current_parts)
                        
                        if current_path not in nodes:
                            # 确定父节点
                            if i == 0:
                                parent_id = ''
                                parent_path = 'ROOT'
                            else:
                                parent_path = '/'.join(parts[:i])
                                parent_id = nodes.get(parent_path, '')
                            
                            part_name = parts[i]
                            
                            # 判断是文件还是目录
                            is_dir = (i < len(parts) - 1) or file_path.endswith('/')
                            icon = '📁' if is_dir else '📄'
                            
                            print(f"  创建节点: '{part_name}' (路径: {current_path}, 父: {parent_path}, 类型: {'目录' if is_dir else '文件'})")
                            
                            node_id = self.structure_tree.insert(
                                parent_id, 'end', 
                                text=f"{icon} {part_name}",
                                open=True if i < 2 else False  # 前两层默认展开
                            )
                            nodes[current_path] = node_id
                
                print("\n=== 最终节点映射 ===")
                for path, node_id in nodes.items():
                    print(f"  '{path}' -> {node_id}")
                
                self.log_message(f"已显示zip文件结构: {len(file_list)}个文件")
                
        except Exception as e:
            self.log_message(f"读取zip文件失败: {e}")            
            # 显示错误信息
            self.structure_tree.insert('', 'end', text=f"❌ 读取失败: {str(e)}")
    
    def show_build_structure(self, build):
        """显示构建的目录结构"""
        if not self.structure_tree:
            return
            
        try:
            # 清空现有内容
            for item in self.structure_tree.get_children():
                self.structure_tree.delete(item)
            
            if 'file_path' in build and os.path.exists(build['file_path']):
                self.show_zip_structure(build['file_path'])
            else:
                self.structure_tree.insert('', 'end', text="❌ 源文件不存在")
                
        except Exception as e:
            self.log_message(f"显示构建结构失败: {e}")
            self.structure_tree.insert('', 'end', text=f"❌ 显示失败: {str(e)}")
    
    def log_message(self, message):
        """添加日志消息"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        if not self.log_text:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
            return
            
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()
    
    def clear_log(self):
        """清空日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def select_file(self):
        """选择文件"""
        file_path = filedialog.askopenfilename(
            title="选择dist.zip文件",
            filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")]
        )
        if file_path:
            self.file_path_var.set(file_path)
            # 显示zip文件内容
            self.show_zip_structure(file_path)
    
    def save_settings(self):
        """保存设置"""
        CONFIG['DOCKERHUB_USERNAME'] = self.username_var.get().strip()
        CONFIG['DOCKERHUB_TOKEN'] = self.token_var.get().strip()
        CONFIG['MAINTAINER'] = self.maintainer_var.get().strip()
        CONFIG['SERVICE_PREFIX'] = self.service_prefix_var.get().strip()
        CONFIG['BASE_IMAGE_NAME'] = self.base_image_name_var.get().strip()
        # 保存JS底座配置
        CONFIG['REMOTE_URL'] = self.remote_url_var.get().strip()
        CONFIG['REMOTE_USERNAME'] = self.remote_username_var.get().strip()
        CONFIG['REMOTE_PASSWORD'] = self.remote_password_var.get().strip()
        CONFIG['CALLBACK_METHOD'] = self.callback_text.get('1.0', tk.END).strip()
        # 保存登录接口配置
        CONFIG['LOGIN_URL'] = self.login_url_var.get().strip()
        CONFIG['REQUEST_METHOD'] = self.request_method_var.get().strip()
        CONFIG['CONTENT_TYPE'] = self.content_type_var.get().strip()
        CONFIG['REQUEST_PARAMS'] = self.request_params_text.get('1.0', tk.END).strip()
        CONFIG['TOKEN_PATH'] = self.token_path_var.get().strip()
        save_config()
        self.log_message("配置已保存")
        messagebox.showinfo("成功", "配置已保存")
    
    def load_settings(self):
        """加载设置"""
        load_config()
        self.username_var.set(CONFIG['DOCKERHUB_USERNAME'])
        # Token不显示明文，但保留实际值
        if CONFIG['DOCKERHUB_TOKEN']:
            self.token_var.set(CONFIG['DOCKERHUB_TOKEN'])  # 保留实际token值
        else:
            self.token_var.set("")
        # 加载maintainer设置
        if CONFIG.get('MAINTAINER'):
            self.maintainer_var.set(CONFIG['MAINTAINER'])
        else:
            self.maintainer_var.set("DevOps Team")
        # 加载服务前缀设置
        if CONFIG.get('SERVICE_PREFIX'):
            self.service_prefix_var.set(CONFIG['SERVICE_PREFIX'])
        else:
            self.service_prefix_var.set("hzxy")
        # 加载基础镜像名称设置
        if CONFIG.get('BASE_IMAGE_NAME'):
            self.base_image_name_var.set(CONFIG['BASE_IMAGE_NAME'])
        else:
            self.base_image_name_var.set("hzxy-webapp-base")
        
        # 加载JS底座配置
        if CONFIG.get('REMOTE_URL'):
            self.remote_url_var.set(CONFIG['REMOTE_URL'])
        if CONFIG.get('REMOTE_USERNAME'):
            self.remote_username_var.set(CONFIG['REMOTE_USERNAME'])
        if CONFIG.get('REMOTE_PASSWORD'):
            self.remote_password_var.set(CONFIG['REMOTE_PASSWORD'])
        if CONFIG.get('CALLBACK_METHOD'):
            self.callback_text.delete('1.0', tk.END)
            self.callback_text.insert('1.0', CONFIG['CALLBACK_METHOD'])
        
        # 加载登录接口配置
        if CONFIG.get('LOGIN_URL'):
            self.login_url_var.set(CONFIG['LOGIN_URL'])
        if CONFIG.get('REQUEST_METHOD'):
            self.request_method_var.set(CONFIG['REQUEST_METHOD'])
        if CONFIG.get('CONTENT_TYPE'):
            self.content_type_var.set(CONFIG['CONTENT_TYPE'])
        if CONFIG.get('REQUEST_PARAMS'):
            self.request_params_text.delete('1.0', tk.END)
            self.request_params_text.insert('1.0', CONFIG['REQUEST_PARAMS'])
        if CONFIG.get('TOKEN_PATH'):
            self.token_path_var.set(CONFIG['TOKEN_PATH'])
    
    def load_builds(self):
        """加载构建历史"""
        try:
            if os.path.exists(self.builds_file):
                with open(self.builds_file, 'r', encoding='utf-8') as f:
                    self.builds = json.load(f)
            else:
                self.builds = []
            self.refresh_builds_list()
        except Exception as e:
            self.log_message(f"加载构建历史失败: {e}")
            self.builds = []
            self.refresh_builds_list()
    
    def save_builds(self):
        """保存构建历史"""
        try:
            with open(self.builds_file, 'w', encoding='utf-8') as f:
                json.dump(self.builds, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_message(f"保存构建历史失败: {e}")
    
    def refresh_builds_list(self):
        """刷新构建列表显示"""
        if not self.builds_tree:
            return
            
        # 清空现有项目
        for item in self.builds_tree.get_children():
            self.builds_tree.delete(item)
        
        # 添加构建项目
        self.log_message(f"加载构建历史: 共{len(self.builds)}个构建记录")
        for build in self.builds:
            # 检查容器状态
            container_status = "未运行"
            test_url = ""
            
            if 'container_name' in build:
                status = get_container_status(build['container_name'])
                if status and status.get('running'):
                    container_status = "运行中"
                    test_url = build.get('test_url', '')
                elif status and not status.get('running'):
                    container_status = "已停止"
                else:
                    container_status = "未运行"
            
            self.builds_tree.insert('', 'end', values=(
                build['app_name'],
                build['build_time'],
                build['status'],
                container_status,
                test_url
            ))
            self.log_message(f"添加构建记录: {build['app_name']} - {build['build_time']}")
        
        # 绑定选择事件
        self.builds_tree.bind('<<TreeviewSelect>>', self.on_build_select)
    
    def start_build(self):
        """开始构建"""
        app_name = self.app_name_var.get().strip()
        file_path = self.file_path_var.get().strip()
        
        if not app_name or app_name == "例如: ai-zhaoshang":
            messagebox.showerror("错误", "请输入应用名称")
            return
        
        if not file_path:
            messagebox.showerror("错误", "请选择dist.zip文件")
            return
        
        if not os.path.exists(file_path):
            messagebox.showerror("错误", "选择的文件不存在")
            return
        
        # 生成构建时间标签
        build_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 创建构建记录
        build_record = {
            'id': f"{app_name}_{build_time}",
            'app_name': app_name,
            'build_time': build_time,
            'file_path': file_path,
            'status': '构建中',
            'docker_image': f"{app_name}:{build_time}",
            'created_at': datetime.now().isoformat()
        }
        
        self.builds.append(build_record)
        self.save_builds()
        self.refresh_builds_list()
        
        # 开始构建过程
        self.build_btn.config(state='disabled')
        threading.Thread(target=self._build_worker, args=(build_record,), daemon=True).start()
    
    def _build_worker(self, build_record):
        """构建工作线程"""
        try:
            self.log_message(f"开始构建 {build_record['app_name']} - {build_record['build_time']}")
            
            # 调用构建函数
            success = build_image(
                build_record['file_path'],
                build_record['app_name'],
                build_record['build_time'],
                self.log_message
            )
            
            # 更新构建状态
            if success:
                build_record['status'] = '构建完成'
                self.log_message(f"✅ 构建完成: {build_record['docker_image']}")
            else:
                build_record['status'] = '构建失败'
                self.log_message(f"❌ 构建失败: {build_record['app_name']}")
            
            self.save_builds()
            self.root.after(0, self.refresh_builds_list)
            
        except Exception as e:
            build_record['status'] = '构建失败'
            self.log_message(f"构建异常: {e}")
            self.save_builds()
            self.root.after(0, self.refresh_builds_list)
        finally:
            self.root.after(0, lambda: self.build_btn.config(state='normal'))
    
    def get_selected_build(self):
        """获取选中的构建记录"""
        selection = self.builds_tree.selection()
        self.log_message(f"当前选中项: {selection}")
        if not selection:
            messagebox.showwarning("警告", "请先选择一个构建项目")
            return None
        
        item = self.builds_tree.item(selection[0])
        values = item['values']
        app_name, build_time = values[0], values[1]
        
        # 确保build_time是字符串类型
        build_time = str(build_time)
        self.log_message(f"选中的构建: '{app_name}' - '{build_time}' (类型: {type(build_time)})")
        
        # 查找对应的构建记录
        for build in self.builds:
            # self.log_message(f"比较构建记录: '{build['app_name']}' - '{build['build_time']}' (类型: {type(build['build_time'])})")
            
            # 处理时间格式差异：移除下划线进行比较
            stored_time = build['build_time'].replace('_', '')
            selected_time = build_time.replace('_', '')
            
            # self.log_message(f"格式化后比较: '{stored_time}' vs '{selected_time}'")
            # self.log_message(f"app_name匹配: {build['app_name'] == app_name}, build_time匹配: {stored_time == selected_time}")
            
            if build['app_name'] == app_name and stored_time == selected_time:
                self.log_message(f"找到匹配的构建记录: {build}")
                return build
        
        self.log_message("未找到匹配的构建记录")
        return None
    
    def test_selected_build(self):
        """测试选中的构建"""
        self.log_message("🧪 本地测试按钮被点击")
        build = self.get_selected_build()
        if not build:
            return
        
        if build['status'] != '构建完成':
            messagebox.showerror("错误", "只能测试构建完成的项目")
            return
        
        # 启动本地测试
        threading.Thread(target=self._test_worker, args=(build,), daemon=True).start()
    
    def _test_worker(self, build):
        """测试工作线程"""
        try:
            self.log_message(f"开始本地测试: {build['docker_image']}")
            
            # 停止可能存在的同名容器
            docker_cmd = find_docker_command()
            if not docker_cmd:
                self.log_message("❌ 未找到Docker命令")
                return

            container_name = f"test_{build['app_name']}_{build['build_time']}"
            
            # 停止并删除现有容器
            subprocess.run([docker_cmd, 'stop', container_name], capture_output=True)
            subprocess.run([docker_cmd, 'rm', container_name], capture_output=True)
            
            # 获取可用端口
            port = get_available_port()
            if not port:
                self.log_message("❌ 无法找到可用端口")
                return
            
            # 启动新容器
            cmd = [
                docker_cmd, 'run', '-d',
                '--name', container_name,
                '-p', f'{port}:80',
                build['docker_image']
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # 保存容器信息到构建记录
                build['container_name'] = container_name
                build['test_port'] = port
                build['test_url'] = f'http://localhost:{port}'
                self.save_builds()
                
                self.log_message(f"✅ 测试容器启动成功: {container_name}")
                self.log_message(f"🌐 访问地址: http://localhost:{port}")
                self.log_message(f"💡 停止测试: docker stop {container_name}")
                
                # 刷新构建列表显示
                self.root.after(0, self.refresh_builds_list)
            else:
                self.log_message(f"❌ 测试容器启动失败: {result.stderr}")
                
        except Exception as e:
            self.log_message(f"测试异常: {e}")
    
    def publish_selected_build(self):
        """发布选中的构建"""
        self.log_message("🚀 发布按钮被点击")
        build = self.get_selected_build()
        if not build:
            return
        
        if build['status'] != '构建完成':
            messagebox.showerror("错误", "只能发布构建完成的项目")
            return
        
        # 弹出版本号输入对话框
        self._show_publish_dialog(build)
    
    def _show_publish_dialog(self, build):
        """显示发布对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("发布到DockerHub")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"应用: {build['app_name']}").pack(pady=(0, 10))
        ttk.Label(frame, text=f"构建时间: {build['build_time']}").pack(pady=(0, 10))
        
        ttk.Label(frame, text="发布版本号:").pack(pady=(0, 5))
        version_var = tk.StringVar()
        
        # 自动推荐版本号
        recommended_version = self._get_recommended_version(build['app_name'])
        version_var.set(recommended_version)
        
        version_entry = ttk.Entry(frame, textvariable=version_var, width=30)
        version_entry.pack(pady=(0, 10))
        version_entry.select_range(0, tk.END)
        version_entry.focus()
        
        ttk.Label(frame, text=f"推荐版本: {recommended_version}", foreground="gray").pack(pady=(0, 10))
        
        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=(10, 0))
        
        def on_publish():
            version = version_var.get().strip()
            if not version:
                messagebox.showerror("错误", "请输入版本号")
                return
            
            dialog.destroy()
            threading.Thread(target=self._publish_worker, args=(build, version), daemon=True).start()
        
        ttk.Button(button_frame, text="发布", command=on_publish).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT)
    
    def _get_recommended_version(self, app_name):
        """获取推荐的版本号"""
        # 查找该应用的历史版本
        versions = []
        for build in self.builds:
            if build['app_name'] == app_name and 'published_version' in build:
                versions.append(build['published_version'])
        
        if not versions:
            return "v1.0.0"
        
        # 解析版本号并自增
        try:
            latest_version = max(versions, key=lambda v: [int(x) for x in v.replace('v', '').split('.')])
            parts = latest_version.replace('v', '').split('.')
            parts[-1] = str(int(parts[-1]) + 1)
            return f"v{'.'.join(parts)}"
        except:
            return "v1.0.0"
    
    def _publish_worker(self, build, version):
        """发布工作线程"""
        try:
            self.log_message(f"开始发布: {build['app_name']} -> {version}")
            
            username = self.username_var.get().strip()
            token = self.token_var.get().strip()
            
            if not username or not token:
                self.log_message("❌ 请先配置DockerHub用户名和Token")
                return
            
            # 调用发布函数
            success, message = build_and_push_image(
                build['app_name'],
                version,
                build['file_path'],
                username,
                token,
                self.log_message
            )
            
            if success:
                build['published_version'] = version
                build['published_at'] = datetime.now().isoformat()
                self.save_builds()
                self.log_message(f"✅ 发布成功: {username}/{build['app_name']}:{version}")
            else:
                self.log_message(f"❌ 发布失败: {message}")
                
        except Exception as e:
            self.log_message(f"发布异常: {e}")
    
    def generate_compose_for_selected(self):
        """为选中的构建生成docker-compose模板"""
        self.log_message("📋 生成Compose模板按钮被点击")
        build = self.get_selected_build()
        if not build:
            return
        
        if 'published_version' not in build:
            messagebox.showerror("错误", "请先发布该构建到DockerHub")
            return
        
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror("错误", "请先配置DockerHub用户名")
            return
        
        app_name = build['app_name']
        version = build['published_version']
        
        service_prefix = CONFIG.get('SERVICE_PREFIX', 'hzxy')
        template = f'''services:
  {service_prefix}-{app_name}:
    image: {username}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:{version}
    container_name: {service_prefix}-{app_name}
    ports:
      - "3000:80"
    restart: unless-stopped
    networks:
      - {service_prefix}-network

networks:
  {service_prefix}-network:
    driver: bridge
'''
        
        # 显示YAML预览和编辑窗口
        self._show_yaml_editor(template, f"docker-compose-{app_name}.yml")
    
    def _show_yaml_editor(self, content, filename):
        """显示YAML编辑器窗口"""
        # 创建新窗口
        editor_window = tk.Toplevel(self.root)
        editor_window.title(f"编辑 {filename}")
        editor_window.geometry("800x600")
        editor_window.transient(self.root)
        editor_window.grab_set()
        
        # 创建主框架
        main_frame = ttk.Frame(editor_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 标题标签
        title_label = ttk.Label(main_frame, text=f"Docker Compose 模板: {filename}", font=('Arial', 12, 'bold'))
        title_label.pack(pady=(0, 10))
        
        # 文本编辑区域
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        text_area = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.NONE,
            font=('Consolas', 11),
            bg='#f8f8f8',
            fg='#333333',
            insertbackground='#333333',
            selectbackground='#0078d4',
            selectforeground='white'
        )
        text_area.pack(fill=tk.BOTH, expand=True)
        text_area.insert('1.0', content)
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 复制到剪贴板按钮
        def copy_to_clipboard():
            content = text_area.get('1.0', tk.END)
            editor_window.clipboard_clear()
            editor_window.clipboard_append(content.strip())
            messagebox.showinfo("成功", "内容已复制到剪贴板")
        
        copy_btn = ttk.Button(button_frame, text="📋 复制到剪贴板", command=copy_to_clipboard)
        copy_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # 保存到文件按钮
        def save_to_file():
            file_path = filedialog.asksaveasfilename(
                title="保存docker-compose模板",
                defaultextension=".yml",
                filetypes=[("YAML文件", "*.yml"), ("所有文件", "*.*")],
                initialfile=filename
            )
            
            if file_path:
                try:
                    content = text_area.get('1.0', tk.END)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content.strip())
                    self.log_message(f"docker-compose模板已保存到: {file_path}")
                    messagebox.showinfo("成功", f"模板已保存到: {file_path}")
                except Exception as e:
                    messagebox.showerror("错误", f"保存失败: {e}")
        
        save_btn = ttk.Button(button_frame, text="💾 保存到文件", command=save_to_file)
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # 关闭按钮
        def close_window():
            editor_window.destroy()
        
        close_btn = ttk.Button(button_frame, text="❌ 关闭", command=close_window)
        close_btn.pack(side=tk.RIGHT)
        
        # 设置窗口居中
        editor_window.update_idletasks()
        x = (editor_window.winfo_screenwidth() // 2) - (editor_window.winfo_width() // 2)
        y = (editor_window.winfo_screenheight() // 2) - (editor_window.winfo_height() // 2)
        editor_window.geometry(f"+{x}+{y}")
    
    def stop_selected_container(self):
        """停止选中构建的容器"""
        self.log_message("⏹️ 停止容器按钮被点击")
        build = self.get_selected_build()
        if not build:
            return
        
        if 'container_name' not in build:
            messagebox.showwarning("警告", "该构建没有运行中的容器")
            return
        
        # 启动停止容器的线程
        threading.Thread(target=self._stop_container_worker, args=(build,), daemon=True).start()
    
    def _stop_container_worker(self, build):
        """停止容器工作线程"""
        try:
            docker_cmd = find_docker_command()
            if not docker_cmd:
                self.log_message("❌ 未找到Docker命令")
                return
            
            container_name = build['container_name']
            self.log_message(f"正在停止容器: {container_name}")
            
            # 停止容器
            result = subprocess.run([docker_cmd, 'stop', container_name], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.log_message(f"✅ 容器已停止: {container_name}")
                # 清除容器相关信息
                if 'test_port' in build:
                    del build['test_port']
                if 'test_url' in build:
                    del build['test_url']
                self.save_builds()
                # 刷新构建列表
                self.root.after(0, self.refresh_builds_list)
            else:
                self.log_message(f"❌ 停止容器失败: {result.stderr}")
                
        except Exception as e:
            self.log_message(f"停止容器异常: {e}")
    
    def delete_selected_build(self):
        """删除选中的构建"""
        self.log_message("🗑️ 删除构建按钮被点击")
        build = self.get_selected_build()
        if not build:
            return
        
        if messagebox.askyesno("确认删除", f"确定要删除构建 {build['app_name']} - {build['build_time']} 吗？"):
            self.builds.remove(build)
            self.save_builds()
            self.refresh_builds_list()
            self.log_message(f"已删除构建: {build['app_name']} - {build['build_time']}")
    
    def on_build_select(self, event):
        """构建选择事件处理"""
        selection = self.builds_tree.selection()
        self.log_message(f"当前选中项: {selection}")
        if not selection:
            return
        
        item = self.builds_tree.item(selection[0])
        values = item['values']
        app_name, build_time = values[0], values[1]
        
        # 确保build_time是字符串类型
        build_time = str(build_time)
        self.log_message(f"选中的构建: '{app_name}' - '{build_time}' (类型: {type(build_time)})")
        
        # 查找对应的构建记录
        for build in self.builds:
            # self.log_message(f"比较构建记录: '{build['app_name']}' - '{build['build_time']}' (类型: {type(build['build_time'])})")
            
            # 处理时间格式差异：移除下划线进行比较
            stored_time = build['build_time'].replace('_', '')
            selected_time = build_time.replace('_', '')
            
            # self.log_message(f"格式化后比较: '{stored_time}' vs '{selected_time}'")
            # self.log_message(f"app_name匹配: {build['app_name'] == app_name}, build_time匹配: {stored_time == selected_time}")
            
            if build['app_name'] == app_name and stored_time == selected_time:
                self.log_message(f"找到匹配的构建记录: {build}")
                self.show_build_structure(build)
                return
        
        self.log_message("未找到匹配的构建记录")
    
    def generate_callback(self):
        """根据配置自动生成登录回调方法"""
        try:
            # 获取配置信息
            login_url = self.login_url_var.get().strip()
            request_method = self.request_method_var.get().strip()
            content_type = self.content_type_var.get().strip()
            request_params = self.request_params_text.get('1.0', tk.END).strip()
            token_path = self.token_path_var.get().strip()
            
            if not login_url:
                messagebox.showerror("错误", "请输入登录接口地址")
                return
            
            if not token_path:
                messagebox.showerror("错误", "请输入Token路径")
                return
            
            # 生成JavaScript回调方法
            callback_code = self._generate_callback_code(login_url, request_method, content_type, request_params, token_path)
            
            # 更新回调方法文本框
            self.callback_text.delete('1.0', tk.END)
            self.callback_text.insert('1.0', callback_code)
            
            messagebox.showinfo("成功", "回调方法已自动生成！")
            
        except Exception as e:
            messagebox.showerror("错误", f"生成回调方法失败: {str(e)}")
    
    def _generate_callback_code(self, login_url, request_method, content_type, request_params, token_path):
        """生成JavaScript回调方法代码"""
        # 解析Token路径
        token_access_code = self._generate_token_access_code(token_path)
        
        # 处理请求参数
        if content_type == "application/json":
            # JSON格式
            try:
                # 替换模板变量
                params_with_vars = request_params.replace('"{{username}}"', 'username').replace('"{{password}}"', 'password')
                body_code = f"JSON.stringify({params_with_vars})"
                content_type_header = "application/json"
            except:
                body_code = "JSON.stringify({username: username, password: password})"
                content_type_header = "application/json"
        elif content_type == "application/x-www-form-urlencoded":
            # 表单格式
            body_code = "new URLSearchParams({username: username, password: password}).toString()"
            content_type_header = "application/x-www-form-urlencoded"
        else:
            # 默认JSON格式
            body_code = "JSON.stringify({username: username, password: password})"
            content_type_header = "application/json"
        
        # 处理登录URL - 如果是完整URL则直接使用，否则与baseUrl拼接
        if login_url.startswith('http://') or login_url.startswith('https://'):
            url_code = f"'{login_url}'"
        else:
            url_code = f"window.location.origin + '{login_url}'"
        
        # 生成完整的回调方法
        callback_template = f"""// 自动生成的登录回调方法
// 接口地址: {login_url}
// 请求方法: {request_method}
// Content-Type: {content_type}
// Token路径: {token_path}
function getAuthToken(username, password) {{
    console.log('=== 开始登录请求 ===');
    console.log('用户名:', username);
    console.log('密码长度:', password ? password.length : 0);
    
    try {{
        // 构建完整的登录URL
        const loginUrl = {url_code};
        console.log('登录URL:', loginUrl);
        
        // 构建请求体
        const requestBody = {body_code};
        console.log('请求体:', requestBody);
        
        // 发送登录请求
        console.log('发送 {request_method} 请求...');
        const xhr = new XMLHttpRequest();
        xhr.open('{request_method}', loginUrl, false); // 同步请求
        xhr.setRequestHeader('Content-Type', '{content_type_header}');
        
        xhr.send(requestBody);
        
        console.log('响应状态码:', xhr.status);
        console.log('响应文本:', xhr.responseText);
        
        if (xhr.status === 200) {{
            const response = JSON.parse(xhr.responseText);
            console.log('解析后的响应:', response);
            
            // 根据配置的路径提取token
            const token = {token_access_code};
            console.log('提取的token:', token);
            
            if (token) {{
                console.log('=== 登录成功 ===');
                return {{
                    token: token,
                    success: true
                }};
            }} else {{
                console.error('未找到token，路径:', '{token_path}');
                console.error('响应结构:', JSON.stringify(response, null, 2));
                return {{
                    token: null,
                    success: false,
                    error: '未找到token'
                }};
            }}
        }} else {{
            console.error('登录失败，状态码:', xhr.status);
            console.error('响应内容:', xhr.responseText);
            return {{
                token: null,
                success: false,
                error: '登录失败: ' + xhr.status
            }};
        }}
    }} catch (error) {{
        console.error('登录请求异常:', error);
        console.error('错误堆栈:', error.stack);
        return {{
            token: null,
            success: false,
            error: '请求异常: ' + error.message
        }};
    }}
}}"""
        
        return callback_template
    
    def _generate_token_access_code(self, token_path):
        """根据Token路径生成JavaScript访问代码"""
        if not token_path:
            return "response"
        
        # 分割路径
        path_parts = token_path.split('.')
        
        # 生成访问代码
        access_code = "response"
        for part in path_parts:
            if part.strip():
                access_code += f"['{part.strip()}']"
        
        return access_code
    
    def start_js_base(self):
        """启动JS底座"""
        if not WEBVIEW_AVAILABLE:
            messagebox.showerror("错误", "JS底座功能不可用，请安装依赖:\npip install pywebview requests")
            return
        
        remote_url = self.remote_url_var.get().strip()
        remote_username = self.remote_username_var.get().strip()
        remote_password = self.remote_password_var.get().strip()
        callback_method = self.callback_text.get('1.0', tk.END).strip()
        
        if not remote_url:
            messagebox.showerror("错误", "请输入远程地址")
            return
        
        if not callback_method:
            messagebox.showerror("错误", "请输入回调方法")
            return
        
        self.log_message("正在启动JS底座...")
        
        # 直接在主线程中启动JS底座
        self._start_js_base_worker(remote_url, remote_username, remote_password, callback_method)
    
    def _start_js_base_worker(self, remote_url, username, password, callback_method):
        """JS底座工作线程"""
        try:
            # 清理之前的临时文件
            self._cleanup_js_base_temp_files()
            
            # 创建HTML页面
            html_content = self._create_js_base_html(remote_url, username, password, callback_method)
            
            # 创建临时HTML文件
            self.js_base_temp_dir = tempfile.mkdtemp()
            html_file = os.path.join(self.js_base_temp_dir, 'js_base.html')
            
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.log_message(f"JS底座已启动，正在加载: {remote_url}")
            
            # 启动webview（启用调试模式）
            webview.create_window('JS底座 - 远程站点免登录', html_file, width=1200, height=800)
            webview.start(debug=True)
            
        except Exception as e:
            self.log_message(f"JS底座启动失败: {str(e)}")
        finally:
            # webview关闭后清理临时文件
            self._cleanup_js_base_temp_files()
    
    def _cleanup_js_base_temp_files(self):
        """清理JS底座临时文件"""
        if self.js_base_temp_dir and os.path.exists(self.js_base_temp_dir):
            try:
                shutil.rmtree(self.js_base_temp_dir)
                self.js_base_temp_dir = None
            except Exception as e:
                self.log_message(f"清理临时文件失败: {str(e)}")
    
    def _create_js_base_html(self, remote_url, username, password, callback_method):
        """创建JS底座HTML页面"""
        html_template = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JS底座 - 远程站点免登录</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
        }}
        .header {{
            background: #2c3e50;
            color: white;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .status {{
            padding: 5px 10px;
            border-radius: 3px;
            font-size: 12px;
        }}
        .status.loading {{
            background: #f39c12;
        }}
        .status.success {{
            background: #27ae60;
        }}
        .status.error {{
            background: #e74c3c;
        }}
        #remote-frame {{
            width: 100%;
            height: calc(100vh - 60px);
            border: none;
        }}
        .loading {{
            text-align: center;
            padding: 50px;
            font-size: 18px;
            color: #7f8c8d;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h3>🌐 JS底座 - {remote_url}</h3>
        <div style="display: flex; align-items: center; gap: 10px;">
            <button id="login-btn" onclick="manualLogin()" style="
                background: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 12px;
            ">🔑 手动登录</button>
            <div id="status" class="status loading">等待手动登录...</div>
        </div>
    </div>
    
    <div id="loading" class="loading">
        <p>正在获取访问令牌并加载远程站点...</p>
        <p>目标地址: {remote_url}</p>
    </div>
    
    <iframe id="remote-frame" style="display: none;"></iframe>
    
    <script>
        // 用户提供的回调方法
        {callback_method}
        
        // 主要逻辑
        async function initializeJSBase() {{
            const statusEl = document.getElementById('status');
            const loadingEl = document.getElementById('loading');
            const frameEl = document.getElementById('remote-frame');
            
            try {{
                // 检查是否有有效的回调方法
                if (typeof getAuthToken === 'function') {{
                    statusEl.textContent = '正在获取访问令牌...';
                    statusEl.className = 'status loading';
                    
                    // 调用用户定义的回调方法获取token
                    const authResult = await getAuthToken('{username}', '{password}');
                    
                    if (!authResult || !authResult.success) {{
                        throw new Error('获取访问令牌失败: ' + (authResult?.message || '未知错误'));
                    }}
                    
                    const token = authResult.token;
                    console.log('获取到访问令牌:', token);
                    
                    statusEl.textContent = '正在加载远程站点...';
                    
                    // 构建带token的URL
                    const targetUrl = buildAuthenticatedUrl('{remote_url}', token);
                    frameEl.src = targetUrl;
                }} else {{
                    // 没有回调方法，直接加载目标网站（测试模式）
                    console.log('未找到getAuthToken方法，直接加载目标网站');
                    statusEl.textContent = '直接加载模式...';
                    statusEl.className = 'status loading';
                    frameEl.src = '{remote_url}';
                }}
                
                frameEl.onload = function() {{
                    statusEl.textContent = '加载完成';
                    statusEl.className = 'status success';
                    loadingEl.style.display = 'none';
                    frameEl.style.display = 'block';
                    
                    // 重新启用登录按钮
                    const loginBtn = document.getElementById('login-btn');
                    loginBtn.disabled = false;
                    loginBtn.textContent = '🔄 重新登录';
                }};
                
                frameEl.onerror = function() {{
                    throw new Error('远程站点加载失败');
                }};
                
            }} catch (error) {{
                console.error('JS底座初始化失败:', error);
                statusEl.textContent = '加载失败: ' + error.message;
                statusEl.className = 'status error';
                loadingEl.innerHTML = `
                    <p style="color: #e74c3c;">❌ 加载失败</p>
                    <p>错误信息: ${{error.message}}</p>
                    <p>请检查回调方法实现和网络连接</p>
                    <p>如果没有实现getAuthToken方法，将尝试直接加载目标网站</p>
                `;
                
                // 重新启用登录按钮
                const loginBtn = document.getElementById('login-btn');
                loginBtn.disabled = false;
                loginBtn.textContent = '🔑 重试登录';
            }}
        }}
        
        // 构建带认证信息的URL
        function buildAuthenticatedUrl(baseUrl, token) {{
            const url = new URL(baseUrl);
            // 可以根据需要调整token的传递方式
            // 方式1: 作为查询参数
            url.searchParams.set('token', token);
            // 方式2: 作为hash参数
            // url.hash = 'token=' + token;
            return url.toString();
        }}
        
        // 手动登录函数
         function manualLogin() {{
             console.log('=== 手动触发登录流程 ===');
             console.log('提示：请查看控制台获取详细日志');
             
             const loginBtn = document.getElementById('login-btn');
             loginBtn.disabled = true;
             loginBtn.textContent = '登录中...';
             
             initializeJSBase();
         }}
         
         // 页面加载完成后准备就绪
         document.addEventListener('DOMContentLoaded', function() {{
             console.log('=== JS底座页面已加载 ===');
             console.log('提示：请点击顶部的"手动登录"按钮开始登录流程');
             console.log('或者打开开发者工具控制台查看详细日志');
         }});
    </script>
</body>
</html>
        """
        return html_template
    
    def on_build_double_click(self, event):
        """构建双击事件处理 - 打开访问地址"""
        build = self.get_selected_build()
        if not build:
            return
        
        # 检查是否有运行中的容器
        if 'container_name' in build:
            status = get_container_status(build['container_name'])
            if status and status.get('running'):
                test_url = build.get('test_url', '')
                if test_url:
                    import webbrowser
                    try:
                        webbrowser.open(test_url)
                        self.log_message(f"已打开访问地址: {test_url}")
                    except Exception as e:
                        self.log_message(f"打开访问地址失败: {e}")
                        messagebox.showerror("错误", f"无法打开访问地址: {e}")
                else:
                    messagebox.showwarning("警告", "该构建没有可用的访问地址")
            else:
                messagebox.showwarning("警告", "该构建的容器未运行，请先启动本地测试")
        else:
            messagebox.showwarning("警告", "该构建没有运行中的容器")
    
    def run(self):
        """运行GUI"""
        self.root.mainloop()

# 命令行接口
@click.group()
def cli():
    """WEB应用容器发布工具"""
    load_config()

@cli.command()
@click.option('--gui', is_flag=True, help='启动图形界面')
def start(gui):
    """启动应用"""
    if gui and GUI_AVAILABLE:
        app = PublisherGUI()
        app.run()
    elif gui and not GUI_AVAILABLE:
        click.echo("❌ GUI模式不可用，请安装tkinter")
        sys.exit(1)
    else:
        click.echo("使用 --gui 参数启动图形界面，或使用其他命令")
        click.echo("运行 'python app.py --help' 查看所有命令")

@cli.command()
@click.argument('dist_file')
@click.argument('app_name')
@click.argument('version')
def publish(dist_file, app_name, version):
    """命令行发布应用"""
    if not os.path.exists(dist_file):
        click.echo(f"❌ 错误: 文件 {dist_file} 不存在")
        sys.exit(1)
    
    if not CONFIG['DOCKERHUB_USERNAME'] or not CONFIG['DOCKERHUB_TOKEN']:
        click.echo("❌ 错误: 请先配置DockerHub用户名和Token")
        click.echo("运行 'python app.py config' 查看配置方法")
        sys.exit(1)
    
    click.echo(f"🚀 发布应用: {app_name} v{version}")
    click.echo(f"📁 源文件: {dist_file}")
    
    success, message = build_and_push_image(app_name, version, dist_file)
    
    if success:
        click.echo(f"✅ {message}")
        click.echo(f"🐳 镜像地址: {CONFIG['DOCKERHUB_USERNAME']}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:{version}")
    else:
        click.echo(f"❌ {message}")
        sys.exit(1)

@cli.command()
def config():
    """配置管理"""
    click.echo("📋 当前配置:")
    click.echo(f"DockerHub用户名: {CONFIG['DOCKERHUB_USERNAME'] or '未设置'}")
    click.echo(f"DockerHub Token: {'已设置' if CONFIG['DOCKERHUB_TOKEN'] else '未设置'}")
    click.echo(f"基础镜像名: {CONFIG['BASE_IMAGE_NAME']}")
    click.echo(f"配置文件: {CONFIG['CONFIG_FILE']}")
    click.echo("")
    click.echo("🔧 环境变量设置:")
    click.echo("export DOCKERHUB_USERNAME=your_username")
    click.echo("export DOCKERHUB_TOKEN=your_token")
    click.echo("")
    click.echo("或者运行 'python app.py start --gui' 使用图形界面配置")

@cli.command()
@click.argument('app_name')
@click.option('--port', default=3000, help='端口号')
def template(app_name, port):
    """生成docker-compose模板"""
    load_config()  # 确保加载最新配置
    service_prefix = CONFIG.get('SERVICE_PREFIX', 'hzxy')
    template_content = f'''services:
  {service_prefix}-{app_name}:
    image: {CONFIG['DOCKERHUB_USERNAME'] or 'your_dockerhub_username'}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:latest
    container_name: {service_prefix}-{app_name}
    ports:
      - "{port}:80"
    restart: unless-stopped
    networks:
      - {service_prefix}-network

networks:
  {service_prefix}-network:
    driver: bridge
'''
    
    filename = f"docker-compose-{app_name}.yml"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(template_content)
    
    click.echo(f"✅ docker-compose模板已生成: {filename}")
    click.echo(f"🚀 使用方法: docker compose -f {filename} up -d")

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # 如果没有参数，尝试启动GUI
        if GUI_AVAILABLE:
            app = PublisherGUI()
            app.run()
        else:
            print("GUI模式不可用，请使用命令行模式")
            print("运行 'python app.py --help' 查看帮助")
    else:
        # 有参数时使用命令行模式
        cli()