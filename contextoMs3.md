# MS3 — Operativo, Inteligente y Logístico

> Microservicio **secundario** (núcleo operativo e inteligente) del Sistema de Courier Inteligente (Grupo #11).
> README general del proyecto en la [raíz](../README.md).

| | |
|---|---|
| **Rol** | Secundario (operación + IA/ML + blockchain) |
| **Stack** | Python + FastAPI + REST + PostgreSQL + IA/ML |
| **Cloud** | Google Cloud Run + Cloud SQL PostgreSQL |
| **API** | REST (`/api/ops`) |
| **Es dueño de** | PostgreSQL (GCP) |

---

## 1. Responsabilidad

Cubre la **operación del courier** y todas las **funciones inteligentes**:

- Encomiendas (creación, estados, **dueño del tracking**)
- Rutas y asignación a repartidores
- Entregas (QR, foto, GPS)
- Incidencias
- **IA:** clasificación de fotos de paquetes (TensorFlow/Keras)
- **ML supervisado:** predicción de riesgo de retraso (scikit-learn)
- **ML no supervisado:** agrupación de zonas (K-Means)
- **Blockchain:** registro de hashes de eventos críticos (Web3.py + Sepolia)
- **Disparador de n8n** ante retrasos

> Es el backend que consume la **app móvil React Native**.

---

## 2. Casos de uso que cubre

| CU | Rol en el MS3 |
|---|---|
| CU-05 Registrar encomienda | **Dueño** — crea envío, genera tracking, estado `REGISTRADO`, dispara blockchain |
| CU-07 Consultar tracking | **Dueño** (rol Asesor) — estado + historial |
| CU-08 Asignar ruta | **Dueño** — K-Means + FCM push |
| CU-09 Escanear QR | **Dueño** — valida paquete vs envío asignado |
| CU-10 Confirmar entrega con foto y GPS | **Dueño** — estado `ENTREGADO`, delega foto a MS2, registra blockchain |
| CU-11 Analizar foto con IA | **Dueño** — TensorFlow |
| CU-12 Predecir retraso | **Dueño** — scikit-learn supervisado |
| CU-13 Agrupar zonas | **Dueño** — K-Means |
| CU-14 Registrar evento blockchain | **Dueño** — Web3.py |
| CU-15 Automatizar aviso de retraso | **Disparador** — detecta retraso → webhook n8n |

---

## 3. Stack técnico

| Tecnología | Uso |
|---|---|
| Python 3.11 | Lenguaje |
| FastAPI | Framework REST |
| SQLAlchemy | ORM sobre PostgreSQL |
| PostgreSQL | Base de datos operativa |
| TensorFlow / Keras (MobileNetV2) | IA visión por computadora |
| scikit-learn | ML supervisado + no supervisado |
| Web3.py | Cliente blockchain (Ethereum Sepolia) |
| python-jose | Validación de JWT |
| httpx | Llamadas REST a MS1 / MS2 / n8n |
| Firebase Admin SDK | Notificaciones push (FCM) |
| Pydantic | Validación de esquemas |

---

## 4. Estructura (FastAPI)

```
app/
├── main.py
├── core/
│   ├── config.py            # settings / env
│   ├── security.py          # validación JWT (clave pública MS1)
│   └── database.py          # engine + session SQLAlchemy
├── routers/
│   ├── encomiendas.py       # /api/ops/encomiendas
│   ├── tracking.py          # /api/ops/encomiendas/{t}/tracking
│   ├── rutas.py             # /api/ops/rutas
│   ├── entregas.py          # /api/ops/entregas, /escaneo-qr
│   ├── ia.py                # /api/ops/ia/analizar-foto
│   ├── ml.py                # /api/ops/ml/predecir-retraso, /agrupar-zonas
│   └── blockchain.py        # /api/ops/blockchain/evento
├── models/                  # SQLAlchemy (Encomienda, Ruta, Entrega...)
├── schemas/                 # Pydantic
├── services/
│   ├── tracking_service.py
│   ├── notificacion_service.py   # FCM
│   ├── ms1_client.py        # httpx → MS1 (cliente, ingreso)
│   └── ms2_client.py        # httpx → MS2 (subir foto)
├── ml_models/
│   ├── cnn_paquete.h5       # MobileNetV2 entrenado
│   ├── retraso.pkl          # RandomForest/GradientBoosting
│   ├── kmeans_zonas.pkl     # K-Means
│   └── inference.py         # carga + preprocesado + predicción
└── blockchain/
    ├── web3_client.py       # conexión Infura/Sepolia
    └── CourierTrace.abi.json
```

---

## 5. Modelo de datos (PostgreSQL — GCP)

```python
encomienda(
  id PK, tracking_code UNIQUE,
  cliente_id,            # REF lógica a MS1
  cliente_nombre, cliente_direccion,   # cache (evita llamada cruzada en lecturas)
  origen, destino, peso, servicio_ref, zona_ref,
  estado,               # REGISTRADO|EN_TRANSITO|EN_REPARTO|ENTREGADO|RETRASADO|CON_INCIDENCIA
  costo, riesgo_retraso, # BAJO|MEDIO|ALTO
  created_at
)
estado_historial(id PK, encomienda_id FK, estado, fecha, ubicacion, gps_lat, gps_lng)
ruta(id PK, asesor_id, zona_ref, fecha, estado)
ruta_encomienda(ruta_id FK, encomienda_id FK)          # N:M
entrega(id PK, encomienda_id FK, asesor_id, foto_url, gps_lat, gps_lng, qr_validado, fecha)
prediccion(id PK, encomienda_id FK, riesgo, modelo, fecha)
incidencia(id PK, encomienda_id FK, tipo, descripcion, foto_url, fecha)  # DANIO|RETRASO|NO_ENTREGA
evento_blockchain(id PK, encomienda_id, tipo_evento, hash_sha256, tx_hash, fecha)
```

Estados de una encomienda:
```
REGISTRADO → EN_TRANSITO → EN_REPARTO → ENTREGADO
                                ↘ RETRASADO
                                ↘ CON_INCIDENCIA
```

---

## 6. API REST

Base: `/api/ops`

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/encomiendas` | Crear envío, generar tracking, estado `REGISTRADO` |
| `GET` | `/encomiendas/{tracking}` | Detalle del envío |
| `GET` | `/encomiendas/{tracking}/tracking` | Historial de estados (línea de tiempo) |
| `POST` | `/rutas` | Asignar ruta a asesor (agrupa por zona, notifica push) |
| `POST` | `/escaneo-qr` | Validar QR vs envío asignado |
| `POST` | `/entregas` | Confirmar entrega (foto + GPS + estado `ENTREGADO`) |
| `POST` | `/ia/analizar-foto` | Clasificar imagen de paquete |
| `POST` | `/ml/predecir-retraso` | Riesgo de retraso de un envío |
| `POST` | `/ml/agrupar-zonas` | Clustering K-Means de zonas |
| `POST` | `/blockchain/evento` | Registrar hash de evento crítico |

---

## 7. Funciones inteligentes (detalle)

### 7.1 IA — análisis de foto (`/ia/analizar-foto`)
- **Modelo:** MobileNetV2 con *transfer learning* (TensorFlow/Keras).
- **Entrada:** imagen (multipart o base64).
- **Salida:** `SIN_DAÑO` · `POSIBLE_DAÑO` · `ETIQUETA_ILEGIBLE`.
- **Acción:** si `POSIBLE_DAÑO` → genera `incidencia` y puede disparar n8n.

### 7.2 ML supervisado — predicción de retraso (`/ml/predecir-retraso`)
- **Modelo:** scikit-learn `RandomForestClassifier` o `GradientBoostingClassifier`.
- **Entrada:** peso, distancia, tipo de servicio, zona, hora, día.
- **Salida:** `BAJO` · `MEDIO` · `ALTO`.
- **Acción:** si `ALTO` → marca seguimiento prioritario + alerta al admin.

### 7.3 ML no supervisado — agrupar zonas (`/ml/agrupar-zonas`)
- **Modelo:** scikit-learn `KMeans`.
- **Entrada:** coordenadas GPS, cantidad de envíos, tiempos de entrega, incidencias.
- **Salida:** grupo (alta demanda / retrasos frecuentes / baja demanda).
- **Acción:** alimenta planificación de rutas y dashboard BI.

### 7.4 Blockchain (`/blockchain/evento`)
- **Red:** Ethereum **Sepolia** testnet (vía Infura).
- **Cliente:** Web3.py invoca un smart contract.
- **Eventos:** `CREACION_GUIA`, `CAMBIO_ESTADO`, `ENTREGA_CONFIRMADA`, `HASH_DOCUMENTO`.
- **Se guarda solo el hash SHA-256** (tracking, actor, timestamp, estado, GPS) + referencia on-chain en PostgreSQL. Verificable en Etherscan Sepolia.
- **Excepciones:** error Infura → reintentar; contrato no disponible → guardar en BD con marca de reintento.

---

## 8. Autenticación

MS3 es **resource server** (no emite tokens).
- Valida el **JWT** con la **clave pública de MS1** (RS256).
- Endpoints de entrega/QR requieren rol **ASESOR**; IA/ML/rutas requieren **ADMIN** (IA también ASESOR).
- Endpoints internos de blockchain/predicción se ejecutan como **sistema** (automáticos).

---

## 9. Comunicación inter-servicio

| Dirección | Con quién | Para qué |
|---|---|---|
| **Entra** | Angular / App móvil (REST) | Operación, IA, tracking |
| **Sale** | MS3 → MS1 | Obtener datos de cliente; registrar ingreso (CU-05) |
| **Sale** | MS3 → MS2 | Almacenar foto de evidencia en S3 (CU-10) |
| **Sale** | MS3 → n8n (webhook) | Disparar aviso de retraso (CU-15) |
| **Sale** | MS3 → FCM | Notificación push al asesor (CU-08) |
| **Sale** | MS3 → Sepolia/Infura | Registrar hash en blockchain |

---

## 10. Variables de entorno

```env
PORT=8000
DATABASE_URL=postgresql://user:pass@<cloudsql-host>:5432/ms3_operativo
JWT_PUBLIC_KEY=<clave pública RS256 de MS1>
MS1_URL=https://<gateway>/graphql
MS2_URL=https://<gateway>/api/docs
N8N_WEBHOOK_URL=https://<n8n-host>/webhook/retraso
FCM_CREDENTIALS=/secrets/firebase-admin.json
WEB3_PROVIDER=https://sepolia.infura.io/v3/<infura-key>
CONTRACT_ADDRESS=0x...
WALLET_PRIVATE_KEY=<clave de la wallet de pruebas>
MODEL_CNN=app/ml_models/cnn_paquete.h5
MODEL_RETRASO=app/ml_models/retraso.pkl
MODEL_KMEANS=app/ml_models/kmeans_zonas.pkl
```

---

## 11. Setup local

```bash
python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head            # migraciones
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Requisitos: Python 3.11, PostgreSQL, modelos en `app/ml_models/`, wallet + Infura key para blockchain.

---

## 12. Despliegue (Google Cloud)

- **App:** Cloud Run (contenedor Docker).
- **BD:** Cloud SQL PostgreSQL.
- Secretos en Secret Manager (Infura, wallet, FCM).
- Exponer `/api/ops/*` a través del API Gateway.
