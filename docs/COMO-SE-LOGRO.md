# Cómo se logró la versión funcional en AWS

Fecha: 9 de noviembre de 2026. Cuenta AWS Academy Learner Lab, `us-east-1`.
Este documento explica, en orden, qué se hizo, qué falló y cómo se resolvió, para que
cualquier compañero (o agente de IA) pueda reproducirlo y defenderlo.

## 1. Resultado final (medido, no estimado)

| Qué | Resultado |
|---|---|
| Infraestructura | EKS `chaos-lab-eks` ACTIVE, 3 nodos t3.medium Ready, addon EBS CSI ACTIVE, 3 repos ECR |
| CD en GitHub Actions | Run en verde: `publish` (imágenes a ECR) → `deploy` (EKS) → smoke test. El paso de rollback se omite porque no hubo fallo |
| Versión en producción | `GET /api/v1/version` → `{"version":"1.0.0","commit":"c25cdd7",...}` (el SHA del commit que disparó el CD) |
| Smoke test | `/api/v1/health`, `/api/v1/events` y `/` devuelven 200 |
| Caos: matar un pod del backend | 47 peticiones OK, 0 fallidas |
| Caos: matar PostgreSQL | un 503 transitorio, recuperación en ~25 s, reinicios del backend = 0 |
| Consistencia | `drift = 0` tras el caos y tras la carga (usuarios 1, 2, 3 y 50) |
| k6 (perfil `ramp`, 8 min, 300 VU) | 218 929 peticiones, 454 req/s, p90 275,6 ms, p95 525,6 ms, media 190 ms, máx 3,19 s; 0,86 % marcadas como fallidas (incluye 402 esperados); umbrales cumplidos |
| HPA backend | 2 → 8 réplicas en ~1 min (CPU 112 % a las 04:30:53, 8 réplicas a las 04:31:57; pico de CPU 189 %) |
| Prometheus | targets del backend en `up` vía ServiceMonitor |

Evidencia cruda: `docs/evidencias/` (`chaos.txt`, `hpa.csv`, `k6-summary.json`, `k6-resumen.txt`).

No se hizo todavía: capturas de Grafana, la demostración de un PR con test roto (pipeline en rojo)
y la consulta del gasto real (*Used $X of $50*).

## 2. Cronología de lo que se hizo

1. **Credenciales**: se reinició el Learner Lab y se guardaron las credenciales temporales en
   `~/.aws/credentials`. `aws sts get-caller-identity` confirmó cuenta `259514203192`, rol `voclabs`.
2. **`terraform plan`** (gratis): 15 recursos a crear. Antes se comprobó que no había clústeres,
   instancias ni balanceadores previos.
3. **`./scripts/aws-up.sh`** (`terraform apply`): creó el clúster EKS y el grupo de nodos.
   El addon EBS CSI no llegó a `ACTIVE` y el apply terminó con *timeout* a los 20 min (ver problema 1).
4. **Diagnóstico y arreglo del addon** (problema 1). Después se hizo `terraform untaint` del addon
   para que el estado de Terraform quedara coherente.
5. **Publicación y despliegue vía CD**: se añadió un disparo *temporal* `push` sobre la rama del PR
   (sin fusionar nada a `main`) para ejecutar el CD con evidencia real. Primer intento: `publish` OK,
   `deploy` falló (problema 2). Tras corregirlo, el run completo quedó en verde.
6. **Validación local del despliegue**: antes de arreglar el CD se ejecutó `deploy-aws.sh` desde el PC
   con las imágenes ya publicadas en ECR. Funcionó entero (es idempotente), lo que demostró que el
   fallo estaba en el CD y no en los manifiestos.
7. **Evidencias**: `demo-chaos.sh`, k6 con registro del HPA y comprobación de drift.

## 3. Problemas encontrados y cómo se resolvieron

### Problema 1: el addon EBS CSI se quedaba en `CREATING`
- **Síntoma**: `terraform apply` falló con `timeout while waiting for state to become 'ACTIVE'`.
  Los pods `ebs-csi-controller` estaban en `CrashLoopBackOff` (1/6 contenedores listos).
- **Causa**: el log decía `no EC2 IMDS role found ... context deadline exceeded`. El controlador usa
  las credenciales del rol del nodo (`LabRole`) a través del servicio de metadatos (IMDS). En estos
  nodos el *hop limit* de IMDS es 1, así que un **pod** (un salto extra de red) no puede leerlo.
  Sin permisos de AWS el controlador no arranca y no se pueden crear volúmenes EBS para PostgreSQL.
- **Por qué no se usó IRSA** (la solución habitual): el Learner Lab no permite crear roles IAM.
- **Arreglo inmediato**: `aws ec2 modify-instance-metadata-options --http-put-response-hop-limit 2`
  en las 3 instancias y reinicio de los pods del controlador. En un minuto quedaron `6/6 Running` y
  el addon pasó a `ACTIVE`.
- **Arreglo permanente en código**: `infra/terraform/main.tf` ahora define un `aws_launch_template`
  con `http_put_response_hop_limit = 2` (y disco gp3 de 20 GB) usado por el grupo de nodos.
  Está validado (`terraform validate`) pero **no aplicado** al clúster actual, que se parcheó a mano.
  Si alguien vuelve a hacer `terraform apply` sobre este clúster, Terraform reemplazará los nodos
  (rolling update). En un clúster nuevo funciona desde el principio.

### Problema 2: el CD fallaba con `Permission denied`
- **Síntoma**: el job `deploy` fallaba en 17 s en el paso *Desplegar*:
  `./scripts/deploy-aws.sh: Permission denied` (código 126).
- **Causa**: los scripts `.sh` se crearon en Windows y git los guardó sin el bit de ejecución.
- **Arreglo**: `git update-index --chmod=+x scripts/*.sh` y commit. Al relanzar, el CD pasó entero.
- **Cómo se encontró**: la API pública de GitHub no da los logs de un job; se leyó el log desde la
  sesión de Chrome del usuario.

### Problema 3: error en `demo-chaos.sh`
- `local secs="$1" ok=0 bad=0 end=$((SECONDS + secs))` falla con `set -u` porque `secs` aún no está
  definida al expandir `end`. Se separó en dos líneas.

### Otros detalles de entorno (Windows)
- Terraform y Helm se instalaron con `winget` y no estaban en el PATH de la terminal ya abierta; se
  usaron con su ruta completa.
- `python3` en Windows es un alias de la Microsoft Store; para ejecutar `deploy-aws.sh` en local se
  creó un pequeño envoltorio que llama a `python`. En el CD (Ubuntu) no hace falta.
- Docker Desktop no llegó a arrancar en este PC en la sesión, por eso se usó el CD (que construye las
  imágenes en GitHub) en lugar de construir localmente.

## 4. Por qué funciona (el mecanismo)

1. **Terraform** crea EKS, nodos, addon EBS CSI y ECR. Todo con `LabRole` porque no se pueden crear roles.
2. **El CD** (`.github/workflows/cd.yml`) toma credenciales de GitHub Secrets, construye las imágenes de
   backend y frontend con `--build-arg GIT_SHA`, las sube a ECR con el SHA corto como etiqueta y ejecuta
   `scripts/deploy-aws.sh`.
3. **`deploy-aws.sh`** (idempotente): crea namespaces, instala metrics-server (lo necesita el HPA) y
   Traefik (balanceador de AWS), genera **secretos aleatorios** una sola vez, crea el ConfigMap de
   semillas, aplica `kubectl kustomize cluster/overlays/aws` sustituyendo las imágenes por las de ECR,
   espera los rollouts, instala kube-prometheus-stack y aplica el ServiceMonitor y el dashboard.
4. **El smoke test** comprueba tres endpoints; si falla, el CD hace `kubectl rollout undo`.
5. **El HPA** escala el backend por CPU (70 %) y memoria (80 %), de 2 a 8 réplicas.
6. **Por qué el drift sigue en 0**: las transacciones en PostgreSQL y la clave de liquidación única
   mantienen la consistencia aunque los pods mueran o se reintenten peticiones.

## 5. Estado actual y qué hacer al despertar

**El clúster sigue encendido y cobrando ≈ 0,25 USD/h** (el crédito restante era bajo, unos 10 USD).
Las credenciales del Learner Lab caducan a las ~4 h de iniciar la sesión; después AWS deniega todo.

Decisión que tienes que tomar:

- **Si vas a hacer la demo en vivo pronto**: déjalo encendido. App en
  `http://aadd1279e11f64a36931da19c48decbd-371785364.us-east-1.elb.amazonaws.com`
  (la URL del balanceador no cambia mientras el servicio exista). Grafana:
  `kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80`; usuario `admin`; contraseña:
  `kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}'` decodificada en base64
  (o el secret `grafana-admin` que crea el script).
- **Si no**: destruye para no gastar crédito: `./scripts/aws-down.sh`. Recrear todo cuesta ~25 min
  (`aws-up.sh`) más el CD.

Si la sesión caduca antes de destruir, reinicia el lab (Start Lab), pega las credenciales nuevas y ejecuta
`aws-down.sh`. Comprueba en la consola que no queden EKS, EC2, balanceadores ni volúmenes EBS.

## 6. Cambios en la rama del PR (para revisar antes de fusionar)

- `cd.yml` tiene un disparo `push` **temporal** sobre `feat/tests-and-ci` y comentarios añadidos
  al final del archivo. **Quítalo antes de fusionar a `main`**; el PR #1 sigue sin fusionar.
- `infra/terraform/main.tf`: plantilla de lanzamiento con IMDS hop limit 2.
- Scripts ejecutables y corrección de `demo-chaos.sh`.
- `docs/evidencias/`, informe y diapositivas actualizados con datos reales.
- Los secrets de GitHub (`AWS_*`) caducan con la sesión del lab: hay que renovarlos para cada CD nuevo.
  Conviene **rotarlos o borrarlos** cuando termines.

## 7. Pendiente

1. Capturas de Grafana (dashboard «Chaos Lab - Backend y HPA») durante una carga.
2. PR con un test roto para demostrar que el pipeline se bloquea (y cerrarlo sin fusionar).
3. Consultar el gasto real (*Used $X of $50*) y anotarlo en el informe.
4. Quitar el disparo temporal del CD, fusionar el PR y destruir el entorno.
5. Cambiar la contraseña de GitHub que se expuso en el chat al inicio del proyecto.
