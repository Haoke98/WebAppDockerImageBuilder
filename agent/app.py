#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HZXY WEB应用容器发布Agent
开发环境专用工具，用于构建前端应用容器镜像并发布到DockerHub
支持GUI界面和命令行两种使用方式
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
import subprocess
import threading
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

def run_command(cmd, cwd=None, callback=None):
    """执行命令并返回结果"""
    try:
        if callback:
            # 实时输出模式
            process = subprocess.Popen(
                cmd, shell=True, cwd=cwd, 
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
            result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
            return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, '', str(e)

def create_dockerfile(app_name, version):
    """创建Dockerfile"""
    dockerfile_content = f'''FROM nginx:alpine

# 设置工作目录
WORKDIR /usr/share/nginx/html

# 删除默认的nginx页面
RUN rm -rf /usr/share/nginx/html/*

# 复制应用文件
COPY dist.zip /tmp/dist.zip

# 解压应用文件
RUN cd /tmp && unzip dist.zip && \
    if [ -d "dist" ]; then cp -r dist/* /usr/share/nginx/html/; \
    else cp -r * /usr/share/nginx/html/; fi && \
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

def build_and_push_image(app_name, version, dist_file_path, callback=None):
    """构建并推送Docker镜像"""
    # 首先检查Docker是否可用
    docker_cmd = find_docker_command()
    if not docker_cmd:
        error_msg = "❌ 错误: 未找到Docker命令，请确保Docker Desktop已安装并运行"
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
        image_tag = f"{CONFIG['DOCKERHUB_USERNAME']}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:{version}"
        latest_tag = f"{CONFIG['DOCKERHUB_USERNAME']}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:latest"
        
        log(f"构建镜像: {image_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} build -t {image_tag} -t {latest_tag} .", 
            cwd=build_dir, 
            callback=log if callback else None
        )
        
        if not success:
            return False, f"构建失败: {stderr}"
        
        # 登录DockerHub
        if CONFIG['DOCKERHUB_TOKEN']:
            log("登录DockerHub...")
            success, _, stderr = run_command(
                f"echo {CONFIG['DOCKERHUB_TOKEN']} | {docker_cmd} login -u {CONFIG['DOCKERHUB_USERNAME']} --password-stdin"
            )
            if not success:
                return False, f"DockerHub登录失败: {stderr}"
        
        # 推送镜像
        log(f"推送镜像: {image_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} push {image_tag}", 
            callback=log if callback else None
        )
        if not success:
            return False, f"推送失败: {stderr}"
        
        log(f"推送镜像: {latest_tag}")
        success, stdout, stderr = run_command(
            f"{docker_cmd} push {latest_tag}", 
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
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # 设置样式
        style = ttk.Style()
        style.theme_use('clam')
        
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        """设置UI界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="🚀 HZXY WEB应用容器发布工具", font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # DockerHub配置
        config_frame = ttk.LabelFrame(main_frame, text="DockerHub配置", padding="10")
        config_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(config_frame, text="用户名:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.username_var = tk.StringVar()
        ttk.Entry(config_frame, textvariable=self.username_var).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        ttk.Label(config_frame, text="Token:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.token_var = tk.StringVar()
        token_entry = ttk.Entry(config_frame, textvariable=self.token_var, show="*")
        token_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        
        ttk.Button(config_frame, text="保存配置", command=self.save_settings).grid(row=0, column=2, rowspan=2)
        
        # 应用信息
        app_frame = ttk.LabelFrame(main_frame, text="应用信息", padding="10")
        app_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        app_frame.columnconfigure(1, weight=1)
        
        ttk.Label(app_frame, text="应用名称:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.app_name_var = tk.StringVar()
        app_entry = ttk.Entry(app_frame, textvariable=self.app_name_var)
        app_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        app_entry.insert(0, "例如: ai-zhaoshang")
        app_entry.bind('<FocusIn>', lambda e: app_entry.delete(0, tk.END) if app_entry.get() == "例如: ai-zhaoshang" else None)
        
        ttk.Label(app_frame, text="版本号:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.version_var = tk.StringVar()
        version_entry = ttk.Entry(app_frame, textvariable=self.version_var)
        version_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 0))
        version_entry.insert(0, "例如: v1.0.0")
        version_entry.bind('<FocusIn>', lambda e: version_entry.delete(0, tk.END) if version_entry.get() == "例如: v1.0.0" else None)
        
        # 文件选择
        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="10")
        file_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        file_frame.columnconfigure(1, weight=1)
        
        ttk.Label(file_frame, text="dist.zip文件:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.file_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_path_var, state="readonly").grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Button(file_frame, text="选择文件", command=self.select_file).grid(row=0, column=2)
        
        # 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(0, 10))
        
        self.publish_btn = ttk.Button(button_frame, text="🚀 构建并发布", command=self.start_publish, style='Accent.TButton')
        self.publish_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(button_frame, text="📋 生成docker-compose模板", command=self.generate_compose_template).pack(side=tk.LEFT)
        
        # 日志输出
        log_frame = ttk.LabelFrame(main_frame, text="构建日志", padding="10")
        log_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 清空日志按钮
        ttk.Button(log_frame, text="清空日志", command=self.clear_log).grid(row=1, column=0, sticky=tk.E, pady=(5, 0))
    
    def log_message(self, message):
        """添加日志消息"""
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
    
    def start_publish(self):
        """开始发布（在新线程中）"""
        app_name = self.app_name_var.get().strip()
        version = self.version_var.get().strip()
        file_path = self.file_path_var.get().strip()
        
        if not all([app_name, version, file_path]):
            messagebox.showerror("错误", "请填写所有必要信息")
            return
        
        if not os.path.exists(file_path):
            messagebox.showerror("错误", "文件不存在")
            return
        
        if not CONFIG['DOCKERHUB_USERNAME'] or not CONFIG['DOCKERHUB_TOKEN']:
            messagebox.showerror("错误", "请先配置DockerHub用户名和Token")
            return
        
        # 禁用按钮
        self.publish_btn.config(state=tk.DISABLED, text="发布中...")
        
        # 在新线程中执行
        def publish_thread():
            try:
                success, message = build_and_push_image(app_name, version, file_path, self.log_message)
                
                # 在主线程中更新UI
                self.root.after(0, lambda: self.publish_complete(success, message))
            except Exception as e:
                self.root.after(0, lambda: self.publish_complete(False, str(e)))
        
        threading.Thread(target=publish_thread, daemon=True).start()
    
    def publish_complete(self, success, message):
        """发布完成回调"""
        self.publish_btn.config(state=tk.NORMAL, text="🚀 构建并发布")
        
        if success:
            messagebox.showinfo("成功", message)
        else:
            messagebox.showerror("失败", message)
    
    def generate_compose_template(self):
        """生成docker-compose模板"""
        app_name = self.app_name_var.get().strip()
        if not app_name:
            messagebox.showerror("错误", "请先输入应用名称")
            return
        
        template = f'''services:
  hzxy-{app_name}:
    image: {CONFIG['DOCKERHUB_USERNAME'] or 'your_dockerhub_username'}/{CONFIG['BASE_IMAGE_NAME']}-{app_name}:latest
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
        
        # 保存到文件
        file_path = filedialog.asksaveasfilename(
            title="保存docker-compose模板",
            defaultextension=".yml",
            filetypes=[("YAML文件", "*.yml"), ("所有文件", "*.*")],
            initialvalue=f"docker-compose-{app_name}.yml"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(template)
                self.log_message(f"docker-compose模板已保存到: {file_path}")
                messagebox.showinfo("成功", f"模板已保存到: {file_path}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")
    
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