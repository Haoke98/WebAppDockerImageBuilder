# 使用官方nginx镜像作为基础镜像
FROM nginx:alpine

# 设置工作目录
WORKDIR /usr/share/nginx/html

# 删除nginx默认的静态文件
RUN rm -rf /usr/share/nginx/html/*

# 复制dist.zip文件到容器中
COPY dist.zip /tmp/dist.zip

# 安装unzip并解压dist.zip文件到nginx静态文件目录
RUN apk add --no-cache unzip && \
    unzip /tmp/dist.zip -d /usr/share/nginx/html && \
    # 如果解压后有dist文件夹，将其内容移动到根目录
    if [ -d "/usr/share/nginx/html/dist" ]; then \
        mv /usr/share/nginx/html/dist/* /usr/share/nginx/html/ && \
        rmdir /usr/share/nginx/html/dist; \
    fi && \
    # 清理临时文件
    rm /tmp/dist.zip && \
    apk del unzip

# 创建自定义nginx配置文件
RUN echo 'server {' > /etc/nginx/conf.d/default.conf && \
    echo '    listen 80;' >> /etc/nginx/conf.d/default.conf && \
    echo '    server_name localhost;' >> /etc/nginx/conf.d/default.conf && \
    echo '    root /usr/share/nginx/html;' >> /etc/nginx/conf.d/default.conf && \
    echo '    index index.html index.htm;' >> /etc/nginx/conf.d/default.conf && \
    echo '    ' >> /etc/nginx/conf.d/default.conf && \
    echo '    # 处理单页应用路由' >> /etc/nginx/conf.d/default.conf && \
    echo '    location / {' >> /etc/nginx/conf.d/default.conf && \
    echo '        try_files $uri $uri/ /index.html;' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '    ' >> /etc/nginx/conf.d/default.conf && \
    echo '    # 静态资源缓存配置' >> /etc/nginx/conf.d/default.conf && \
    echo '    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {' >> /etc/nginx/conf.d/default.conf && \
    echo '        expires 1y;' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "public, immutable";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '}' >> /etc/nginx/conf.d/default.conf

# 暴露80端口
EXPOSE 80

# 启动nginx
CMD ["nginx", "-g", "daemon off;"]