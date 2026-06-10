FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make wget \
    && rm -rf /var/lib/apt/lists/*

# 安装TA-Lib系统库（ta-lib Python包依赖此C库）
RUN wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib \
    && ./configure --prefix=/usr --build=aarch64-unknown-linux-gnu \
    && make \
    && make install \
    && cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
    && ldconfig

# ta-lib Python包需要与numpy 1.x编译（numpy 2.x API不兼容）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple 'numpy==1.26.2' \
    && CFLAGS="-Wno-error=incompatible-pointer-types" pip install --no-cache-dir --no-build-isolation -i https://pypi.tuna.tsinghua.edu.cn/simple 'ta-lib==0.4.28'

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
