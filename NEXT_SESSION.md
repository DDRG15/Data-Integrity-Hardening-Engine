# Pendiente — continuar mañana

## Estado actual
V3.2 completa. CLI funciona, 42 tests verdes, Docker listo, commit local grabado.
Falta: live test, PyPI, y push a GitHub.

---

## 1. Live test del recon (prioridad alta)
Los tests del Seer son mocks — nunca se probó contra URLs reales.

```bash
# Crear un CSV con URLs reales de prueba
echo "URL" > data/urls_test.csv
echo "https://www.example.com" >> data/urls_test.csv

dih-engine recon --input data/urls_test.csv --output data/plan_test.csv --sample-size 1
```

Verificar que el Intelligence Report imprime stack correcto y que el CSV se genera.

---

## 2. Push a GitHub
```bash
git push origin main --force-with-lease
```

---

## 3. PyPI publish (opcional — decide si es el momento)
Necesitas un token de PyPI. Si decides publicar:

```bash
pip install build twine
python -m build
twine upload dist/*
```

O agregar el workflow de CI para que publique automáticamente en cada tag:
- Archivo: `.github/workflows/publish.yml`
- Requiere: secret `PYPI_API_TOKEN` configurado en el repo de GitHub

---

## 4. Cosas menores pendientes
- Agregar `.gitattributes` para fijar line endings (LF) — git está convirtiendo a CRLF en Windows y genera warnings en cada commit
- Decidir si `.claude/` va al `.gitignore` (contiene config local de Claude Code)
