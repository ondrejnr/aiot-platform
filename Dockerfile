FROM alpine:3.19
LABEL maintainer="ondrejnr" \
      description="AIoT Platform - Full K8s Cluster Backup" \
      version="2026-03-10"
RUN apk add --no-cache kubectl bash
COPY . /backup
WORKDIR /backup
RUN chmod +x scripts/*.sh
ENTRYPOINT ["/bin/bash"]
