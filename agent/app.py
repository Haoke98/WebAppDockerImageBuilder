#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HZXY WEB应用容器发布Agent
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

# 配置
CONFIG = {
    'DOCKERHUB_USERNAME': os.getenv('DOCKERHUB_USERNAME', ''),
    'DOCKERHUB_TOKEN': os.getenv('DOCKERHUB_TOKEN', ''),
    'BASE_IMAGE_NAME': 'hzxy-webapp-base',
    'BUILD_FOLDER': 'builds',
    'CONFIG_FILE': os.path.expanduser('~/.hzxy-agent-config.json')
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
            'BASE_IMAGE_NAME': CONFIG['BASE_IMAGE_NAME']
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

def create_dockerfile(app_name, version):
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
LABEL maintainer="HZXY DevOps Team"

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
        dockerfile_content = create_dockerfile(app_name, build_time)
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
        dockerfile_content = create_dockerfile(app_name, version)
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
        
        ttk.Button(config_frame, text="保存配置", command=self.save_settings).grid(row=0, column=2, rowspan=2)
        
        # 新建构建
        build_frame = ttk.LabelFrame(left_panel, text="新建构建", padding="10")
        build_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
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
        structure_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
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
        left_panel.rowconfigure(2, weight=1)
        
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
        if not self.structure_tree:
            return
            
        try:
            # 清空现有内容
            for item in self.structure_tree.get_children():
                self.structure_tree.delete(item)
            
            # 读取zip文件内容
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                file_list = zip_file.namelist()
                
                # 构建树形结构
                nodes = {}
                
                for file_path in sorted(file_list):
                    parts = file_path.split('/')
                    current_path = ''
                    
                    for i, part in enumerate(parts):
                        if not part:  # 跳过空字符串
                            continue
                            
                        parent_path = current_path
                        current_path = '/'.join(parts[:i+1]) if current_path else part
                        
                        if current_path not in nodes:
                            if parent_path and parent_path in nodes:
                                parent_id = nodes[parent_path]
                            else:
                                parent_id = ''
                            
                            # 判断是文件还是目录
                            is_dir = file_path.endswith('/') or i < len(parts) - 1
                            icon = '📁' if is_dir else '📄'
                            
                            node_id = self.structure_tree.insert(
                                parent_id, 'end', 
                                text=f"{icon} {part}",
                                open=True if i < 2 else False  # 前两层默认展开
                            )
                            nodes[current_path] = node_id
                
                self.log_message(f"已显示zip文件结构: {len(file_list)}个文件")
                
        except Exception as e:
            self.log_message(f"读取zip文件失败: {e}")            
            # 显示错误信息
            self.structure_tree.insert('', 'end', text=f"❌ 读取失败: {str(e)}")
    
    def show_zip_structure(self, zip_path):
        """显示zip文件的目录结构"""
        if not self.structure_tree:
            return
            
        try:
            # 清空现有内容
            for item in self.structure_tree.get_children():
                self.structure_tree.delete(item)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                file_list = zip_file.namelist()
                
                # 构建树形结构
                nodes = {}  # 存储已创建的节点
                
                for file_path in sorted(file_list):
                    if file_path.endswith('/'):
                        continue  # 跳过目录条目
                    
                    parts = file_path.split('/')
                    current_path = ''
                    parent_id = ''
                    
                    for i, part in enumerate(parts):
                        if not part:  # 跳过空部分
                            continue
                            
                        current_path = '/'.join(parts[:i+1]) if current_path else part
                        
                        if current_path not in nodes:
                            # 判断是否为目录
                            is_dir = file_path.endswith('/') or i < len(parts) - 1
                            icon = '📁' if is_dir else '📄'
                            
                            node_id = self.structure_tree.insert(
                                parent_id, 'end', 
                                text=f"{icon} {part}",
                                open=True if i < 2 else False  # 前两层默认展开
                            )
                            nodes[current_path] = node_id
                
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
            self.log_message(f"比较构建记录: '{build['app_name']}' - '{build['build_time']}' (类型: {type(build['build_time'])})")
            
            # 处理时间格式差异：移除下划线进行比较
            stored_time = build['build_time'].replace('_', '')
            selected_time = build_time.replace('_', '')
            
            self.log_message(f"格式化后比较: '{stored_time}' vs '{selected_time}'")
            self.log_message(f"app_name匹配: {build['app_name'] == app_name}, build_time匹配: {stored_time == selected_time}")
            
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
        
        template = f'''services:
  hzxy-{app_name}:
    image: {username}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:{version}
    container_name: hzxy-{app_name}
    ports:
      - "3000:80"
    restart: unless-stopped
    networks:
      - hzxy-network

networks:
  hzxy-network:
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
            self.log_message(f"比较构建记录: '{build['app_name']}' - '{build['build_time']}' (类型: {type(build['build_time'])})")
            
            # 处理时间格式差异：移除下划线进行比较
            stored_time = build['build_time'].replace('_', '')
            selected_time = build_time.replace('_', '')
            
            self.log_message(f"格式化后比较: '{stored_time}' vs '{selected_time}'")
            self.log_message(f"app_name匹配: {build['app_name'] == app_name}, build_time匹配: {stored_time == selected_time}")
            
            if build['app_name'] == app_name and stored_time == selected_time:
                self.log_message(f"找到匹配的构建记录: {build}")
                self.show_build_structure(build)
                return
        
        self.log_message("未找到匹配的构建记录")
    
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
    """HZXY WEB应用容器发布工具"""
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
    template_content = f'''services:
  hzxy-{app_name}:
    image: {CONFIG['DOCKERHUB_USERNAME'] or 'your_dockerhub_username'}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:latest
    container_name: hzxy-{app_name}
    ports:
      - "{port}:80"
    restart: unless-stopped
    networks:
      - hzxy-network

networks:
  hzxy-network:
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