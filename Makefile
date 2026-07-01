# AI Trade Bot — sık kullanılan komutlar.
# Kullanım: `make <hedef>`  (örn. `make setup`, `make test`)
# Windows'ta `make` yoksa komutları doğrudan çalıştırabilirsiniz (aşağıdaki satırlara bakın).

.PHONY: help setup setup-py setup-js dev engine execd execd-test execd-build test test-py test-js lint typecheck gen-types check check-fast build dist clean

help:
	@echo "Hedefler:"
	@echo "  setup      - Python venv + npm bağımlılıkları"
	@echo "  dev        - Electron uygulamasını geliştirme modunda başlat"
	@echo "  engine     - Python motor sunucusunu başlat (uvicorn :8787)"
	@echo "  test       - Tüm testler (pytest + vitest)"
	@echo "  lint       - ruff (Python)"
	@echo "  typecheck  - tsc --strict (TypeScript)"
	@echo "  gen-types  - models.py'den TS tiplerini üret"
	@echo "  check      - GENEL kontrol: pytest+import+tsc+rust+backtest"
	@echo "  check-fast - check (Rust service derlemesi atlanır)"
	@echo "  build      - electron-vite derleme"
	@echo "  dist       - kurulum paketi üret (electron-builder)"

setup: setup-py setup-js

setup-py:
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements-dev.txt

setup-js:
	npm install

dev:
	npm run dev

engine:
	python -m uvicorn engine.app:app --port 8787 --reload

execd:
	cd execd && cargo run --bin execd

execd-test:
	cd execd && cargo test -p execd-core && cargo clippy -p execd-core -- -D warnings

execd-build:
	cd execd && cargo build --release --bin execd

check:
	python scripts/check_all.py

check-fast:
	python scripts/check_all.py --fast

test: test-py test-js

test-py:
	pytest

test-js:
	npm test

lint:
	ruff check engine scripts tests

typecheck:
	npm run typecheck

gen-types:
	python scripts/gen_types.py

build:
	npm run build

dist:
	npm run dist

clean:
	rm -rf out release __pycache__ .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
