proxy_pass http://api;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
# nunca repassar identidade vinda do cliente
proxy_set_header X-User-ID "";
proxy_set_header X-Tenant-ID "";
proxy_set_header X-User-Roles "";
proxy_read_timeout 120s;
