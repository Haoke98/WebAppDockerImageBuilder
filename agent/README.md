# HZXY WEB应用容器发布Agent

开发环境专用工具，用于构建前端应用容器镜像并发布到DockerHub。支持GUI界面和命令行两种使用方式。

## 功能特性

- 🖥️ **跨平台支持**: Windows、macOS、Linux
- 🎨 **GUI界面**: 基于tkinter的友好图形界面
- 💻 **命令行工具**: 支持脚本自动化
- 🐳 **Docker集成**: 自动构建和推送镜像到DockerHub
- 📋 **模板生成**: 自动生成docker-compose部署模板
- ⚙️ **配置管理**: 支持配置文件和环境变量

## 安装要求

### 系统要求
- Python 3.7+
- Docker Desktop (已安装并运行)
- DockerHub账号和访问令牌

### Python依赖
```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 环境配置

设置DockerHub凭据（二选一）：

**方法一：环境变量**
```bash
export DOCKERHUB_USERNAME=your_username
export DOCKERHUB_TOKEN=your_token
```

**方法二：GUI界面配置**
```bash
python app.py start --gui
```

### 2. 启动方式

**GUI模式（推荐）**
```bash
# 直接运行（默认启动GUI）
python app.py

# 或明确指定GUI模式
python app.py start --gui

# 使用便捷脚本
./start.sh
```

**命令行模式**
```bash
# 发布应用
python app.py publish ai-zhaoshang 1.0.0 /path/to/dist.zip

# 查看配置
python app.py config

# 生成docker-compose模板
python app.py template ai-zhaoshang --port 3000

# 查看帮助
python app.py --help
```

## 使用流程

### GUI模式使用流程

1. **配置DockerHub**
   - 填写DockerHub用户名和访问令牌
   - 点击"保存配置"

2. **填写应用信息**
   - 应用名称：如 `ai-zhaoshang`
   - 版本号：如 `1.0.0`

3. **选择文件**
   - 点击"选择文件"按钮
   - 选择前端团队提供的 `dist.zip` 文件

4. **构建发布**
   - 点击"🚀 构建并发布"按钮
   - 查看实时构建日志
   - 等待发布完成

5. **生成部署模板**
   - 点击"📋 生成docker-compose模板"
   - 保存模板文件用于AI盒子部署

### 命令行模式使用流程

```bash
# 1. 检查配置
python app.py config

# 2. 发布应用
python app.py publish ai-zhaoshang 1.0.0 ./ai-zhaoshang-dist.zip

# 3. 生成部署模板
python app.py template ai-zhaoshang --port 3000
```

## 镜像命名规范

生成的Docker镜像遵循以下命名规范：
- 格式：`{DOCKERHUB_USERNAME}/hzxy-webapp-base-{应用名称}:{版本号}`
- 示例：`myuser/hzxy-webapp-base-ai-zhaoshang:1.0.0`
- 同时会创建 `latest` 标签

## 部署模板

工具会自动生成适用于AI盒子的docker-compose模板：

```yaml
services:
  hzxy-ai-zhaoshang:
    image: myuser/hzxy-webapp-base-ai-zhaoshang:latest
    container_name: hzxy-ai-zhaoshang
    ports:
      - "3000:80"
    restart: unless-stopped
    networks:
      - hzxy-network

networks:
  hzxy-network:
    driver: bridge
```

## 文件结构

```
agent/
├── app.py              # 主程序文件
├── requirements.txt    # Python依赖
├── start.sh           # 启动脚本
├── README.md          # 说明文档
├── builds/            # 构建临时目录
└── ~/.hzxy-agent-config.json  # 配置文件
```

## 配置文件

配置文件位置：`~/.hzxy-agent-config.json`

```json
{
  "DOCKERHUB_USERNAME": "your_username",
  "BASE_IMAGE_NAME": "hzxy-webapp-base"
}
```

## 故障排除

### 常见问题

**1. GUI模式无法启动**
```
警告: 无法导入tkinter，GUI模式不可用
```
解决方案：
- macOS: `brew install python-tk`
- Ubuntu: `sudo apt-get install python3-tk`
- Windows: 重新安装Python并勾选tkinter组件

**2. Docker构建失败**
```
Cannot connect to the Docker daemon
```
解决方案：
- 确保Docker Desktop已启动
- 检查Docker服务状态

**3. DockerHub推送失败**
```
denied: requested access to the resource is denied
```
解决方案：
- 检查DockerHub用户名和Token是否正确
- 确保Token有推送权限

### 日志查看

- GUI模式：查看界面底部的"构建日志"区域
- 命令行模式：直接在终端查看输出
- 构建过程中的临时文件在 `builds/` 目录

## 开发说明

### 项目结构
- `PublisherGUI`: GUI界面类
- `build_and_push_image()`: 核心构建发布函数
- `cli`: Click命令行接口
- 配置管理：支持文件和环境变量

### 扩展功能
- 支持多种基础镜像
- 自定义Dockerfile模板
- 批量发布功能
- 发布历史记录

## 许可证

内部工具，仅供HZXY团队使用。