# execd — çok aşamalı derleme (rust:slim -> ince runtime).
# Build:  docker build -f execd/Dockerfile -t ai-trade-bot-execd .
# Run:    docker run --env-file .env -p 8788:8788 ai-trade-bot-execd
FROM rust:1.81-slim AS build
WORKDIR /build
# Bağımlılık cache'i: önce manifest'ler
COPY execd/Cargo.toml execd/Cargo.toml
COPY execd/core/Cargo.toml execd/core/Cargo.toml
COPY execd/service/Cargo.toml execd/service/Cargo.toml
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
# Kaynak
COPY execd/ execd/
WORKDIR /build/execd
RUN cargo build --release --bin execd

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/execd/target/release/execd /usr/local/bin/execd
ENV EXECD_PORT=8788
EXPOSE 8788
# Not: container içinden Python motoruna erişim için execd 0.0.0.0'a bağlanacaksa
# main.rs'teki bind adresini env ile ayarlayın (varsayılan loopback güvenlik içindir).
USER 10001
ENTRYPOINT ["execd"]
