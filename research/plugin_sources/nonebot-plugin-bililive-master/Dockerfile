FROM mcr.microsoft.com/playwright/python:v1.22.0-focal

LABEL maintainer="https://github.com/Akiyy-dev/nonebot-plugin-bililive"

EXPOSE 8080

RUN pip install nonebot-plugin-bililive -i https://mirrors.aliyun.com/pypi/simple/

WORKDIR /bililive

COPY .env.prod /bililive/.env.prod

ENV TZ=Asia/Shanghai LANG=zh_CN.UTF-8 HOST=0.0.0.0

CMD ["bililive", "run"]