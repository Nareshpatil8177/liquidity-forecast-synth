PY ?= python
.PHONY: test starter full repro all clean
test:     ; $(PY) -m pytest -q
starter:  ; $(PY) -m liquidity generate --scale starter
full:     ; $(PY) -m liquidity generate --scale full --formats csv,sql --gzip-sql
repro:    ; $(PY) -m liquidity repro --scale starter --out reports/reproducibility_starter.json
all:      ; $(PY) scripts/run_all.py
clean:    ; rm -rf data/starter data/full .pytest_cache
