# --- build stage ---
FROM --platform=linux/amd64 golang:1.25-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /src

# Cache deps first.
COPY go.mod go.sum ./
RUN go mod download

# Build.
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" -o /out/bot .

# --- runtime stage ---
FROM --platform=linux/amd64 alpine:3.20

RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S bot && adduser -S -G bot bot

WORKDIR /app
COPY --from=builder /out/bot /app/bot

USER bot

ENV HTTP_ADDR=":8080"
EXPOSE 8080

ENTRYPOINT ["/app/bot"]
