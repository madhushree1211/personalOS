test:
	cd backend && python -m pytest -q

build:
	cd frontend && npm run build
