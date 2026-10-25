#!/bin/sh
set -eu
name=xinghe-ppt-cloud
image=xinghe-ppt-cloud:1.1.0
root=/opt/xinghe-ppt-cloud
if docker container inspect "$name" >/dev/null 2>&1; then
  echo '容器已存在，请人工核对后进行版本更新；本脚本不自动替换正在运行的服务。' >&2
  exit 2
fi
mkdir -p "$root/data" "$root/socket"
chown 10001:10001 "$root/data" "$root/socket"
chmod 0700 "$root/data"
chmod 0755 "$root/socket"
# Allow Nginx traversal to the dedicated socket; data remains 0700.
chmod 0711 "$root"
docker run -d --name "$name" --init --restart unless-stopped \
  --network none \
  --memory 1280m --memory-swap 1280m --cpus 1 --pids-limit 128 \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --mount type=bind,src="$root/data",dst=/data \
  --mount type=bind,src="$root/socket",dst=/run/ppt-cloud \
  --env PPT_SOCKET=/run/ppt-cloud/api.sock \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env PPT_PUBLIC_BASE=https://www.tuokexing.net/ppt-service/v1 \
  "$image"
