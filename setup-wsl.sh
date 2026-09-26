#!/bin/bash
set -e
apt-get update -qq
apt-get install -y --no-install-recommends default-jre-headless php-cli ruby python3
phar_ini=$(php -r 'echo php_ini_loaded_file();')
if ! grep -q "phar.readonly=0" "$phar_ini" 2>/dev/null; then
    echo "phar.readonly=0" >> "$phar_ini"
fi
echo "[+] Versions installed:"
java -version 2>&1 | head -1
php --version 2>&1 | head -1
ruby --version
python3 --version
