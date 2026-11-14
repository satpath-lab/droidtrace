# Test image: upstream QEMU (plugins enabled) for the end-to-end plugin test.
FROM debian:trixie
ARG QEMU_VERSION=10.0.3
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends build-essential ninja-build \
    meson pkg-config cmake libglib2.0-dev python3 python3-venv curl xz-utils ca-certificates \
    flex bison git >/dev/null
COPY qemu-patch /opt/dt/qemu-patch
COPY plugin /opt/dt/plugin
RUN curl -sfL https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz | tar xJ -C /opt \
 && sh /opt/dt/qemu-patch/apply.sh /opt/qemu-${QEMU_VERSION} \
 && cd /opt/qemu-${QEMU_VERSION} && ./configure --prefix=/usr/local --target-list=aarch64-linux-user \
    --enable-plugins --disable-docs --disable-tools >/dev/null && make -j"$(nproc)" >/dev/null \
 && make install >/dev/null && mkdir -p /opt/qemu-inc/include/qemu \
 && cp include/qemu/qemu-plugin.h /opt/qemu-inc/include/qemu/ && rm -rf /opt/qemu-${QEMU_VERSION}
