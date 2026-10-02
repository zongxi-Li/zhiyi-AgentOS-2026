#!/bin/sh
set -eu
. "$(dirname "$0")/_common.sh"
"$SCRIPT_DIR/preflight.sh"
[ ! -e "$INSTALL_ROOT/current" ] || fail "deployment already installed; use upgrade.sh"
load_manifest
load_deployment

for archive in "$PACKAGE_ROOT"/images/*.tar.gz; do
  gzip -dc "$archive" | docker load >/dev/null
done
verify_image_arches

home=$(release_home "$RELEASE_VERSION")
[ ! -e "$home" ] || fail "release directory already exists: $home"
mkdir -p "$INSTALL_ROOT/releases"
cp -a "$PACKAGE_ROOT" "$home"
export KINLIN_RELEASE_HOME=$home
compose config --quiet
compose up -d --pull never --no-build --wait postgres redis
# schema mutation 的唯一正式 owner 是 backend 启动期 Flyway（flyway.enabled=true）。
# schema-tool 仅为 MANUAL_TOOL（见 compose.yaml），不得在此自动执行迁移。
compose up -d --pull never --no-build --wait
compose exec -T frontend wget -qO- http://127.0.0.1:8080/health >/dev/null

printf '%s\n' "$KINLIN_DEPLOYMENT_ID" > "$INSTALL_ROOT/deployment-id"
ln -s "$home" "$INSTALL_ROOT/current"
echo "installed Kinlin AI $RELEASE_VERSION for linux/$RELEASE_ARCH"
