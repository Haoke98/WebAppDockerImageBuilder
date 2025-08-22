#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JS 插件注入调试服务
提供静态资源服务或反向代理功能，并对 index.html 进行实时 JS 插件注入
"""

import os
import re
import requests
from flask import Flask, request, Response, send_from_directory, abort
from urllib.parse import urljoin, urlparse
import argparse
import logging
from pathlib import Path

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局配置
config = {
    'mode': 'static',  # 'static' 或 'proxy'
    'static_path': None,  # 静态资源目录路径
    'target_url': None,  # 目标站点URL
    'plugin_path': None,  # JS插件文件路径
    'port': 8080,
    'host': '0.0.0.0'
}

def load_plugin_content():
    """加载JS插件内容"""
    if not config['plugin_path'] or not os.path.exists(config['plugin_path']):
        logger.error(f"插件文件不存在: {config['plugin_path']}")
        return None
    
    try:
        with open(config['plugin_path'], 'r', encoding='utf-8') as f:
            content = f.read()
            logger.info(f"成功加载插件文件: {config['plugin_path']}")
            return content
    except Exception as e:
        logger.error(f"读取插件文件失败: {e}")
        return None

def inject_plugin_to_html(html_content):
    """向HTML内容注入JS插件"""
    plugin_content = load_plugin_content()
    if not plugin_content:
        return html_content
    
    # 创建插件脚本标签
    plugin_script = f'\n<script type="text/javascript">\n{plugin_content}\n</script>\n'
    
    # 尝试在 </head> 标签前注入
    if '</head>' in html_content:
        html_content = html_content.replace('</head>', plugin_script + '</head>')
        logger.info("插件已注入到 </head> 标签前")
    # 如果没有 </head>，尝试在 <body> 标签后注入
    elif '<body' in html_content:
        # 找到 <body> 标签的结束位置
        body_match = re.search(r'<body[^>]*>', html_content, re.IGNORECASE)
        if body_match:
            insert_pos = body_match.end()
            html_content = html_content[:insert_pos] + plugin_script + html_content[insert_pos:]
            logger.info("插件已注入到 <body> 标签后")
    # 如果都没有，在文档开头注入
    else:
        html_content = plugin_script + html_content
        logger.info("插件已注入到文档开头")
    
    return html_content

@app.route('/sdm-plugins/<path:filename>')
def handle_plugin_static(filename):
    """处理插件静态资源请求"""
    plugin_static_path = '/Users/lucius/Projects/WebAppHostingBase/agent/plugins'
    
    if not os.path.exists(plugin_static_path):
        abort(404, "插件目录不存在")
    
    file_path = os.path.join(plugin_static_path, filename)
    
    # 安全检查：防止路径遍历攻击
    if not os.path.abspath(file_path).startswith(os.path.abspath(plugin_static_path)):
        abort(403, "访问被拒绝")
    
    if not os.path.exists(file_path):
        abort(404, "插件文件不存在")
    
    try:
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        return send_from_directory(directory, filename)
    except Exception as e:
        logger.error(f"发送插件文件失败: {e}")
        abort(404, "文件不存在")

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def handle_request(path):
    """处理所有请求"""
    # 如果是插件相关路径，跳过（已由专门的路由处理）
    if path.startswith('sdm-plugins/'):
        abort(404, "路径不存在")
    
    if config['mode'] == 'static':
        return handle_static_request(path)
    elif config['mode'] == 'proxy':
        return handle_proxy_request(path)
    else:
        abort(500, "未知的服务模式")

def handle_static_request(path):
    """处理静态文件请求"""
    static_path = config['static_path']
    
    if not static_path or not os.path.exists(static_path):
        abort(404, "静态资源目录不存在")
    
    # 如果路径为空或以 / 结尾，默认查找 index.html
    if not path or path.endswith('/'):
        path = os.path.join(path, 'index.html')
    
    file_path = os.path.join(static_path, path)
    
    # 安全检查：防止路径遍历攻击
    if not os.path.abspath(file_path).startswith(os.path.abspath(static_path)):
        abort(403, "访问被拒绝")
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        # 判断是否为静态资源文件（有明确的文件扩展名）
        _, ext = os.path.splitext(path)
        if ext and ext.lower() in ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map', '.json']:
            # 静态资源文件不存在时直接返回404
            abort(404, "文件不存在")
        else:
            # 对于页面路由（无扩展名或html扩展名），回退到 index.html
            index_path = os.path.join(static_path, 'index.html')
            if os.path.exists(index_path):
                file_path = index_path
            else:
                abort(404, "文件不存在")
    
    # 如果是 index.html 文件，进行插件注入
    if os.path.basename(file_path).lower() == 'index.html':
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # 注入插件
            html_content = inject_plugin_to_html(html_content)
            
            return Response(html_content, mimetype='text/html')
        except Exception as e:
            logger.error(f"读取HTML文件失败: {e}")
            abort(500, "读取文件失败")
    
    # 其他文件直接返回
    try:
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        return send_from_directory(directory, filename)
    except Exception as e:
        logger.error(f"发送文件失败: {e}")
        abort(404, "文件不存在")

def handle_proxy_request(path):
    """处理反向代理请求"""
    target_url = config['target_url']
    
    if not target_url:
        abort(500, "目标URL未配置")
    
    # 构建完整的目标URL
    if path:
        full_url = urljoin(target_url.rstrip('/') + '/', path)
    else:
        full_url = target_url
    
    # 添加查询参数
    if request.query_string:
        full_url += '?' + request.query_string.decode('utf-8')
    
    try:
        # 准备请求头
        headers = dict(request.headers)
        # 移除可能导致问题的头部
        headers.pop('Host', None)
        headers.pop('Content-Length', None)
        
        # 发送请求到目标服务器
        if request.method == 'GET':
            resp = requests.get(full_url, headers=headers, stream=True, timeout=30)
        elif request.method == 'POST':
            resp = requests.post(full_url, headers=headers, data=request.get_data(), stream=True, timeout=30)
        elif request.method == 'PUT':
            resp = requests.put(full_url, headers=headers, data=request.get_data(), stream=True, timeout=30)
        elif request.method == 'DELETE':
            resp = requests.delete(full_url, headers=headers, stream=True, timeout=30)
        else:
            resp = requests.request(request.method, full_url, headers=headers, data=request.get_data(), stream=True, timeout=30)
        
        # 检查是否是HTML内容且是index.html
        content_type = resp.headers.get('Content-Type', '').lower()
        is_html = 'text/html' in content_type
        is_index = path == '' or path.endswith('/') or 'index.html' in path.lower()
        
        # 准备响应头
        response_headers = dict(resp.headers)
        # 移除可能导致问题的头部
        response_headers.pop('Content-Encoding', None)
        response_headers.pop('Transfer-Encoding', None)
        response_headers.pop('Content-Length', None)
        
        if is_html and is_index:
            # 对HTML内容进行插件注入
            html_content = resp.text
            html_content = inject_plugin_to_html(html_content)
            
            return Response(html_content, status=resp.status_code, headers=response_headers)
        else:
            # 其他内容直接返回
            return Response(resp.content, status=resp.status_code, headers=response_headers)
    
    except requests.exceptions.RequestException as e:
        logger.error(f"代理请求失败: {e}")
        abort(502, "代理请求失败")
    except Exception as e:
        logger.error(f"处理代理请求时发生错误: {e}")
        abort(500, "服务器内部错误")

@app.route('/health')
def health_check():
    """健康检查接口"""
    return {
        'status': 'ok',
        'mode': config['mode'],
        'plugin_loaded': config['plugin_path'] is not None and os.path.exists(config['plugin_path'])
    }

@app.route('/config')
def get_config():
    """获取当前配置"""
    return {
        'mode': config['mode'],
        'static_path': config['static_path'],
        'target_url': config['target_url'],
        'plugin_path': config['plugin_path'],
        'port': config['port'],
        'host': config['host']
    }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='JS插件注入调试服务')
    parser.add_argument('--mode', choices=['static', 'proxy'], default='static',
                       help='服务模式: static(静态文件服务) 或 proxy(反向代理)')
    parser.add_argument('--static-path', type=str,
                       help='静态资源目录路径 (mode=static时必需)')
    parser.add_argument('--target-url', type=str,
                       help='目标站点URL (mode=proxy时必需)')
    parser.add_argument('--plugin-path', type=str, 
                        default='/Users/lucius/Projects/WebAppHostingBase/agent/plugins/auto-login-plugin.js',
                        help='JS插件文件路径')
    parser.add_argument('--port', type=int, default=8080,
                       help='服务端口号')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='服务主机地址')
    
    args = parser.parse_args()
    
    # 更新配置
    config['mode'] = args.mode
    config['static_path'] = args.static_path
    config['target_url'] = args.target_url
    config['plugin_path'] = args.plugin_path
    config['port'] = args.port
    config['host'] = args.host
    
    # 验证配置
    if config['mode'] == 'static' and not config['static_path']:
        logger.error("静态文件模式需要指定 --static-path 参数")
        return
    
    if config['mode'] == 'proxy' and not config['target_url']:
        logger.error("代理模式需要指定 --target-url 参数")
        return
    
    if config['mode'] == 'static' and not os.path.exists(config['static_path']):
        logger.error(f"静态资源目录不存在: {config['static_path']}")
        return
    
    if not os.path.exists(config['plugin_path']):
        logger.error(f"插件文件不存在: {config['plugin_path']}")
        return
    
    # 打印配置信息
    logger.info("=== JS插件注入调试服务 ===")
    logger.info(f"服务模式: {config['mode']}")
    if config['mode'] == 'static':
        logger.info(f"静态资源目录: {config['static_path']}")
    else:
        logger.info(f"目标站点URL: {config['target_url']}")
    logger.info(f"插件文件: {config['plugin_path']}")
    logger.info(f"服务地址: http://{config['host']}:{config['port']}")
    logger.info("=========================")
    
    # 启动服务
    app.run(host=config['host'], port=config['port'], debug=True)

if __name__ == '__main__':
    main()