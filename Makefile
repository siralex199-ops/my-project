.PHONY: web cli test data backtest

web:            ## اجرای رابط وب روی پورت ۸۰۰۰
	python3 web/server.py

cli:            ## نمونه‌ی خط فرمان
	python3 -m football_predictor.cli fixtures --league en.1 --limit 8

test:           ## اجرای تست‌ها
	python3 -m unittest discover -s tests -v

data:           ## بازسازی دیتاست از مخزن openfootball
	python3 scripts/build_dataset.py

backtest:       ## اعتبارسنجی مدل روی فصل‌های گذشته
	python3 scripts/backtest.py
