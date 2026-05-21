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

---

## [2026-05-21] Seer V4 implementado — Option A + Option B

### Qué se hizo
- **Option A (error diagnostics)**: `ProbeResult` dataclass reemplaza las tuplas crudas.
  Cada URL obtiene un `status` clasificado: `ok`, `http_403`, `http_429`, `http_other`,
  `timeout`, `ssl_error`, `connection_error`, `js_required`.
  El CSV de salida ahora incluye columnas `Status`, `Error_Detail`, `Fallback_Module`.
  El Intelligence Report imprime el breakdown de errores y qué módulos de fallback se necesitan.

- **Option B (fallback chain)**: arquitectura modular en `src/dih_engine/recon/modules/`:
  - `requests_probe.py` — módulo base (siempre disponible)
  - `curlffi_probe.py` — bypass de WAF via TLS fingerprinting (`pip install "dih-engine[tls]"`)
  - `playwright_probe.py` — headless browser para páginas CSR (`pip install "dih-engine[browser]"`)
  - `error_taxonomy.py` — mapa `{http_403: curl_cffi, ssl_error: curl_cffi, http_429: delay_retry, timeout: delay_retry, js_required: playwright}`

- `pyproject.toml`: agregados optional extras `[tls]`, `[browser]`, `[full]`.
- 49 tests verdes (22 nuevos para V4, incluyendo `TestBuildProbeResult`).

### Pendiente de esta sesión
- **Live test en URLs reales** con el nuevo `--sample-size 10` para ver los nuevos campos en acción.
- **Push a GitHub** — no se hizo aún.
- **PyPI** — pendiente de decisión.
- **Slack template** — el usuario mencionó que quiere un template de notificaciones Slack
  para el proyecto (no está activo, solo como placeholder).

---

## [2026-05-21] curl_cffi instalado + live test completo de 100 URLs

### Resultados del live test (data/plan_test_full.csv)
```
87 ok              -- éxito directo
 6 http_403        -- WAF block; curl_cffi rescató 3 (riachuelo, codepen, behance)
 3 http_other      -- errores HTTP varios
 2 timeout         -- delay_retry resolvió ambos (canva rescatada con 429 -> retry ok)
 1 ssl_error       -- tricae.com.br: cert expirado en el servidor (terminal, sin solución)
 1 connection_error -- fallo DNS (terminal)
```

### Sitios que necesitan el próximo módulo (proxy_probe.py)
- stackoverflow.com  -- Cloudflare Enterprise, bloquea requests y curl_cffi
- centauro.com.br    -- WAF persistente
- etsy.com           -- bot protection avanzada

### Notificaciones
- Slack + Discord ambos funcionando (200 / 204)
- Webhooks guardados en .env (gitignored)

### Pendiente
- **proxy_probe.py** -- módulo de rotación de proxies (Scrapfly/ZenRows/Oxylabs)
- **Push a GitHub** -- 9 commits locales sin subir
- **PyPI** -- pendiente de decisión
