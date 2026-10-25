# Independent PPT task API; do not add other application routes here.
location ^~ /ppt-service/ {
    client_max_body_size 20m;
    proxy_pass http://unix:/opt/xinghe-ppt-cloud/socket/api.sock:/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Authorization $http_authorization;
    proxy_connect_timeout 5s;
    proxy_send_timeout 30s;
    proxy_read_timeout 60s;
    proxy_redirect off;
    proxy_buffering off;
}
