# Dashboard Dockerfile
# Builds the QuantTradingSystem dashboard as a standalone Nginx image
FROM nginx:alpine

# Copy Nginx configuration + remove default conflicting config
COPY nginx.conf /etc/nginx/nginx.conf
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy dashboard static files
COPY *.html *.js *.css *.svg *.json /usr/share/nginx/html/
# 2026-10-16 审计修复：原通配符不含子目录，镜像缺 vendor/ 与 js/ → 页面脚本全 404
COPY vendor/ /usr/share/nginx/html/vendor/
COPY js/     /usr/share/nginx/html/js/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost/index.html || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
