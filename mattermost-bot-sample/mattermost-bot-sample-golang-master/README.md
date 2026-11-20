# Mattermost Bot Sample

## Overview

## Запуск
### Запуск в контейнере на локальном хосте

```
docker run -d --name mm-bot -p 8080:8080 --env-file Dockerfile.env \
    -e MM_SERVER='http://host.docker.internal:8065' \
    -e BOT_PUBLIC_URL='http://localhost:8080' \
    -e HTTP_ADDR=':8080' --add-host host.docker.internal:host-gateway mm-bot:latest
```

### Запуск для песочницы https://feature-sandbox.tag-test.corp.tander.ru/

```
sudo docker run -d --name mm-bot-golang -p 8081:8081 \
    -e MM_TEAM='magnit' \
    -e MM_TOKEN='hgzt3jj567g7txt5rkq6jfukhy' \
    -e MM_CHANNEL='town-square' \
    -e MM_USERNAME='sample-bot-golang' \
    -e MM_SERVER='https://feature-sandbox.tag-test.corp.tander.ru' \
    -e BOT_PUBLIC_URL='http://10.9.44.104:8081' \
    -e HTTP_ADDR=':8081' \
    -e SSL_SKIP_VERIFY='true' \
    --add-host host.docker.internal:host-gateway dev-mattermost-docker.repo.corp.tander.ru/mattermost-bot-sample-golang:feature-bot-init
```
