# 作用：只信任 Nginx 写入的客户端信息，丢弃外部伪造的代理头。
proxy_pass http://api:8001;
proxy_http_version 1.1;
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_connect_timeout 3s;
proxy_send_timeout 10s;
proxy_read_timeout 10s;
proxy_request_buffering on;
