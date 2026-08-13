# syntax=docker/dockerfile:1.7

FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/wa-gateway ./cmd/wa-gateway

FROM alpine:3.22 AS runtime
RUN apk add --no-cache ca-certificates
COPY --from=build /out/wa-gateway /wa-gateway
USER 65532:65532
EXPOSE 8010
ENTRYPOINT ["/wa-gateway"]
