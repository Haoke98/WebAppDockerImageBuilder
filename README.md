# 前端项目容器化部署

这个项目提供了一个完整的Docker解决方案来部署两个独立的前端应用：AI招商和产业大脑。

## 使用方法

### 1. 准备文件
将前端团队提供的编译好的dist文件放在项目根目录下：
- AI招商应用：`ai-zhaoshang-dist.zip`
- 产业大脑应用：`chanye-danao-dist.zip`

### 2. 使用Docker Compose部署
```bash
# 启动所有服务
docker compose up -d

# 启动单个服务
docker compose up -d hzxy-ai-zhaoshang
docker compose up -d hzxy-chanye-danao
```

### 3. 访问应用
- AI招商应用：`http://localhost:3002`
- 产业大脑应用：`http://localhost:3001`

## 功能特性

- **基于Nginx Alpine**: 使用轻量级的nginx alpine镜像，体积小，性能好
- **自动解压**: 自动解压dist.zip文件并部署到nginx目录
- **SPA支持**: 配置了单页应用路由支持，所有路由都会回退到index.html
- **静态资源缓存**: 对JS、CSS、图片等静态资源配置了1年的缓存策略
- **生产优化**: 删除了不必要的文件和工具，减小镜像体积

## 目录结构
```
.
├── Dockerfile          # Docker构建文件
├── .dockerignore       # Docker忽略文件
├── README.md          # 说明文档
└── dist.zip           # 前端编译文件（需要放置）
```

## 常用Docker Compose命令

```bash
# 查看运行中的容器
docker compose ps

# 停止所有服务
docker compose down

# 停止单个服务
docker compose stop hzxy-ai-zhaoshang
docker compose stop hzxy-chanye-danao

# 重启服务
docker compose restart

# 查看容器日志
docker compose logs hzxy-ai-zhaoshang
docker compose logs hzxy-chanye-danao

# 查看所有服务日志
docker compose logs
```

## 注意事项

1. 确保两个dist文件都在项目根目录：
   - `ai-zhaoshang-dist.zip`（AI招商应用）
   - `chanye-danao-dist.zip`（产业大脑应用）
2. 两个应用使用不同端口：AI招商(3002)，产业大脑(3001)
3. 如果需要修改端口，可以在docker-compose.yml中调整ports配置
4. 如果前端应用有特殊的nginx配置需求，可以修改Dockerfile中的nginx配置部分
5. 可以独立部署单个应用，也可以同时部署两个应用