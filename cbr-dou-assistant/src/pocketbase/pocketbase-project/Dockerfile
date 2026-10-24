# PocketBase строго 0.22.x — версия закреплена build-аргументом
FROM alpine:3.20

ARG PB_VERSION=0.22.21
ARG TARGETARCH=amd64

RUN apk add --no-cache ca-certificates
ADD https://github.com/pocketbase/pocketbase/releases/download/v${PB_VERSION}/pocketbase_${PB_VERSION}_linux_${TARGETARCH}.zip /tmp/pb.zip
RUN apk add --no-cache --virtual .unzip unzip \
    && unzip /tmp/pb.zip -d /pb \
    && rm /tmp/pb.zip \
    && chmod +x /pb/pocketbase \
    && apk del .unzip

COPY pb_migrations /pb/pb_migrations
COPY pb_hooks /pb/pb_hooks

EXPOSE 8090
CMD ["/pb/pocketbase", "serve", \
     "--http=0.0.0.0:8090", \
     "--dir=/pb/pb_data", \
     "--migrationsDir=/pb/pb_migrations", \
     "--hooksDir=/pb/pb_hooks"]
