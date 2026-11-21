#!/bin/sh
set -eu

packaging_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH='' cd -- "$packaging_dir/../.." && pwd)
version='0.1.0~beta1'
output_dir="$project_dir/dist"
package="$output_dir/bitcoin-carteira_${version}_all.deb"
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT
trap 'exit 1' HUP INT TERM

mkdir -p "$staging/DEBIAN" "$staging/usr/bin" "$staging/usr/share/applications" \
    "$staging/usr/share/bitcoin-carteira/assets" "$output_dir"
chmod 0755 "$staging"

cat > "$staging/DEBIAN/control" <<CONTROL
Package: bitcoin-carteira
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: Projeto Carteira Bitcoin
Depends: python3 (>= 3.10), python3-tk, python3-cryptography, python3-mnemonic (>= 0.19)
Description: Carteira Bitcoin desktop para regtest
 Cria carteiras BIP39, acompanha o saldo e assina transações de teste.
 Usa um nó Bitcoin Core regtest instalado separadamente.
CONTROL

for module in addresses app history recovery sending signing watching; do
    install -m 0644 "$project_dir/$module.py" "$staging/usr/share/bitcoin-carteira/"
done
install -m 0644 "$project_dir/assets/logo.png" "$staging/usr/share/bitcoin-carteira/assets/"
install -m 0644 "$packaging_dir/bitcoin-carteira.desktop" "$staging/usr/share/applications/"
install -m 0755 "$packaging_dir/bitcoin-carteira" "$staging/usr/bin/"

dpkg-deb --root-owner-group --build "$staging" "$package"
