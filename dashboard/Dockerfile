# Dashboard Dockerfile
# Builds the QuantTradingSystem dashboard as a standalone Nginx image
FROM nginx:alpine

# Copy Nginx configuration (baked in)
COPY nginx.conf /etc/nginx/nginx.conf

# Copy dashboard static files
COPY *.html *.js *.css /usr/share/nginx/html/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost/index.html || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
