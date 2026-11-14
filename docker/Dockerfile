# Reproducible build of upstream QEMU (with plugin support) + DroidTrace.
FROM debian:trixie AS build
ARG QEMU_VERSION=10.0.3
ARG QEMU_TARGETS=aarch64-softmmu,x86_64-softmmu
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ninja-build meson pkg-config cmake python3 python3-venv python3-pip \
      libglib2.0-dev libpixman-1-dev libslirp-dev libfdt-dev flex bison wget xz-utils ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN wget -q https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz \
 && tar xf qemu-${QEMU_VERSION}.tar.xz && mv qemu-${QEMU_VERSION} qemu
COPY plugin /src/droidtrace/plugin
COPY qemu-patch /src/droidtrace/qemu-patch
# Built-in tracer (fast path) is compiled into QEMU; plugin support stays enabled too.
RUN sh /src/droidtrace/qemu-patch/apply.sh /src/qemu
RUN cd qemu && ./configure --prefix=/opt/qemu --target-list=${QEMU_TARGETS} \
      --enable-plugins --enable-slirp --disable-docs && make -j"$(( $(nproc) > 4 ? 4 : $(nproc) ))" && make install
RUN cmake -S /src/droidtrace/plugin -B /src/build -DQEMU_SRC=/src/qemu -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /src/build -j

FROM debian:trixie
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libglib2.0-0t64 libpixman-1-0 libslirp0 libfdt1 python3 python3-pip python3-venv adb aapt \
    && rm -rf /var/lib/apt/lists/* && useradd -m analyst
COPY --from=build /opt/qemu /opt/qemu
COPY --from=build /src/build/libinsntrace.so /opt/droidtrace/libinsntrace.so
COPY . /opt/droidtrace/src
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir "/opt/droidtrace/src[disasm,parquet]"
ENV PATH=/opt/venv/bin:/opt/qemu/bin:$PATH
EXPOSE 8765
USER analyst
WORKDIR /work
ENTRYPOINT ["droidtrace"]
