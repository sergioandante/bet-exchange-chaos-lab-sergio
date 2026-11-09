# HANDOFF — Estado del proyecto y guía para continuar con agentes de IA

> Documento pensado para pegarse **entero como primer mensaje** a un agente de IA
> (Claude Code, Cursor, Copilot, etc.) que va a continuar este trabajo.
> Fecha de corte: 2026-11-09. Repo: `sergioandante/bet-exchange-chaos-lab-sergio`
> (fork de `helvetios16/bet-exchange-chaos-lab`). PR abierto: #1, rama `feat/tests-and-ci` → `main`.

---

## 0. Instrucciones para el agente que lea esto

- Idioma de trabajo con el equipo: **español**.
- **No** fusiones el PR #1 ni hagas push a `main` sin que un humano lo pida.
- **Nunca** escribas credenciales (AWS, GitHub, tokens) en archivos, commits ni chat.
  Los secretos van en GitHub Secrets o en `~/.aws/credentials` del usuario.
- **No crees recursos AWS** (`aws-up.sh`, `terraform apply`) sin confirmación explícita del humano:
  cuestan dinero y el crédito restante es muy bajo (ver §3).
- Si algo no se ha probado, dilo. La spec del profesor exige **evidencia real**.
- Antes de afirmar que algo funciona, ejecútalo (tests, `terraform validate`, `kubectl kustomize`).

---

## 1. Objetivo del proyecto

Proyecto Integrador de **Cloud Computing**. Se adaptó el laboratorio
`bet-exchange-chaos-lab` (simulador de exchange de apuestas: FastAPI + nginx + PostgreSQL,
originalmente en Kubernetes local con `kind`) para cumplir:

| Req. | Descripción | Estado |
|---|---|---|
| 4.1 | Git, ramas, PRs, documentación | ✅ PR #1 abierto |
| 4.2 | Testing (pytest unit + integración, reportes, tests rotos bloquean pipeline) | ✅ |
| 4.3 | Docker + registry (ECR), imágenes versionadas | ✅ escrito (CD aún no ejecutado) |
| 4.4 | IaC (Terraform) | ✅ `validate` OK · ⏳ `apply` no ejecutado |
| 4.5 | CI (GitHub Actions) | ✅ verde en GitHub |
| 4.6 | CD (build → ECR → deploy → smoke → rollback) | ⏳ escrito, sin ejecutar |
| 4.7 | Kubernetes (probes, secrets, recursos, recuperación) | ✅ manifiestos · ⏳ sin probar en EKS |
| 4.8 | HPA + k6 | ⏳ escrito, sin ejecutar |
| 4.9 | Monitoring (Prometheus/Grafana) | ⏳ escrito, sin ejecutar |
| Seguridad/costos | Sin credenciales en repo, destruir recursos | ✅ escaneo limpio · scripts de destrucción listos |
| Entregables | 9 entregables + demo en vivo de 15 min | ⏳ informe en borrador |

> Nota: la sección «Estado actual» del `README.md` dice que el CI "aún no se ejecutó en GitHub".
> Está desactualizada: **el CI ya corrió en verde** en el PR #1 (ruff, tests con Postgres, build de 3 imágenes).

Propiedad de negocio que se vigila siempre: **`drift = wallets.available − SUM(transactions.amount) = 0`**.
La liquidación es idempotente (clave única `liquidation_key`).

---

## 2. Arquitectura (resumen)

```
Código ─► PR ─► CI (ruff → pytest+Postgres → build 3 imágenes)
                  │ verde en main
                  ▼
          CD ─► ECR (imagen:SHA corto) ─► EKS (kubectl kustomize + sed de tags)
                                              │
 Usuario ─► LB de AWS ─► Traefik ─► backend ×2..8 (HPA) ─► PostgreSQL (StatefulSet, EBS gp2)
                                └─► frontend ×2..6 (HPA)
 Prometheus + Grafana (kube-prometheus-stack) ◄── /metrics del backend, pods, CPU, memoria
 Terraform crea/destruye: EKS, node group, addon EBS CSI, repos ECR
```

- **Backend** (`app/backend/app.py`): FastAPI, pool async de psycopg, circuit breaker, rate limit en memoria,
  `/metrics` Prometheus, probes separadas (startup/liveness/readiness), **nuevo** `GET /api/v1/version`
  (devuelve versión, `GIT_SHA`, nombre del pod; el Dockerfile recibe `ARG GIT_SHA`).
- **Frontend**: nginx. **BD**: PostgreSQL 16 StatefulSet.
- **Ingress**: Traefik (chart 33.2.1) con Middlewares CRD (ratelimit, inflight).
- **HPA**: CPU 70 %, memoria 80 %, base 2→10; overlay AWS limita a 8. PDB y NetworkPolicy incluidos
  (EKS **no** aplica NetworkPolicy sin habilitarlo en el CNI).

---

## 3. Restricciones del entorno (MUY importantes)

- **AWS Academy Learner Lab**, región `us-east-1`, rol `LabRole` (no se pueden crear roles IAM).
- **Crédito restante ≈ 10 USD** (aprox. "Used $40 of $50" al medirlo). Solo **una** persona tiene lab.
- Las credenciales del lab **caducan (~4 h)** y al terminar la sesión una política (`voc-cancel-cred`)
  deniega todo. Hay que pulsar *Start Lab* y copiar credenciales nuevas a `~/.aws/credentials`
  (incluye `aws_session_token`). Los *secrets* de GitHub Actions también hay que refrescarlos cada sesión.
- Coste del entorno encendido ≈ **0,25 USD/h** (EKS + 3×t3.medium + EBS + LB). Olvidarlo encendido ≈ 6 USD/día.
  **Siempre** terminar con `./scripts/aws-down.sh`.
- Plazo original: ~12 h desde el cuestionario inicial (priorizar lo mínimo que dé evidencia real).
- Los otros cursos de AWS Academy listados no se consideraron fuente fiable de crédito adicional.

---

## 4. Qué se hizo (inventario de archivos)

Rama `feat/tests-and-ci` (5 commits, 38 archivos): `35713f0`, `e76fc65`, `d9c8f7a`, `9d84dc6`, `ed5e97b`.

**Tests y calidad**
- `tests/unit/test_backend_unit.py` (41 tests), `tests/unit/test_seed_unit.py`.
- `tests/integration/` (17 tests con PostgreSQL real vía `TEST_DB_*`; `REQUIRE_DB=1` hace que falten-BD = fallo, no skip).
- `tests/conftest.py` (añade `app/backend` a `sys.path`; en Windows fuerza `WindowsSelectorEventLoopPolicy`).
- `pytest.ini`, `ruff.toml` (E9,F), `requirements-dev.txt`.
- Se quitaron 3 variables sin usar en `seed.py`, `seed_load.py`, `tests/load/load.py`.

**CI/CD** (`.github/workflows/`)
- `ci.yml`: lint → test (servicio `postgres:16`, JUnit + cobertura como artefactos) → build de 3 imágenes (necesita lint+test).
- `cd.yml`: se dispara con `workflow_run` (CI OK en `main`) y `workflow_dispatch`. Publica a ECR con SHA corto +
  `--build-arg GIT_SHA`, despliega con `scripts/deploy-aws.sh`, smoke test, y `kubectl rollout undo` si falla.
  Requiere secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`.

**IaC** (`infra/terraform/`: `versions.tf variables.tf main.tf outputs.tf .terraform.lock.hcl`)
- EKS `chaos-lab-eks` (v1.31), node group 3×t3.medium (label `workload=app`), addon `aws-ebs-csi-driver`
  (toggle `enable_ebs_csi`), 3 repos ECR (`chaos-lab/backend|frontend|loadgen`) con lifecycle, VPC por defecto,
  `LabRole` para cluster y nodos. Provider `aws ~> 5.80`, Terraform 1.17.0.
- `terraform validate` OK. `terraform plan` quedó bloqueado por sesión de lab expirada (no se evadió).

**Kubernetes**
- `cluster/base/kustomization.yaml` (recursos 00,01,03,04,05,06; **excluye** `02-secret.yaml`).
- `cluster/overlays/aws/` (StorageClass gp2, HPA max 8, límites de tasa altos para carga, borra ConfigMap local de seeds)
  + `monitoring-netpol.yaml`. Compila con `kubectl kustomize`.

**Scripts** (`scripts/`): `aws-up.sh` (terraform apply + kubeconfig), `deploy-aws.sh` (namespaces, metrics-server v0.7.2,
Traefik LB, secretos aleatorios, seeds, aplicar kustomize + tags ECR, esperar rollouts, kube-prometheus-stack,
ServiceMonitor, dashboard; imprime URL del LB), `smoke-test.sh`, `aws-down.sh` (helm uninstall, borrar ns/PVC,
terraform destroy, lista restos), `demo-chaos.sh`, `demo-hpa.sh` (CSV en `reports/`).

**Monitoring** (`monitoring/`): `values.yaml`, `servicemonitor.yaml`, `dashboard.yaml` (8 paneles «Chaos Lab - Backend y HPA»).

**Carga**: `tests/load/k6-load.js` (perfiles `ramp` y `spike`, `BASE_URL` por env).

**Docs**: `README.md` (guía del equipo al inicio), `docs/RUNBOOK-AWS.md`, `docs/TUTORIAL-EQUIPO.md` (paso a paso A–I),
`docs/INFORME.md` (borrador con marcadores `[COMPLETAR]`), este archivo.

---

## 5. Cómo verificar en local (sin AWS, sin costo)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                   # usar Python 3.12 (3.14 no tiene wheel de psycopg-binary 3.2.3)
ruff check app tests
pytest tests/unit
docker run -d --name pg-test -e POSTGRES_USER=kuber -e POSTGRES_PASSWORD=kuber \
  -e POSTGRES_DB=kuber_test -p 55432:5432 postgres:16
REQUIRE_DB=1 TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 pytest tests/integration
docker rm -f pg-test
terraform -chdir=infra/terraform init -backend=false && terraform -chdir=infra/terraform validate
kubectl kustomize cluster/overlays/aws > /dev/null
```

Resultado verificado: 41 unit + 17 integración pasan; CI verde en GitHub.

---

## 6. Qué falta (orden recomendado)

1. **Revisión humana del PR #1** (Sergio lo está revisando). No fusionar hasta que lo apruebe.
2. Humano: *Start Lab* → copiar credenciales nuevas a `~/.aws/credentials` → mirar «Used $X of $50».
3. `aws sts get-caller-identity` y `terraform -chdir=infra/terraform plan` (solo lectura, gratis).
4. **Con confirmación**: `./scripts/aws-up.sh` (12–18 min, ≈0,25 USD/h). Si el crédito es muy justo,
   considerar bajar nodos (variable en `variables.tf`) o hacer la demo en una sola sesión corta.
5. Humano añade los 3 secrets en *Settings → Secrets and variables → Actions* del fork.
6. Fusionar PR → CD publica a ECR y despliega → `scripts/smoke-test.sh` → abrir URL del LB.
7. Evidencias reales: `scripts/demo-chaos.sh`, `k6 run -e BASE_URL=http://<LB> tests/load/k6-load.js` +
   `scripts/demo-hpa.sh`, capturas de Grafana, `kubectl get hpa/pods`, imagen en ECR.
8. Abrir un PR con un test roto para **demostrar que el pipeline bloquea** (y cerrarlo sin fusionar).
9. Rellenar `docs/INFORME.md` (`[COMPLETAR]`) con datos reales; completar los 9 entregables.
10. **Destruir todo**: `./scripts/aws-down.sh` y comprobar en consola que no queda EKS/EC2/ELB/EBS/NAT.
11. Herramientas pendientes en la PC del usuario: `winget install Helm.Helm k6.k6 GitHub.cli`
    (Terraform y AWS CLI ya instalados).

---

## 7. Riesgos y problemas conocidos

| Problema | Detalle / solución |
|---|---|
| Sesión de lab expirada | Error `AccessDenied` por `voc-cancel-cred`. Reiniciar lab y renovar credenciales. |
| psycopg + Windows | Requiere `SelectorEventLoop` (ya en `tests/conftest.py`). |
| Python 3.14 | Sin wheel de `psycopg-binary==3.2.3`; usar 3.12 (CI ya lo hace). |
| Docker Desktop en Windows | Sockets AF_UNIX obsoletos impedían arrancar; se resolvió renombrando `%LOCALAPPDATA%\Docker\run` y reiniciando WSL. Poca RAM libre agrava el problema. |
| CD no visible | `cd.yml` solo funciona tras fusionar a `main` y con cluster+ECR+secrets creados. |
| NetworkPolicy en EKS | Existe pero no se aplica sin habilitarla en el CNI. |
| LabRole | No hay mínimo privilegio completo (limitación del Learner Lab); explicarlo en el informe. |
| Hallazgos menores de la app (sin corregir) | Los 500 de excepciones no controladas no se cuentan en métricas; `settle_bet` tiene un `return` duplicado inalcanzable. |

---

## 8. Seguridad (recordatorio)

- Escaneo de secretos del repo: limpio.
- Un password de GitHub se expuso en una conversación de chat: **debe cambiarse** (ver `Settings → Password`).
- `02-secret.yaml` no se aplica; `deploy-aws.sh` genera secretos aleatorios en el clúster.
- `.gitignore` excluye `.terraform/`, `*.tfstate`, `*.tfvars` (salvo ejemplo).

---

## 9. Plantilla de prompt para el siguiente agente

```
Contexto: lee docs/HANDOFF-IA.md, docs/RUNBOOK-AWS.md y docs/TUTORIAL-EQUIPO.md del repo.
Rama de trabajo: crea una rama nueva desde feat/tests-and-ci (o desde main si el PR #1 ya se fusionó).
Tarea: <ej. "validar terraform plan con credenciales nuevas" / "rellenar docs/INFORME.md con los resultados de k6">.
Reglas: no crear recursos AWS sin mi confirmación; no escribir credenciales; no fusionar PRs;
ejecuta tests antes de afirmar que algo funciona; responde en español.
```

---

## 10. Guion de la demo final (15 min)

1. Cambiar algo visible (p. ej. versión en `/api/v1/version`). 2. Push + PR. 3. Mostrar CI corriendo.
4. Mostrar imagen nueva en ECR. 5. Mostrar despliegue automático en K8s. 6. Abrir la app y `/api/v1/version`.
7. Lanzar k6. 8. Mostrar HPA (`scripts/demo-hpa.sh`) y Grafana. 9. Explicar `aws-up.sh` / `aws-down.sh`.
Opcional: `scripts/demo-chaos.sh` (matar pods de backend y Postgres con tráfico, `drift` sigue en 0).
