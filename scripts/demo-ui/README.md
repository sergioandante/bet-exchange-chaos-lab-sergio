# Interfaz local para la demo del HPA

Muestra en vivo réplicas, CPU y pods del backend, y lanza/para la carga k6.

Requisitos: `kubectl` con acceso al clúster (`aws eks update-kubeconfig --name chaos-lab-eks --region us-east-1`),
`k6` instalado y Python 3.

```bash
python scripts/demo-ui/server.py      # abre http://localhost:8099
```

Usa el perfil **rampa** (~8 min): es el que escala el backend de 2 a 8 réplicas.
El perfil «pico» puede no superar el 70 % de CPU y no escalar.
El HPA tarda ~5 min en bajar réplicas tras parar la carga.
