QEMU_SRC ?= /opt/qemu
BUILD    ?= build

.PHONY: plugin test lint fmt clean docker
plugin:
	cmake -S plugin -B $(BUILD) -DQEMU_SRC=$(QEMU_SRC) -DCMAKE_BUILD_TYPE=Release
	cmake --build $(BUILD) -j
test:
	pytest -q
lint:
	ruff check src tests && mypy src
fmt:
	ruff format src tests
docker:
	docker build -t droidtrace -f docker/Dockerfile .
clean:
	rm -rf $(BUILD) dist *.egg-info
