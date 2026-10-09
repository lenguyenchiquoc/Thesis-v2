FROM python:3.12-slim

# Java (chay tools/java/ysoserial-all.jar), PHP CLI (chay tools/phpggc/phpggc)
# va Ruby (payloadMutation.py:_mutate_ruby(), goi "ruby -e ..." de sinh Marshal
# payload) la 3 runtime ngoai ma payloadMutation.py shell ra qua subprocess de
# sinh gadget-chain thuc - khong the thay bang thu vien Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        php-cli \
        ruby \
    && rm -rf /var/lib/apt/lists/*

# phpggc can phar.readonly=0 de sinh duoc payload .phar (_mutate_wrapper_phar) -
# giong dung cau hinh trong Dockerfile chinh thuc cua phpggc
# (tools/phpggc/Dockerfile). Tim dung file php.ini dang duoc nap, khong doan
# duong dan cung vi no thay doi theo version PHP cua base image.
RUN echo "phar.readonly=0" >> "$(php -r 'echo php_ini_loaded_file();')"

WORKDIR /app
COPY . .

# Fail fast ngay luc build neu java/php/ruby khong goi duoc, thay vi de nguoi
# dung tu phat hien luc chay (dung dung cac lenh ma payloadMutation.py se goi).
RUN java -version && php -version && ruby --version

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
