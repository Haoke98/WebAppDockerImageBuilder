#!/bin/bash

# HZXY WEB应用容器发布Agent启动脚本

set -e

echo "🚀 HZXY WEB应用容器发布Agent"
echo "================================"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到Python3，请先安装Python3"
    exit 1
fi

# 检查Docker环境
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: 未找到Docker，请先安装Docker"
    exit 1
fi

# 检查Docker是否运行
if ! docker info &> /dev/null; then
    echo "❌ 错误: Docker未运行，请启动Docker"
    exit 1
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "📦 创建Python虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "📥 安装依赖包..."
pip install -r requirements.txt

# 检查环境变量
echo "🔍 检查配置..."
if [ -z "$DOCKERHUB_USERNAME" ]; then
    echo "⚠️  警告: 未设置DOCKERHUB_USERNAME环境变量"
    echo "   请设置: export DOCKERHUB_USERNAME=your_username"
fi

if [ -z "$DOCKERHUB_TOKEN" ]; then
    echo "⚠️  警告: 未设置DOCKERHUB_TOKEN环境变量"
    echo "   请设置: export DOCKERHUB_TOKEN=your_token"
fi

# 创建必要目录
mkdir -p uploads builds

echo ""
echo "✅ 环境准备完成！"
echo ""
echo "🌐 启动Web服务: python app.py"
echo "💻 命令行帮助: python app.py --help"
echo "📖 查看配置: python app.py config"
echo ""
echo "Web界面将在 http://localhost:5000 启动"
echo ""

# 如果有参数，直接执行
if [ $# -gt 0 ]; then
    python app.py "$@"
else
    # 否则启动Web服务
    python app.py
fi