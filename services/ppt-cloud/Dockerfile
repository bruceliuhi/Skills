FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp LANG=C.UTF-8
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=1 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=1 -o Acquire::https::Timeout=30 install -y --no-install-recommends libreoffice-impress poppler-utils fonts-noto-cjk fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir --index-url https://pypi.org/simple python-pptx==1.0.2 XlsxWriter==3.2.9 Pillow==11.3.0 lxml==5.4.0 typing_extensions==4.15.0
COPY engine/ /engine/
COPY app.py limit_exec.py /app/
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ppt && mkdir /data && chown 10001:10001 /data
USER 10001:10001
WORKDIR /app
CMD ["python","-B","/app/app.py"]
