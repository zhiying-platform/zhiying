# 知映 zhiying — 后端镜像（V1.0 产品化）
# 多阶段构建：builder 安装依赖 → runtime 精简运行
# 前端静态文件由 ZHIYING_WEB_DIST 挂载（见 docker-compose.yml），单容器=完整产品
FROM python:3.12-slim AS builder

# 国内网络：使用 PyPI 镜像源（构建参数可覆盖）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# 源码与打包配置（pip install . 需要 pyproject + src）
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime

# 安装产物（包 + console scripts: zhiying / zhiying-api / zhiying-mcp）
COPY --from=builder /install /usr/local

WORKDIR /app

# 数据目录（源视频/转写/帧/摘要）挂载点；默认与 docker-compose 一致
RUN mkdir -p /data
ENV ZHIYING_DATA=/data

# 前端静态目录（compose 挂载 zhiying-web/dist，FastAPI 自动托管；不挂载则纯 API）
ENV ZHIYING_WEB_DIST=/app/web

# 非 root 运行
RUN useradd -m zhiying && chown -R zhiying /data /app
USER zhiying

EXPOSE 8600

# 默认启动 API 服务（含前端托管）；MCP Server 经宿主机 zhiying-mcp.cmd 连 8600
CMD ["python", "-m", "zhiying.api"]
